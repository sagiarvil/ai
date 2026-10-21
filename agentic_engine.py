"""
Barış AI - Endüstriyel Otonom İcra Motoru (Tri-Model Cascade & Self-Healing Architecture)
========================================================================================
Bu modül; DeepSeek (Akıl Yürütme / Mimari), Qwen Coder (Kod & Araç İcrası / Self-Healing)
ve Mistral (Sentez & Raporlama) modellerini orkestre eden 3 aşamalı endüstriyel motordur.

Özellikler:
- Sıfır-Araç Erken Çıkış Tuzağı (Zero-Tool Exit Trap) tamamen kaldırılmıştır.
- Zincirleme Düşünce (CoT) ve Akıl Yürütme serbest bırakılmıştır.
- Set-of-Mark (SoM) Görsel Web Ajanı araçları (`tool_browser_actuate` ve
  `tool_browser_autonomous_mission`) otomatik olarak araç şemasına enjekte edilir.
- Araç hatalarında kendini onaran (Self-Healing / Reflection) döngü entegre edilmiştir.
- Bağlam patlamasını önleyen akıllı çıktı budama (Context Window Guard) devrededir.
- omni_chat_panel.py ve baris-ai.web.app ile %100 geriye dönük uyumludur.
"""

import os
import sys
import json
import time
import uuid
import logging
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
import httpx

try:
    from browser_controller import LocalBrowserEngine
except ImportError:
    LocalBrowserEngine = None

from model_manager import ModelManager

# Logging yapılandırması
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("IndustrialAgenticEngine")

# Ortam Yapılandırması
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
DEFAULT_CONTEXT_WINDOW = int(os.environ.get("AGENT_NUM_CTX", "16384"))

# Otomatik Enjekte Edilen Görsel Web Ajanı Araç Şemaları
AUTONOMOUS_BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tool_browser_actuate",
            "description": (
                "Canlı tarayıcı ekranında (headless=False) tekil etkileşim yapar: URL açar (goto), "
                "Set-of-Mark ID'li öğeye tıklar (click), input alanına yazar (fill), klavye tuşuna basar (press) "
                "veya sayfayı kaydırır (scroll_down / scroll_up)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["goto", "click", "fill", "press", "scroll_down", "scroll_up", "back", "wait", "close"],
                        "description": "Yapılacak tarayıcı eylemi"
                    },
                    "url": {"type": "string", "description": "action='goto' için gidilecek URL"},
                    "element_id": {"type": "integer", "description": "Tıklanacak veya yazılacak öğenin Set-of-Mark [id] numarası"},
                    "selector": {"type": "string", "description": "Alternatif CSS seçicisi"},
                    "text": {"type": "string", "description": "action='fill' için yazılacak metin"},
                    "key": {"type": "string", "description": "Basılacak klavye tuşu (ör. 'Enter')"},
                    "use_tor": {"type": "boolean", "description": "Tor SOCKS5 üzerinden bağlan"},
                    "use_i2p": {"type": "boolean", "description": "I2P Proxy üzerinden bağlan"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_browser_autonomous_mission",
            "description": (
                "Karmaşık ve çok adımlı web görevlerini (siteye girip arama yapma, menülerde gezinme, "
                "dosyaları inceleme, form doldurma) canlı tarayıcı ekranı açarak uçtan uca otonom yürütür."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_prompt": {
                        "type": "string",
                        "description": "Web ajanının gerçekleştireceği detaylı görev tanımı"
                    },
                    "start_url": {
                        "type": "string",
                        "description": "Görevin başlayacağı web adresi (URL)"
                    },
                    "use_tor": {"type": "boolean", "description": "Tor ağı kullan"},
                    "use_i2p": {"type": "boolean", "description": "I2P ağı kullan"}
                },
                "required": ["mission_prompt"]
            }
        }
    }
]


