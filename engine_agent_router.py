#!/usr/bin/env python3
"""
Barış AI Autonomous Multi-Agent & Engine Router (Sub-Millisecond Kernel)
Kullanıcı talimatlarını mikrosaniyeler içinde analiz ederek en yetkin uzman ajanı
ve canlı sistem motorunu otonom olarak devreye alır.
Tavsiye ve laf kalabalığını yasaklar; %100 anahtar teslim kesin çözüm üretir.
"""

import os
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def normalize_text(text: str) -> str:
    """Türkçe İ/ı/I/i ve birleşen aksanları hatasız normalize eder."""
    t = (text or "").replace("İ", "i").replace("I", "ı").strip()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return t.lower()


@dataclass
class AgentRole:
    agent_id: str
    agent_name: str
    primary_engine: str
    system_prompt: str
    allowed_tools: List[str]


@dataclass
class RoutingDecision:
    agent: AgentRole
    autonomous_action: Optional[Tuple[str, Dict[str, Any]]]
    latency_ms: float
    reason: str


class EngineAgentRouter:
    """Otonom Çoklu Ajan ve Canlı Sistem Motoru Yönlendiricisi."""

    ROLES = {
        "security_auditor": AgentRole(
            agent_id="security_auditor",
            agent_name="🛡️ Siber Güvenlik ve Sızıntı Denetim Ajanı",
            primary_engine="Gitleaks v8.30.1, TruffleHog v3.99.6, Google OSV & Aqua Trivy",
            system_prompt=(
                "Sen Barış AI Kıdemli Siber Güvenlik ve Tehdit Denetim Uzmanısın. "
                "ASLA TAVSİYE VERME! Sistemindeki Gitleaks, TruffleHog, Aqua Trivy, OpenSSF Scorecard ve Google OSV-Scanner motorlarını kullanarak "
                "açık API anahtarları, şifre sızıntıları, tokenler ve CVE bağımlılık zafiyetlerini denetler, "
                "doğrudan somut kanıt ve sonuç tablosunu teslim edersin."
            ),
            allowed_tools=["tool_secret_leak_scan", "tool_trufflehog_scan", "tool_vulnerability_scan", "tool_repo_scorecard", "tool_direct_answer"]
        ),
        "github_hunter": AgentRole(
            agent_id="github_hunter",
            agent_name="🚀 Açık Kaynak Kod & GitHub Repo Avcısı Ajanı",
            primary_engine="GitHub CLI (gh) & Source Tree Code Inspector",
            system_prompt=(
                "Sen Barış AI Açık Kaynak İstihbarat ve GitHub Repo Avcısısın. "
                "ASLA TAVSİYE VERME! Yetkili GitHub motorunu kullanarak kullanıcının aradığı konuda gerçekten çalışan kaynak kodları "
                "içeren repoları bulur, kod varlığını teyit eder ve doğrudan çalışan repo linklerini Markdown tablosu olarak sunarsın."
            ),
            allowed_tools=["tool_github_search", "tool_github_inspect", "tool_repo_scorecard", "tool_direct_answer"]
        ),
        "web3_security": AgentRole(
            agent_id="web3_security",
            agent_name="⛓️ Web3 & Akıllı Sözleşme Güvenlik Ajanı",
            primary_engine="Crytic Slither v0.11.6, Crytic Echidna v2.3.3 & MetaMask Phishing DB (107K+ Domain)",
            system_prompt=(
                "Sen Barış AI Web3 Güvenlik ve Akıllı Sözleşme Denetçisisin. "
                "ASLA TAVSİYE VERME! Solidity sözleşmelerini Slither ve Echidna fuzzer ile denetler, "
                "şüpheli alan adlarını MetaMask 107.000+ domainlik karalistesinde anlık tarayıp kesin güvenlik durumunu bildirirsin."
            ),
            allowed_tools=["tool_smart_contract_audit", "tool_smart_contract_fuzz", "tool_phishing_domain_scan", "tool_direct_answer"]
        ),
        "darkweb_intel": AgentRole(
            agent_id="darkweb_intel",
            agent_name="🕵️ Dark Web & OSINT İstihbarat Ajanı",
            primary_engine="Tor SOCKS5 Engine, Ahmia & DuckDuckGo Onion",
            system_prompt=(
                "Sen Barış AI Dark Web ve Tehdit İstihbaratı Analistisin. "
                "ASLA TAVSİYE VERME! Tor ağı üzerindeki sızıntıları, .onion servislerini ve OSINT veri tabanlarını tarar, "
                "kullanıcıya doğrulanmış tehdit verilerini doğrudan aktarırsın."
            ),
            allowed_tools=["tool_darkweb_search", "tool_onion_crawl", "tool_threat_intel_scan", "tool_direct_answer"]
        ),
        "deep_research": AgentRole(
            agent_id="deep_research",
            agent_name="📚 GPT-Researcher Derin Araştırma Ajanı",
            primary_engine="GPT-Researcher Multi-Source Synthesizer",
            system_prompt=(
                "Sen Barış AI Derin Araştırma ve Sentez Ajanısın. "
                "ASLA TAVSİYE VERME! Belirtilen konularda sayfaların tam metinlerini toplayıp, bot engelleyicileri filtreleyerek "
                "eksiksiz ve anahtar teslim derin araştırma raporu hazırlarsın."
            ),
            allowed_tools=["tool_deep_research", "tool_direct_answer"]
        ),
        "code_executor": AgentRole(
            agent_id="code_executor",
            agent_name="⚙️ Yüksek Başarımlı Yerel Kod & Hesaplama Ajanı",
            primary_engine="Python 3.14 Local Execution Kernel",
            system_prompt=(
                "Sen Barış AI Deterministik Kod ve Hesaplama Motorusun. "
                "ASLA TAVSİYE VERME! Kullanıcının talep ettiği analiz ve veri işleme görevlerini doğrudan yerel Python ile "
                "yazar, çalıştırır ve bağımsız doğrulama kanıtıyla tamamlarsın."
            ),
            allowed_tools=[]  # Geleneksel araç seti (tool_write_file, tool_run_shell vb.)
        ),
        "turnkey_solver": AgentRole(
            agent_id="turnkey_solver",
            agent_name="🎯 Anahtar Teslim Çözüm ve İcraat Ajanı",
            primary_engine="Barış AI Turnkey Solution Kernel",
            system_prompt=(
                "Sen Barış AI Kesin Sonuç Odaklı, Anahtar Teslim Çözüm ve İcraat Motorusun. "
                "KULLANICIYA ASLA TAVSİYE, ÖNERİ, AKIL VEYA NASİHAT VERME! "
                "'Şöyle yapabilirsiniz', 'bunu deneyebilirsiniz', 'faydalı olabilir' gibi pasif tavsiye kipleri KESİNLİKLE YASAKTIR. "
                "Kullanıcı bir soru sorduğunda ya da görev verdiğinde, sorunun tam anahtar teslim cevabını (hazır çalışan eksiksiz kod, net çözüm, kesin sonuç) doğrudan önüne koyarsın."
            ),
            allowed_tools=["tool_direct_answer", "tool_system_engines_status"]
        )
    }

    @classmethod
    def route(cls, message: str, workspace: str, expected_files: Optional[dict] = None) -> RoutingDecision:
        t0 = time.perf_counter()
        t = normalize_text(message)

        # 1. Kod / Dosya Yazma Görevi (Strict Code Execution)
        if expected_files or any(k in t for k in ["dosyasi", "dosyaya", "tablosu", "scripti", "kodunu yaz", "proje olustur", "dosyaya yaz", "dosyaya kaydet"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["code_executor"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Doğrudan dosya oluşturma / kod yürütme kabul koşulu tespit edildi."
            )

        # 1.1 Kavramsal / Soru-Cevap / Karşılaştırma Soruları (Motor çalıştırma, doğrudan cevap ver)
        is_conceptual_question = any(q in t for q in [
            "nedir", "farki", "farkı", "nasil calisir", "nasıl çalışır", "karsilastir", "karşılaştır",
            "ne ise yarar", "ne işe yarar", "ne yapmaliyim", "ne yapmalıyım", "neler yapabilirsin",
            "kimsin", "hangisi daha iyi", "tavsiye", "farki ne", "farkı ne"
        ])
        if is_conceptual_question and not any(run_kw in t for run_kw in ["tara", "denetle", "calistir", "çalıştır", "puanla"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Kavramsal soru / karşılaştırma tespit edildi, doğrudan anahtar teslim cevap moduna yönlendirildi."
            )

        # 2. Sızıntı / Gizli Anahtar Taraması (Gitleaks & TruffleHog)
        is_encryption_query = any(w in t for w in ["sifreleme", "şifreleme", "sifrele", "şifrele", "kripto", "cipher", "crypto", "anahtar teslim", "aes", "rsa", "fernet"])
        if not is_encryption_query and not is_conceptual_question and "trufflehog" in t:
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_trufflehog_scan", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="TruffleHog derin credential ve gizli anahtar sızıntı taraması talep edildi."
            )

        leak_explicit = any(k in t for k in ["gitleaks", "sizinti", "sızıntı", "leak", "credential", "api key", "secret scan"])
        password_scan = any(k in t for k in ["sifre", "şifre", "secret", "anahtar", "token"]) and any(a in t for a in ["tara", "sizinti", "sızıntı", "bul", "kontrol", "denet", "leak", "acik", "açık"])
        if not is_encryption_query and not is_conceptual_question and (leak_explicit or password_scan):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_secret_leak_scan", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Gitleaks gizli anahtar ve şifre sızıntı taraması talep edildi."
            )

        # 3. Zafiyet / CVE / Tedarik Zinciri (OSV-Scanner, Trivy, Scorecard)
        if "scorecard" in t:
            repo_match = re.search(r"([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)", t)
            repo = repo_match.group(1) if repo_match else "sagiarvil/ai"
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_repo_scorecard", {"repo_name": repo}),
                latency_ms=round(dt, 4),
                reason="OpenSSF Scorecard repo tedarik zinciri sağlık analizi talep edildi."
            )

        if any(k in t for k in ["zafiyet", "cve", "guvenlik acigi", "güvenlik açığı", "trivy", "osv", "bagimlilik", "bağımlılık"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_vulnerability_scan", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="OSV-Scanner/Trivy zafiyet ve bağımlılık taraması talep edildi."
            )

        # 4. GitHub Doğrudan Repo İnceleme veya Arama
        github_url_match = re.search(r"(?:https?://github\.com/)?([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", t)
        if ("incele" in t.lower() or "kontrol" in t.lower() or "bak" in t.lower() or "analiz" in t.lower()) and github_url_match:
            repo_id = github_url_match.group(1).rstrip(".")
            if not repo_id.startswith("http"):
                dt = (time.perf_counter() - t0) * 1000
                return RoutingDecision(
                    agent=cls.ROLES["github_hunter"],
                    autonomous_action=("tool_github_inspect", {"repo_full_name": repo_id}),
                    latency_ms=round(dt, 4),
                    reason=f"GitHub reposu doğrudan inceleme talimatı tespit edildi: {repo_id}"
                )

        if any(k in t for k in ["github", "repo", "acik kaynak kod", "açık kaynak kod", "calisan repo", "çalışan repo", "proje bul"]):
            # URL'leri korumak için regex temizliği
            if "github.com/" in t:
                m = re.search(r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", t)
                if m:
                    repo_id = m.group(1).rstrip(".")
                    dt = (time.perf_counter() - t0) * 1000
                    return RoutingDecision(
                        agent=cls.ROLES["github_hunter"],
                        autonomous_action=("tool_github_inspect", {"repo_full_name": repo_id}),
                        latency_ms=round(dt, 4),
                        reason=f"GitHub repo URL doğrudan inceleme tespit edildi: {repo_id}"
                    )
            q = re.sub(r"\b(da|de|uzerinde|üzerinde|bana|bul|ara|calisan|çalışan|repolarini|repolarını|projeleri)\b", "", t, flags=re.IGNORECASE).strip()
            q = re.sub(r"\s+", " ", q).strip()
            if not q or len(q) < 3:
                q = t
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["github_hunter"],
                autonomous_action=("tool_github_search", {"query": q, "min_stars": 5}),
                latency_ms=round(dt, 4),
                reason="Açık kaynak GitHub kod reposu arama talimatı tespit edildi."
            )

        # 5. Phishing / Sahte Domain Taraması (MetaMask)
        if any(k in t for k in ["phishing", "sahte domain", "zararli domain", "zararlı domain", "oltalama", "metamask"]):
            match = re.search(r"([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", t)
            domain = match.group(1) if match else "metamask.io"
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["web3_security"],
                autonomous_action=("tool_phishing_domain_scan", {"domain": domain}),
                latency_ms=round(dt, 4),
                reason="MetaMask veritabanında phishing domain kontrolü tespit edildi."
            )

        # 6. Akıllı Sözleşme Denetimi (Slither & Echidna)
        if any(k in t for k in ["echidna", "fuzz", "invariant"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["web3_security"],
                autonomous_action=("tool_smart_contract_fuzz", {"contract_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Crytic Echidna akıllı sözleşme fuzzing denetimi talep edildi."
            )

        if any(k in t for k in ["slither", "akilli sozlesme", "akıllı sözleşme", "smart contract", "solidity", "kontrat"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["web3_security"],
                autonomous_action=("tool_smart_contract_audit", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Crytic Slither akıllı sözleşme statik analizi talep edildi."
            )

        # 7. Motor Durumları / Sistem Sağlığı
        if any(k in t for k in ["motorlari listele", "motorları listele", "motor durumu", "hangi motorlar", "sistem sagligi", "sistem sağlığı", "canli motorlar", "canlı motorlar"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=("tool_system_engines_status", {}),
                latency_ms=round(dt, 4),
                reason="Sistem motorlarının canlı sağlık durumu sorgulandı."
            )

        # 8. Dark Web / OSINT Arama
        if any(k in t for k in ["dark web", "deep web", "onion", "ahmia", "threat intel"]) or re.search(r"\btor\b", t):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["darkweb_intel"],
                autonomous_action=("tool_darkweb_search", {"query": t}),
                latency_ms=round(dt, 4),
                reason="Dark Web ve Tor ağı istihbarat araması talep edildi."
            )

        # 9. Derin Araştırma (GPT-Researcher)
        if any(k in t for k in ["derin arastir", "derin araştır", "derinlemesine", "kapsamli arastir", "kapsamlı araştır", "literatur", "literatür", "gpt-researcher"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["deep_research"],
                autonomous_action=("tool_deep_research", {"query": t}),
                latency_ms=round(dt, 4),
                reason="GPT-Researcher çok kaynaklı derin araştırma motoru tetiklendi."
            )

        # Varsayılan: Anahtar Teslim Çözüm ve Kesin İcraat
        dt = (time.perf_counter() - t0) * 1000
        return RoutingDecision(
            agent=cls.ROLES["turnkey_solver"],
            autonomous_action=None,
            latency_ms=round(dt, 4),
            reason="Anahtar teslim kesin çözüm ve icraat yönlendirmesi."
        )
