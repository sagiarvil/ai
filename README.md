# Barış AI // Otonom İcra, Güvenlik & Gizlilik Ağları Platformu

**Simülasyon veya Sahte Veri Yoktur — Tüm Motorlar Fiziksel ve Canlıdır**

Canlı Web Paneli: [https://baris-ai.web.app](https://baris-ai.web.app)  
GitHub Deposu: [https://github.com/sagiarvil/ai](https://github.com/sagiarvil/ai)

---

## 🏛️ %100 Gerçek ve Fiziksel Motor Mimarisi

| Motor | Gerçekleştirim & Kanıt | Fiziksel Durum |
|---|---|---|
| **Otonom İcra Motoru** | OpenHands tabanlı Deterministik Durum Makinesi (`agentic_engine.py`) | **AKTİF (RECEIVED -> VERIFIED)** |
| **Sandbox İzolasyonu** | Komut Enjeksiyonu ve Dizin İzolasyonu (`sandbox_executor.py`) | **AKTİF (Güvenli Yürütme)** |
| **Yerel Tarayıcı Motoru** | Google Chrome & Safari Playwright CDP (`browser_controller.py`) | **AKTİF (Yerel İnternet / Oturum Kaydı)** |
| **I2P Gizlilik Ağı** | macOS `i2pd` Daemon (`127.0.0.1:4444` HTTP / `7070` Konsol) | **AKTİF (Invisible Internet)** |
| **Tor Ağ Güvenliği** | macOS `/opt/homebrew/bin/tor` daemon (`127.0.0.1:9050` SOCKS5) | **AKTİF (IP Maskeleme)** |
| **Akıllı Kontrat Analizi** | Crytic Slither 0.11.6 + Solc 0.8.20 Statik Güvenlik Motoru | **AKTİF (Reentrancy & Açık Tespiti)** |
| **Crawl4AI Web Kazıma** | Dinamik Headless Web Kazıyıcı (`crawl4ai 0.9.5`) | **AKTİF (Markdown Çıktı)** |
| **Sansürsüz LLM Çıkarımı** | Apple M4 Metal iGPU üzerinde `mistral-small-24b-abliterated` | **AKTİF (Port 5050 / Ollama 11434)** |

---

## 🚀 Çalıştırma ve Doğrulama

```bash
# 1. Test süitini çalıştırıp fiziksel motorları doğrulayın (6/6 PASS)
python3 test_suite.py

# 2. Sunucuyu ve Web Arayüzünü başlatın
python3 server.py
# Tarayıcıda: http://127.0.0.1:5050 veya canlıda https://baris-ai.web.app
```
