"""
Barış AI - Endüstriyel Otonom Web Ajanı ve Görsel Tarayıcı Motoru (Set-of-Mark & Live Actuation)
================================================================================================
Bu modül; sıradan bir Playwright betiği değil, endüstriyel seviyede bir "Web Browser Agent"
mimarisi sunar:
1. Set-of-Mark (SoM) İşaretleme: Sayfadaki tüm etkileşimli öğelere (buton, input, link) benzersiz
   [data-baris-id] numaraları atar ve canlı ekranda görsel rozetlerle (badge) işaretler.
2. Canlı Görsel İmleç & Vurgulama (Visual Highlight): Ajan bir öğeye tıklamadan veya yazmadan
   hemen önce ekranda o öğeyi parlak çerçeveyle vurgular; kullanıcı ajanın ne yaptığını canlı izler.
3. Otonom Görev Döngüsü (actuate_autonomous_mission): Üst düzey bir görev emri aldığında
   (Gözlemle -> Düşün -> Tıkla/Yaz -> Doğrula) döngüsünü kendi içinde 15 adıma kadar otonom yürütür.
4. Kalıcı Oturum (Stateful Context) ve Tor / I2P Gizlilik Ağı Desteği.
5. Geriye Dönük %100 Uyumluluk: LocalBrowserEngine.open_and_extract() imzasını birebir korur.
"""

import os
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("AutonomousBrowserAgent")

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SESSIONS_DIR = Path(__file__).parent.resolve() / "tools" / "browser_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


