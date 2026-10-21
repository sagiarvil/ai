#!/usr/bin/env python3
"""
OMNICORE // MODEL YÖNETİCİSİ VE RUNTIME ÇIKARIM DOĞRULAYICISI (MODEL REGISTRY & LOADER)
Kural: Sadece active_engines.json içine isim yazmak kabul edilmez.
Modelin Ollama üzerinde yüklü olduğu, belleğe alındığı ve gerçek çıkarım ürettiği
fiziksel token yanıtı ile kanıtlanmalıdır.
"""

import time
import json
import httpx
from typing import Dict, Any, Optional, List

OLLAMA_BASE_URL = "http://127.0.0.1:11434"

class ModelManager:
    @classmethod
    async def list_available_models(cls) -> List[Dict[str, Any]]:
        """Ollama üzerinde yüklü gerçek modelleri listeler."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    return data.get("models", [])
        except Exception:
            pass
        return []

    @classmethod
    async def verify_model_runtime(cls, model_name: str) -> Dict[str, Any]:
        """
        Modele canlı çıkarım testi (inference probe) göndererek yanıtı ve hızı ölçer.
        Sahte veya çalışmayan modelleri kesin olarak eler.
        """
        start_t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 1. Modelin varlığını doğrula
                show_res = await client.post(
                    f"{OLLAMA_BASE_URL}/api/show",
                    json={"name": model_name}
                )
                if show_res.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Model Ollama üzerinde bulunamadı: {model_name}",
                        "inference_pass": False
                    }
                model_info = show_res.json()

                # 2. Canlı test çıkarımı (Live Probe)
                probe_res = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": "Echo: RUNTIME_PROBE_PASS",
                        "stream": False,
                        "options": {
                            "num_thread": 8,
                            "temperature": 0.0,
                            "num_predict": 15
                        }
                    }
                )
                elapsed = round(time.perf_counter() - start_t, 3)
                if probe_res.status_code == 200:
                    p_data = probe_res.json()
                    response_text = p_data.get("response", "").strip()
                    eval_count = p_data.get("eval_count", 0)
                    eval_duration = p_data.get("eval_duration", 1)
                    tps = round(eval_count / (eval_duration / 1e9), 2) if eval_duration > 0 else 0.0
                    if not response_text or type(eval_count) is not int or eval_count <= 0:
                        return {'success': False, 'inference_pass': False,
                                'error': 'HTTP 200 alındı ancak gerçek metin/token üretimi doğrulanamadı.'}

                    return {
                        "success": True,
                        "inference_pass": True,
                        "model": model_name,
                        "response": response_text,
                        "tokens_per_second": tps,
                        "latency_sec": elapsed,
                        "details": {
                            "family": model_info.get("details", {}).get("family", "unknown"),
                            "parameter_size": model_info.get("details", {}).get("parameter_size", "unknown"),
                            "quantization_level": model_info.get("details", {}).get("quantization_level", "unknown")
                        }
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Çıkarım testi başarısız: HTTP {probe_res.status_code}",
                        "inference_pass": False,
                        "latency_sec": elapsed
                    }
        except Exception as e:
            elapsed = round(time.perf_counter() - start_t, 3)
            return {
                "success": False,
                "error": f"Model çıkarım bağlantı hatası: {str(e)}",
                "inference_pass": False,
                "latency_sec": elapsed
            }

if __name__ == '__main__':
    import asyncio
    async def run_test():
        res = await ModelManager.verify_model_runtime('mistral-small-24b-abliterated:latest')
        print('Model Doğrulama Sonucu:', json.dumps(res, indent=2, ensure_ascii=False))
    asyncio.run(run_test())

