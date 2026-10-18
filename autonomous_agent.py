#!/usr/bin/env python3
"""
OMNICORE // OTONOM YAZILIM MÜHENDİSİ AJAN ÇEKİRDEĞİ (OPENHANDS TABANLI İCRA)
"""

import asyncio
import json
import sys
from pathlib import Path
from agentic_engine import AutonomousExecutionEngine, TaskState
from omni_chat_panel import tools, dispatch_tool_call

async def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Chrome ile https://httpbin.org/ip adresine git ve veriyi kaydet"
    print(f"[*] Görev Başlatıldı: '{prompt}'\n")
    
    res = await AutonomousExecutionEngine.execute_verified_task(
        prompt=prompt,
        tools_schema=tools,
        call_tool_fn=dispatch_tool_call
    )
    
    print(f"\n[DURUM]: {res['status']} (Doğrulandı: {res['verified']})")
    print(f"[YANIT]:\n{res['reply']}")
    print(f"[KANIT SAYISI]: {len(res['evidences'])}")
    for ev in res['evidences']:
        print(f" - [{ev['category']}]: {ev['detail']} (Başarılı: {ev['success']})")

if __name__ == "__main__":
    asyncio.run(main())
