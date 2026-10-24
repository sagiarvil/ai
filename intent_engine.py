"""
intent_engine.py — Baris AI Semantic Intent Gate
Python >= 3.11, pydantic >= 2.7

SSOT: INTENT_REGISTRY
Bu modül:
  - HİÇBİR zaman kullanıcı metnini düzenlemez / temizlemez.
  - HİÇBİR zaman subprocess, network, LLM çağrısı yapmaz.
  - Yalnızca enjekte edilen Embedder üzerinden vektör alır.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────
# 1. NİYET SÖZLÜĞÜ
# ─────────────────────────────────────────────────────────────
class Intent(StrEnum):
    REPO_INSPECT = "repo_inspect"
    REPO_SEARCH = "repo_search"
    SECURITY_SCAN = "security_scan"
    CODE_CHANGE = "code_change"
    ARCHITECTURAL_REASONING = "architectural_reasoning"
    GENERAL_CHAT = "general_chat"


class Route(StrEnum):
    TOOL = "tool"        # Araç çalıştırma yetkisi VAR
    REASON = "reason"    # Sadece mevcut kanıt + hafıza ile muhakeme
    ABSTAIN = "abstain"  # Emin değil -> araç YOK, kullanıcıya net soru


# ─────────────────────────────────────────────────────────────
# 2. TEK GERÇEKLİK KAYNAĞI (POLICY + EXEMPLAR)
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class IntentSpec:
    intent: Intent
    allowed_tools: tuple[str, ...]
    grounding_required: bool
    output_token_budget: int
    exemplars: tuple[str, ...]


INTENT_REGISTRY: dict[Intent, IntentSpec] = {
    Intent.REPO_INSPECT: IntentSpec(
        Intent.REPO_INSPECT,
        ("tool_github_inspect",),
        True, 1200,
        (
            "bu repoyu incele",
            "şu github bağlantısındaki kodu analiz et",
            "repo yapısını çıkar ve dosya satır kanıtı göster",
            "inspect this repository",
            "review the codebase structure",
        ),
    ),
    Intent.REPO_SEARCH: IntentSpec(
        Intent.REPO_SEARCH,
        ("tool_github_search",),
        True, 800,
        (
            "bana ast tabanlı arama yapan açık kaynak repo bul",
            "yıldız sayısına göre benzer projeleri listele",
            "find an open source repository for vector search",
        ),
    ),
    Intent.SECURITY_SCAN: IntentSpec(
        Intent.SECURITY_SCAN,
        ("tool_security_scan",),
        True, 1200,
        (
            "repoyu gitleaks ile tara",
            "güvenlik açığı ve sızmış secret var mı kontrol et",
            "scan this repo for vulnerabilities",
        ),
    ),
    Intent.CODE_CHANGE: IntentSpec(
        Intent.CODE_CHANGE,
        ("tool_apply_patch", "tool_run_tests"),
        True, 1600,
        (
            "bu fonksiyonu düzelt ve testleri çalıştır",
            "şu hataya patch yaz",
            "implement the missing validation and run tests",
        ),
    ),
    Intent.ARCHITECTURAL_REASONING: IntentSpec(
        Intent.ARCHITECTURAL_REASONING,
        (),                      # <-- HİÇBİR ARAÇ YETKİSİ YOK
        True,                    # <-- repo iddiası için ÖNCEKİ doğrulanmış kanıt şart
        1200,
        (
            "bu repo baris ai için bize nasıl katkı sağlar",
            "bu mimari 24gb ram üzerinde mantıklı mı",
            "sence hangi yaklaşım daha doğru",
            "ne önerirsin, avantajları ve dezavantajları neler",
            "how would this improve my architecture",
            "what do you think about this design",
        ),
    ),
    Intent.GENERAL_CHAT: IntentSpec(
        Intent.GENERAL_CHAT,
        (),
        False, 800,
        (
            "merhaba",
            "bugün nasılsın",
            "kısaca açıklar mısın",
            "hello",
        ),
    ),
}

# Açık kayıt hatası: yeni bir Intent eklenip registry unutulursa IMPORT anında patlar.
assert set(INTENT_REGISTRY) == set(Intent), "Registry/Enum uyuşmazlığı: SSOT ihlali"


# ─────────────────────────────────────────────────────────────
# 3. ÇIKTI SÖZLEŞMESİ (Pydantic v2, immutable)
# ─────────────────────────────────────────────────────────────
class IntentDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: Intent
    route: Route
    similarity: float = Field(ge=0.0, le=1.0)
    margin: float = Field(ge=0.0, le=1.0)
    allowed_tools: tuple[str, ...]
    grounding_required: bool
    output_token_budget: int
    urls: tuple[str, ...] = ()
    reason_code: str
    raw_input: str  # ASLA düzenlenmemiş ham metin


class RouterSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    similarity_threshold: float = Field(default=0.55, gt=0, le=1)
    min_margin: float = Field(default=0.04, ge=0, lt=1)
    exemplar_top_k: int = Field(default=2, ge=1, le=5)


# ─────────────────────────────────────────────────────────────
# 4. ENJEKSİYON NOKTASI (testler model indirmeden çalışır)
# ─────────────────────────────────────────────────────────────
class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


# ─────────────────────────────────────────────────────────────
# 5. URL KORUMA KALKANI — METNE DOKUNMAZ, SADECE OKUR
# ─────────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:github|gitlab)\.com/"
    r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+",
    re.IGNORECASE,
)
_EXECUTE = ("incele", "kontrol et", "analiz et", "klonla", "tara",
            "inspect", "analyze", "review", "clone", "scan", "patch")
_CONSULT = ("nasıl katkı", "sence", "ne önerir", "avantaj", "dezavantaj",
            "mantıklı mı", "gerekiyor mu", "fikir", "what do you think",
            "how would this", "should i")


def extract_urls(text: str) -> tuple[str, ...]:
    """Ham metni DEĞİŞTİRMEZ. Sadece URL'yi olduğu gibi geri verir."""
    return tuple(_URL_RE.findall(text))


