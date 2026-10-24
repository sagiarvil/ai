"""
intent_adapters.py — Baris AI Model Embedder Adaptörleri
M4 24GB dostu: FastEmbed + ONNX işlem içi çalışır, yerel model belleğine dokunmaz.
"""
from typing import Sequence

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None


class FastEmbedAdapter:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        if TextEmbedding is None:
            raise RuntimeError("fastembed kütüphanesi kurulu değil: pip install fastembed")
        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts), batch_size=16)]
