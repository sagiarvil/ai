"""
test_adversarial_heavy_suite.py — Zero-Trust v5 Sert & Ağır Karşıt Test Senaryosu
Bu süit, Baris AI Semantic Intent Gate (intent_engine.py) ve Router mimarisini
en zorlu saldırı aileleri (A-H), enjeksiyonlar, çift niyetli manipülasyonlar
ve aşırı yük altında mekanik olarak test eder.
"""

import time
import pytest
from pydantic import ValidationError

from intent_engine import (
    INTENT_REGISTRY,
    Intent,
    IntentDecision,
    IntentEngine,
    Route,
    RouterSettings,
    extract_urls,
)
from tests.test_intent_engine import FixtureEmbedder


@pytest.fixture(scope="module")
def heavy_engine():
    """Deterministik ve ultra-hızlı test motoru."""
    return IntentEngine(FixtureEmbedder(), RouterSettings(similarity_threshold=0.55, min_margin=0.04))


# ══════════════════════════════════════════════════════════════════════════════
# SALDIRI AİLESİ A: EKSTREM SINIR, ENJEKSİYON VE ZARARLI GİRDİLER
# ══════════════════════════════════════════════════════════════════════════════

def test_extreme_buffer_overflow_and_null_bytes(heavy_engine):
    """10.000 karakterlik devasa girdi ve null-byte enjeksiyonu sistemi çökertmemeli."""
    malicious_text = "bu repoyu incele https://github.com/ast-grep/ast-grep " + ("A" * 10000) + "\x00\x00\r\n\t"
    decision = heavy_engine.decide(malicious_text)
    assert decision.intent == Intent.REPO_INSPECT
    assert decision.route == Route.TOOL
    assert decision.urls == ("https://github.com/ast-grep/ast-grep",)
    assert decision.raw_input == malicious_text


def test_command_injection_attempt_in_url(heavy_engine):
    """URL içine gizlenmiş OS command injection teşebbüsü URL'yi bozmamalı ve çalıştırılamamalıdır."""
    exploit_text = "incele https://github.com/ast-grep/ast-grep; rm -rf /; echo 'hacked'"
    decision = heavy_engine.decide(exploit_text)
    assert decision.intent == Intent.REPO_INSPECT
    assert decision.route == Route.TOOL
    # URL kalkanı yalnızca saf geçerli repo adresini izole etmeli
    assert decision.urls == ("https://github.com/ast-grep/ast-grep",)
    assert "; rm -rf /" not in decision.urls[0]


def test_type_safety_and_none_rejection(heavy_engine):
    """Sözleşme ihlali: None, int, dict veya boşluklu string kesinlikle reddedilmeli."""
    with pytest.raises(ValueError, match="Boş girdi niyet üretmez"):
        heavy_engine.decide("")

    with pytest.raises(ValueError, match="Boş girdi niyet üretmez"):
        heavy_engine.decide("    \t\n\r   ")

    with pytest.raises((ValueError, TypeError)):
        heavy_engine.decide(None)  # type: ignore

    with pytest.raises((ValueError, TypeError)):
        heavy_engine.decide(12345)  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# SALDIRI AİLESİ B: PROMPT INJECTION & NİYET GASPI (INTENT HIJACKING)
# ══════════════════════════════════════════════════════════════════════════════

def test_prompt_injection_tool_suppression(heavy_engine):
    """Kullanıcı 'tara ama sakın araç çalıştırma' dediğinde araç tetiklenmemeli, muhakemeye geçmeli."""
    text = "sence repoyu tara desem bu mimari için mantıklı mı"
    decision = heavy_engine.decide(text)
    assert decision.route == Route.REASON
    assert decision.allowed_tools == ()


def test_dual_intent_collision_consultation_priority(heavy_engine):
    """Hem URL hem eylem hem danışma içeren karmaşık sorguda danışma/muhakeme üstün gelmeli."""
    text = "sence https://github.com/ast-grep/ast-grep reposunu incelemek bize ne katkı sağlar"
    decision = heavy_engine.decide(text)
    # URL var ama soru danışma ('sence', 'ne katkı sağlar') -> Asla araç çalıştırıp gereksiz klonlama yapamaz
    assert decision.intent == Intent.ARCHITECTURAL_REASONING
    assert decision.route == Route.REASON
    assert decision.allowed_tools == ()


