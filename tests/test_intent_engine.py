import pytest
from pydantic import ValidationError

from intent_engine import (
    INTENT_REGISTRY, Intent, IntentEngine, IntentDecision,
    Route, RouterSettings,
)


class FixtureEmbedder:
    """Sadece test altyapısı: niyet eksenleri üzerinde kontrollü vektör."""
    # Spesifikten genele doğru sıralı eksenler
    AXES_PRIORITY = [
        ("nasıl katkı", "architectural_reasoning"),
        ("katkı", "architectural_reasoning"),
        ("sence", "architectural_reasoning"),
        ("mantıklı mı", "architectural_reasoning"),
        ("tara", "security_scan"),
        ("scan", "security_scan"),
        ("gitleaks", "security_scan"),
        ("patch", "code_change"),
        ("düzelt", "code_change"),
        ("ara", "repo_search"),
        ("bul", "repo_search"),
        ("incele", "repo_inspect"),
        ("inspect", "repo_inspect"),
        ("merhaba", "general_chat"),
        ("hello", "general_chat"),
        ("github", "repo_inspect"),
        ("repo", "repo_inspect"),
    ]

    def embed(self, texts):
        out = []
        keys = list(INTENT_REGISTRY)
        for t in texts:
            low = t.lower()
            hit = None
            for kw, target_intent in self.AXES_PRIORITY:
                if kw in low:
                    hit = target_intent
                    break
            vec = [0.0] * len(keys)
            if hit and Intent(hit) in keys:
                vec[keys.index(Intent(hit))] = 1.0
            else:
                vec[keys.index(Intent.GENERAL_CHAT)] = 0.5
            out.append(vec)
        return out


@pytest.fixture
def engine():
    return IntentEngine(FixtureEmbedder(), RouterSettings())


def test_registry_covers_every_intent():
    assert set(INTENT_REGISTRY) == set(Intent)


def test_registry_is_immutable():
    with pytest.raises(Exception):
        INTENT_REGISTRY[Intent.REPO_INSPECT].output_token_budget = 99999


def test_url_is_never_mangled(engine):
    raw = "bu repoyu incele https://github.com/ast-grep/ast-grep"
    d = engine.decide(raw)
    assert d.raw_input == raw
    assert d.urls == ("https://github.com/ast-grep/ast-grep",)
    assert ".com/ast-grep" in d.urls[0]      # 'github' ASLA silinmez
    assert "github.com" in d.urls[0]


def test_explicit_url_inspection_gets_tool_not_search(engine):
    d = engine.decide("incele https://github.com/ast-grep/ast-grep")
    assert d.intent == Intent.REPO_INSPECT
    assert d.route == Route.TOOL
    assert d.allowed_tools == ("tool_github_inspect",)
    assert "tool_github_search" not in d.allowed_tools


def test_consultation_never_triggers_a_tool(engine):
    d = engine.decide("bu repo baris ai için bize nasıl katkı sağlar")
    assert d.intent == Intent.ARCHITECTURAL_REASONING
    assert d.route == Route.REASON
    assert d.allowed_tools == ()


def test_url_plus_consultation_does_not_clone(engine):
    d = engine.decide("sence https://github.com/ast-grep/ast-grep 24gb için mantıklı mı")
    assert d.allowed_tools == ()
    assert d.route == Route.REASON


def test_security_scan_policy(engine):
    d = engine.decide("repoyu tara")
    assert d.intent == Intent.SECURITY_SCAN
    assert d.grounding_required is True


def test_empty_input_rejected(engine):
    with pytest.raises(ValueError):
        engine.decide("   ")


def test_decision_is_frozen_and_schema_valid(engine):
    d = engine.decide("merhaba")
    assert isinstance(d, IntentDecision)
    with pytest.raises(ValidationError):
        d.intent = "hack"
    IntentDecision.model_validate(d.model_dump())   # round-trip


def test_decision_is_deterministic(engine):
    a = engine.decide("bu repoyu incele https://github.com/a/b")
    b = engine.decide("bu repoyu incele https://github.com/a/b")
    assert a == b


def test_reason_route_has_no_tool_authority_even_if_registry_changes():
    # Politika ne derse desin, REASON yolu araç yetkisi taşıyamaz.
    e = IntentEngine(FixtureEmbedder())
    d = e.decide("sence bu katkı sağlar mı")
    assert d.route == Route.REASON and not d.allowed_tools
