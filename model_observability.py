#!/usr/bin/env python3
"""
OMNICORE X // FAZ 4 & FAZ 8: LOCAL REASONING, METAL GPU & OBSERVABILITY
Yetkinlikler:
- Apple Silicon M4 Metal GPU çıkarım izleme ve kıyaslama (Benchmark)
- TTFT (Time to First Token) ve Tokens/sec ölçümü
- Bellek baskısı (Memory Pressure), Swap ve Kaynak Tüketim Monitörü (psutil & sysctl)
- Yüksek bellek baskısında dinamik kaynak kısma (Dynamic Concurrency Throttling)
- Model sağlık kontrolü (Continuous Health Probe)
"""

import asyncio
import subprocess
import time
from typing import Dict, Any
import httpx
import psutil

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "mistral-small-24b-abliterated:latest"

class ModelObservabilityEngine:
    @classmethod
    def get_system_telemetry(cls) -> Dict[str, Any]:
        """Sistemin anlık bellek, CPU, swap ve Apple Metal donanım durumunu raporlar."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        cpu_pct = psutil.cpu_percent(interval=None)

        # Bellek Baskısı Hesaplama
        # macOS üzerinde available bellek %15'in altına düşerse veya swap > 2GB ise kritik
        memory_pressure = "NORMAL"
        available_pct = (mem.available / mem.total) * 100
        if available_pct < 15.0 or swap.used > (2 * 1024 * 1024 * 1024):
            memory_pressure = "HIGH"
        elif available_pct < 25.0:
            memory_pressure = "MODERATE"

        # Apple M4 Donanım Bilgisi
        chip_info = "Apple Silicon M4 (Metal GPU Accelerate)"
        try:
            sp = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            if sp.returncode == 0 and sp.stdout.strip():
                chip_info = sp.stdout.strip()
        except Exception:
            pass

        return {
            "hardware": chip_info,
            "cpu_percent": cpu_pct,
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_available_pct": round(available_pct, 1),
            "memory_pressure": memory_pressure,
            "swap_used_mb": round(swap.used / (1024**2), 1),
            "recommended_concurrency": 1 if memory_pressure == "HIGH" else (2 if memory_pressure == "MODERATE" else 4)
        }

    @classmethod
    async def benchmark_model_runtime(cls, model_name: str = DEFAULT_MODEL, test_prompt: str = "Bana 10 kelimelik kısa bir cümle yaz.") -> Dict[str, Any]:
        """
        Modelin TTFT (Time to First Token) ve Tokens/Sec metriklerini doğrudan canlı ölçer.
        """
        telemetry = cls.get_system_telemetry()
        t0 = time.perf_counter()
        ttft = 0.0
        token_count = 0
        full_text = []

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                req_payload = {
                    "model": model_name,
                    "prompt": test_prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.0,
                        "num_predict": 50,
                        "num_thread": 8
                    }
                }
                async with client.stream("POST", OLLAMA_GENERATE_URL, json=req_payload) as response:
                    if response.status_code != 200:
                        return {
                            "success": False,
                            "error": f"Model servisi HTTP {response.status_code} döndü.",
                            "telemetry": telemetry
                        }

                    first_token_received = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if not first_token_received:
                            ttft = round(time.perf_counter() - t0, 3)
                            first_token_received = True

                        import json
                        chunk = json.loads(line)
                        txt = chunk.get("response", "")
                        full_text.append(txt)
                        token_count += 1
                        if chunk.get("done", False):
                            break

            total_elapsed = time.perf_counter() - t0
            tokens_per_sec = round(token_count / total_elapsed, 2) if total_elapsed > 0 else 0.0

            return {
                "success": True,
                "model": model_name,
                "ttft_sec": ttft,
                "total_elapsed_sec": round(total_elapsed, 3),
                "token_count": token_count,
                "tokens_per_sec": tokens_per_sec,
                "sample_output": "".join(full_text).strip(),
                "telemetry": telemetry
            }
        except Exception as e:
            return {
                "success": False,
                "model": model_name,
                "error": str(e),
                "telemetry": telemetry
            }

if __name__ == "__main__":
    import asyncio
    print("Sistem Telemetrisi:", ModelObservabilityEngine.get_system_telemetry())
    res = asyncio.run(ModelObservabilityEngine.benchmark_model_runtime())
    print("Model Canlı Benchmark:", res)
