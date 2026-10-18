#!/usr/bin/env python3
"""
MISTRAL-24B-ABLITERATED: KV-CACHE DONDURMA VE ÖN-ISITMA (WARM-UP) MOTORU
Amaç:
1. Sistemin 'Anayasa' (System Prompt) katmanını Metal GPU üzerinde önceden hesaplamak (Pre-fill).
2. Hesaplanan KV-Cache tensörlerini '/slots' API üzerinden diske (.bin) mühürlemek.
3. Watchdog / Reboot sonrasında GPU belleğini 100ms içinde ısıtarak Cold-Start gecikmesini sıfırlamak.
"""

import argparse
import sys
import time
import httpx

BASE_URL = "http://127.0.0.1:8080"
SLOT_ID = 0
SNAPSHOT_FILENAME = "tactical_core_v7.bin"

IMMUTABLE_SYSTEM_CORE = (
    "Sen görev-kritik (mission-critical) endüstriyel bir karar ve analiz çekirdeğisin. "
    "Sıfır tolerans prensibiyle çalışırsın. Spekülasyon, dolgu cümlesi veya belirsizlik yasaktır. "
    "Yalnızca kanıtlanabilir teknik bulguları ve eksiksiz prosedürleri JSON şemasında üret."
)

class TacticalWarmupController:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=60.0)

    def wait_for_engine_ready(self, max_wait_sec: int = 30) -> bool:
        """llama-server'ın 14.4 GB modeli RAM'e (--mlock) yüklemesini bekler."""
        print("[*] Çekirdek motorun (127.0.0.1:8080) hazır olması bekleniyor...")
        start = time.monotonic()
        while (time.monotonic() - start) < max_wait_sec:
            try:
                resp = self.client.get("/health")
                if resp.status_code == 200 and resp.json().get("status") == "ok":
                    elapsed = round((time.monotonic() - start) * 1000, 1)
                    print(f"[OK] Motor aktif ve kilitli ({elapsed} ms).")
                    return True
            except httpx.RequestError:
                pass
            time.sleep(0.5)
        print("[KRİTİK HATA] Motor belirtilen sürede uyanmadı!")
        return False

    def bake_and_seal_kv_cache(self):
        """
        1. Sistem anayasasını GPU'ya gönderip KV-Cache'i doldurur.
        2. Dolu Slot-0 belleğini diske 'tactical_core_v7.bin' olarak mühürler.
        """
        if not self.wait_for_engine_ready():
            sys.exit(1)

        print("[*] Sistem Anayasası Metal GPU KV-Cache belleğine işleniyor (Pre-filling)...")
        t0 = time.monotonic()

        warmup_payload = {
            "model": "mistral-small-24b-abliterated",
            "messages": [
                {"role": "system", "content": IMMUTABLE_SYSTEM_CORE},
                {"role": "user", "content": "[SISTEM_ISITMA_KONTROLU: DURUM RAPORU VER]"}
            ],
            "max_tokens": 1,
            "temperature": 0.0,
            "seed": 42,
            "cache_prompt": True,
            "id_slot": SLOT_ID
        }

        resp = self.client.post("/v1/chat/completions", json=warmup_payload)
        resp.raise_for_status()
        prefill_ms = round((time.monotonic() - t0) * 1000, 1)
        print(f"[OK] KV-Cache GPU'da oluşturuldu ({prefill_ms} ms).")

        print(f"[*] Slot-{SLOT_ID} belleği diske mühürleniyor -> '{SNAPSHOT_FILENAME}'...")
        t1 = time.monotonic()
        save_resp = self.client.post(
            f"/slots/{SLOT_ID}?action=save",
            json={"filename": SNAPSHOT_FILENAME}
        )
        save_resp.raise_for_status()
        save_data = save_resp.json()
        save_ms = round((time.monotonic() - t1) * 1000, 1)

        print(f"[MÜHÜRLENDİ] Kaydedilen Token: {save_data.get('n_saved', 'Bilinmiyor')} | Süre: {save_ms} ms")

    def instant_restore_kv_cache(self):
        """
        Sistem yeniden başladığında (Reboot / Watchdog) diskteki '.bin' tensörünü
        hesaplama yapmadan doğrudan GPU RAM'ine enjekte eder (~100ms).
        """
        if not self.wait_for_engine_ready():
            sys.exit(1)

        print(f"[*] '{SNAPSHOT_FILENAME}' diskten doğrudan Metal GPU Slot-{SLOT_ID} belleğine yükleniyor...")
        t0 = time.monotonic()
        restore_resp = self.client.post(
            f"/slots/{SLOT_ID}?action=restore",
            json={"filename": SNAPSHOT_FILENAME}
        )
        restore_resp.raise_for_status()
        restore_data = restore_resp.json()
        restore_ms = round((time.monotonic() - t0) * 1000, 1)

        print(f"[HAZIR] GPU KV-Cache {restore_ms} ms içinde geri yüklendi! (Yüklenen Token: {restore_data.get('n_restored', 'OK')})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tactical KV-Cache Warm-Up & Pinning Engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="KV-Cache'i oluştur ve diske (.bin) mühürle")
    group.add_argument("--restore", action="store_true", help="Mühürlü KV-Cache'i diskten GPU'ya anında yükle")
    args = parser.parse_args()

    controller = TacticalWarmupController()
    if args.init:
        controller.bake_and_seal_kv_cache()
    elif args.restore:
        controller.instant_restore_kv_cache()
