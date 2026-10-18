#!/usr/bin/env python3
"""
BARIŞ AI // ÇOKLU YEREL TARAYICI YÖNETİM & WEB İCRA MOTORU (BROWSER CONTROLLER)
Desteklenen Tarayıcılar:
1. Google Chrome (/Applications/Google Chrome.app) - Playwright CDP & Binary
2. Safari (/Applications/Safari.app) - AppleScript & WebKit Engine
3. Chromium & Firefox (Playwright Headless/Headed)
4. Tor Yönlendirmeli Tarayıcı (SOCKS5 127.0.0.1:9050 Proxy)
5. Doğrudan Yerel İnternet Bağlantısı (Local ISP Direct)
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from playwright.async_api import async_playwright

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
        headless: bool = True,
        wait_seconds: float = 3.0
    ) -> Dict[str, Any]:
        """
        İstenen yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak belirtilen URL'ye gider,
        veriyi çeker ve oturum kaydını kaydeder.
        """
        b_name = browser_name.lower().strip()
        t0 = time.time()
        proxy_config = {"server": "socks5://127.0.0.1:9050"} if use_tor else None

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
                
                cls._save_session("safari", url, content)
                return {
                    "status": "SUCCESS",
                    "browser": "Safari (AppleScript Native)",
                    "url": url,
                    "elapsed": elapsed,
                    "content": content
                }
            except Exception as e:
                pass

        # 2. Playwright Motorları (Chrome, Chromium, WebKit)
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
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                title = await page.title()
                # Temiz metin çıkarma
                text_content = await page.evaluate("() => document.body.innerText")
                elapsed = round(time.time() - t0, 2)
                
                await browser.close()

                cls._save_session(used_engine, url, text_content[:4000])

                return {
                    "status": "SUCCESS",
                    "browser": used_engine,
                    "title": title,
                    "url": url,
                    "elapsed": elapsed,
                    "use_tor": use_tor,
                    "content": text_content[:4000]
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "browser": browser_name,
                "url": url,
                "error": str(e)
            }

    @classmethod
    def _save_session(cls, browser: str, url: str, content: str):
        """Tarayıcı ile toplanan verileri oturum dosyasına kaydeder."""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_name = "".join([c if c.isalnum() else "_" for c in url[:40]])
            filepath = SESSIONS_DIR / f"session_{timestamp}_{safe_name}.json"
            data = {
                "browser": browser,
                "url": url,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "content_preview": content[:1000]
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @classmethod
    def list_saved_sessions(cls) -> List[Dict[str, Any]]:
        """Kaydedilmiş tüm tarayıcı oturumlarını listeler."""
        sessions = []
        if SESSIONS_DIR.exists():
            for f in sorted(SESSIONS_DIR.glob("*.json"), reverse=True)[:10]:
                try:
                    with open(f, "r", encoding="utf-8") as sfile:
                        sessions.append(json.load(sfile))
                except Exception:
                    continue
        return sessions

if __name__ == "__main__":
    async def main():
        print("[*] Yerel Google Chrome Testi Başlatılıyor...")
        r = await LocalBrowserEngine.open_and_extract("https://httpbin.org/headers", browser_name="chrome")
        print("Sonuç:", r.get("status"), r.get("browser"), r.get("content")[:200])
    asyncio.run(main())
