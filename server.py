#!/usr/bin/env python3
"""
BARIŞ AI // ANA SUNUCU ÇALIŞTIRICI
durable_api.py uygulamasını 127.0.0.1:5050 üzerinde başlatır.
"""

from durable_api import app

if __name__ == "__main__":
    import uvicorn
    print("[*] Barış AI OmniCore Sunucusu: http://127.0.0.1:5050")
    uvicorn.run(app, host="127.0.0.1", port=5050)

