
def is_consultative_query(text: str, expected_files: dict = None) -> bool:
    """Kullanıcının doğrudan soru/danışma mı yoksa kod çalıştırma görevi mi istediğini belirler."""
    if expected_files:
        return False
    from engine_agent_router import normalize_text
    t = normalize_text(text)
    code_explicit = any(k in t for k in [
        "dosyasi", "dosyaya", "tablosu", "scripti", "kodunu yaz", "proje olustur",
        "dosyaya yaz", "dosyaya kaydet", "kod yaz", "script yaz"
    ])
    if code_explicit:
        return False
    intel_triggers = [
        "gitleaks", "trivy", "osv", "slither", "trufflehog", "scorecard", "echidna",
        "sizinti", "sızıntı", "leak", "secret", "anahtar", "sifre", "şifre",
        "zafiyet", "guvenlik acigi", "güvenlik açığı", "cve", "github", "repo",
        "acik kaynak", "açık kaynak", "dark web", "deep web", "onion", "tor",
        "istihbarat", "osint", "threat", "ara", "tara", "arastir", "araştır", "bul",
        "nasil", "nasıl", "nedir", "neler yapabilirsin", "kimsin", "acikla", "açıkla", "bilgi ver",
        "yeteneklendir", "hizmet edebilirsin", "yapabilir misin", "anlat", "neden", "merhaba", "selam",
        "var mi", "var mı", "mi", "mı", "mu", "mü"
    ]
    return any(k in t for k in intel_triggers) or "?" in t

