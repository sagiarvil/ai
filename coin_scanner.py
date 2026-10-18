#!/usr/bin/env python3
"""
INVERSIONCORE COIN SCANNER & CRYPTO TELEMETRY ENGINE
Binance & DEX canlı veri çekici ve sinyal analiz modülü.
"""

import re
from typing import Dict, Any, Optional, List
import httpx

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"

COMMON_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI", "PEPE", "NEAR", "APT", "ARB", "OP"]

class CoinScanner:
    @classmethod
    def detect_symbols(cls, text: str) -> List[str]:
        """Metin içindeki coin sembollerini veya kontrat adreslerini tespit eder."""
        text_upper = text.upper()
        found = []
        for coin in COMMON_COINS:
            pattern = rf"\b{coin}(USDT)?\b"
            if re.search(pattern, text_upper):
                found.append(coin)
        
        # 0x ile başlayan adres tespiti
        eth_addresses = re.findall(r"\b0x[a-fA-F0-9]{40}\b", text)
        for addr in eth_addresses:
            found.append(addr)
            
        return found or (["BTC"] if any(k in text.lower() for k in ["kripto", "piyasa", "coin", "market"]) else [])

    @classmethod
    async def get_ticker(cls, symbol: str) -> Optional[Dict[str, Any]]:
        """Binance üzerinden tekil sembolün 24 saatlik piyasa verisini çeker."""
        clean_symbol = symbol.upper().replace("USDT", "") + "USDT"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{BINANCE_TICKER_URL}?symbol={clean_symbol}")
                if resp.status_code == 200:
                    d = resp.json()
                    price = float(d.get("lastPrice", 0))
                    change = float(d.get("priceChangePercent", 0))
                    volume = float(d.get("quoteVolume", 0))
                    high = float(d.get("highPrice", 0))
                    low = float(d.get("lowPrice", 0))
                    
                    # Basit teknik sinyal tahmini
                    signal = "NÖTR"
                    if change > 3.0:
                        signal = "GÜÇLÜ BOĞA (YÜKSELİŞ)"
                    elif change > 0.5:
                        signal = "ILIMLI BOĞA"
                    elif change < -3.0:
                        signal = "GÜÇLÜ AYI (DÜŞÜŞ)"
                    elif change < -0.5:
                        signal = "ILIMLI AYI"

                    return {
                        "symbol": symbol.upper(),
                        "pair": clean_symbol,
                        "price": price,
                        "change_24h": round(change, 2),
                        "volume_usdt": round(volume, 2),
                        "high_24h": high,
                        "low_24h": low,
                        "signal": signal
                    }
        except Exception:
            pass
        return None

    @classmethod
    async def get_top_watchlist(cls) -> List[Dict[str, Any]]:
        """Popüler izleme listesi coinlerinin anlık fiyatlarını çeker."""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
        try:
            param = '["' + '","'.join(symbols) + '"]'
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{BINANCE_TICKER_URL}?symbols={param}")
                if resp.status_code == 200:
                    data = resp.json()
                    watchlist = []
                    for item in data:
                        sym = item.get("symbol", "").replace("USDT", "")
                        watchlist.append({
                            "symbol": sym,
                            "price": float(item.get("lastPrice", 0)),
                            "change_24h": round(float(item.get("priceChangePercent", 0)), 2)
                        })
                    return watchlist
        except Exception:
            pass
        return [
            {"symbol": "BTC", "price": 0.0, "change_24h": 0.0},
            {"symbol": "ETH", "price": 0.0, "change_24h": 0.0},
            {"symbol": "SOL", "price": 0.0, "change_24h": 0.0}
        ]