class LocalBrowserEngine:
    """
    Set-of-Mark (SoM) görsel indeksleme ve otonom görev döngüsüne sahip
    canlı tarayıcı kontrol motoru.
    """
    _playwright = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _active_network: str = "Yerel İnternet"

    @classmethod
    def _get_proxy_config(cls, use_tor: bool, use_i2p: bool) -> Optional[Dict[str, str]]:
        if use_tor:
            cls._active_network = "Tor SOCKS5 (127.0.0.1:9050)"
            return {"server": "socks5://127.0.0.1:9050"}
        if use_i2p:
            cls._active_network = "I2P HTTP Proxy (127.0.0.1:4444)"
            return {"server": "http://127.0.0.1:4444"}
        cls._active_network = "Yerel İnternet"
        return None

    @classmethod
    async def ensure_live_session(
        cls,
        browser_name: str = "chrome",
        use_tor: bool = False,
        use_i2p: bool = False,
        headless: bool = False  # Varsayılan olarak CANLI EKRAN açar
    ) -> Page:
        """Canlı tarayıcı penceresini başlatır veya mevcut açık pencereyi döndürür."""
        if cls._page and not cls._page.is_closed():
            return cls._page

        if not cls._playwright:
            cls._playwright = await async_playwright().start()

        proxy_cfg = cls._get_proxy_config(use_tor, use_i2p)
        b_name = browser_name.lower()

        launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"]

        if "chrome" in b_name and os.path.exists(CHROME_PATH):
            cls._browser = await cls._playwright.chromium.launch(
                executable_path=CHROME_PATH,
                headless=headless,
                proxy=proxy_cfg,
                args=launch_args
            )
        elif "firefox" in b_name:
            cls._browser = await cls._playwright.firefox.launch(headless=headless, proxy=proxy_cfg)
        elif "webkit" in b_name or "safari" in b_name:
            cls._browser = await cls._playwright.webkit.launch(headless=headless, proxy=proxy_cfg)
        else:
            cls._browser = await cls._playwright.chromium.launch(
                headless=headless,
                proxy=proxy_cfg,
                args=launch_args
            )

        cls._context = await cls._browser.new_context(viewport={"width": 1440, "height": 900})
        cls._page = await cls._context.new_page()
        return cls._page

    @classmethod
    async def inject_som_and_extract_dom(cls, page: Page, show_badges: bool = True) -> List[Dict[str, Any]]:
        """
        Set-of-Mark (SoM) Enjeksiyonu:
        Sayfadaki tüm görünür etkileşimli öğelere [data-baris-id="N"] atar,
        ekranda numaralı görsel etiketler çizer ve LLM için temiz bir liste döndürür.
        """
        js_som = """
        (showBadges) => {
            // Eski rozetleri temizle
            document.querySelectorAll('.baris-som-badge').forEach(e => e.remove());

            const interactiveSelectors = [
                'a[href]', 'button', 'input:not([type="hidden"])', 'textarea',
                'select', '[role="button"]', '[role="link"]', '[role="tab"]',
                '[onclick]', 'summary'
            ];
            const rawElements = document.querySelectorAll(interactiveSelectors.join(','));
            const items = [];
            let idCounter = 1;

            rawElements.forEach((el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (
                    rect.width > 8 && rect.height > 8 &&
                    rect.top >= 0 && rect.left >= 0 &&
                    rect.top <= window.innerHeight &&
                    style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    parseFloat(style.opacity || '1') > 0.1
                ) {
                    const barisId = idCounter++;
                    el.setAttribute('data-baris-id', String(barisId));

                    if (showBadges) {
                        const badge = document.createElement('div');
                        badge.className = 'baris-som-badge';
                        badge.innerText = `[${barisId}]`;
                        badge.style.cssText = `
                            position: fixed;
                            top: ${Math.max(0, rect.top - 8)}px;
                            left: ${Math.max(0, rect.left - 4)}px;
                            background: rgba(220, 38, 38, 0.9);
                            color: #fff;
                            font-family: monospace;
                            font-size: 10px;
                            font-weight: bold;
                            padding: 1px 4px;
                            border-radius: 3px;
                            z-index: 2147483647;
                            pointer-events: none;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.4);
                        `;
                        document.body.appendChild(badge);
                    }

                    const label = (
                        el.innerText ||
                        el.value ||
                        el.placeholder ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('title') ||
                        el.getAttribute('href') ||
                        ''
                    ).replace(/\\s+/g, ' ').trim().slice(0, 90);

                    items.push({
                        id: barisId,
                        tag: el.tagName.toLowerCase(),
                        type: el.getAttribute('type') || '',
                        text: label,
                        href: el.getAttribute('href') || ''
                    });
                }
            });
            return items.slice(0, 80);
        }
        """
        try:
            return await page.evaluate(js_som, show_badges)
        except Exception as e:
            logger.warning(f"SoM DOM çıkarma uyarısı: {e}")
            return []

    @classmethod
    async def highlight_element(cls, page: Page, selector: str):
        """Ajan işlem yapmadan önce hedef öğeyi canlı ekranda parlak mavi çerçeveyle vurgular."""
        js_highlight = """
        (sel) => {
            const el = document.querySelector(sel);
            if (el) {
                el.scrollIntoView({behavior: 'smooth', block: 'center'});
                const origOutline = el.style.outline;
                const origBg = el.style.backgroundColor;
                el.style.outline = '3px solid #00e5ff';
                el.style.backgroundColor = 'rgba(0, 229, 255, 0.15)';
                setTimeout(() => {
                    el.style.outline = origOutline;
                    el.style.backgroundColor = origBg;
                }, 1200);
            }
        }
        """
        try:
            await page.evaluate(js_highlight, selector)
            await asyncio.sleep(0.4)
        except Exception:
            pass

    @classmethod
    async def actuate_step(
        cls,
        action: str,
        url: Optional[str] = None,
        element_id: Optional[int] = None,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        headless: bool = False,
        use_tor: bool = False,
        use_i2p: bool = False
    ) -> Dict[str, Any]:
        """
        Canlı ekranda tekil otonom eylem yürütür.
        Desteklenen eylemler: 'goto', 'click', 'fill', 'press', 'scroll_down', 'scroll_up', 'back', 'wait', 'close'
        Öğeler ister `element_id` (SoM numarası) ister CSS `selector` ile hedeflenebilir.
        """
        t0 = time.time()
        page = await cls.ensure_live_session(headless=headless, use_tor=use_tor, use_i2p=use_i2p)

        target_selector = f'[data-baris-id="{element_id}"]' if element_id is not None else selector

        try:
            if action == "goto" and url:
                await page.goto(url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(1.5)
            elif action == "click" and target_selector:
                await cls.highlight_element(page, target_selector)
                await page.click(target_selector, timeout=10000)
                await asyncio.sleep(1.5)
            elif action == "fill" and target_selector and text is not None:
                await cls.highlight_element(page, target_selector)
                await page.fill(target_selector, text, timeout=10000)
                await asyncio.sleep(0.5)
                if key:
                    await page.keyboard.press(key)
                    await asyncio.sleep(1.2)
            elif action == "press" and key:
                await page.keyboard.press(key)
                await asyncio.sleep(1.2)
            elif action == "scroll_down":
                await page.evaluate("window.scrollBy({top: 650, behavior: 'smooth'})")
                await asyncio.sleep(0.8)
            elif action == "scroll_up":
                await page.evaluate("window.scrollBy({top: -650, behavior: 'smooth'})")
                await asyncio.sleep(0.8)
            elif action == "back":
                await page.go_back(wait_until="domcontentloaded")
                await asyncio.sleep(1.0)
            elif action == "wait":
                await asyncio.sleep(2.5)
            elif action == "close":
                await cls.close_session()
                return {"status": "CLOSED", "success": True}

            title = await page.title()
            body_text = await page.inner_text("body")
            interactive_dom = await cls.inject_som_and_extract_dom(page, show_badges=True)

            return {
                "success": True,
                "action": action,
                "current_url": page.url,
                "title": title,
                "interactive_elements": interactive_dom,
                "content_preview": body_text[:3500],
                "elapsed": round(time.time() - t0, 2)
            }
        except Exception as e:
            return {
                "success": False,
                "action": action,
                "error": str(e),
                "current_url": page.url if page else ""
            }

    @classmethod
    async def actuate_autonomous_mission(
        cls,
        mission_prompt: str,
        start_url: Optional[str] = None,
        max_steps: int = 12,
        headless: bool = False,
        use_tor: bool = False,
        use_i2p: bool = False
    ) -> Dict[str, Any]:
        """
        Üst Seviye Otonom Web Ajanı (Gözlemle -> Karar Ver -> Ekranda İcra Et -> Doğrula):
        Kullanıcının verdiği karmaşık bir web görevini canlı ekran açarak uçtan uca tamamlar.
        """
        coder_model = os.environ.get("MODEL_CODER", "qwen-coder-14b-abliterated:latest")
        history_log: List[Dict[str, Any]] = []

        if start_url:
            state = await cls.actuate_step(
                action="goto",
                url=start_url,
                headless=headless,
                use_tor=use_tor,
                use_i2p=use_i2p
            )
        else:
            page = await cls.ensure_live_session(headless=headless, use_tor=use_tor, use_i2p=use_i2p)
            state = await cls.actuate_step(action="wait", headless=headless)

        system_instructions = (
            "Sen canlı bir web tarayıcısını yöneten Otonom Web Ajanısın. "
            "Sana mevcut sayfanın URL'si, metin içeriği ve ekrandaki numaralandırılmış etkileşimli öğeler "
            "([id] tag: text) verilecek.\n"
            "Amacın: Kullanıcının verdiği görevi adım adım tamamlamaktır.\n"
            "SADECE aşağıdaki JSON formatında tek bir karar döndür:\n"
            '{\n'
            '  "thought": "Şu an sayfada ne gördüğün ve neden bu adımı seçtiğin",\n'
            '  "action": "goto | click | fill | press | scroll_down | scroll_up | back | done",\n'
            '  "element_id": 12,\n'
            '  "url": "https://...",\n'
            '  "text": "yazılacak metin",\n'
            '  "key": "Enter",\n'
            '  "final_report": "Eğer action=\'done\' ise topladığın tüm detaylı bulgular ve cevap"\n'
            '}'
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            for step_idx in range(1, max_steps + 1):
                dom_summary = "\n".join(
                    f"[{item['id']}] <{item['tag']} type='{item['type']}'> {item['text']} ({item['href'][:50]})"
                    for item in state.get("interactive_elements", [])[:50]
                )
                observation = (
                    f"GÖREV: {mission_prompt}\n"
                    f"ADIM: {step_idx}/{max_steps}\n"
                    f"MEVCUT URL: {state.get('current_url')}\n"
                    f"SAYFA BAŞLIĞI: {state.get('title')}\n"
                    f"ÖNCEKİ ADIMLAR: {json.dumps(history_log[-4:], ensure_ascii=False)}\n\n"
                    f"EKRANDAKİ ETKİLEŞİMLİ ÖĞELER (Set-of-Mark ID):\n{dom_summary}\n\n"
                    f"SAYFA METİN ÖZETİ:\n{state.get('content_preview', '')[:2000]}\n\n"
                    "Bir sonraki eylemini JSON olarak üret:"
                )

                payload = {
                    "model": coder_model,
                    "messages": [
                        {"role": "system", "content": system_instructions},
                        {"role": "user", "content": observation}
                    ],
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1, "num_ctx": 16384}
                }

                try:
                    resp = await client.post(OLLAMA_CHAT_URL, json=payload)
                    raw_decision = resp.json().get("message", {}).get("content", "{}")
                    decision = json.loads(raw_decision)
                except Exception as e:
                    logger.error(f"Otonom tarayıcı karar hatası: {e}")
                    break

                act = decision.get("action", "done")
                thought = decision.get("thought", "")
                logger.info(f"[BrowserAgent Adım {step_idx}] Düşünce: {thought} | Eylem: {act}")

                if act == "done":
                    return {
                        "success": True,
                        "steps_executed": step_idx - 1,
                        "final_url": state.get("current_url"),
                        "report": decision.get("final_report", state.get("content_preview", "")),
                        "history": history_log
                    }

                state = await cls.actuate_step(
                    action=act,
                    url=decision.get("url"),
                    element_id=decision.get("element_id"),
                    selector=decision.get("selector"),
                    text=decision.get("text"),
                    key=decision.get("key"),
                    headless=headless,
                    use_tor=use_tor,
                    use_i2p=use_i2p
                )

                history_log.append({
                    "step": step_idx,
                    "thought": thought,
                    "action": act,
                    "element_id": decision.get("element_id"),
                    "url": state.get("current_url"),
                    "success": state.get("success", False),
                    "error": state.get("error")
                })

        return {
            "success": True,
            "steps_executed": len(history_log),
            "final_url": state.get("current_url"),
            "report": state.get("content_preview", ""),
            "history": history_log
        }

    @classmethod
    async def close_session(cls):
        """Açık olan canlı tarayıcı oturumunu güvenli şekilde kapatır."""
        try:
            if cls._browser:
                await cls._browser.close()
            if cls._playwright:
                await cls._playwright.stop()
        except Exception:
            pass
        finally:
            cls._page = None
            cls._context = None
            cls._browser = None
            cls._playwright = None

    @classmethod
    def _save_session(cls, browser: str, url: str, content: str, network: str, title: str):
        ts = int(time.time())
        session_file = SESSIONS_DIR / f"session_{ts}.json"
        data = {
            "timestamp": ts,
            "browser": browser,
            "network": network,
            "url": url,
            "title": title,
            "preview": content[:1000]
        }
        try:
            session_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    async def open_and_extract(
        cls,
        url: str,
        browser_name: str = "chrome",
        use_tor: bool = False,
        use_i2p: bool = False,
        headless: bool = False,
        wait_seconds: float = 3.0
    ) -> Dict[str, Any]:
        """
        omni_chat_panel.py ile %100 geriye dönük uyumlu metot.
        Canlı pencere açar, Set-of-Mark rozetlerini işler ve içeriği döndürür.
        """
        t0 = time.time()
        res = await cls.actuate_step(
            action="goto",
            url=url,
            headless=headless,
            use_tor=use_tor,
            use_i2p=use_i2p
        )
        await asyncio.sleep(wait_seconds)

        content = res.get("content_preview", "")
        title = res.get("title", "")
        cls._save_session(browser_name, url, content, cls._active_network, title)

        return {
            "status": "SUCCESS",
            "browser": browser_name,
            "network": cls._active_network,
            "url": res.get("current_url", url),
            "title": title,
            "content": content,
            "interactive_elements": res.get("interactive_elements", []),
            "elapsed": round(time.time() - t0, 2)
        }
