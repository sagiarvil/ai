#!/usr/bin/env python3
"""
BARIŞ AI // ÇOKLU YEREL TARAYICI VE GİZLİLİK AĞLARI YÖNETİM MOTORU (BROWSER CONTROLLER)
Desteklenen Motorlar ve Ağlar:
1. Google Chrome (/Applications/Google Chrome.app) - Playwright CDP & Binary
2. Safari (/Applications/Safari.app) - AppleScript & WebKit Engine
3. Chromium & Firefox (Playwright Headless/Headed)
4. Tor Yönlendirmeli Ağ (SOCKS5 127.0.0.1:9050 Proxy)
5. I2P (Invisible Internet Project - i2pd HTTP Proxy 127.0.0.1:4444 / SOCKS5 127.0.0.1:4447)
6. Doğrudan Yerel İnternet Bağlantısı (Local ISP Direct)
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
SESSIONS_DIR = WORKSPACE_ROOT / "tools" / "browser_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SAFARI_PATH = "/Applications/Safari.app"

class LocalBrowserEngine:
    @classmethod
    async def open_and_extract(
        cls,
        url: str,
        browser_name: str = "chrome",
        use_tor: bool = False,
        use_i2p: bool = False,
        headless: bool = True,
        wait_seconds: float = 3.0
    ) -> Dict[str, Any]:
        """
        İstenen yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak belirtilen URL'ye gider,
        veriyi çeker ve oturum kaydını kaydeder. Tor veya I2P ağlarını destekler.
        """
        b_name = browser_name.lower().strip()
        t0 = time.time()

        proxy_config = None
        network_name = "Yerel İnternet"
        if use_tor:
            proxy_config = {"server": "socks5://127.0.0.1:9050"}
            network_name = "Tor SOCKS5 (9050)"
        elif use_i2p:
            proxy_config = {"server": "http://127.0.0.1:4444"}
            network_name = "I2P Invisible Internet (i2pd 4444)"

        # 1. Safari (AppleScript ile Yerel Safari Yönetimi)
        if "safari" in b_name and not headless:
            try:
                sc = f'''
                tell application "Safari"
                    activate
                    open location "{url}"
                    delay {wait_seconds}
                    set docText to text of front document
                    return docText
                end tell
                '''
                res = subprocess.run(["osascript", "-e", sc], capture_output=True, text=True, timeout=30)
                elapsed = round(time.time() - t0, 2)
                content = res.stdout[:5000] if res.returncode == 0 else f"[Safari AppleScript Hatası]: {res.stderr}"

                cls._save_session("safari", url, content, network_name)
                return {
                    "status": "SUCCESS",
                    "browser": "Safari (AppleScript Native)",
                    "network": network_name,
                    "url": url,
                    "elapsed": elapsed,
                    "content": content
                }
            except Exception:
                pass

        # 2. Playwright Motorları (Chrome, Chromium, WebKit)
        if not async_playwright:
            return {
                "status": "FAILED",
                "browser": b_name,
                "network": network_name,
                "url": url,
                "error": "Playwright modülü sistemde kurulu değil."
            }

        try:
            async with async_playwright() as p:
                browser = None
                if "chrome" in b_name and os.path.exists(CHROME_PATH):
                    browser = await p.chromium.launch(
                        executable_path=CHROME_PATH,
                        headless=headless,
                        proxy=proxy_config,
                        args=["--no-sandbox", "--disable-dev-shm-usage"]
                    )
                    used_engine = "Google Chrome (Local Binary)"
                elif "firefox" in b_name:
                    browser = await p.firefox.launch(headless=headless, proxy=proxy_config)
                    used_engine = "Firefox (Playwright)"
                elif "webkit" in b_name or "safari" in b_name:
                    browser = await p.webkit.launch(headless=headless, proxy=proxy_config)
                    used_engine = "WebKit (Safari Engine)"
                else:
                    browser = await p.chromium.launch(headless=headless, proxy=proxy_config)
                    used_engine = "Chromium (Playwright)"

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(wait_seconds)

                page_title = await page.title()
                raw_text = await page.inner_text("body")
                elapsed = round(time.time() - t0, 2)

                cls._save_session(used_engine, url, raw_text[:6000], network_name, page_title)
                await browser.close()

                return {
                    "status": "SUCCESS",
                    "browser": used_engine,
                    "network": network_name,
                    "url": url,
                    "title": page_title,
                    "elapsed": elapsed,
                    "content": raw_text[:4000]
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "browser": b_name,
                "network": network_name,
                "url": url,
                "error": str(e)
            }

    @classmethod
    def _save_session(cls, browser: str, url: str, content: str, network: str = "Direct", title: str = ""):
        sanitized_url = "".join([c if c.isalnum() else "_" for c in url])[:40]
        ts = time.strftime("%Y%m%d_%H%M%S")
        filepath = SESSIONS_DIR / f"session_{ts}_{sanitized_url}.json"
        data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "browser": browser,
            "network": network,
            "url": url,
            "title": title,
            "content_length": len(content),
            "content": content
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def list_sessions(cls) -> List[Dict[str, Any]]:
        sessions = []
        for p in sorted(SESSIONS_DIR.glob("session_*.json"), reverse=True):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    sessions.append({
                        "id": p.name,
                        "timestamp": d.get("timestamp"),
                        "browser": d.get("browser"),
                        "network": d.get("network", "Direct"),
                        "url": d.get("url"),
                        "title": d.get("title")
                    })
            except Exception:
                continue
        return sessions

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://httpbin.org/ip"
    use_i2p_flag = "--i2p" in sys.argv
    use_tor_flag = "--tor" in sys.argv
    print(f"[*] Test Başlatılıyor: {url} (I2P: {use_i2p_flag}, Tor: {use_tor_flag})")
    res = asyncio.run(LocalBrowserEngine.open_and_extract(url, browser_name="chrome", use_tor=use_tor_flag, use_i2p=use_i2p_flag))
    print(json.dumps(res, indent=2, ensure_ascii=False))