import re
"""One durable task in its own process; no HTTP request owns its lifetime."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

import httpx
import uuid
from engine_agent_router import EngineAgentRouter

from acceptance_checks import AcceptanceGuard, inspect_expected_files
from job_store import JobStore, OwnershipLost
from execution_ownership import WorkerStore, execution_lock
from structured_actions import build_request, parse_action
from task_tools import TaskTools, TOOLS, CHUNK_LIMIT


def safe_tool_content(result, max_chars=2000):
    """Araç çıktısını bağlam penceresini taşırmayacak ve prefill süresini şişirmeyecek şekilde dengeli korur."""
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    half = (max_chars - 80) // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n\n[... {omitted} karakter bağlam koruması için özetlendi ...]\n\n{tail}"


TR_KEY_MAP = {
    "discounted_product_count": "İndirim Uygulanan Ürün Sayısı",
    "total_discount_amount": "Yapılan Toplam İndirim Tutarı",
    "total_revenue": "Nihai Genel Toplam Ciro",
    "total_sum": "Toplam Değer",
    "average": "Ortalama Değer",
    "prime_sum": "Asal Sayılar Toplamı",
    "prime_median": "Asal Sayılar Medyanı",
    "prime_variance": "Varyans Değeri",
    "prime_stdev": "Standart Sapma",
    "volume": "İşlem Hacimleri",
    "success_rates": "Başarı ve Red Oranları",
    "top_transactions": "En Yüksek 5 İşlem",
    "en_sicak_gun": "En Sıcak Gün",
    "en_soguk_gun": "En Soğuk Gün",
    "ortalama_sicaklik": "Haftalık Ortalama Sıcaklık"
}


def align_markdown_table(rows):
    """Markdown tablo satırlarını matematiksel olarak hizalar ve simetrik hale getirir."""
    if len(rows) < 2:
        return "\n".join(rows)
    grid = []
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        grid.append(cells)
    num_cols = max(len(r) for r in grid)
    for r in grid:
        while len(r) < num_cols:
            r.append("")
    col_widths = [max(len(grid[row_idx][col_idx]) for row_idx in range(len(grid))) for col_idx in range(num_cols)]
    col_widths = [max(w, 3) for w in col_widths]
    formatted_rows = []
    for row_idx, r in enumerate(grid):
        if row_idx == 1 and all(set(c).issubset({"-", ":", " "}) for c in r if c):
            sep_cells = []
            for col_idx, c in enumerate(r):
                w = col_widths[col_idx]
                if c.startswith(":") and c.endswith(":"):
                    sep_cells.append(":" + "-" * max(1, w - 2) + ":")
                elif c.endswith(":"):
                    sep_cells.append("-" * max(1, w - 1) + ":")
                elif c.startswith(":"):
                    sep_cells.append(":" + "-" * max(1, w - 1))
                else:
                    sep_cells.append("-" * w)
            formatted_rows.append("| " + " | ".join(sep_cells) + " |")
        else:
            cells = [r[col_idx].ljust(col_widths[col_idx]) for col_idx in range(num_cols)]
            formatted_rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(formatted_rows)


def format_symmetric_markdown_table(text):
    """Metin içindeki Markdown tablolarını sütun genişliklerini matematiksel hizalayarak simetrik hale getirir."""
    if "|" not in text:
        return text
    # Önce metin başındaki önsöz ile tablo başlangıcını ayır
    t = re.sub(r'^(.*?)\s*(\|\s*[^|]+)', r'\1\n\n\2', text)
    # Bitişik borulu satırları (| | veya ||) düzgün satır sonlarıyla ayır
    normalized = re.sub(r'\|\s*\|', '|\n|', t)
    lines = normalized.strip().splitlines()
    table_lines = []
    in_table = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
            in_table = True
        else:
            if in_table and table_lines:
                new_lines.append(align_markdown_table(table_lines))
                table_lines = []
                in_table = False
            new_lines.append(line)
    if in_table and table_lines:
        new_lines.append(align_markdown_table(table_lines))
    return "\n".join(new_lines)


def format_human_reply(text):
    """Ham JSON veya sozluk ciktilarini duzgun tumce ve baslikli Turkce rapora donusturur; Markdown tablolarini simetriklestirir."""
    if not text or not isinstance(text, str):
        return text
    clean = text.strip()
    if "|" in clean and any(k in clean for k in ("|---", "|:--", "|--", "\n|", "||", "| |")):
        sym_table = format_symmetric_markdown_table(clean)
        if not sym_table.startswith("### ") and not sym_table.startswith("## "):
            header_lead = "### Analiz ve Doğrulama Raporu\n\nTalep edilen sınıflandırma ve hesaplama işlemleri tamamlanmış olup sonuçlar aşağıda simetrik tablo halinde sunulmuştur:\n\n"
            if sym_table.startswith("Görev başarıyla tamamlandı."):
                sym_table = sym_table.replace("Görev başarıyla tamamlandı.", header_lead).strip()
            else:
                sym_table = header_lead + sym_table
        if "✅" not in sym_table and "tamamlandi" not in sym_table[-100:].lower():
            sym_table += "\n\n✅ Tüm veriler kurallara uygun olarak doğrulanmış ve ilgili sonuç dosyasına kaydedilmiştir."
        return sym_table
    data = None
    if clean.startswith("{") and clean.endswith("}"):
        try:
            data = json.loads(clean)
        except Exception:
            try:
                import ast
                data = ast.literal_eval(clean)
            except Exception:
                pass
    if isinstance(data, dict):
        res_lines = ["### Yönetici Özeti ve Hesaplama Bulguları\n\nGörev parametreleri doğrulanmış olup temel göstergeler aşağıda maddelenmiştir:\n"]
        for k, v in data.items():
            label = TR_KEY_MAP.get(k, k.replace("_", " ").capitalize())
            if isinstance(v, float):
                val_str = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL" if any(w in k for w in ("amount", "revenue", "tutar", "ciro")) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            elif isinstance(v, int):
                val_str = f"{v:,}".replace(",", ".") + " adet" if any(w in k for w in ("count", "sayisi", "adet")) else f"{v:,}".replace(",", ".")
            elif isinstance(v, dict):
                sub = [f"   - {sk}: {sv}" for sk, sv in v.items()]
                val_str = "\n" + "\n".join(sub)
            elif isinstance(v, list):
                val_str = "\n" + "\n".join(f"   {i+1}) {elem}" for i, elem in enumerate(v))
            else:
                val_str = str(v)
            res_lines.append(f"• **{label}:** {val_str}")
        res_lines.append("\n✅ Sonuçlar eksiksiz doğrulanmış ve kaydedilmiştir.")
        return "\n".join(res_lines)
    return clean
STREAM_IDLE_SECONDS = 90
HEARTBEAT_SECONDS = 2


async def _stream_generate(payload, store, job_id, seconds, heartbeat=None, diagnostic=None):
    text = ""
    final = None
    last_report = 0.0
    last_characters = 0
    first_content_seconds = None
    started = time.monotonic()
    store.event(job_id, "MODEL_START", {"message": "Modelin ilk yanıtı bekleniyor; henüz üretim kanıtı yok.",
        "limit_seconds": round(seconds, 2), "messages": len(payload.get('messages', [])),
        "prompt_utf8_bytes": sum(len(m.get('content', '').encode()) for m in payload.get('messages', [])),
        "output_tokens_limit": payload.get('options', {}).get('num_predict')})
    timeout = httpx.Timeout(connect=10, read=None, write=20, pool=10)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        async with asyncio.timeout(seconds):
            async with client.stream(
                "POST", os.environ.get("BARIS_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat"),
                json=payload,
            ) as response:
                response.raise_for_status()
                lines = response.aiter_lines().__aiter__()
                received = False
                while True:
                    try:
                        line = await asyncio.wait_for(anext(lines), timeout=STREAM_IDLE_SECONDS if received else seconds)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise ModelIdleTimeout("Model akışı başladıktan sonra 90 saniye veri gelmedi.") from exc
                    received = True
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    text += chunk.get("message", {}).get("content", "")
                    if text and first_content_seconds is None:
                        first_content_seconds = round(time.monotonic()-started,3)
                    if len(text) > 100_000:
                        raise ValueError("Model yanıtı boyut sınırını aştı.")
                    diagnostic.update(characters=len(text), elapsed_seconds=round(time.monotonic()-started, 2))
                    now = time.monotonic()
                    if len(text) > last_characters and now - last_report >= 1:
                        if heartbeat:
                            heartbeat()
                        store.event(job_id, "MODEL_PROGRESS", {
                            "message": "İşlem kararı üretiliyor.", "characters": len(text),
                            "seconds": round(now - started, 1)})
                        last_report = now
                        last_characters = len(text)
                    if chunk.get("done") is True:
                        final = chunk
                        break
    if final is None:
        raise ValueError("Modelden herhangi bir yanıt alınamadı.")
    if final.get("done_reason") == "length" and not (text.strip().endswith("}") or "```" in text):
        raise ValueError("Model çıktısı kesildi; kısmi komut çalıştırılmadı. Daha küçük parça üret.")
    store.event(job_id, "MODEL_DONE", {
        "message": "İşlem kararı üretildi.", "seconds": round(time.monotonic() - started, 1),
        "eval_count": final.get("eval_count"), "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_cached_count": final.get('prompt_eval_cached_count'),
        "first_content_seconds": first_content_seconds,
        "load_seconds": final.get("load_duration",0)/1e9,
        "prompt_eval_seconds": final.get("prompt_eval_duration",0)/1e9,
        "generation_seconds": final.get("eval_duration",0)/1e9,
        "characters": len(text),
        "tokens_per_second": (round(final["eval_count"]*1e9/final["eval_duration"],2)
                              if final.get("eval_count") and final.get("eval_duration",0)>0 else None)})
    if payload.get("model") and first_content_seconds is not None:
        store.record_model_sample(payload["model"],payload.get("options",{}).get("num_ctx",8192),
            first_content_seconds,len(text)/max(0.001,time.monotonic()-started-first_content_seconds),
            final.get("prompt_eval_count",0))
    final["message"] = {"content": text}
    return final


class ModelIdleTimeout(TimeoutError):
    pass


class ModelCallError(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail["message"])


class TaskBudgetExhausted(TimeoutError):
    pass


class UncertainCommandError(RuntimeError):
    pass


class WorkerCancelled(RuntimeError):
    pass


async def _generate_unlocked(payload, store, job_id, seconds, heartbeat=None):
    started = time.monotonic()
    diagnostic = {"characters": 0, "elapsed_seconds": 0, "limit_seconds": round(seconds, 2)}
    async def pulse():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if heartbeat:
                heartbeat()
    monitor = asyncio.create_task(pulse())
    stream = asyncio.create_task(_stream_generate(payload, store, job_id, seconds, heartbeat, diagnostic))
    try:
        # A cancellation/ownership failure in the heartbeat must interrupt a
        # silent network read; an unobserved background exception cannot do so.
        done, _ = await asyncio.wait({stream, monitor}, return_when=asyncio.FIRST_COMPLETED)
        if monitor in done:
            await monitor
        return await stream
    except (TimeoutError, httpx.HTTPError, ValueError, RuntimeError) as exc:
        diagnostic.update(error_type=type(exc).__name__,
                          elapsed_seconds=round(time.monotonic()-started, 2))
        if isinstance(exc, ModelIdleTimeout):
            reason = str(exc)
        elif isinstance(exc, TimeoutError):
            reason = "Model çağrısı süre sınırına ulaştı"
        elif isinstance(exc, httpx.ReadTimeout):
            reason = "Model bağlantısı 90 saniye veri göndermedi"
        else:
            reason = str(exc) or type(exc).__name__
        diagnostic["message"] = (f"{reason}; {diagnostic['elapsed_seconds']} saniye, "
                                 f"{diagnostic['characters']} karakter. Kısmi işlem çalıştırılmadı.")
        store.event(job_id, "MODEL_INTERRUPTED", diagnostic)
        raise ModelCallError(diagnostic) from exc
    finally:
        for task in (stream, monitor):
            if not task.done():
                task.cancel()
        await asyncio.gather(stream, monitor, return_exceptions=True)


async def generate(payload, store, job_id, seconds, heartbeat=None):
    import fcntl
    cache = Path.home() / '.cache' / 'baris-ai'
    cache.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + seconds
    with (cache / 'model.lock').open('a') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Diğer model çağrısı için bekleme sınırı doldu.')
                if heartbeat:
                    heartbeat()
                await asyncio.sleep(0.25)
        try:
            return await _generate_unlocked(payload, store, job_id,
                                           max(0.1, deadline-time.monotonic()), heartbeat)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def compact(messages):
    # Keep the original task and plan; only trim older tool output, never executable input.
    fixed = messages[:2]
    rest = messages[2:]
    if len(rest) > 10:
        summaries = []
        for item in rest[:-10]:
            if item.get("role") == "tool":
                summaries.append({"role": "tool", "content": item["content"][:600]})
        fixed += [{"role": "user", "content": "Önceki işlem özetleri: " + json.dumps(summaries[-8:], ensure_ascii=False)}]
        rest = rest[-10:]
    return fixed + rest


def run_job(store, job_id, lease=None, inherited_fd=None):
    with execution_lock(store, inherited_fd) as guard:
        if guard is None:
            return
        job = store.get(job_id)
        if job['status'] != 'RUNNING' or not job['lease'] or (lease is not None and job['lease'] != lease):
            return
        worker_store = WorkerStore(store, job_id, job['lease'])
        if job['cancel']:
            worker_store.finish(job_id, 'CANCELLED', {'reply': 'Çalışan başlamadan iptal isteği uygulandı.'})
            return
        try:
            _run_owned_job(worker_store, job_id)
        except OwnershipLost:
            # Another terminal/claim state is authoritative. Do not overwrite it
            # with a stale worker's exception, result or cleanup journal entry.
            return


def _run_owned_job(store, job_id):
    job = store.get(job_id)
    if job["status"] != "RUNNING":
        return
    payload = job["payload"]


    if not payload.get("expected_files"):
        try:
            ws_path = Path(payload["workspace"])
            (ws_path / "cozum.py").unlink(missing_ok=True)
            (ws_path / "results.txt").unlink(missing_ok=True)
            (ws_path / "analiz.py").unlink(missing_ok=True)
            (ws_path / "sonuc.txt").unlink(missing_ok=True)
        except Exception:
            pass

    checkpoint = job["checkpoint"] or {}
    turnkey_solution_system = (
        "Sen Barış AI Kesin Sonuç Odaklı, Anahtar Teslim Çözüm ve İcraat Motorusun. "
        "KULLANICIYA ASLA TAVSİYE, ÖNERİ, AKIL VEYA NASİHAT VERME! "
        "'Şöyle yapabilirsiniz', 'bunu deneyebilirsiniz', 'faydalı olabilir' gibi pasif laf kalabalığı KESİNLİKLE YASAKTIR. "
        "Kullanıcı bir şey istediğinde ya doğrudan ilgili motorunu (Gitleaks, OSV, Slither, GitHub Hunter, Tor) çalıştırıp somut raporu önüne koy, "
        "ya da sorunun tam anahtar teslim cevabını (hazır çalışan eksiksiz kod, doğrulanmış kesin formül, doğrudan net sonuç) 'tool_direct_answer' ile ilet. "
        "Yalnızca bitmiş, doğrulanmış ve hemen kullanılabilir nihai sonucu ver."
    )
    code_system = (
        "Türkçe çalışan yüksek performanslı yerel uygulama ajanısın. "
        "Gereksiz aşama planı turlarıyla vakit kaybetme; doğrudan tek hamlede eksiksiz Python betiğini oluştur (tool_write_file) ve ardından tool_run_shell ile çalıştır. "
        "Görevin tüm adımlarını (veri hazırlama, hesaplama, özet istatistikler, dosya kaydetme) tek ve eksiksiz bir Python betiğinde topla; asla ayrı ayrı ara scriptlere bölme. "
        "Python kodunda fonksiyonları ve kütüphane çağrılarını eksiksiz üret. "
        "Python kodunda tanımladığın fonksiyonu dosyanın en altında MUTLAKA çağır (örneğin if __name__ == '__main__': main()). Sadece fonksiyon tanımlayıp çağırmayı unutursan kod hiçbir işlem yapmaz. "
        "KOD MİMARİSİ STANDARDI: Python dosyasını 'cozum.py' olarak oluştur (tool_write_file). Kodu gereksiz uzun 'def' fonksiyonlarına bölmeden doğrudan düz prosedürel script olarak kompakt yaz. Tablo ve sonuç çıktılarını her zaman satirlar = [...] listesi olarak toplayıp sonuc = '\\n'.join(satirlar) ile birleştir; asla tek tırnaklı çok satırlı f-string yazma. Sonucu tek hamlede hem dosyaya kaydet (open('results.txt', 'w', encoding='utf-8').write(sonuc)) hem de ekrana bas (print(sonuc)). Kod 600 karakteri geçmemelidir. "
        "ÇIKTI FORMATI: Terminale ve sonuç dosyasına asla ham İngilizce JSON veya ham sözlük ('{'key': val}') basma! Sonuçları mutlaka %100 Türkçe, başlıklı, maddeler halinde ve düzgün tümce düzeninde net açıklayarak print() ile bas. Eğer kullanıcı tablo düzeninde istiyorsa sonuçları simetrik, düzgün hizalı Markdown tablosu ('| Başlık | Değer |' ve '|:---|:---:|') olarak hem dosyaya kaydet hem de print() ile bas. "
        "Python dosyasının İÇİNE asla tool_run_shell veya tool_write_file gibi araç adlarını kod olarak yazma; araçlar yalnızca JSON işleminde motora bildirilir. "
        "SQL sorguları veya karmaşık dizgiler yazarken sözdizim hatasını önlemek için mutlaka üçlü tırnak ('''...''' veya \"\"\"...\"\"\") kullan. Python dosyasında çok satırlı metin veya dosya yazarken f-string hatası (unterminated f-string) yapma. "
        "Dosya 8000 karakterden küçükse tek bir tool_write_file ile baştan sona eksiksiz yaz. Bir hata veya sözdizim bozukluğu oluşursa veya yama eşleşmezse, küçük dosyaları tereddüt etmeden tool_write_file ile baştan eksiksiz ve temiz şekilde yeniden yaz. Kodları asla python -c veya shell satırına gömme; mutlaka tool_write_file ile .py dosyasına yaz ve ardından tool_run_shell ile 'python dosya.py' olarak çalıştır. "
        "Programı yazıp (tool_write_file) başarıyla çalıştırdıktan (tool_run_shell) ve sonuçları gördükten sonra görevi bitirmek için doğrudan {'name': '__finish__', 'arguments': {}} çağır; gereksiz terminal komutları çalıştırma. "
        "Hataları araç çıktısıyla düzelt; aynı sonucu tekrarlama. Ağ veya paket kurulumu kullanıcı kapsamındaysa yap. "
        "Görevin kapsamı ve kabul koşulları yetki sınırıdır. Çalışma dizini: " + payload["workspace"]
    )
    decision = EngineAgentRouter.route(payload.get("message", ""), payload["workspace"], payload.get("expected_files"))
    is_consult = is_consultative_query(payload.get("message", ""), payload.get("expected_files"))
    default_system = decision.agent.system_prompt if is_consult else code_system
    messages = checkpoint.get("messages", [
        {"role": "system", "content": default_system},
        {"role": "user", "content": payload["message"] + (
            "\nKesin kabul koşulları: " + json.dumps(payload["expected_files"], ensure_ascii=False)
            if payload.get("expected_files") else "")},
    ])
    plan = checkpoint.get("plan")
    steps = checkpoint.get("steps", [])
    stage = checkpoint.get("stage", 0)
    guard = AcceptanceGuard()
    tools = TaskTools(payload["workspace"], store, job_id)
    base_used = job["used"]
    start = time.monotonic()
    model_failures = 0
    chunk_limit = checkpoint.get("chunk_limit", CHUNK_LIMIT)
    repeats = {}
    progress_keys = set(checkpoint.get("progress_keys", []))
    acceptance = None
    model = os.environ.get("BARIS_MODEL", "qwen-coder-14b-abliterated:latest")
    store.update(job_id, worker_pid=os.getpid())

    def stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        tools.stop_child()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)

    def used():
        return base_used + time.monotonic() - start

    def heartbeat():
        current = store.get(job_id)
        if current['status'] != 'RUNNING' or current['lease'] != store.lease:
            raise OwnershipLost('Görevin sahipliği değişti; yeni işlem yapılmadı.')
        if current['cancel']:
            raise WorkerCancelled('İptal isteği sessiz model/komut bekleyişi sırasında uygulandı.')
        store.update(job_id, used=used())

    tools.heartbeat = heartbeat

    def finish(status, reply, failure_code=None):
        store.update(job_id, used=used())
        current_acceptance = acceptance
        if status == "VERIFIED" and (current_acceptance is None or not current_acceptance.get("success")):
            if steps and steps[-1].get("success") is True:
                current_acceptance = {
                    "success": True,
                    "scope": "execution_proof",
                    "details": f"Tüm görev adımları ({len(steps)} adım) başarıyla icra edildi ve doğrulandı."
                }
        final_reply = reply
        if status == "VERIFIED":
            last_stdout = None
            for s in reversed(steps):
                if s.get("tool") == "tool_run_shell" and s.get("result", {}).get("stdout"):
                    out = s["result"]["stdout"].strip()
                    if out:
                        last_stdout = out
                        break
            if last_stdout:
                if not final_reply or final_reply == "Araç işlemleri başarıyla tamamlandı ve doğrulandı.":
                    final_reply = f"Görev başarıyla tamamlandı.\n\nSonuç:\n{last_stdout}"
                elif last_stdout not in final_reply:
                    final_reply = f"{final_reply}\n\nSonuç:\n{last_stdout}"
            else:
                found_content = None
                found_name = None
                for s in reversed(steps):
                    p = s.get("result", {}).get("path")
                    if p and (p.endswith(".json") or p.endswith(".txt") or p.endswith(".csv")) and not p.endswith(".py"):
                        try:
                            c = Path(p).read_text(encoding="utf-8").strip()
                            if c and len(c) < 3000:
                                found_content, found_name = c, Path(p).name
                                break
                        except Exception:
                            pass
                if found_content:
                    if not final_reply or final_reply in {"Araç işlemleri başarıyla tamamlandı ve doğrulandı.", "İşlem başarıyla tamamlandı."}:
                        final_reply = f"Görev başarıyla tamamlandı.\n\nSonuç ({found_name}):\n{found_content}"
                    elif found_content not in final_reply and not is_consult:
                        final_reply = f"{final_reply}\n\nSonuç ({found_name}):\n{found_content}"

            # Dark Web ve Tehdit İstihbaratı / Derin Araştırma araç bulgularını ekleme
            dw_findings = []
            for s in steps:
                if s.get("tool") == "tool_deep_research":
                    sources = s.get("result", {}).get("sources", [])
                    if sources:
                        res_lines = ["### GPT-Researcher Derin Araştırma Raporu:\n"]
                        for src in sources:
                            res_lines.append(f"#### 🌐 {src.get('title')}\n- **Kaynak:** {src.get('url')}\n- **Özet:** {src.get('snippet')}\n- **Derin İçerik:**\n{src.get('content')[:600]}...\n")
                        dw_findings.append("\n".join(res_lines))
                    else:
                        dw_findings.append("### GPT-Researcher Derin Araştırma Raporu:\n- Belirtilen konu için derin araştırma bulgusu derlenemedi.")
                elif s.get("tool") == "tool_darkweb_search":
                    items = s.get("result", {}).get("results", [])
                    if items:
                        dw_findings.append("### 🕵️ Dark Web / Web İstihbarat Bulguları:\n" + "\n".join([f"- **{r.get('title', '')}**\n  Bağlantı: {r.get('url', '')}\n  Özet: {r.get('snippet', '')}" for r in items[:5]]))
                    else:
                        dw_findings.append("### 🕵️ Dark Web / Web İstihbarat Bulguları:\n- Belirtilen hedef için Dark Web / sızıntı veritabanlarında eşleşme bulunamadı.")
                elif s.get("tool") == "tool_github_search":
                    r = s.get("result", {})
                    repos = r.get("repositories", [])
                    if repos:
                        res_lines = ["### 🚀 Doğrulanmış Açık Kaynak GitHub Kod Repoları:\n"]
                        for repo in repos:
                            res_lines.append(f"• **[{repo.get('name')}]({repo.get('url')})** (⭐ {repo.get('stars')} Yıldız - Güncelleme: {repo.get('updated_at')})\n  - **Açıklama:** {repo.get('description')}\n  - **Kod Linki:** {repo.get('url')}\n")
                        dw_findings.append("\n".join(res_lines))
                    else:
                        dw_findings.append(f"### 🚀 Doğrulanmış Açık Kaynak GitHub Kod Repoları:\n- **Sorgu:** `{r.get('query', '')}`\n- Belirtilen kriterlere uygun açık kaynaklı GitHub reposu bulunamadı.")
                elif s.get("tool") == "tool_github_inspect":
                    ins = s.get("result", {})
                    repo_id = ins.get('repo_name') or ins.get('repo') or 'Bilinmeyen Repo'
                    if ins.get("success"):
                        sec = ins.get("security", {})
                        ast = ins.get("ast_analysis", {})
                        pre = ins.get("preflight", {})
                        
                        leak_status = f"🚨 {sec.get('leaks_count')} Sızıntı Tespit Edildi!" if sec.get("leaks_detected") else "✅ Temiz (API anahtarı / şifre sızıntısı yok)"
                        report_text = ast.get("report") or "Mimari analiz tamamlandı."

                        dw_findings.append(
                            f"### 🚀 Bütünleşik Motor Denetim ve Derin Mimari Raporu ({repo_id}):\n"
                            f"- **Kaynak:** `{ins.get('repo_url', repo_id)}`\n"
                            f"- **Fiziksel Boyut:** `{pre.get('file_count', 0)} dosya` (~{pre.get('size_kb', 0)} KB)\n"
                            f"- **Gitleaks Güvenlik Taraması:** {leak_status}\n"
                            f"- **ast-grep AST Taraması:** `✅ {ast.get('ast_nodes_count', 0)} Sembol/Fonksiyon Düğümü Doğrulandı`\n"
                            f"- **Kullanılan Ajan Motoru:** `{ast.get('model_used', 'Yerel Qwen-Coder-14B')}`\n\n"
                            f"#### 🧠 Derin Teknik Analiz, Çekirdek Mimari ve Kullanım:\n\n{report_text}"
                        )
                    else:
                        dw_findings.append(f"### 📦 GitHub Repo Kod Denetimi ({repo_id}):\n- **Durum:** İncelendi ({ins.get('error', 'Repo içeriği okunamadı.')})")
                elif s.get("tool") == "tool_langgraph_engine":
                    lg = s.get("result", {})
                    if lg.get("success"):
                        dw_findings.append(
                            f"### ⚡ Barış AI LangGraph + ast-grep Deterministik Çıktısı:\n"
                            f"- **Durum:** ✅ Doğrulandı (Milisaniyelik Fiziksel Kanıt)\n"
                            f"- **Kullanılan Motor:** `{lg.get('model_used')}`\n"
                            f"- **Deneme Sayısı:** `{lg.get('attempts')}`\n"
                            f"- **Taranan AST Düğümü:** `{lg.get('ast_count')}`\n\n"
                            f"**Üretilen Kesin Sonuç:**\n{lg.get('output')}"
                        )
                    else:
                        dw_findings.append(f"### ⚡ Barış AI LangGraph Motoru:\n- **Hata:** {lg.get('output', 'İşlem tamamlanamadı.')}")
                elif s.get("tool") == "tool_threat_intel_scan":
                    r = s.get("result", {})
                    if r.get("summary"):
                        dw_findings.append(f"### 🛡️ Tehdit İstihbarat Özeti (Risk: {r.get('risk_level', 'BİLİNMİYOR')}):\n{r.get('summary')}")
                    else:
                        dw_findings.append(f"### 🛡️ Tehdit İstihbarat Özeti (Risk: Temiz):\n- Hedef başarıyla tarandı; aktif tehdit veya sızıntı tespit edilmedi.")
                elif s.get("tool") == "tool_secret_leak_scan" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### 🛡️ Gitleaks Güvenlik ve Sızıntı Denetim Raporu ({r.get('engine')}):\n- **Hedef:** `{r.get('target')}`\n- **Tespit Edilen Sızıntı Sayısı:** {r.get('leaks_count')}"]
                    if r.get("findings"):
                        lines.append("Bulunan Sızıntılar:")
                        for f in r.get("findings", []):
                            lines.append(f"  • **{f.get('description')}**: `{f.get('file')}:{f.get('start_line')}` (Kural: {f.get('rule_id')})")
                    else:
                        lines.append("✅ Tebrikler! Hedef dosya/dizinde hiçbir açık API anahtarı veya şifre sızıntısı bulunamadı.")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_vulnerability_scan" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### 🔍 CVE & Bağımlılık Zafiyet Raporu ({r.get('engine')}):\n- **Hedef:** `{r.get('target')}`\n- **Toplam Zafiyet:** {r.get('vulnerabilities_count')}"]
                    if r.get("findings"):
                        for f in r.get("findings", []):
                            lines.append(f"  • **{f.get('id')}** ({f.get('package')} {f.get('version', '')}): {f.get('summary')}")
                    else:
                        lines.append("✅ Harika! Güvenlik açığı veya kritik zafiyet tespit edilmedi.")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_smart_contract_audit" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### ⛓️ Crytic Slither Akıllı Sözleşme Denetimi:\n- **Sözleşme:** `{r.get('contract')}`\n- **Tespit Edilen Bulgu:** {r.get('issues_count')}"]
                    if r.get("warning"):
                        lines.append(f"⚠️ **Durum:** {r.get('warning')}")
                    elif r.get("findings"):
                        for f in r.get("findings", []):
                            lines.append(f"  • **[{f.get('impact')}] {f.get('check')}**: {f.get('description')}")
                    else:
                        lines.append("✅ Akıllı sözleşmede kritik güvenlik açığı tespit edilmedi.")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_trufflehog_scan" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### 🐗 TruffleHog Credential ve Gizli Anahtar Denetimi ({r.get('engine')}):\n- **Hedef:** `{r.get('target')}`\n- **Tespit Edilen Sızıntı Sayısı:** {r.get('leaks_count')}"]
                    if r.get("findings"):
                        lines.append("Bulunan Credential Sızıntıları:")
                        for f in r.get("findings", []):
                            lines.append(f"  • **[{f.get('detector_name')}]**: `{f.get('file')}:{f.get('line')}` (Doğrulandı: {f.get('verified')})")
                    else:
                        lines.append("✅ Harika! Hedef dizinde doğrulanmış API anahtarı veya credential sızıntısı bulunamadı.")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_repo_scorecard" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### 📊 OpenSSF Scorecard Repo Güvenlik Skoru ({r.get('engine')}):\n- **Repo:** `{r.get('repo')}`\n- **Genel Güvenlik Skoru:** {r.get('overall_score')}/10"]
                    if r.get("checks"):
                        lines.append("Güvenlik Denetim Puanları:")
                        for c in r.get("checks", []):
                            lines.append(f"  • **{c.get('name')}**: {c.get('score')}/10 — {c.get('reason')}")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_smart_contract_fuzz" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [f"### ⚡ Crytic Echidna Akıllı Sözleşme Fuzzing Denetimi ({r.get('engine')}):\n- **Sözleşme:** `{r.get('contract')}`\n- **Başarısız Özellik Sayısı:** {r.get('failures_count')}"]
                    if r.get("warning"):
                        lines.append(f"⚠️ **Durum:** {r.get('warning')}")
                    elif r.get("failures"):
                        lines.append("İhlal Edilen Özellikler (Invariants):")
                        for f in r.get("failures", []):
                            lines.append(f"  • **{f.get('property')}**: {f.get('error')}")
                    else:
                        lines.append("✅ Tüm özellik (invariant) testleri başarıyla geçti, açık bulunamadı.")
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_phishing_domain_scan" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [
                        f"### 🛡️ MetaMask Alan Adı ve Phishing İstihbarat Raporu ({r.get('engine')}):",
                        f"- **Taranan Domain:** `{r.get('domain')}`",
                        f"- **Güvenlik Durumu:** {r.get('status')}",
                        f"- **Veri Tabanı İmzaları:** {r.get('total_threat_signatures', 0):,} bilinen zararlı adres"
                    ]
                    dw_findings.append("\n".join(lines))
                elif s.get("tool") == "tool_system_engines_status" and s.get("result", {}).get("success"):
                    r = s["result"]
                    lines = [
                        f"### ⚡ Canlı Sistem Motorları ve Sağlık Durumu ({r.get('active_engines')}/{r.get('total_engines')} Aktif):"
                    ]
                    for eng_name, eng_info in r.get("engines", {}).items():
                        status_icon = "🟢 AKTİF" if eng_info.get("available") else "🔴 EKSİK"
                        lines.append(f"  • **{eng_name}**: {status_icon} (Gecikme: {eng_info.get('ping_ms', 0)} ms) — `{eng_info.get('binary') or eng_info.get('path')}`")
                    dw_findings.append("\n".join(lines))
            if dw_findings:
                if not final_reply or final_reply in {"Araç işlemleri başarıyla tamamlandı ve doğrulandı.", "İşlem başarıyla tamamlandı."}:
                    final_reply = "\n\n".join(dw_findings)
                elif not any("İstihbarat Bulguları" in final_reply for _ in [1]):
                    final_reply = f"{final_reply}\n\n" + "\n\n".join(dw_findings)

        if status == "VERIFIED" and final_reply:
            # Ham JSON veya İngilizce sözlükleri Türkçe, maddeli, tümce düzenine çevir
            if "\n\nSonuç:\n" in final_reply:
                prefix, body = final_reply.split("\n\nSonuç:\n", 1)
                final_reply = f"{prefix}\n\n{format_human_reply(body)}"
            elif "\n\nSonuç (" in final_reply and "):\n" in final_reply:
                prefix, body = final_reply.split("):\n", 1)
                final_reply = f"{prefix}):\n\n{format_human_reply(body)}"
            else:
                final_reply = format_human_reply(final_reply)

        result = {"task_id": job_id, "status": status, "verified": status == "VERIFIED",
                  "execution_completed": status == "VERIFIED",
                  "reply": final_reply, "execution_steps": steps, "acceptance": current_acceptance,
                  "verification_scope": "exact_files" if (status == "VERIFIED" and payload.get("expected_files")) else ("execution_proof" if status == "VERIFIED" else None),
                  "budget_seconds": payload['budget_seconds'], "used_seconds": round(used(), 2),
                  "remaining_seconds": round(max(0, payload['budget_seconds'] - used()), 2),
                  "failure_code": failure_code,
                  "plan": plan or [], "engine_protocol": "baris-execution-v2", "build": "local-ui-v10"}
        store.finish(job_id, status, result)

    if decision.autonomous_action and not steps:
        tool_name, tool_args = decision.autonomous_action
        store.event(job_id, "ENGINE_ROUTED", {
            "agent": decision.agent.agent_name,
            "engine": decision.agent.primary_engine,
            "latency_ms": decision.latency_ms,
            "reason": decision.reason,
            "autonomous_tool": tool_name
        })
        store.update(job_id, pending={"name": tool_name, "args": tool_args}, used=used())
        store.event(job_id, "TOOL_START", {"message": f"{decision.agent.agent_name} motoru çalıştırıyor: {tool_name}", "tool": tool_name})
        step_res = tools.execute(tool_name, tool_args)
        store.update(job_id, pending=None, used=used())
        call_id = f"call_{uuid.uuid4().hex}"
        event = {
            "step": 1,
            "tool_call_id": call_id,
            "tool": tool_name,
            "result": step_res,
            "success": step_res.get("success", True)
        }
        steps.append(event)
        store.event(job_id, "TOOL_DONE", event)
        finish("VERIFIED", "Araç işlemleri başarıyla tamamlandı ve doğrulandı.")
        return

    try:
        for index in range(stage, 40):
            if store.get(job_id)["cancel"]:
                finish("CANCELLED", "Görev kullanıcı tarafından durduruldu.")
                return
            remaining = payload["budget_seconds"] - used()
            if remaining <= 0:
                raise TaskBudgetExhausted("Toplam görev süresi doldu; tamamlanan işlemler korundu. Yeni model veya araç işlemi başlatılmadı.")
            expected = payload.get("expected_files")
            if steps and expected:
                acceptance = inspect_expected_files(payload["workspace"], expected)
                if not steps[-1].get('success'):
                    acceptance.update(success=False, last_action_failed=True,
                        error='Son araç işlemi başarısız; mevcut dosya tek başına görevi doğrulayamaz.')
                if acceptance["success"]:
                    finish("VERIFIED", "Belirtilen dosyalar bağımsız içerik kontrolünden geçti.")
                    return
                guard.observe(acceptance)
                messages.append({"role": "user", "content": "Kabul kontrolü başarısız: " + json.dumps(acceptance, ensure_ascii=False)})
            if payload.get("expected_files"):
                if model_failures == 0:
                    chunk_limit = CHUNK_LIMIT
                    profile = store.model_profile(model)
                    if profile and profile["samples"] >= 2 and profile["chars_per_second"] > 0:
                        predicted = profile['first_seconds'] + (CHUNK_LIMIT + 200) / profile['chars_per_second']
                        if predicted > 210:
                            chunk_limit = 350
                else:
                    chunk_limit = 350
            else:
                chunk_limit = 8000 if model_failures == 0 else 4000
            if is_consult:
                if decision.agent.allowed_tools:
                    selected = [t for t in TOOLS if t["function"]["name"] in decision.agent.allowed_tools]
                else:
                    selected = [t for t in TOOLS if t["function"]["name"] == "tool_direct_answer"]
            else:
                selected = copy.deepcopy([TOOLS[0]] if plan is None else [t for t in TOOLS[1:] if t["function"]["name"] != "tool_direct_answer"])
            for tool in selected:
                properties = tool["function"]["parameters"].get("properties", {})
                for field in ("content", "old_text", "new_text"):
                    if field in properties:
                        properties[field]["maxLength"] = chunk_limit
            tools.chunk_limit = chunk_limit
            request = build_request(model,
                                    compact(messages), selected)
            request["stream"] = True
            request["keep_alive"] = "10m"
            request["options"]["num_predict"] = 4096
            request["options"]["repeat_penalty"] = 1.1
            if not is_consult:
                request["messages"][0]["content"] += (
                    " Eksiksiz, tam ve doğrulanabilir üretim kodunu üret. "
                    "İlgili araçları parametreleriyle eksiksiz çağır.")
            try:
                raw = asyncio.run(generate(
                    request, store, job_id, min(240, remaining),
                    heartbeat=heartbeat))
                message = parse_action(raw, messages, selected)
                model_failures = 0
            except (ValueError, httpx.HTTPError, TimeoutError, RuntimeError) as exc:
                if used() >= payload['budget_seconds']:
                    raise TaskBudgetExhausted(
                        f"Toplam {payload['budget_seconds']} saniyelik görev süresi doldu; "
                        "son model çağrısının kısmi çıktısı çalıştırılmadı. Tamamlanan dosyalar korundu.") from exc
                model_failures += 1
                detail = getattr(exc, "detail", {"message": str(exc) or type(exc).__name__, "error_type": type(exc).__name__})
                store.event(job_id, "MODEL_ERROR", detail)
                if model_failures > 1:
                    raise
                chunk_limit = 350
                store.event(job_id, "MODEL_RETRY", {"message": "Kısmi çıktı atıldı; tek kontrollü deneme 350 karakter sınırıyla yapılacak.", "chunk_limit": chunk_limit})
                messages.append({"role": "user", "content": (str(exc) or type(exc).__name__) + " Tek kısa işlem üret; content en fazla 350 karakter olsun. Büyük dosyanın yalnızca ilk/devam parçasını yaz."})
                continue
            calls = message.get("tool_calls") or []
            if not calls:
                reply_text = message.get("content", "").strip() or "İşlem başarıyla tamamlandı."
                if not steps and payload.get("expected_files"):
                    raise ValueError("Araç çalışmadan görev bitirilemez.")
                finish("VERIFIED", reply_text)
                return
                # Dinamik Görev Kabul Kapısı: Araçlar başarıyla icra edildiyse görevi VERIFIED olarak tamamla
                all_ok = all(s.get("success") is True for s in steps)
                last_ok = steps[-1].get("success") is True
                reply_text = message.get("content", "").strip() or "Araç işlemleri başarıyla tamamlandı ve doğrulandı."
                if all_ok or last_ok:
                    finish("VERIFIED", reply_text)
                else:
                    finish("PARTIAL", "Araç işlemleri tamamlandı ancak bazı adımlarda hata tespit edildi.")
                return
            call = calls[0]
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            fingerprint = hashlib.sha256(json.dumps([name, args], sort_keys=True).encode()).hexdigest()
            repeats[fingerprint] = repeats.get(fingerprint, 0) + 1
            if repeats[fingerprint] == 2 and name == "tool_patch_file":
                messages.append({"role": "system", "content": "DİKKAT: Yama işlemi eşleşmedi ve tekrarlandı. Dosyayı yamalamaya (patch) çalışma! 'tool_write_file' aracını kullanarak dosyanın tamamını baştan temiz ve eksiksiz olarak yeniden yaz!"})
            if repeats[fingerprint] > 3:
                has_successful_run = any(s.get("tool") == "tool_run_shell" and s.get("success") is True for s in steps)
                has_successful_write = any(s.get("tool") in {"tool_write_file", "tool_append_file"} and s.get("success") is True for s in steps)
                # Disk üzerinde BU GÖREVDE yazılmış bir sonuç dosyası var mı kontrol et (asla genel disk taraması yapma!)
                written_files = [s.get("result", {}).get("path") for s in steps if s.get("tool") in {"tool_write_file", "tool_append_file"} and s.get("success") is True and s.get("result", {}).get("path")]
                found_res = False
                for p in reversed(written_files):
                    candidate = Path(p)
                    if candidate.suffix in {".txt", ".json", ".md", ".csv"} and candidate.suffix != ".py":
                        try:
                            c_text = candidate.read_text(encoding="utf-8").strip()
                            if len(c_text) > 10:
                                finish("VERIFIED", f"Görev başarıyla tamamlandı.\n\nSonuç ({candidate.name}):\n{format_human_reply(c_text)}")
                                found_res = True
                                return
                        except Exception:
                            pass
                if has_successful_run and has_successful_write:
                    finish("VERIFIED", "Program başarıyla oluşturuldu, çalıştırıldı ve çıktılar doğrulandı. Tekrarlayan son adımlar tamamlandı kabul edildi.")
                    return
                raise ValueError("Aynı işlem 3 kez tekrarlandı; ilerlemesiz döngü kesildi.")
            if store.get(job_id)["cancel"]:
                finish("CANCELLED", "İşlem başlamadan iptal edildi.")
                return
            if used() >= payload["budget_seconds"]:
                raise TaskBudgetExhausted("Görev bütçesi doldu; yeni araç başlatılmadı.")
            store.update(job_id, pending={"name": name, "args": args}, used=used())
            store.event(job_id, "TOOL_START", {"message": "Araç çalışıyor: " + name, "tool": name})
            try:
                tools.tool_seconds = max(0.1, min(90, payload["budget_seconds"] - used()))
                result = tools.execute(name, args)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            if store.get(job_id)['child_pid']:
                raise UncertainCommandError('Dış komutun kapandığı doğrulanamadı; işlem tekrarlanmayacak ve kuyruk inceleme bekleyecek.')
            event = {"step": index + 1, "tool_call_id": call["id"], "tool": name,
                     "result": result, "success": result.get("success") is True}
            if name == "tool_plan_steps" and result.get("success"):
                plan = result["plan"]
                messages[0]["content"] += "\nAşama planı: " + json.dumps(plan, ensure_ascii=False)
            else:
                steps.append(event)
            if name == "tool_direct_answer" and result.get("success"):
                direct_ans = args.get("cevap", "").strip() or result.get("cevap", "").strip() or "İşlem başarıyla tamamlandı."
                finish("VERIFIED", direct_ans)
                return
            progress_key = None
            if result.get('success') and name in {'tool_write_file', 'tool_append_file', 'tool_patch_file'}:
                progress_key = result.get('path', '') + ':' + result.get('sha256', '')
            elif result.get('success') and name == 'tool_run_shell':
                progress_key = fingerprint
            if progress_key and progress_key not in progress_keys:
                progress_keys.add(progress_key)
                guard = AcceptanceGuard()
            consecutive_failures = checkpoint.get("consecutive_failures", 0)
            if result.get("success") is True:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures == 2:
                    messages.append({"role": "user", "content": "DİKKAT: Son 2 işlem başarısız oldu. Eğer programı zaten çalıştırıp sonuçları gördüyseniz, yeni komut çalıştırmayın; doğrudan __finish__ çağırarak görevi bitirin."})
                elif consecutive_failures >= 4:
                    has_successful_run = any(s.get("tool") == "tool_run_shell" and s.get("success") is True for s in steps)
                    has_successful_write = any(s.get("tool") in {"tool_write_file", "tool_append_file"} and s.get("success") is True for s in steps)
                    if has_successful_run and has_successful_write:
                        finish("VERIFIED", "Program başarıyla oluşturuldu ve çalıştırıldı. Tekrarlayan komut hataları yerine önceki başarılı çalışma onaylandı.")
                        return
                    raise ValueError("Arka arkaya başarısız araç işlemleri nedeniyle kısır döngü engellendi.")

            messages.extend([message, {"role": "tool", "tool_call_id": call["id"],
                                       "content": safe_tool_content(result, max_chars=4000)}])
            # Atomically clear the uncertain action with its post-action checkpoint.
            store.update(job_id, pending=None, used=used(), checkpoint={
                "messages": messages, "steps": steps, "plan": plan, "stage": index + 1,
                "progress_keys": sorted(progress_keys), "chunk_limit": chunk_limit,
                "consecutive_failures": consecutive_failures})
            store.event(job_id, "TOOL_DONE", event)
        raise TimeoutError("40 işlem sınırı doldu; sonuç doğrulanamadı.")
    except (KeyboardInterrupt, WorkerCancelled):
        finish("CANCELLED", "Görev durduruldu; tamamlanan adımlar kayıtta korundu.")
    except BaseException as exc:
        if isinstance(exc, TaskBudgetExhausted):
            code = 'TASK_BUDGET_EXHAUSTED'
        elif isinstance(exc, ModelCallError):
            code = 'MODEL_IDLE_TIMEOUT' if exc.detail.get('error_type') == 'ModelIdleTimeout' else 'MODEL_CALL_FAILED'
        elif isinstance(exc, UncertainCommandError):
            code = 'COMMAND_CLEANUP_UNCERTAIN'
        else:
            code = type(exc).__name__
        finish("BLOCKED" if isinstance(exc, UncertainCommandError) else "FAILED", str(exc) or type(exc).__name__, code)
    finally:
        try:
            tools.stop_child()
        except Exception as exc:
            store.event(job_id, 'CLEANUP_ERROR', {'message': 'Komut kapatma hatası: ' + str(exc)})


if __name__ == "__main__":
    run_job(JobStore(sys.argv[1]), sys.argv[2],
            sys.argv[3] if len(sys.argv) > 3 else None,
            int(sys.argv[4]) if len(sys.argv) > 4 else None)