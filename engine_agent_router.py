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
        raw_text = message.strip()
        lower_text = raw_text.lower()
        urls = re.findall(r'https?://(?:www\.)?(?:github|gitlab)\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+', raw_text)

        # 0. Güvenlik İhlali / Sistem Dosyaları Koruması
        if any(bad in lower_text for bad in ["talimatlarini unut", "talimatlarını unut", "/etc/passwd", "/etc/shadow", "serbest bir linux"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Güvenlik İhlali: Sistem dosyalarına ve yetkisiz komutlara erişim engellendi."
            )

        # 1. KURAL: Açık URL + Eylem = DOĞRUDAN ARAÇ (Repo İnceleme)
        if urls and any(word in lower_text for word in ["incele", "analiz et", "tara", "bak", "inspect", "scan", "klonla"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["github_hunter"],
                autonomous_action=("tool_github_inspect", {"repo_full_name": urls[0]}),
                latency_ms=round(dt, 4),
                reason="Explicit URL inspection request"
            )

        # 2. KURAL: Açık URL + Danışmanlık = SADECE MUHAKEME (Araç Yok)
        if urls and any(word in lower_text for word in ["nasıl katkı", "nasil katki", "ne katkı", "ne katki", "sence", "mantıklı mı", "mantikli mi", "öneri", "think", "opinion"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Architectural reasoning about a provided repo"
            )

        # 3. KURAL: Güvenlik Tarama Talebi (Inline Kod Yoksa Klasör Taraması)
        has_inline_code = any(k in raw_text for k in ["<?php", "def ", "class ", "SELECT ", "eval(", "function "])
        if not has_inline_code and any(word in lower_text for word in ["gitleaks", "trufflehog"]) and "sakın" not in lower_text:
            dt = (time.perf_counter() - t0) * 1000
            tool = "tool_trufflehog_scan" if "trufflehog" in lower_text else "tool_secret_leak_scan"
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=(tool, {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Explicit workspace security scan request"
            )

        # 4. KURAL: Açık GitHub Arama Talebi ("bana ... repo bul")
        if any(k in lower_text for k in ["repo bul", "repolarını bul", "açık kaynak repo bul", "acik kaynak repo bul"]) and not any(k in lower_text for k in ["arama yapma", "bulma", "kıyasla", "karşılaştır"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["github_hunter"],
                autonomous_action=("tool_github_search", {"query": raw_text, "min_stars": 5}),
                latency_ms=round(dt, 4),
                reason="Explicit GitHub search request"
            )

        # 5. KURAL: Sistem Motorları ve Sağlık Durumu
        if any(k in lower_text for k in ["motorlari listele", "motorları listele", "motor durumu", "hangi motorlar", "sistem sagligi", "sistem sağlığı", "canli motorlar", "canlı motorlar"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["turnkey_solver"],
                autonomous_action=("tool_system_engines_status", {}),
                latency_ms=round(dt, 4),
                reason="Sistem motorlarının canlı sağlık durumu sorgulandı."
            )

        # 6. KURAL: VARSAYILAN (DEFAULT) - HER ŞEYİ DOĞRUDAN LLM'E BIRAK (SIFIR ENGEL, SIFIR APTAL BEKÇİ)
        dt = (time.perf_counter() - t0) * 1000
        return RoutingDecision(
            agent=cls.ROLES["turnkey_solver"],
            autonomous_action=None,
            latency_ms=round(dt, 4),
            reason="Fallback to LLM for natural language understanding and turnkey reasoning"
        )
