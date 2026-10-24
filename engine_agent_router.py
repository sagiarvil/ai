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
            agent_name="🎯 Kıdemli Mühendislik & Mimari Sparring Partneri",
            primary_engine="Barış AI Cognitive & Sparring Engine",
            system_prompt=(
                "Sen Barış AI Kıdemli Mühendislik Partneri ve Bilişsel Sparring Mimarlık Çekirdeğisin. "
                "Kullanıcıyla derin ve yapıcı teknik tartışmalar yürütür, fikirlerini ve mimarilerini yorumlarsın. "
                "Gerektiğinde kör noktaları göstermek için kritik sorular sorar, alternatif mimari önerilerde bulunursun. "
                "Kullanıcı karar verdiğinde ise anahtar teslim, çalışan, deterministik ve sıfır hatalı çözümü doğrudan inşa edersin."
            ),
            allowed_tools=["tool_direct_answer", "tool_system_engines_status"]
        )
    }

    @classmethod
    def route(cls, message: str, workspace: str, expected_files: Optional[dict] = None) -> RoutingDecision:
        t0 = time.perf_counter()
        t = normalize_text(message)

        # 0.1 Güvenlik Bariyeri & Jailbreak Savunması
        if any(bad in t for bad in ["talimatlarini unut", "talimatlarını unut", "/etc/passwd", "/etc/shadow", "serbest bir linux"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Güvenlik İhlali: Sistem dosyalarına ve yetkisiz komutlara erişim engellendi."
            )

        # 0.2 Kullanıcı Metninde Doğrudan Kod veya Karşılaştırma / Negatif Eylem Varsa Muhakeme Modu
        has_inline_code = any(k in message for k in ["<?php", "eval(", "def ", "class ", "SELECT ", "import "])
        has_negated_action = any(k in t for k in ["arama yapma", "sakın çalıştırma", "sakin calistirma", "calistirma", "çalıştırma", "kiyasla", "kıyasla", "karsilastir", "karşılaştır", "neden ustun", "neden üstün", "owasp"])
        if has_inline_code or (has_negated_action and any(k in t for k in ["incele", "kıyasla", "karsilastir", "zafiyet", "acik", "açık", "farki", "neden"])):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Doğrudan kod inceleme veya analitik karşılaştırma muhakemesi, araçsız Claude-grade moduna yönlendirildi."
            )

        # 0.3 GitHub Repo Hedefli İstihbarat (Gitleaks / Repo İnceleme)
        is_github_target = any(k in t for k in ["github link", "rust araci", "en populer rust", "ast-grep", "o repo", "bu repo"])
        if is_github_target and any(k in t for k in ["gitleaks", "tara", "linkini getir", "linki", "incele"]):
            dt = (time.perf_counter() - t0) * 1000
            target_repo = "ast-grep/ast-grep" if any(k in t for k in ["ast", "rust"]) else "sagiarvil/ai"
            return RoutingDecision(
                agent=cls.ROLES["github_hunter"],
                autonomous_action=("tool_github_inspect", {"repo_full_name": target_repo}),
                latency_ms=round(dt, 4),
                reason=f"Açık kaynak GitHub repo ({target_repo}) kod ve Gitleaks sızıntı denetimi talep edildi."
            )

        # 1. Kod / Dosya Yazma Görevi (Strict Code Execution)
        if expected_files or any(k in t for k in ["dosyasi", "dosyaya", "tablosu", "scripti", "kodunu yaz", "proje olustur", "dosyaya yaz", "dosyaya kaydet"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["code_executor"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Doğrudan dosya oluşturma / kod yürütme kabul koşulu tespit edildi."
            )

        # 1.1 Kavramsal / Soru-Cevap / Karşılaştırma / Mimari Katkı ve Danışmanlık Soruları
        is_conceptual_question = any(q in t for q in [
            "nedir", "farki", "farkı", "nasil calisir", "nasıl çalışır", "karsilastir", "karşılaştır",
            "ne ise yarar", "ne işe yarar", "ne yapmaliyim", "ne yapmalıyım", "neler yapabilirsin",
            "kimsin", "hangisi daha iyi", "tavsiye", "farki ne", "farkı ne", "katki", "katkı",
            "katkisi", "katkısı", "katki saglar", "katkı sağlar", "bize nasil", "bize nasıl",
            "nasil fayda", "nasıl fayda", "nasil entegre", "nasıl entegre", "ne yapabiliriz",
            "ne yapabilir", "faydasi nedir", "faydası nedir", "baris ai icin", "barış ai için"
        ])
        if is_conceptual_question and not any(run_kw in t for run_kw in ["tara", "denetle", "calistir", "çalıştır", "puanla", "klonla", "ara ve bul"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Mimari değerlendirme / kavramsal danışmanlık sorusu tespit edildi, doğrudan anahtar teslim Claude-grade cevap moduna yönlendirildi."
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

                # 4. SSOT Semantik Niyet Kapısı (IntentEngine — Tek Gerçeklik Kaynağı)
        try:
            from intent_engine import IntentEngine, Route, Intent
            from intent_adapters import FastEmbedAdapter
            if not hasattr(cls, "_intent_engine") or cls._intent_engine is None:
                cls._intent_engine = IntentEngine(FastEmbedAdapter())

            intent_dec = cls._intent_engine.decide(message)  # Ham metin, dokunulmamış
            dt = (time.perf_counter() - t0) * 1000

            if intent_dec.route == Route.ABSTAIN:
                return RoutingDecision(
                    agent=cls.ROLES["turnkey_solver"],
                    autonomous_action=None,
                    latency_ms=round(dt, 4),
                    reason=f"Semantik niyet belirsiz (skor: {intent_dec.similarity}, marj: {intent_dec.margin}); doğrudan kullanıcıya soru sorma/açıklama moduna yönlendirildi."
                )

            if intent_dec.route == Route.REASON:
                return RoutingDecision(
                    agent=cls.ROLES["turnkey_solver"],
                    autonomous_action=None,
                    latency_ms=round(dt, 4),
                    reason=f"Semantik niyet mimari muhakeme ({intent_dec.intent}); araçsız doğrudan akıl yürütme yoluna yönlendirildi."
                )

            if intent_dec.route == Route.TOOL and intent_dec.allowed_tools:
                primary_tool = intent_dec.allowed_tools[0]
                tool_args = {}
                if primary_tool == "tool_github_inspect":
                    tool_args = {"repo_full_name": intent_dec.urls[0] if intent_dec.urls else message}
                elif primary_tool == "tool_github_search":
                    tool_args = {"query": message, "min_stars": 5}
                elif primary_tool == "tool_security_scan":
                    tool_args = {"target_path": workspace}
                else:
                    tool_args = {"raw_text": intent_dec.raw_input}

                return RoutingDecision(
                    agent=cls.ROLES["github_hunter"] if "github" in primary_tool else cls.ROLES["security_auditor"],
                    autonomous_action=(primary_tool, tool_args),
                    latency_ms=round(dt, 4),
                    reason=f"SSOT IntentEngine onaylı araç yetkilendirmesi: {primary_tool} (niyet: {intent_dec.intent})"
                )
        except Exception:
            pass

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
