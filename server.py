#!/usr/bin/env python3
"""
INVERSIONCORE TACTICAL WEB UI & REST API SERVER
Mistral-Small-24B-2501-Abliterated Görev-Kritik Denetim ve Kontrol Paneli
"""

import asyncio
import os
import sqlite3
import time
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from inversioncore_audit_engine import (
    ContractSurfaceExtractor,
    InversionCoreEngine,
    InversionCoreAuditReport,
    IMMUTABLE_SYSTEM_CORE,
    LLM_BASE_URL,
    PINNED_SLOT_ID
)
from tactical_warmup import TacticalWarmupController

app = FastAPI(
    title="InversionCore Tactical AI Interface",
    description="Mistral-Small-24B-2501 Zırhlı Kontrat Denetim ve Telemetri Arayüzü",
    version="1.0.0"
)

engine = InversionCoreEngine()
warmup_ctrl = TacticalWarmupController()

class AuditRequest(BaseModel):
    audit_id: Optional[str] = Field(None, description="Opsiyonel denetim kimliği")
    contract_code: str = Field(..., min_length=20, description="Denetlenecek Solidity kaynak kodu")

class WarmupRequest(BaseModel):
    action: str = Field("restore", description="'init' (oluştur) veya 'restore' (yükle)")

@app.get("/api/status")
async def get_node_status():
    """Çekirdek llama-server (127.0.0.1:8080) sağlık durumunu kontrol eder."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{LLM_BASE_URL.replace('/v1', '')}/health")
            if resp.status_code == 200:
                health_data = resp.json()
                return {
                    "online": True,
                    "status": health_data.get("status", "ok"),
                    "endpoint": LLM_BASE_URL,
                    "model": "mistral-small-24b-abliterated",
                    "slot_id": PINNED_SLOT_ID
                }
            return {
                "online": False,
                "status": f"HTTP {resp.status_code}",
                "endpoint": LLM_BASE_URL,
                "slot_id": PINNED_SLOT_ID
            }
    except Exception as e:
        return {
            "online": False,
            "status": "OFFLINE (Sunucu Başlatılmadı veya Kilitli)",
            "detail": str(e),
            "endpoint": LLM_BASE_URL,
            "slot_id": PINNED_SLOT_ID
        }

@app.post("/api/warmup")
async def trigger_warmup(req: WarmupRequest):
    """KV-Cache mühürleme veya bellek geri yükleme tetikler."""
    try:
        if req.action == "init":
            warmup_ctrl.bake_and_seal_kv_cache()
            return {"status": "SUCCESS", "message": "KV-Cache GPU'da hesaplandı ve diske mühürlendi."}
        else:
            warmup_ctrl.instant_restore_kv_cache()
            return {"status": "SUCCESS", "message": "Mühürlü KV-Cache 100ms içinde GPU'ya geri yüklendi."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/audit")
async def perform_audit(req: AuditRequest):
    """Akıllı kontrat denetimi yürütür, AST filtreler ve Gatekeeper raporu döndürür."""
    audit_id = req.audit_id or f"INV-{int(time.time())}"
    try:
        report = await engine.audit_contract(audit_id=audit_id, contract_code=req.contract_code)
        return report.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Denetim motoru hatası: {str(e)}")

@app.get("/api/audits")
async def get_audit_history(limit: int = 20):
    """SQLite WAL denetim defterindeki son kayıtları listeler."""
    try:
        with sqlite3.connect("inversioncore_ledger.db") as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT audit_id, timestamp_utc, code_sha256, risk_score, posture, latency_ms, report_json "
                "FROM contract_audits ORDER BY timestamp_utc DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        return []

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Temiz, modern, endüstriyel taktiksel kullanıcı arayüzü."""
    html_content = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>InversionCore // Tactical Mistral-24B UI</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0B0F17; color: #E2E8F0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .card { background-color: #111827; border: 1px solid #1F2937; }
    .border-glow:focus-within { border-color: #3B82F6; box-shadow: 0 0 15px rgba(59, 130, 246, 0.3); }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased">
  <!-- Üst Bar -->
  <header class="card border-b border-gray-800 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center gap-3">
      <div class="w-3.5 h-3.5 rounded-full bg-blue-500 shadow-[0_0_10px_#3B82F6]"></div>
      <h1 class="text-xl font-bold tracking-wider mono text-white">INVERSION<span class="text-blue-500">CORE</span> // TACTICAL</h1>
      <span class="text-xs bg-gray-800 text-gray-400 px-2.5 py-1 rounded-md mono border border-gray-700">M4 24GB AIR-GAP</span>
    </div>
    
    <div class="flex items-center gap-4 text-sm mono">
      <div class="flex items-center gap-2 bg-gray-900 px-3 py-1.5 rounded border border-gray-800">
        <span class="text-gray-400">Node:</span>
        <span id="nodeStatus" class="font-bold text-yellow-400">KONTROL EDİLİYOR...</span>
      </div>
      <button onclick="restoreCache()" class="bg-gray-800 hover:bg-gray-700 text-gray-200 px-3 py-1.5 rounded border border-gray-700 transition">
        ⚡ 100ms KV-Restore
      </button>
      <button onclick="bakeCache()" class="bg-gray-800 hover:bg-gray-700 text-gray-200 px-3 py-1.5 rounded border border-gray-700 transition">
        🔒 KV-Bake Diske
      </button>
    </div>
  </header>

  <!-- Ana İçerik -->
  <main class="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
    <!-- Sol Panel: Giriş ve Kontroller (7 Kolon) -->
    <section class="lg:col-span-7 flex flex-col gap-6">
      <div class="card p-5 rounded-lg border-glow flex flex-col flex-1">
        <div class="flex justify-between items-center mb-3">
          <label class="text-sm font-semibold mono text-gray-300 flex items-center gap-2">
            <span>🛡️ AKILLI KONTRAT KAYNAK KODU (Solidity)</span>
          </label>
          <button onclick="loadSample()" class="text-xs text-blue-400 hover:text-blue-300 mono underline">
            [Örnek Zafiyetli Vault Yükle]
          </button>
        </div>

        <textarea id="contractCode" rows="18" 
          class="w-full bg-black/60 text-green-400 mono text-sm p-4 rounded border border-gray-800 focus:outline-none focus:border-blue-500 flex-1 leading-relaxed" 
          placeholder="// Akıllı kontrat kodunuzu buraya yapıştırın..."></textarea>

        <div class="mt-4 flex flex-wrap items-center justify-between gap-4">
          <div class="flex items-center gap-2 text-xs mono text-gray-400">
            <span>Audit ID:</span>
            <input id="auditId" type="text" placeholder="Otomatik (INV-...)" class="bg-gray-900 border border-gray-700 px-2.5 py-1 rounded text-gray-200 w-36 focus:outline-none">
          </div>
          <button id="auditBtn" onclick="runAudit()" class="bg-blue-600 hover:bg-blue-500 text-white font-bold px-6 py-2.5 rounded mono shadow-[0_0_15px_rgba(59,130,246,0.4)] transition flex items-center gap-2">
            <span>🚀 ZIRHLI DENETİMİ BAŞLAT</span>
          </button>
        </div>
      </div>

      <!-- Denetim Defteri (Son Kayıtlar) -->
      <div class="card p-5 rounded-lg">
        <div class="flex justify-between items-center mb-3">
          <h3 class="text-sm font-semibold mono text-gray-300">📜 GEÇMİŞ DENETİM DEFTERİ (SQLite WAL)</h3>
          <button onclick="loadHistory()" class="text-xs text-blue-400 hover:text-blue-300 mono underline">Yenile</button>
        </div>
        <div id="historyList" class="space-y-2 text-xs mono max-h-48 overflow-y-auto pr-1">
          <div class="text-gray-500">Kayıtlar yükleniyor...</div>
        </div>
      </div>
    </section>

    <!-- Sağ Panel: Denetim Sonuçları ve Telemetri (5 Kolon) -->
    <section class="lg:col-span-5 flex flex-col gap-6">
      <div class="card p-5 rounded-lg flex-1 flex flex-col">
        <h2 class="text-sm font-semibold mono text-gray-300 mb-3 flex items-center justify-between">
          <span>📊 DENETİM RAPORU & TELEMETRİ</span>
          <span id="riskBadge" class="hidden px-2.5 py-0.5 rounded text-xs font-bold mono"></span>
        </h2>

        <!-- Sonuç Paneli -->
        <div id="resultEmpty" class="flex-1 flex flex-col items-center justify-center text-center p-8 text-gray-500 border border-dashed border-gray-800 rounded">
          <svg class="w-12 h-12 mb-3 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
          <p class="text-sm mono">Henüz bir denetim çalıştırılmadı.</p>
          <p class="text-xs text-gray-600 mt-1">Kontrat kodunu girip 'Başlat' butonuna tıklayın.</p>
        </div>

        <div id="resultContent" class="hidden flex-1 flex flex-col gap-4 text-xs mono">
          <div class="grid grid-cols-2 gap-2 bg-gray-900/80 p-3 rounded border border-gray-800">
            <div><span class="text-gray-500">Risk Puanı:</span> <span id="rRisk" class="font-bold text-white text-base">0/100</span></div>
            <div><span class="text-gray-500">Duruş:</span> <span id="rPosture" class="font-bold text-white text-base">-</span></div>
          </div>

          <div>
            <h4 class="text-gray-400 font-semibold mb-1">🚨 BULGULAR:</h4>
            <div id="rFindings" class="space-y-1.5 max-h-40 overflow-y-auto"></div>
          </div>

          <div>
            <h4 class="text-gray-400 font-semibold mb-1">📐 DEĞİŞMEZLİK KURALLARI (Invariants):</h4>
            <ul id="rInvariants" class="list-disc list-inside space-y-1 text-gray-300 bg-gray-950 p-2.5 rounded border border-gray-800 max-h-28 overflow-y-auto"></ul>
          </div>

          <div class="flex-1 flex flex-col">
            <div class="flex justify-between items-center mb-1">
              <h4 class="text-gray-400 font-semibold">✅ GÜVENLİK YAMASI (Remediated Code):</h4>
              <button onclick="copyPatch()" class="text-xs text-blue-400 hover:text-blue-300">Kopyala</button>
            </div>
            <pre id="rPatch" class="bg-black/80 text-green-300 p-3 rounded border border-gray-800 overflow-x-auto flex-1 max-h-56 leading-relaxed select-all"></pre>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer class="card border-t border-gray-800 px-6 py-3 text-center text-xs text-gray-500 mono">
    InversionCore // Mistral-Small-24B-Instruct-2501-Abliterated // Mission-Critical Architecture
  </footer>

  <script>
    const sampleVault = `pragma solidity ^0.8.20;
contract VulnerableVault {
    mapping(address => uint256) public balances;
    address public owner;

    constructor() { owner = msg.sender; }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "Insufficient balance");
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");
        balances[msg.sender] -= amount;
    }

    function sweepEmergency(address payable recipient) external {
        require(tx.origin == owner, "Not authorized");
        recipient.transfer(address(this).balance);
    }
}`;

    function loadSample() {
      document.getElementById('contractCode').value = sampleVault;
    }

    async function checkStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const badge = document.getElementById('nodeStatus');
        if (data.online) {
          badge.textContent = "ONLINE (BAĞLI)";
          badge.className = "font-bold text-green-400";
        } else {
          badge.textContent = "OFFLINE (8080)";
          badge.className = "font-bold text-red-400";
        }
      } catch (e) {
        document.getElementById('nodeStatus').textContent = "HATA";
      }
    }

    async function restoreCache() {
      if(!confirm("Slot-0 mühürlü KV-Cache diskten GPU'ya geri yüklensin mi?")) return;
      try {
        const res = await fetch('/api/warmup', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action: 'restore'})
        });
        const data = await res.json();
        alert(data.message || "Başarılı!");
      } catch(e) {
        alert("Hata: " + e);
      }
    }

    async function bakeCache() {
      if(!confirm("Sistem anayasası GPU'da hesaplanıp diske kalıcı olarak mühürlensin mi?")) return;
      try {
        const res = await fetch('/api/warmup', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action: 'init'})
        });
        const data = await res.json();
        alert(data.message || "Başarılı!");
      } catch(e) {
        alert("Hata: " + e);
      }
    }

    async function runAudit() {
      const code = document.getElementById('contractCode').value.trim();
      if (!code) { alert("Lütfen akıllı kontrat kodunu girin."); return; }

      const btn = document.getElementById('auditBtn');
      const originalText = btn.innerHTML;
      btn.innerHTML = "<span>⏳ DENETLENİYOR...</span>";
      btn.disabled = true;

      try {
        const res = await fetch('/api/audit', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            audit_id: document.getElementById('auditId').value.trim() || undefined,
            contract_code: code
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Sunucu hatası");
        }

        const data = await res.json();
        displayResult(data);
        loadHistory();
      } catch (e) {
        alert("Denetim Hatası: " + e.message);
      } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
      }
    }

    function displayResult(data) {
      document.getElementById('resultEmpty').classList.add('hidden');
      document.getElementById('resultContent').classList.remove('hidden');

      const riskBadge = document.getElementById('riskBadge');
      riskBadge.classList.remove('hidden');
      riskBadge.textContent = data.overall_security_posture;

      if (data.overall_security_posture === 'COMPROMISED_RISK') {
        riskBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold mono bg-red-900 text-red-200 border border-red-700";
      } else if (data.overall_security_posture === 'WARNING') {
        riskBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold mono bg-yellow-900 text-yellow-200 border border-yellow-700";
      } else {
        riskBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold mono bg-green-900 text-green-200 border border-green-700";
      }

      document.getElementById('rRisk').textContent = data.risk_score + " / 100";
      document.getElementById('rPosture').textContent = data.overall_security_posture;

      const fBox = document.getElementById('rFindings');
      fBox.innerHTML = '';
      (data.findings || []).forEach(f => {
        const div = document.createElement('div');
        div.className = "p-2 bg-gray-950 rounded border border-gray-800";
        div.innerHTML = `<span class="text-red-400 font-bold">[${f.severity}]</span> <span class="text-blue-400">${f.category}</span> @ <code class="text-yellow-300">${f.affected_function}</code><br><span class="text-gray-400 mt-1 block">${f.state_transition_flaw}</span>`;
        fBox.appendChild(div);
      });

      const invBox = document.getElementById('rInvariants');
      invBox.innerHTML = '';
      (data.formal_invariants || []).forEach(inv => {
        const li = document.createElement('li');
        li.textContent = inv;
        invBox.appendChild(li);
      });

      document.getElementById('rPatch').textContent = data.remediated_solidity_code || "// Yama kodu yok.";
    }

    function copyPatch() {
      const patch = document.getElementById('rPatch').textContent;
      navigator.clipboard.writeText(patch);
      alert("Güvenlik yama kodu panoya kopyalandı!");
    }

    async function loadHistory() {
      try {
        const res = await fetch('/api/audits');
        const rows = await res.json();
        const box = document.getElementById('historyList');
        if (!rows.length) {
          box.innerHTML = '<div class="text-gray-500">Kayıtlı denetim yok.</div>';
          return;
        }
        box.innerHTML = '';
        rows.forEach(r => {
          const div = document.createElement('div');
          div.className = "p-2 bg-gray-900 rounded border border-gray-800 hover:border-gray-700 cursor-pointer flex justify-between items-center";
          div.onclick = () => {
            try {
              const parsed = JSON.parse(r.report_json);
              displayResult(parsed);
            } catch(e){}
          };
          div.innerHTML = `<div><span class="text-blue-400 font-bold">${r.audit_id}</span> <span class="text-gray-500">(${r.timestamp_utc.slice(11,19)})</span></div><div class="flex items-center gap-2"><span class="${r.risk_score > 50 ? 'text-red-400' : 'text-green-400'} font-bold">${r.risk_score} pts</span><span class="text-gray-500">${r.latency_ms}ms</span></div>`;
          box.appendChild(div);
        });
      } catch(e){}
    }

    // Başlangıç kontrolleri
    checkStatus();
    loadHistory();
    setInterval(checkStatus, 10000);
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    print("[*] InversionCore Taktiksel Web Arayüzü Başlatılıyor: http://127.0.0.1:5050")
    uvicorn.run("server:app", host="127.0.0.1", port=5050, reload=False)
