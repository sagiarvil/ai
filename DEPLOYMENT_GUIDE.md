# 🛡️ Barış AI // Endüstriyel 360° Tri-Model Otonom İcra Mimarisi Dağıtım Kılavuzu

Bu belge, `sagiarvil/ai` çekirdeğindeki kilitlenmeleri, erken çıkış hatalarını ve model potansiyelinin kullanılamamasını kalıcı olarak ortadan kaldıran; DeepSeek, Qwen Coder ve Mistral modellerini fiziksel döngüye sokan **Endüstriyel 360° Tri-Model Otonom İcra Mimarisi**'nin uçtan uca mimari şartnamesi, ortam değişkenleri ve adım adım dağıtım kılavuzudur.

---

## 🏛️ Mimari Katmanlar (Tri-Model Cascade)

```
                 ┌────────────────────────────────────────────────────────┐
                 │                Kullanıcı / API Talebi                  │
                 └───────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │ 1. AŞAMA: REASONING TIER (DeepSeek-R1)                                           │
   │ - Zincirleme Düşünce (Chain-of-Thought) akıl yürütme                             │
   │ - Cerrahi mimari analiz, algoritma şartnamesi ve edge-case tespiti              │
   └─────────────────────────────────────────┬────────────────────────────────────────┘
                                             │ [Mimari Şartname (Blueprint)]
                                             ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │ 2. AŞAMA: EXECUTION & SELF-HEALING TIER (Qwen2.5-Coder)                          │
   │ - Sıfır-Araç Tuzağı Koruması: Eylem gerektiren görevlerde salt metinle çıkış yok│
   │ - Dinamik Araç Dağıtımı (dispatch_tool_call & ReAct döngüsü)                    │
   │ - Reflektif Self-Healing: stderr / hata çıktılarının modele geri beslenmesi     │
   │ - Bağlam Patlaması Koruması (Context Window Guard): 16K token süzgeci           │
   └─────────────────────────────────────────┬────────────────────────────────────────┘
                                             │ [Fiziksel Kanıtlar (Evidences & Steps)]
                                             ▼
   ┌──────────────────────────────────────────────────────────────────────────────────┐
   │ 3. AŞAMA: PRESENTATION TIER (Mistral-Small-24B-Abliterated)                      │
   │ - Yürütülen tüm adımların fiziksel kanıtlarını sentezleme                        │
   │ - Halüsinasyonsuz, net, dobra ve profesyonel Türkçe sonuç raporu                │
   └─────────────────────────────────────────┬────────────────────────────────────────┘
                                             │
                                             ▼
                 ┌────────────────────────────────────────────────────────┐
                 │   Nihai Doğrulanmış Yanıt & Bağımsız Denetim (VERIFIED)│
                 └────────────────────────────────────────────────────────┘
```

---

## ⚙️ Ortam Değişkenleri (Environment Variables)

Sistem modelleri Ollama üzerinde otomatik olarak tarar ve en uygun sansürsüz modellere dinamik olarak atar. İsteğe bağlı olarak `.env` dosyanızda veya terminalinizde modelleri ve bağlam penceresini özelleştirebilirsiniz:

| Değişken Adı | Açıklama | Varsayılan Değer |
|---|---|---|
| `MODEL_REASONER` | Aşama 1 Baş Sistem Mimarı & Stratejist | `deepseek-r1-14b-abliterated:latest` / `deepseek-r1:latest` |
| `MODEL_CODER` | Aşama 2 Mühendislik, Kodlama ve Araç İcrası | `qwen-coder-14b-abliterated:latest` / `qwen2.5-coder:32b` |
| `MODEL_PRESENTER`| Aşama 3 İletişim, Kanıt Doğrulama ve Raporlama| `mistral-small-24b-abliterated:latest` |
| `AGENT_NUM_CTX` | Model bağlam penceresi token bütçesi | `16384` |
| `WORKSPACE_ROOT`| Proje çalışma alanı kök dizini (dinamik) | `Path.cwd()` |
| `OMNICORE_HOME` | Omnicore yapılandırma ve geçici dizin kökü | `~/.omnicore` |
| `OLLAMA_BASE_URL`| Ollama yerel servis adresi | `http://127.0.0.1:11434` |

---

## 🚀 Dağıtım ve Başlatma Adımları

### 1. Ortam Değişkenlerini Tanımlama (İsteğe Bağlı)
```bash
export MODEL_REASONER="deepseek-r1-14b-abliterated:latest"
export MODEL_CODER="qwen-coder-14b-abliterated:latest"
export MODEL_PRESENTER="mistral-small-24b-abliterated:latest"
export AGENT_NUM_CTX=16384
```

### 2. Kabul Kapısı Test Süitini Çalıştırma (7/7 PASS)
```bash
python3 test_suite.py
```
Test süiti şu 7 kritik kabul kapısını fiziksel olarak denetler:
1. Tor SOCKS5 yerel ağı (127.0.0.1:9050)
2. Canlı TLS doğrulamalı DuckDuckGo Web Araştırması
3. Slither Akıllı Kontrat Statik Güvenlik Analizi
4. Yerel Tarayıcı Motoru (Chrome Headless)
5. Gerçek Sandbox İzolasyonu ve Sır Sızdırmazlık (macOS Seatbelt)
6. Model Runtime Inference Canlı Çıkarım Testi (Inference Probe)
7. FastAPI Sıkılaştırılmış CORS ve Güvenli API Uç Noktası

### 3. Sunucuyu Başlatma
```bash
python3 server.py
# veya
python3 omni_chat_panel.py
```

---

## 🛡️ Kalıcı Mühendislik Çözümleri

1. **Sıfır-Araç Tuzağı (Zero-Tool Exit Trap) Kaldırıldı**:
   Model araç çağırmadan önce selamlama veya düşünce metni ürettiğinde döngünün anında `break` ile kırılıp görevi yarıda bırakması engellendi. Görev fiziksel işlem gerektiriyorsa model araç çağırmaya yönlendirilir.

2. **Reflektif Self-Healing Döngüsü**:
   Çalıştırılan bir araç hata verdiğinde (`exit_code != 0`, `stderr`), hata imzası modele geri beslenerek parametrelerin veya komutların kendi kendini onarması sağlanır.

3. **Bağlam Patlaması Koruması (Context Window Guard)**:
   Aşırı uzun terminal veya web kazıma çıktılarının 16384 token bütçesini taşırıp model hafızasını silmesini engellemek amacıyla `ContextWindowGuard.sanitize_tool_output` entegre edilmiştir.

4. **Taşınabilir Güvenli Ortam (Portable Sandbox)**:
   Sabit kodlanmış kullanıcı yolları tamamen dinamik `Path.cwd()`, `Path.home()` ve `WORKSPACE_ROOT` ile değiştirilmiştir.

5. **Geriye Dönük %100 API Uyumluluğu**:
   `AutonomousExecutionEngine.execute_verified_task` fonksiyon imzası ve dönen JSON kontratı (`task_id`, `status`, `reply`, `execution_steps`, `evidences`, `verified`) eksiksiz korunmuştur.
