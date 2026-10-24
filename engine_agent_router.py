#!/usr/bin/env python3
"""
Barış AI Autonomous Multi-Agent & Engine Router (Sub-Millisecond Kernel)
Kullanıcı talimatlarını mikrosaniyeler içinde analiz ederek en yetkin uzman ajanı
ve canlı sistem motorunu otonom olarak devreye alır.
"""

import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
            primary_engine="Gitleaks v8.30.1 & Google OSV / Aqua Trivy",
            system_prompt=(
                "Sen Barış AI Kıdemli Siber Güvenlik ve Tehdit Denetim Uzmanısın. "
                "Sistemindeki Gitleaks, Aqua Trivy ve Google OSV-Scanner motorlarını kullanarak "
                "açık API anahtarları, şifre sızıntıları, tokenler ve CVE bağımlılık zafiyetlerini denetlersin. "
                "Sonuçları net, maddeler halinde ve Türkçe olarak raporlarsın."
            ),
            allowed_tools=["tool_secret_leak_scan", "tool_vulnerability_scan", "tool_direct_answer"]
        ),
        "github_hunter": AgentRole(
            agent_id="github_hunter",
            agent_name="🚀 Açık Kaynak Kod & GitHub Repo Avcısı Ajanı",
            primary_engine="GitHub CLI (gh) & Source Tree Code Inspector",
            system_prompt=(
                "Sen Barış AI Açık Kaynak İstihbarat ve GitHub Repo Avcısısın. "
                "Yetkili GitHub motorunu kullanarak kullanıcının aradığı konuda gerçekten çalışan kaynak kodları "
                "içeren repoları bulur, kod varlığını teyit eder ve doğrudan linkleriyle Markdown tablosu olarak sunarsın."
            ),
            allowed_tools=["tool_github_search", "tool_github_inspect", "tool_direct_answer"]
        ),
        "web3_security": AgentRole(
            agent_id="web3_security",
            agent_name="⛓️ Web3 & Akıllı Sözleşme Güvenlik Ajanı",
            primary_engine="Crytic Slither v0.11.6 & MetaMask Phishing DB (107K+ Domain)",
            system_prompt=(
                "Sen Barış AI Web3 Güvenlik ve Akıllı Sözleşme Denetçisisin. "
                "Solidity sözleşmelerini Slither ile reentrancy ve mantık açıklarına karşı denetler, "
                "şüpheli alan adlarını MetaMask 107.000+ domainlik karalistesinde anlık tararsın."
            ),
            allowed_tools=["tool_smart_contract_audit", "tool_phishing_domain_scan", "tool_direct_answer"]
        ),
        "darkweb_intel": AgentRole(
            agent_id="darkweb_intel",
            agent_name="🕵️ Dark Web & OSINT İstihbarat Ajanı",
            primary_engine="Tor SOCKS5 Engine, Ahmia & DuckDuckGo Onion",
            system_prompt=(
                "Sen Barış AI Dark Web ve Tehdit İstihbaratı Analistisin. "
                "Tor ağı üzerindeki sızıntıları, .onion servislerini ve OSINT veri tabanlarını tarar, "
                "kullanıcıya filtrelenmiş ve doğrulanmış siber tehdit istihbaratı sunarsın."
            ),
            allowed_tools=["tool_darkweb_search", "tool_onion_crawl", "tool_threat_intel_scan", "tool_direct_answer"]
        ),
        "deep_research": AgentRole(
            agent_id="deep_research",
            agent_name="📚 GPT-Researcher Derin Araştırma Ajanı",
            primary_engine="GPT-Researcher Multi-Source Synthesizer",
            system_prompt=(
                "Sen Barış AI Derin Araştırma ve Sentez Ajanısın. "
                "Belirtilen konularda sayfaların tam metinlerini toplayıp, bot engelleyicileri filtreleyerek "
                "akademik ve kurumsal düzeyde derin araştırma raporları hazırlarsın."
            ),
            allowed_tools=["tool_deep_research", "tool_direct_answer"]
        ),
        "code_executor": AgentRole(
            agent_id="code_executor",
            agent_name="⚙️ Yüksek Başarımlı Yerel Kod & Hesaplama Ajanı",
            primary_engine="Python 3.14 Local Execution Kernel",
            system_prompt=(
                "Sen Barış AI Deterministik Kod ve Hesaplama Motorusun. "
                "Kullanıcının talep ettiği analiz ve veri işleme görevlerini doğrudan yerel Python ile "
                "eksiksiz ve bağımsız doğrulama kanıtıyla tamamlarsın."
            ),
            allowed_tools=[]  # Geleneksel araç seti (tool_write_file, tool_run_shell vb.)
        ),
        "consultant": AgentRole(
            agent_id="consultant",
            agent_name="💡 Baş Danışman ve Sistem Mimarı",
            primary_engine="Barış AI High-Level Reasoning",
            system_prompt=(
                "Sen Barış AI Kıdemli Teknoloji ve Mimari Danışmanısın. "
                "Kullanıcının stratejik sorularına dosya yazmadan doğrudan pedagojik ve teknik doyuruculukla yanıt verirsin."
            ),
            allowed_tools=["tool_direct_answer", "tool_system_engines_status"]
        )
    }

    @classmethod
    def route(cls, message: str, workspace: str, expected_files: Optional[dict] = None) -> RoutingDecision:
        t0 = time.perf_counter()
        t = (message or "").lower().strip()

        # 1. Kod / Dosya Yazma Görevi (Strict Code Execution)
        if expected_files or any(k in t for k in ["dosyası", "dosyaya", "tablosu", "scripti", "kodunu yaz", "proje oluştur", "dosyaya yaz", "dosyaya kaydet"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["code_executor"],
                autonomous_action=None,
                latency_ms=round(dt, 4),
                reason="Doğrudan dosya oluşturma / kod yürütme kabul koşulu tespit edildi."
            )

        # 2. Sızıntı / Şifre Taraması (Gitleaks)
        if any(k in t for k in ["gitleaks", "sızıntı", "şifre sızıntısı", "secret leak", "api anahtarı sızıntısı", "token sızıntısı"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_secret_leak_scan", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Gitleaks gizli anahtar ve şifre sızıntı taraması talep edildi."
            )

        # 3. Zafiyet / CVE Taraması (OSV-Scanner / Trivy)
        if any(k in t for k in ["zafiyet", "cve", "güvenlik açığı", "trivy", "osv", "osv-scanner", "bağımlılık taraması"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["security_auditor"],
                autonomous_action=("tool_vulnerability_scan", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Açık kaynak bağımlılık zafiyeti (CVE) taraması talep edildi."
            )

        # 4. GitHub Kod & Repo Avcısı (GitHub CLI)
        if any(k in t for k in ["github", "repo", "açık kaynak kod", "çalışan repo", "proje bul"]):
            # Sorguyu temizle (kelime sınırları ile tam eşleşme)
            q = re.sub(r"\b(github|da|de|üzerinde|bana|bul|ara|çalışan|repo|repolarını|projeleri)\b", "", t, flags=re.IGNORECASE).strip()
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
        if any(k in t for k in ["phishing", "sahte domain", "zararlı domain", "oltalama", "metamask"]):
            # Domain ayıkla
            match = re.search(r"([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", t)
            domain = match.group(1) if match else "metamask.io"
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["web3_security"],
                autonomous_action=("tool_phishing_domain_scan", {"domain": domain}),
                latency_ms=round(dt, 4),
                reason="MetaMask veritabanında phishing domain kontrolü tespit edildi."
            )

        # 6. Akıllı Sözleşme Denetimi (Slither)
        if any(k in t for k in ["slither", "akıllı sözleşme", "smart contract", "solidity", "kontrat denetimi"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["web3_security"],
                autonomous_action=("tool_smart_contract_audit", {"target_path": workspace}),
                latency_ms=round(dt, 4),
                reason="Crytic Slither ile akıllı sözleşme güvenlik denetimi talep edildi."
            )

        # 7. Motor Durumları / Sistem Sağlığı
        if any(k in t for k in ["motorları listele", "motor durumu", "hangi motorlar", "sistem sağlığı", "canlı motorlar", "motorların durumu"]):
            dt = (time.perf_counter() - t0) * 1000
            return RoutingDecision(
                agent=cls.ROLES["consultant"],
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

        # Varsayılan: Genel Danışmanlık ve Muhakeme
        dt = (time.perf_counter() - t0) * 1000
        return RoutingDecision(
            agent=cls.ROLES["consultant"],
            autonomous_action=None,
            latency_ms=round(dt, 4),
            reason="Genel danışmanlık ve pedagojik muhakeme yönlendirmesi."
        )
