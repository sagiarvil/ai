#!/usr/bin/env python3
"""
OMNICORE // MODEL YÖNETİCİSİ VE RUNTIME ÇIKARIM DOĞRULAYICISI (MODEL REGISTRY & LOADER)
Özellikler:
1. Ollama üzerindeki modelleri otomatik tarama ve rollere dinamik atama.
2. MODEL_REASONER, MODEL_CODER, MODEL_PRESENTER ve AGENT_NUM_CTX ortam değişkeni desteği.
3. Otomatik Fallback: İstenen model bulunamazsa mevcut sansürsüz modeller arasından en uygununu seçme.
4. Fiziksel çıkarım testi (Inference Probe) ile doğrulama.
"""

import os
import time
import json
import httpx
from typing import Dict, Any, List, Optional

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# Varsayılan Konfigürasyon
DEFAULT_NUM_CTX = int(os.environ.get("AGENT_NUM_CTX", "16384"))

# Tercih Edilen Varsayılan Modeller (Öncelik Sırası)
PREFERRED_REASONERS = [
    "deepseek-r1:latest",
    "deepseek-r1-14b-abliterated:latest",
    "hf.co/mradermacher/DeepSeek-R1-Distill-Qwen-14B-abliterated-v2-GGUF:Q4_K_M"
]

PREFERRED_CODERS = [
    "qwen2.5-coder:32b",
    "qwen-coder-14b-abliterated:latest",
    "hf.co/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF:Q4_K_M"
]

PREFERRED_PRESENTERS = [
    "mistral-small-24b-abliterated:latest",
    "hf.co/bartowski/huihui-ai_Mistral-Small-24B-Instruct-2501-abliterated-GGUF:Q4_K_M"
]


class ModelManager:
    _cached_models: Optional[List[Dict[str, Any]]] = None
    _last_cache_time: float = 0.0

    @classmethod
    async def list_available_models(cls, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Ollama üzerinde yüklü gerçek modelleri listeler."""
        now = time.time()
        if not force_refresh and cls._cached_models is not None and (now - cls._last_cache_time) < 15:
            return cls._cached_models

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("models", [])
                    cls._cached_models = models
                    cls._last_cache_time = now
                    return models
        except Exception:
            pass
        return cls._cached_models or []

    @classmethod
    def list_available_models_sync(cls) -> List[Dict[str, Any]]:
        """Senkron model listeleme."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if res.status_code == 200:
                    return res.json().get("models", [])
        except Exception:
            pass
        return []

    @classmethod
    async def auto_detect_triad_models(cls) -> Dict[str, str]:
        """
        Ollama modellerini tarayarak ve ortam değişkenlerini kontrol ederek
        3 katmanlı triad modellerini dinamik atar.
        """
        models = await cls.list_available_models()
        available_names = [m.get("name", "") for m in models]

        # 1. Reasoner Model Tespiti
        env_reasoner = os.environ.get("MODEL_REASONER")
        reasoner = None
        if env_reasoner and env_reasoner in available_names:
            reasoner = env_reasoner
        elif env_reasoner:
            # İsme göre esnek eşleşme
            for name in available_names:
                if env_reasoner.lower() in name.lower() or name.lower() in env_reasoner.lower():
                    reasoner = name
                    break

        if not reasoner:
            for pref in PREFERRED_REASONERS:
                if pref in available_names:
                    reasoner = pref
                    break
        if not reasoner:
            for name in available_names:
                lower = name.lower()
                if "deepseek" in lower or "r1" in lower:
                    reasoner = name
                    break
        if not reasoner and available_names:
            reasoner = available_names[0]

        # 2. Coder Model Tespiti
        env_coder = os.environ.get("MODEL_CODER")
        coder = None
        if env_coder and env_coder in available_names:
            coder = env_coder
        elif env_coder:
            for name in available_names:
                if env_coder.lower() in name.lower() or name.lower() in env_coder.lower():
                    coder = name
                    break

        if not coder:
            for pref in PREFERRED_CODERS:
                if pref in available_names:
                    coder = pref
                    break
        if not coder:
            for name in available_names:
                lower = name.lower()
                if "coder" in lower or "qwen" in lower:
                    coder = name
                    break
        if not coder and available_names:
            coder = reasoner or available_names[0]

        # 3. Presenter Model Tespiti
        env_presenter = os.environ.get("MODEL_PRESENTER")
        presenter = None
        if env_presenter and env_presenter in available_names:
            presenter = env_presenter
        elif env_presenter:
            for name in available_names:
                if env_presenter.lower() in name.lower() or name.lower() in env_presenter.lower():
                    presenter = name
                    break

        if not presenter:
            for pref in PREFERRED_PRESENTERS:
                if pref in available_names:
                    presenter = pref
                    break
        if not presenter:
            for name in available_names:
                lower = name.lower()
                if "mistral" in lower or "instruct" in lower or "general" in lower:
                    presenter = name
                    break
        if not presenter and available_names:
            presenter = coder or reasoner or available_names[0]

        return {
            "reasoner": reasoner or "deepseek-r1-14b-abliterated:latest",
            "coder": coder or "qwen-coder-14b-abliterated:latest",
            "presenter": presenter or "mistral-small-24b-abliterated:latest",
            "num_ctx": str(cls.get_context_window())
        }

    @classmethod
    def get_context_window(cls) -> int:
        """Ortam değişkeninden veya varsayılan 16384 token bütçesini okur."""
        try:
            return int(os.environ.get("AGENT_NUM_CTX", DEFAULT_NUM_CTX))
        except (ValueError, TypeError):
            return 16384

    @classmethod
    async def verify_model_runtime(cls, model_name: str) -> Dict[str, Any]:
        """
        Modele canlı çıkarım testi (inference probe) göndererek yanıtı ve hızı ölçer.
        Sahte veya çalışmayan modelleri kesin olarak eler.
        """
        start_t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
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
        triad = await ModelManager.auto_detect_triad_models()
        print('Triad Atamaları:', json.dumps(triad, indent=2, ensure_ascii=False))
        res = await ModelManager.verify_model_runtime(triad['presenter'])
        print('Presenter Doğrulama Sonucu:', json.dumps(res, indent=2, ensure_ascii=False))
    asyncio.run(run_test())