def _lower(text: str) -> str:
    return text.lower()


# ─────────────────────────────────────────────────────────────
# 6. SAF MATEMATİK (I/O yok, yan etki yok)
# ─────────────────────────────────────────────────────────────
def _normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return [0.0] * len(vec)
    return [x / norm for x in vec]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Embedding boyut uyuşmazlığı")
    return max(0.0, min(1.0, sum(x * y for x, y in zip(a, b))))


def _intent_score(q: list[float], exemplars: list[list[float]], k: int) -> float:
    scores = sorted((_cosine(q, e) for e in exemplars), reverse=True)[:k]
    return sum(scores) / len(scores) if scores else 0.0


# ─────────────────────────────────────────────────────────────
# 7. MOTOR
# ─────────────────────────────────────────────────────────────
class IntentEngine:
    def __init__(
        self,
        embedder: Embedder,
        settings: RouterSettings | None = None,
    ) -> None:
        self._embedder = embedder
        self._settings = settings or RouterSettings()
        self._exemplar_vectors: dict[Intent, list[list[float]]] | None = None

    def _warm(self) -> None:
        if self._exemplar_vectors is not None:
            return
        pairs = [
            (intent, exemplar)
            for intent, spec in INTENT_REGISTRY.items()
            for exemplar in spec.exemplars
        ]
        vectors = self._embedder.embed([text for _, text in pairs])
        if len(vectors) != len(pairs):
            raise RuntimeError("Embedder çıktı sayısı uyuşmuyor")
        result: dict[Intent, list[list[float]]] = {i: [] for i in INTENT_REGISTRY}
        for (intent, _), vec in zip(pairs, vectors):
            result[intent].append(_normalize(vec))
        self._exemplar_vectors = result

    def _decide(self, text: str, intent: Intent, score: float,
                margin: float, route: Route, reason: str,
                urls: tuple[str, ...] = ()) -> IntentDecision:
        spec = INTENT_REGISTRY[intent]   # <-- policy'nin TEK kaynağı
        return IntentDecision(
            intent=intent,
            route=route,
            similarity=round(score, 6),
            margin=round(margin, 6),
            allowed_tools=spec.allowed_tools if route == Route.TOOL else (),
            grounding_required=spec.grounding_required,
            output_token_budget=spec.output_token_budget,
            urls=urls,
            reason_code=reason,
            raw_input=text,
        )

    def decide(self, text: str) -> IntentDecision:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Boş girdi niyet üretmez")

        urls = extract_urls(text)
        low = _lower(text)

        # --- Deterministik üst koruma: URL + açık eylem -> SEMANTİK ARAMAYA DÜŞMEZ
        if urls and any(v in low for v in _EXECUTE):
            intent = (Intent.SECURITY_SCAN if "tara" in low or "scan" in low
                      else Intent.REPO_INSPECT)
            return self._decide(text, intent, 1.0, 1.0, Route.TOOL,
                                "guard_url_explicit_action", urls)

        # --- URL var ama amaç DANIŞMA -> araç çalıştırılmaz
        if urls and any(v in low for v in _CONSULT):
            return self._decide(text, Intent.ARCHITECTURAL_REASONING,
                                1.0, 1.0, Route.REASON,
                                "guard_url_consultation", urls)

        # --- Semantik kapı
        self._warm()
        q = _normalize(self._embedder.embed([text])[0])
        ranked = sorted(
            ((_intent_score(q, self._exemplar_vectors[i],
                            self._settings.exemplar_top_k), i)
             for i in INTENT_REGISTRY),
            reverse=True,
        )
        best, second = ranked[0], ranked[1]
        score, intent = best
        margin = score - second[0]

        if score < self._settings.similarity_threshold or margin < self._settings.min_margin:
            # GÜVENLİ VARSAYILAN: araç YOK, kullanıcıya soru sorulacak.
            return self._decide(text, Intent.ARCHITECTURAL_REASONING,
                                score, margin, Route.ABSTAIN, "low_confidence", urls)

        route = Route.TOOL if INTENT_REGISTRY[intent].allowed_tools else Route.REASON
        return self._decide(text, intent, score, margin, route,
                            "semantic_match", urls)