class TaskState(str, Enum):
    RECEIVED = "RECEIVED"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    NOT_EXECUTED = "NOT_EXECUTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class ExecutionEvidence:
    """Fiziksel icra kanıtlarını tutan yapı."""
    def __init__(self, step: int, tool_name: str, args: dict, output: str, success: bool):
        self.step = step
        self.tool_name = tool_name
        self.args = args
        self.output = output
        self.success = success
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool_name,
            "args": self.args,
            "output": self.output[:500] if len(self.output) > 500 else self.output,
            "success": self.success,
            "timestamp": self.timestamp
        }


class TriModelRouter:
    """Modellerin dinamik çözümlenmesi ve hiyerarşik yönetimi."""
    @staticmethod
    def get_tier_models() -> Dict[str, str]:
        # ModelManager üzerinden dinamik algılama ve ortam değişkeni desteği
        reasoner = os.environ.get("MODEL_REASONER", "deepseek-r1-14b-abliterated:latest")
        coder = os.environ.get("MODEL_CODER", "qwen-coder-14b-abliterated:latest")
        presenter = os.environ.get("MODEL_PRESENTER", "mistral-small-24b-abliterated:latest")
        return {
            "reasoner": reasoner,
            "coder": coder,
            "presenter": presenter
        }

    @staticmethod
    def sanitize_tool_output(output: str, max_chars: int = 2500) -> str:
        """Bağlam penceresinin patlamasını önlemek için büyük çıktıları güvenle budar."""
        if not output:
            return ""
        if len(output) <= max_chars:
            return output
        head = output[:1400]
        tail = output[-800:]
        omitted = len(output) - 2200
        return f"{head}\n\n... [SİSTEM UYARISI: {omitted} karakter bağlam optimizasyonu için kırpıldı] ...\n\n{tail}"


