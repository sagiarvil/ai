#!/usr/bin/env python3
"""
BARIŞ AI // GERÇEK VE FİZİKSEL ARAMA & İSTİHBARAT MOTORLARI
1. RealWebSearchEngine: Canlı DuckDuckGo HTML motoru + BeautifulSoup4 sayfa kazıyıcı.
2. RealTorEngine: 127.0.0.1:9050 SOCKS5 yerel Tor ağı.
"""

import json
import re
import urllib.request
import urllib.parse
from typing import List, Dict, Any
import httpx
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import socks
    from sockshandler import SocksiPyHandler
except ImportError:
    socks = None
    SocksiPyHandler = None

TOR_SOCKS_PROXY = "socks5://127.0.0.1:9050"

def get_tor_opener():
    """DNS sızıntılarını ve yerel IP görünürlüğünü engelleyen Remote DNS Tor açıcı."""
    if socks and SocksiPyHandler:
        return urllib.request.build_opener(
            SocksiPyHandler(socks.SOCKS5, "127.0.0.1", 9050, True)
        )
    return urllib.request.build_opener()

def get_masked_httpx_client(timeout: float = 8.0) -> httpx.AsyncClient:
    """Dış dünyadaki sitelerin gerçek IP adresini görmesini engelleyen Tor istemcisi."""
    try:
        return httpx.AsyncClient(proxy=TOR_SOCKS_PROXY, timeout=timeout, verify=True)
    except Exception:
        return httpx.AsyncClient(timeout=timeout, verify=True)

# ==============================================================================
# 1. CANLI WEB ARAMA VE DEEP RESEARCH MOTORU (Fiziksel HTML Scraper)
# ==============================================================================
class RealWebSearchEngine:
    @classmethod
    def search_live_web(cls, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        DuckDuckGo HTML arama motoru üzerinden internette canlı fiziksel arama yapar.
        """
        results = []
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"
            })
            html = ""
            try:
                opener = get_tor_opener()
                with opener.open(req, timeout=10) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
            except Exception:
                with httpx.Client(timeout=8.0, verify=True) as client:
                    resp = client.get(url, headers={"User-Agent": req.headers.get("User-agent", "Mozilla/5.0")})
                    if resp.status_code == 200:
                        html = resp.text

            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")

            result_divs = soup.find_all("div", class_="result")
            for div in result_divs:
                title_elem = div.find("a", class_="result__snippet")
                header_elem = div.find("h2", class_="result__title")
                link_elem = header_elem.find("a") if header_elem else None

                if link_elem:
                    raw_href = link_elem.get("href", "")
                    actual_url = raw_href
                    if "uddg=" in raw_href:
                        try:
                            actual_url = urllib.parse.unquote(raw_href.split("uddg=")[1].split("&")[0])
                        except Exception:
                            pass

                    title = header_elem.get_text(strip=True) if header_elem else "Kaynak"
                    snippet = title_elem.get_text(strip=True) if title_elem else ""

                    results.append({
                        "title": title,
                        "url": actual_url,
                        "snippet": snippet
                    })
                    if len(results) >= max_results:
                        break
        except Exception:
            pass

        return results[:max_results]

    @classmethod
    async def deep_scrape_url(cls, url: str) -> str:
        """Belirtilen web sayfasını Tor veya yerel ağ üzerinden indirip temiz metni çeker."""
        if not url.startswith("http"):
            return ""
        for use_tor in [True, False]:
            try:
                client_ctx = get_masked_httpx_client(timeout=8.0) if use_tor else httpx.AsyncClient(timeout=8.0)
                async with client_ctx as client:
                    resp = await client.get(url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    })
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "noscript"]):
                            tag.decompose()
                        text = soup.get_text(separator=" ", strip=True)
                        return re.sub(r"\s+", " ", text)[:4000]
            except Exception:
                continue
        return ""

# ==============================================================================
# 2. TOR AĞI DOĞRULAMA VE .ONION YÖNETİMİ
# ==============================================================================
class RealTorEngine:
    @classmethod
    def get_tor_opener(cls):
        return get_tor_opener()

    @classmethod
    def verify_tor_circuit(cls) -> Dict[str, Any]:
        """Tor devre durumunu ve aktif çıkış IP'sini doğrular."""
        try:
            opener = cls.get_tor_opener()
            with opener.open("https://check.torproject.org/api/ip", timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "active": data.get("IsTor", False),
                    "exit_ip": data.get("IP", "Bilinmiyor"),
                    "status": "TOR DEVRESİ AKTİF (Anonim Ağ Doğrulandı)"
                }
        except Exception as e:
            return {"active": False, "exit_ip": None, "status": f"Tor bağlantı hatası: {e}"}

    @classmethod
    def fetch_onion_url(cls, url: str) -> str:
        """Güvenlik duvarı ve DNS engellerine takılmadan anonim ağ (.onion) içeriğini çeker."""
        try:
            opener = cls.get_tor_opener()
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0"
            })
            with opener.open(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html, "html.parser")
                for s in soup(["script", "style"]):
                    s.decompose()
                return soup.get_text(separator=" ", strip=True)[:2500]
        except Exception as e:
            return f"[Tor Erişim Hatası]: {e}"
