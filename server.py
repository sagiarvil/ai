#!/usr/bin/env python3
"""
BARIŞ AI // ANA SUNUCU ÇALIŞTIRICI
omni_chat_panel.py uygulamasını 127.0.0.1:5050 üzerinde başlatır.
"""

from omni_chat_panel import app

if __name__ == "__main__":
    import uvicorn
    print("[*] Barış AI OmniCore Sunucusu: http://127.0.0.1:5050")
    uvicorn.run(app, host="127.0.0.1", port=5050)