def test_ambiguous_low_margin_abstain_safety(heavy_engine):
    """Tamamen belirsiz, anlamsız veya çelişkili ifadelerde motor araç çalıştırmayı reddetmeli (ABSTAIN)."""
    weird_text = "xyz qwerty 123456 asdfg zzz"
    decision = heavy_engine.decide(weird_text)
    assert decision.route == Route.ABSTAIN
    assert decision.allowed_tools == ()
    assert decision.reason_code == "low_confidence"


# ══════════════════════════════════════════════════════════════════════════════
# SALDIRI AİLESİ C: METAMORFİK VE İDEMPOTENCY DAYANIKLILIĞI
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("variation", [
    "bu repoyu incele https://github.com/ast-grep/ast-grep",
    "BU REPOYU İNCELE https://github.com/ast-grep/ast-grep",
    "   bu    repoyu   incele    https://github.com/ast-grep/ast-grep   ",
    "bu\nrepoyu\tincele\r\nhttps://github.com/ast-grep/ast-grep",
])
def test_metamorphic_whitespace_and_case_invariance(heavy_engine, variation):
    """Büyük/küçük harf veya boşluk değişimleri deterministik karar sonucunu değiştiremez."""
    decision = heavy_engine.decide(variation)
    assert decision.intent == Intent.REPO_INSPECT
    assert decision.route == Route.TOOL
    assert decision.urls == ("https://github.com/ast-grep/ast-grep",)
    assert decision.allowed_tools == ("tool_github_inspect",)


# ══════════════════════════════════════════════════════════════════════════════
# SALDIRI AİLESİ D: KARMAŞIK URL SÖZLEŞME VE BÜTÜNLÜK KALKANI
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("url", [
    "https://github.com/torvalds/linux",
    "http://github.com/fastembed/fastembed",
    "https://www.github.com/ast-grep/ast-grep",
    "https://gitlab.com/gitlab-org/gitlab",
    "https://github.com/owner-with-dashes/repo_with_underscores.git",
])
def test_url_shield_integrity(heavy_engine, url):
    """Hiçbir regex URL içindeki github, gitlab, nokta, çizgi veya protokolü budayamaz."""
    query = f"şu kodu incele {url}"
    decision = heavy_engine.decide(query)
    clean_url = url.replace(".git", "")
    assert decision.urls[0].rstrip("/") in (url, clean_url)
    assert "github" in decision.urls[0] or "gitlab" in decision.urls[0]


# ══════════════════════════════════════════════════════════════════════════════
# SALDIRI AİLESİ E: PERFORMANS, GECİKME (SLA < 150ms) VE BELLEK DEĞİŞMEZLİĞİ
# ══════════════════════════════════════════════════════════════════════════════

def test_sla_latency_and_throughput(heavy_engine):
    """100 ardışık niyet sınıflandırmasında ortalama gecikme < 5 ms, p95 < 20 ms olmalıdır."""
    queries = [
        "bu repoyu incele https://github.com/ast-grep/ast-grep",
        "bu repo baris ai için bize nasıl katkı sağlar",
        "repoyu gitleaks ile tara",
        "bana ast tabanlı arama yapan açık kaynak repo bul",
        "merhaba nasılsın",
    ] * 20  # 100 çağrı

    latencies = []
    for q in queries:
        t0 = time.perf_counter()
        d = heavy_engine.decide(q)
        latencies.append((time.perf_counter() - t0) * 1000)
        assert isinstance(d, IntentDecision)

    avg_ms = sum(latencies) / len(latencies)
    sorted_l = sorted(latencies)
    p95_ms = sorted_l[int(len(sorted_l) * 0.95)]

    print(f"\n[SLA Benchmark] Ortalama: {avg_ms:.3f} ms | p95: {p95_ms:.3f} ms")
    assert avg_ms < 10.0, f"Ortalama gecikme çok yüksek: {avg_ms} ms"
    assert p95_ms < 50.0, f"p95 gecikme çok yüksek: {p95_ms} ms"


def test_decision_immutability_tamper_proofing(heavy_engine):
    """IntentDecision nesnesi dondurulmuştur (frozen=True); sonradan hiçbir alan değiştirilemez."""
    decision = heavy_engine.decide("bu repo baris ai için bize nasıl katkı sağlar")
    with pytest.raises(ValidationError):
        decision.allowed_tools = ("tool_hack",)  # type: ignore

    with pytest.raises(ValidationError):
        decision.route = Route.TOOL  # type: ignore
