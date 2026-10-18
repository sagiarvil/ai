# InversionCore // Tactical Mistral-24B Mission-Critical Security Engine

**Apple Silicon M4 (24 GB RAM) Üzerinde NATO / Endüstriyel Sınıf Görev-Kritik Akıllı Kontrat Denetim ve Telemetri Çekirdeği**

---

## 🏛️ Mimari Genel Bakış

Bu depo, **Mistral-Small-24B-Instruct-2501-Abliterated (Q4_K_M - 14.4 GB)** modelini temel alan; tam donanımsal bellek kilitlemeli, Air-Gap güvenlik duvarlı, 100ms ön-ısıtmalı ve C++ FSM / Pydantic Gatekeeper denetimli zırhlı bir akıllı kontrat güvenlik motorudur.

Canlı Web Arayüzü: [https://baris-ai.web.app](https://baris-ai.web.app)  
GitHub Deposu: [https://github.com/sagiarvil/ai](https://github.com/sagiarvil/ai)

```
[İstemci / Web UI (baris-ai.web.app)]
                 │
                 ▼
     [FastAPI /v1 REST API (:5050)]
                 │
  ┌──────────────┴──────────────────────────────┐
  ▼                                             ▼
[ContractSurfaceExtractor (AST)]     [TacticalAuditLedger (SQLite WAL)]
  │ (Durum Geçişleri & CEI Tespiti)             │ (SHA-256 Kriptografik Mühür)
  └──────────────┬──────────────────────────────┘
                 ▼
[InversionCore Gatekeeper (Pydantic / Strict FSM)]
  │ (Sıfır Tolerans & Self-Healing Doğrulama)
  ▼
[llama-server / Metal GPU Node (Port 8080)]
  ├─ --mlock (14.4 GB RAM Çivileme / 0-Swap)
  ├─ pfctl Air-Gap Firewall (Yalnızca 127.0.0.1 lo0)
  ├─ macOS launchd Watchdog Daemon (2s Auto-Resurrect)
  ├─ caffeinate -dimsu (Derin Uyku ve GPU Throttling Engeli)
  └─ Slot-0 Mühürlü KV-Cache (100ms Cold-Start Ön-Isıtma)
```

---

## 🚀 Bileşenler ve Dosya Yapısı

| Dosya | Açıklama |
|---|---|
| `deploy_armored_node.sh` | macOS launchd Daemon, 20 GB Metal VRAM ve BSD pfctl Air-Gap güvenlik duvarı kurulum betiği. |
| `tactical_warmup.py` | Sistem anayasasını GPU'da hesaplayıp diske (`.bin`) mühürleyen ve cold-start'ı sıfırlayan motor. |
| `inversioncore_audit_engine.py` | AST tehdit yüzeyi çıkarıcı, Pydantic Gatekeeper ve SQLite WAL mühürlü denetim motoru. |
| `server.py` | REST API ve yerel taktiksel dashboard sunucusu (`http://127.0.0.1:5050`). |
| `public/index.html` | Firebase Hosting (`baris-ai.web.app`) üzerinde çalışan bağımsız/hibrit web arayüzü. |
| `test_suite.py` | 5/5 otomatik deterministik test süiti (AST, Gatekeeper, SQLite WAL, FastAPI). |
| `requirements.txt` | Python bağımlılıkları (`fastapi`, `uvicorn`, `pydantic`, `httpx`, `openai`, `instructor`). |
| `firebase.json` / `.firebaserc` | Firebase Hosting dağıtım konfigürasyonu (`yesilay-finans-kokpit` -> `baris-ai`). |

---

## 🛠️ Kurulum ve Çalıştırma

### 1. Bağımlılıkları Yükleyin
```bash
pip3 install -r requirements.txt
```

### 2. Zırhlı Düğümü Başlatın (macOS LaunchDaemon)
```bash
chmod +x deploy_armored_node.sh
sudo ./deploy_armored_node.sh
```

### 3. Slot-0 KV-Cache'i Isıtın ve Mühürleyin
```bash
# İlk kurulumda GPU'ya yaz ve diske kaydet:
python3 tactical_warmup.py --init

# Sunucu yeniden başladığında 100ms içinde geri yükle:
python3 tactical_warmup.py --restore
```

### 4. Taktiksel Web Arayüzünü Ateşleyin
```bash
python3 server.py
# Tarayıcıda http://127.0.0.1:5050 adresini açın
```

### 5. Testleri Çalıştırın
```bash
python3 test_suite.py
```

---

## 🔒 Güvenlik Standartları

1. **Air-Gap İzolasyonu:** BSD `pfctl` güvenlik duvarı, 8080 portunu dış ağ arayüzlerine (Wi-Fi, Ethernet, VPN) tamamen kapatır. Sadece yerel `127.0.0.1` erişebilir.
2. **Kriptografik İzi:** Her analiz SHA-256 hash imzasıyla `mission_audit_ledger.db` (SQLite WAL) tablosuna kaydedilir.
3. **Deterministik Çıkarım:** `seed=42`, `temperature=0.0` ve Pydantic Strict JSON Schema ile sıfır sapmalı, yüzde yüz tekrarlanabilir çıktılar üretilir.

---
© 2026 InversionCore Systems. All rights reserved.
