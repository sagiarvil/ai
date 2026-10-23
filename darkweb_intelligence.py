#!/usr/bin/env python3
"""
BARIŞ AI // DARK WEB İSTİHBARAT & TOR CRAWLER ÇEKİRDEĞİ (v1.0)
Özellikler:
1. TorCrawler: aiohttp_socks + SOCKS5 (127.0.0.1:9050) üzerinden .onion sitelerini anonim kazıma ve ayrıştırma.
2. DarkWebIntelligence: Tor arama motorları üzerinden kullanıcı adı, e-posta, marka ve alan adı sızıntı taraması (OSINT).
3. E-posta, kripto cüzdan (BTC/XMR) ve .onion bağlantılarını otomatik ayıklayan istihbarat ayrıştırıcısı.
"""

import asyncio
import re
import urllib.parse
from typing import Dict, Any, List, Optional
import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup

TOR_SOCKS_URL = "socks5://127.0.0.1:9050"
DDG_ONION_SEARCH = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/html/?q="

# OSINT Regex Kalıpları
RE_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')
RE_ONION = re.compile(r'\b[a-z2-7]{16,56}\.onion\b', re.IGNORECASE)
RE_BTC = re.compile(r'\b(?:1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,45}\b')
RE_XMR = re.compile(r'\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b')


class TorCrawler:
    """Tor SOCKS5 yerel ağı üzerinden .onion sitelerini güvenle ziyaret eden ve kazıyan motor."""

    @classmethod
    async def crawl(cls, url: str, timeout: int = 25) -> Dict[str, Any]:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url

        connector = ProxyConnector.from_url(TOR_SOCKS_URL, rdns=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        try:
            timeout_cfg = aiohttp.ClientTimeout(total=timeout, connect=12)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(url, timeout=timeout_cfg, allow_redirects=True) as resp:
                    status = resp.status
                    raw_html = await resp.text(encoding="utf-8", errors="replace")

                    soup = BeautifulSoup(raw_html, "html.parser")
                    title = soup.title.string.strip() if soup.title and soup.title.string else "Başlık Yok"

                    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
                        tag.decompose()

                    clean_text = soup.get_text(separator=" ", strip=True)
                    clean_text = re.sub(r"\s+", " ", clean_text)

                    # Otomatik OSINT ayrıştırma
                    emails = sorted(set(RE_EMAIL.findall(raw_html)))
                    onions = sorted(set(RE_ONION.findall(raw_html)))
                    btc_wallets = sorted(set(RE_BTC.findall(raw_html)))
                    xmr_wallets = sorted(set(RE_XMR.findall(raw_html)))

                    return {
                        "success": True,
                        "url": url,
                        "title": title,
                        "status_code": status,
                        "content_length": len(clean_text),
                        "snippet": clean_text[:3000],
                        "emails": emails[:20],
                        "onion_links": onions[:30],
                        "wallets": {
                            "btc": btc_wallets[:10],
                            "xmr": xmr_wallets[:10]
                        }
                    }
        except asyncio.TimeoutError:
            return {"success": False, "url": url, "error": f"Tor bağlantı zaman aşımı ({timeout}s). .onion sunucusu kapalı veya yanıt vermiyor."}
        except Exception as e:
            return {"success": False, "url": url, "error": f"Tor kazıma hatası: {str(e)}"}

    @classmethod
    def crawl_sync(cls, url: str, timeout: int = 25) -> Dict[str, Any]:
        """Senkron ortamlardan doğrudan çağırmak için yürütücü."""
        return asyncio.run(cls.crawl(url, timeout=timeout))


class DarkWebIntelligence:
    """Dark Web ve Tor arama motorları üzerinden tehdit ve sızıntı istihbaratı (OSINT)."""

    @classmethod
    async def search(cls, query: str, max_results: int = 10, timeout: int = 25) -> List[Dict[str, str]]:
        """Tor DuckDuckGo Onion üzerinden canlı arama yapar."""
        encoded = urllib.parse.quote(query)
        search_url = f"{DDG_ONION_SEARCH}{encoded}"

        connector = ProxyConnector.from_url(TOR_SOCKS_URL, rdns=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
        }

        results = []
        try:
            timeout_cfg = aiohttp.ClientTimeout(total=timeout, connect=12)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(search_url, timeout=timeout_cfg) as resp:
                    if resp.status != 200:
                        return []
                    html = await resp.text(encoding="utf-8", errors="replace")
                    soup = BeautifulSoup(html, "html.parser")

                    for div in soup.find_all("div", class_="result"):
                        h2 = div.find("h2", class_="result__title")
                        snip = div.find("a", class_="result__snippet")
                        if h2:
                            link = h2.find("a")
                            raw_href = link.get("href", "") if link else ""
                            actual_url = raw_href
                            if "uddg=" in raw_href:
                                try:
                                    actual_url = urllib.parse.unquote(raw_href.split("uddg=")[1].split("&")[0])
                                except Exception:
                                    pass

                            results.append({
                                "title": h2.get_text(strip=True),
                                "url": actual_url,
                                "snippet": snip.get_text(strip=True) if snip else ""
                            })
                            if len(results) >= max_results:
                                break
        except Exception:
            pass

        return results[:max_results]

    @classmethod
    def search_sync(cls, query: str, max_results: int = 10, timeout: int = 25) -> List[Dict[str, str]]:
        return asyncio.run(cls.search(query, max_results=max_results, timeout=timeout))

    @classmethod
    async def osint_threat_scan(cls, target: str, scan_type: str = "genel") -> Dict[str, Any]:
        """
        Belirtilen hedef (e-posta, kullanıcı adı, alan adı, marka) için
        Dark Web sızıntı ve tehdit istihbaratı taraması yürütür.
        """
        scan_queries = [
            f'"{target}" leak breach',
            f'"{target}" credentials password',
            f'"{target}" database dump'
        ]

        aggregated_findings = []
        seen_urls = set()

        for q in scan_queries:
            items = await cls.search(q, max_results=5)
            for it in items:
                u = it.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    aggregated_findings.append(it)

        # Risk Seviyesi Belirleme
        severity = "DÜŞÜK"
        if len(aggregated_findings) >= 5:
            severity = "YÜKSEK"
        elif len(aggregated_findings) >= 2:
            severity = "ORTA"

        return {
            "target": target,
            "scan_type": scan_type,
            "severity": severity,
            "total_findings": len(aggregated_findings),
            "findings": aggregated_findings,
            "status": "TAMAMLANDI",
            "summary": f"'{target}' için Dark Web üzerinde {len(aggregated_findings)} sızıntı/istihbarat kaydı tespit edildi. Risk Seviyesi: {severity}."
        }

    @classmethod
    def osint_threat_scan_sync(cls, target: str, scan_type: str = "genel") -> Dict[str, Any]:
        return asyncio.run(cls.osint_threat_scan(target, scan_type=scan_type))