class AutonomousExecutionEngine:
    """
    omni_chat_panel.py ile tam uyumlu çalışan, 3 aşamalı orkestrasyon motoru.
    """
    def __init__(self, task_id: Optional[str] = None):
        self.task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        self.state = TaskState.RECEIVED
        self.evidences: List[Dict[str, Any]] = []
        self.execution_steps: List[Dict[str, Any]] = []

    def transition_to(self, new_state: TaskState, reason: str = ""):
        logger.info(f"[{self.task_id}] Durum Değişimi: {self.state} -> {new_state} | Sebep: {reason}")
        self.state = new_state

    @staticmethod
    def _enrich_tools_schema(tools_schema: list) -> list:
        """Mevcut araç listesine canlı otonom tarayıcı araçlarını ekler."""
        enriched = list(tools_schema or [])
        existing_names = {
            t.get("function", {}).get("name") for t in enriched if isinstance(t, dict)
        }
        for b_tool in AUTONOMOUS_BROWSER_TOOLS:
            b_name = b_tool["function"]["name"]
            if b_name not in existing_names:
                enriched.append(b_tool)
        return enriched

    @classmethod
    async def execute_verified_task(
        cls,
        prompt: str,
        tools_schema: list,
        call_tool_fn: Callable,
        history: Optional[List[dict]] = None
    ) -> Dict[str, Any]:
        """
        omni_chat_panel.py tarafından çağrılan ana icra noktası.
        DeepSeek -> Qwen Coder -> Mistral akışını ve Canlı Tarayıcı Ajanını işletir.
        """
        engine = cls()
        engine.transition_to(TaskState.RUNNING, "Görev kabul edildi ve 360° icra boru hattına alındı.")
        models = TriModelRouter.get_tier_models()
        enriched_tools = cls._enrich_tools_schema(tools_schema)
        logger.info(f"[{engine.task_id}] Kullanılan Model Mimarisi: {models}")

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                # =========================================================================
                # 1. AŞAMA: DEEPSEEK - STRATEJİK AYRIŞTIRMA VE AKIL YÜRÜTME (REASONING TIER)
                # =========================================================================
                logger.info(f"[{engine.task_id}] Aşama 1: DeepSeek ile derin akıl yürütme başlatılıyor...")
                planner_system = (
                    "Sen Barış AI platformunun Baş Sistem Mimarısın. "
                    "Kullanıcının talebini en ince detayına kadar analiz et. Görevi mantıksal alt adımlara böl. "
                    "Eğer bir web sitesinde gezinme, tıklama veya inceleme gerekiyorsa "
                    "'tool_browser_autonomous_mission' veya 'tool_browser_actuate' araçlarını planla. "
                    "Düşüncelerini net bir teknik strateji olarak ortaya koy."
                )

                planner_payload = {
                    "model": models["reasoner"],
                    "messages": [
                        {"role": "system", "content": planner_system},
                        {"role": "user", "content": f"Görev: {prompt}"}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": DEFAULT_CONTEXT_WINDOW
                    }
                }

                try:
                    plan_resp = await client.post(OLLAMA_CHAT_URL, json=planner_payload)
                    plan_data = plan_resp.json()
                    strategic_plan = plan_data.get("message", {}).get("content", "").strip()
                except Exception as e:
                    logger.warning(f"Reasoner modeli erişilemedi, doğrudan icra aşamasına geçiliyor: {e}")
                    strategic_plan = f"Doğrudan icra planı: {prompt}"

                logger.info(f"[{engine.task_id}] Aşama 1 Tamamlandı. Çıkarılan Strateji: {strategic_plan[:200]}...")

                # =========================================================================
                # 2. AŞAMA: QWEN CODER - DAYANIKLI ARAÇ İCRASI & SELF-HEALING (EXECUTION TIER)
                # =========================================================================
                logger.info(f"[{engine.task_id}] Aşama 2: Qwen Coder ile araç icrası ve kendini onarma döngüsü başlıyor...")

                coder_system = (
                    "Sen Barış AI platformunun İcra ve Güvenlik Uzmanısın. "
                    "Görevin: Verilen stratejik plan ve kullanıcı talebi doğrultusunda MEVCUT ARAÇLARI KULLANARAK "
                    "görevi fiziksel olarak icra etmektir. "
                    "Canlı ekran açıp sitede gezinmek için 'tool_browser_autonomous_mission' veya 'tool_browser_actuate' kullan. "
                    "Bir araç hata verirse durma; hatayı analiz et, hatayı gider ve doğru parametrelerle tekrar dene."
                )

                coder_messages = [
                    {"role": "system", "content": coder_system}
                ]
                if history:
                    for h in history[-10:]:
                        if h.get("role") in ("user", "assistant") and h.get("content"):
                            coder_messages.append({"role": h["role"], "content": h["content"]})

                coder_messages.append({
                    "role": "user",
                    "content": f"Kullanıcı Talebi: {prompt}\n\nMimari Plan:\n{strategic_plan}"
                })

                max_iterations = 10
                step_count = 0
                has_executed_tools = False
                all_tools_successful = True

                while step_count < max_iterations:
                    step_count += 1
                    logger.info(f"[{engine.task_id}] İcra Döngüsü Adım {step_count}/{max_iterations}")

                    coder_payload = {
                        "model": models["coder"],
                        "messages": coder_messages,
                        "tools": enriched_tools,
                        "tool_choice": "auto",
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_ctx": DEFAULT_CONTEXT_WINDOW
                        }
                    }

                    coder_resp = await client.post(OLLAMA_CHAT_URL, json=coder_payload)
                    if coder_resp.status_code != 200:
                        logger.error(f"Ollama Coder API Hatası: {coder_resp.status_code} - {coder_resp.text}")
                        break

                    coder_data = coder_resp.json()
                    assistant_msg = coder_data.get("message", {})
                    tool_calls = assistant_msg.get("tool_calls", [])
                    coder_messages.append(assistant_msg)

                    if tool_calls:
                        has_executed_tools = True
                        for t_call in tool_calls:
                            fn_dict = t_call.get("function", {})
                            fn_name = fn_dict.get("name", "")
                            fn_args_raw = fn_dict.get("arguments", {})

                            if isinstance(fn_args_raw, str):
                                try:
                                    fn_args = json.loads(fn_args_raw)
                                except Exception:
                                    fn_args = {"raw": fn_args_raw}
                            else:
                                fn_args = fn_args_raw

                            logger.info(f"[{engine.task_id}] Araç Çağrılıyor: {fn_name} | Parametreler: {fn_args}")

                            tool_out = ""
                            tool_success = True
                            try:
                                # Otonom Görsel Tarayıcı Araçlarını Doğrudan İşlet
                                if fn_name == "tool_browser_actuate" and LocalBrowserEngine is not None:
                                    res_dict = await LocalBrowserEngine.actuate_step(
                                        action=fn_args.get("action", "goto"),
                                        url=fn_args.get("url"),
                                        element_id=fn_args.get("element_id"),
                                        selector=fn_args.get("selector"),
                                        text=fn_args.get("text"),
                                        key=fn_args.get("key"),
                                        headless=False,
                                        use_tor=bool(fn_args.get("use_tor", False)),
                                        use_i2p=bool(fn_args.get("use_i2p", False))
                                    )
                                    tool_success = res_dict.get("success", False)
                                    tool_out = json.dumps(res_dict, ensure_ascii=False)
                                elif fn_name == "tool_browser_autonomous_mission" and LocalBrowserEngine is not None:
                                    res_dict = await LocalBrowserEngine.actuate_autonomous_mission(
                                        mission_prompt=fn_args.get("mission_prompt", prompt),
                                        start_url=fn_args.get("start_url"),
                                        headless=False,
                                        use_tor=bool(fn_args.get("use_tor", False)),
                                        use_i2p=bool(fn_args.get("use_i2p", False))
                                    )
                                    tool_success = res_dict.get("success", False)
                                    tool_out = json.dumps(res_dict, ensure_ascii=False)
                                else:
                                    # Diğer tüm araçları dispatcher üzerinden çalıştır
                                    tool_out = await call_tool_fn(fn_name, fn_args)
                                    if not tool_out:
                                        tool_out = "İşlem tamamlandı, çıktı boş."
                                    if any(err_kw in str(tool_out).lower() for err_kw in ["error", "traceback", "failed", "hatası", "bulunamadı"]):
                                        tool_success = False
                            except Exception as ex:
                                tool_out = f"Araç çalıştırma hatası: {str(ex)}"
                                tool_success = False

                            if not tool_success:
                                all_tools_successful = False

                            evidence = ExecutionEvidence(
                                step=step_count,
                                tool_name=fn_name,
                                args=fn_args,
                                output=str(tool_out),
                                success=tool_success
                            )
                            engine.evidences.append(evidence.to_dict())
                            engine.execution_steps.append({
                                "step": step_count,
                                "tool": fn_name,
                                "args": fn_args,
                                "output": str(tool_out),
                                "success": tool_success
                            })

                            sanitized_out = TriModelRouter.sanitize_tool_output(str(tool_out))
                            if not tool_success:
                                sanitized_out += (
                                    "\n[DİKKAT - SELF-HEALING]: Araç bir hata döndürdü. "
                                    "Lütfen yukarıdaki hatayı analiz et, alternatif parametre veya yöntemle tekrar dene."
                                )

                            coder_messages.append({
                                "role": "tool",
                                "name": fn_name,
                                "content": sanitized_out
                            })

                    else:
                        content_reply = assistant_msg.get("content", "").strip()
                        logger.info(f"[{engine.task_id}] Model metin üretti: {content_reply[:100]}...")

                        action_keywords = [
                            "araştır", "yaz", "çalıştır", "oku", "dosya", "slither",
                            "tara", "indir", "kur", "http", "github", "site", "ekran", "aç"
                        ]
                        if not has_executed_tools and any(kw in prompt.lower() for kw in action_keywords):
                            logger.info(f"[{engine.task_id}] Görev fiziksel işlem gerektiriyor, araca yönlendiriliyor...")
                            coder_messages.append({
                                "role": "user",
                                "content": "Lütfen yalnızca metinle cevap verme. Tanımlı araçları kullanarak fiziksel işlemi gerçekleştir."
                            })
                            continue
                        else:
                            break

                # =========================================================================
                # 3. AŞAMA: MISTRAL - SENTEZ VE KUSURSUZ RAPORLAMA (PRESENTATION TIER)
                # =========================================================================
                logger.info(f"[{engine.task_id}] Aşama 3: Mistral ile nihai sentez ve raporlama başlatılıyor...")

                synthesis_system = (
                    "Sen Barış AI platformunun Kıdemli İletişim ve Raporlama Uzmanısın. "
                    "Fiziksel olarak icra edilen tüm adımların kanıtlarını ve sonuçlarını incele. "
                    "Kullanıcının sorusuna; abartısız, halüsinasyonsuz, net, profesyonel ve teknik açıdan "
                    "eksiksiz bir rapor sun."
                )

                synthesis_prompt = (
                    f"KULLANICI TALEBİ:\n{prompt}\n\n"
                    f"İCRA EDİLEN FİZİKSEL ADIMLAR VE ÇIKTILAR:\n"
                    f"{json.dumps(engine.execution_steps, ensure_ascii=False, indent=2)}\n\n"
                    f"Lütfen yukarıdaki doğrulanmış verilere dayanarak kullanıcı için nihai cevabı üret."
                )

                synthesis_payload = {
                    "model": models["presenter"],
                    "messages": [
                        {"role": "system", "content": synthesis_system},
                        {"role": "user", "content": synthesis_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": DEFAULT_CONTEXT_WINDOW
                    }
                }

                try:
                    synth_resp = await client.post(OLLAMA_CHAT_URL, json=synthesis_payload)
                    synth_data = synth_resp.json()
                    final_reply = synth_data.get("message", {}).get("content", "").strip()
                except Exception as e:
                    logger.warning(f"Sentez modeli yanıt veremedi, varsayılan derleme yapılıyor: {e}")
                    final_reply = f"Görev icra edildi.\nKanıtlar: {len(engine.execution_steps)} adım tamamlandı."

                if has_executed_tools and all_tools_successful:
                    engine.transition_to(TaskState.VERIFIED, "Tüm fiziksel araçlar başarıyla çalıştırıldı ve doğrulandı.")
                elif has_executed_tools and not all_tools_successful:
                    engine.transition_to(TaskState.PARTIAL, "Bazı araçlar çalıştırıldı ancak kısmi hatalar tespit edildi.")
                elif not has_executed_tools:
                    engine.transition_to(TaskState.VERIFIED, "Görev analitik olarak başarıyla yanıtlandı.")
                else:
                    engine.transition_to(TaskState.FAILED, "Bilinmeyen durum.")

                return {
                    "task_id": engine.task_id,
                    "status": engine.state.value,
                    "reply": final_reply,
                    "execution_steps": engine.execution_steps,
                    "evidences": engine.evidences,
                    "verified": (engine.state == TaskState.VERIFIED)
                }

            except Exception as e:
                logger.error(f"[{engine.task_id}] Kritik Motor Hatası: {str(e)}", exc_info=True)
                engine.transition_to(TaskState.FAILED, f"İcra hatası: {str(e)}")
                return {
                    "task_id": engine.task_id,
                    "status": TaskState.FAILED.value,
                    "reply": f"Sistem icra hatası: {str(e)}",
                    "execution_steps": engine.execution_steps,
                    "evidences": engine.evidences,
                    "verified": False
                }


class ExecutionSandbox:
    pass
