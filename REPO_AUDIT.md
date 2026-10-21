# Uçtan uca depo denetimi — local-ui-v9

Denetlenen başlangıç: `70e099c22e1687e70d837461870488f5fb602de5`,
`fix/verified-execution-loop`. Tarih: 21 Ekim 2026.

## Sonuç ve kanıt düzeyi

Başlangıç sürümüne eklenen ilk on regresyon kontrolü **9 başarısızlık ve 1 hata**
üretti. Aynı kontroller düzeltmelerden sonra geçti. Son genişletilmiş testlerin
adları, sonuçları, gerçek komutları ve çıkış kodları `AUDIT_EVIDENCE.json` içindedir.
Bu kayıt geliştirme ortamının kanıtıdır; kullanıcının Mac'inde canlı Mistral
kabulü yapılmış olduğunu söylemez. Proje için ölçülmüş genel başarı yüzdesi yoktur.

## Tarama kapsamı

GitHub'ın tam ağaç kaydında 49 dosya vardı: 39 kaynak/yapılandırma/belge,
10 tarihsel görev/tarayıcı kaydı. Kaynak, yapılandırma, testler ve başlangıç yolları
incelendi. Eski oturum verilerinin içeriği çalışma kalitesi kanıtı yapılmadı.

| Alan | İncelenen ana dosyalar |
|---|---|
| Mac açılışı ve girişler | baris_local.py, install_macos_app.py, server.py, omni_chat_panel.py, autonomous_agent.py |
| API ve yetki sınırları | durable_api.py, yerel Host/Origin, gövde ve yol doğrulaması |
| Kalıcılık ve zamanlama | job_store.py, task_service.py, iptal, toparlanma ve belirsiz komut durumu |
| Model ve bağlam | task_worker.py, structured_actions.py, akış, kesik çıktı, profil ve bütçe |
| Gerçek işlemler | task_tools.py, acceptance_checks.py, dosya ve süreç yaşam döngüsü |
| Arayüz | public/index.html, public/app.js, kanıt kapsamı, yeniden bağlanma, zaman göstergesi |
| Eski yollar | agentic_engine.py, execution_loop.py, browser_controller.py, real_engines.py, model_manager.py, deterministic_engine.py, sandbox_executor.py, deploy_armored_node.sh |
| Tekrar üretilebilirlik | CI, bağımlılıklar, test dosyaları, Firebase ve eski kayıt yapılandırmaları |

Desteklenen girişlerin yerel import zinciri ayrıca çıkarıldı: eski tarayıcı/Tor/
shell katmanı bu zincirde bulunmuyor. Eski web modülü opt-in arşivine taşındı;
uyumluluk modülü aynı durable uygulamayı export ediyor. Firebase statik barındırma
yerel Python motorunu çalıştırmaz; bir bulut kopyası yerel app yerine sayılmaz.

## Doğrulanmış bulgular ve düzeltmeler

| Bulgu | Etki | Uygulanan değişiklik / kanıt |
|---|---|---|
| Ana süreç çıktıktan sonra alt süreç sürüyor | TOOL_DONE sonrası diske geç yazma | Gerçek alt süreç testi eski sürümde dosya değiştirdi; süreç grubu ana süreçten bağımsız kapatılır |
| Çocuk PID kaydı başarısız olursa komut açık kalıyor | Veritabanı hatası sonrası sahipsiz süreç | Kayıt işlemi cleanup kapsamına alındı; enjekte edilen kayıt hatasında geç yazma engellenir |
| Kapatılamayan komut için ilerleme devam edebiliyor | Belirsiz yan etkiler ve sonraki işler | PID korunur, BLOCKED ve COMMAND_CLEANUP_UNCERTAIN; kuyruk bekler |
| Başarısız adım + önceden doğru dosya VERIFIED oluyor | Gerçek exit 2 olmasına rağmen başarı | Son adım başarısızsa dosya varlığı yeterli değil; yeniden üretim testi |
| Konuşma bütünü tek JSON içine gömülüyor | Ek kaçışlar, büyüyen yeniden değerlendirme | Native metin turları; önceki mesaj öneki sabit kalır; native tool parser hâlâ kullanılmaz |
| Sadece karakter hızıyla parçayı küçültme | Aynı işi daha çok model turuna bölme | İlk yanıt + üretim süresi birlikte; sığan parça 700 kalır, gerekli durumda 350 |
| Toplam bütçe model çağrısı hatası gibi görünüyor | 25 saniyelik son bekleyiş yanlış teşhis ediliyor | TASK_BUDGET_EXHAUSTED, kullanılan/toplam/kalan süre, bütçe dolunca retry yok |
| Aynı JSON anahtarı iki kez kabul ediliyor | Belirsiz araç adı/parametre | Yinelenen anahtar ve standart dışı JSON sayısı reddedilir |
| Origin kontrolü tek başına Host'a güveniyor | Başka Host ile yerel API'ye erişim | Loopback Host allowlist, gerçek TCP ve ASGI reddetme testleri |
| JSON doğrulamasından önce gövde sınırsız | Büyük/chunked istekte gereksiz bellek | Ham gövde 256 KiB ve alım 10 sn; 413/408 yanıtları |
| NUL içeren yol 500 üretiyor | Geçersiz kullanıcı girdisi sunucu hatası oluyor | Geçersiz yol 422 olarak reddedilir |
| Belirsiz komut arkasına yeni iş alınıyor | Çalışmayacak iş sırada gizleniyor | BLOCKED dış komut varsa gönderim 503 |
| Büyük dosya tamamen belleğe okunuyor | 100 KB sınırı geç uygulanıyor | Sınırlı okuma, append/patch toplam boyut sınırı; dosya korunma testi |
| Eski giriş yeni motoru atlıyor | Aynı arayüzden farklı yürütme davranışı | Web aliasları, CLI ve başlatıcı tek motora bağlandı; eski katman açıkça seçilmeli |
| Süreç kimliği araçları kapatmayı engelliyor | Gerçek start/status/reuse geçip stop kod 1 üretti; bu ortamın PID ve /proc alanları da eşleşmedi | Yeni yönetilen sunucu özel anahtarla kendi kendini kapatır; anahtar API'de sunulmaz ve çalışana aktarılmaz. Eski sürümlerde native Linux /proc ve macOS ps kimlik denetimi korunur. Başarısız denemeler JSON kanıtında tutulur |
| HTTP 200, boş model yanıtına başarı oluyor | Sahte inference probe | Metin ve pozitif gerçek eval_count zorunlu |
| İşletim ortamı hareketli bağımlılıklara bağlı | Sonraki kurulum farklı sürümler getiriyor | Temiz venv'de sınanan tam sürüm listesi ve pip check |
| CI yalnızca Python 3.12 tanımlıyor | Kullanıcının 3.14 hataları kapsam dışında | Linux/macOS × 3.12/3.14 matrisi; gerçek CI sonucu ayrı kapı |
| Modelin kendi test raporu kabul ediliyor | Örnek cevabı tekrar etmek başarı sanılıyor | Dış kabul denetleyicisi programı yedi kez çalıştırır; ezber çıktı kenar testinde kalır |
| Bütün görev doğrulanmış gibi başlık | Dosya kontrolü program davranışıyla karışıyor | verification_scope=exact_files; DOSYA KABULÜ DOĞRULANDI; Node regresyonu |
| Çince plan açıklaması görünebiliyor | Türkçe arayüz talebi ihlali | Türkçe açıklama üretilemedi kaydı, CJK plan metni kullanıcıya sunulmaz; ham kullanıcı verisi tercüme edilmez |
| Yardımcı modüller sabit Mac dizinine yazıyor | Yanlış çalışma alanı ve import yan etkisi | BARIS_WORKSPACE ve kullanım anında dizin oluşturma |
| Eski sistem betiği doğrudan ayar değiştiriyor | Yanlışlıkla farklı model sunucusu/OS ayarı | Açık legacy uygulama seçeneği olmadan çıkış 2 ve sıfır ayar değişikliği |

## Kabul testinin bağımsızlığı

`verify-live` yeni bir dizin ve koruma dosyası oluşturur. Modelin yazdığı program,
önceden model konuşmasına verilmeyen normal/kenar/boş veri ile çalıştırılır.
Eksik ve bozuk girdi ile mevcut doğru çıktının korunması, aynı girdi/çıktı yolunun
reddi ve hata sonrası normal çalışma kontrol edilir. Dış denetleyici stdout,
stderr, gerçek süreç çıkış kodu ve içerik karşılaştırmasını kaydeder.

Bir fixture testi doğru programın bu kapıdan geçtiğini gösterir. Başka bir fixture
programı sadece örnek sonucu yazdığı için kenar veride kalır. Bu iki sonuç, kabul
denetleyicisinin sınamasıdır; canlı Mistral becerisi için veri değildir.
Gerçek TCP testi ayrıca ASGI sunucusu, SQLite, ayrı çalışan süreç ve diski birlikte
kullanır; model tarafı bu testte de kontrollü yanıttır.

## Açık yayın kapıları

| Açık konu | Gereken gerçek kanıt | Mevcut durum |
|---|---|---|
| Mac/Mistral görevi gerçekten tamamlıyor mu? | Kullanıcının çalışan sürümünde verify-live raporu | Bu ortamdan cihaz erişimi yok; yapılmış sayılmadı |
| Uzun kod ve bağlam kapasitesi | 8192 token için gerçek model/tokenizer, görev ve kaynak ölçümleri | Kesin tokenizer tabanlı giriş bütçesi yok; sınırsız uzun görev garantisi yok |
| İşletim sistemi erişim izolasyonu | Ayrı kullanıcı/VM/container politikası ve kaçış testleri | Python komutu kullanıcının yetkileriyle çalışır; os_sandbox=false |
| Süreç grubundan ayrılan çocuklar | OS sandbox/cgroup veya eşdeğer süreç sahipliği | Grup dışına bilerek ayrılma bu mekanizma tarafından kapsanmaz |
| macOS Dock/Swift/AppKit | Gerçek kurulum, yeniden açma, Python güncellemesi ve simge kontrolü | Linux'ta native paket testi yapılmadı |
| Uyku/uyanma, Metal ve RAM baskısı | Mac üzerindeki kayıtlı dayanıklılık/kapasite çalışması | Çevrimdışı testler bu kanıt değildir |
| Güç kesintisi ve dosya sistemi yarışı | Gerçek arıza/çok yazıcılı dosya sistemi testleri | Temp/fsync/replace ve SHA kontrolü tam OS kilidi veya güç kaybı sertifikası değildir |
| macOS/Python 3.14 CI | Yeni commit'in gerçek workflow sonuçları | Matris tanımlandı; tanım geçiş sayılmaz |
| Genel başarı yüzdesi | Sabit, temsil edici görev kümesi; tekrar sayısı, hata sınıfları ve süreler | Ölçülmedi; yüzde verilmez |

Eski Tor/tarayıcı/kurulum araçları; shell=True, değişen harici servisler ve farklı
yetkiler nedeniyle ayrıca yeniden tasarlanmadan desteklenen motorun kalite
kapsamına alınamaz. Opt-in arşivinin bulunması bu özelliklerin güvenli veya canlı
çalıştığının ilanı değildir. Mevcut aktif motor gerçek çoklu ajan sistemi değildir.

Bu açık kapılar kapatılmadan projeye 100/100, hatasız veya endüstriyel sertifikalı
etiketi verilmez. Bu sürümün iddiası, belgelenmiş hataların düzeltilmesi ve kontrol
edilebilir doğrulama yoludur.

## Dayanaklar

- [Ollama Chat API: mesaj dizisi, şema, done ve süre alanları](https://docs.ollama.com/api/chat)
- [Ollama FAQ: bağlam/paralellik, bellek ve GPU durumu](https://docs.ollama.com/faq)
- [Python subprocess: süreç, çıkış kodu ve oturum davranışı](https://docs.python.org/3.12/library/subprocess.html)
- [SQLite transaction](https://www.sqlite.org/lang_transaction.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite güç kesintisi/atomik commit sınırları](https://www.sqlite.org/atomiccommit.html)

Ollama'nın güncel belgesindeki cache sayacı her sürümde bulunmayabilir. Alan yoksa
ölçüm null kalır; eksik sayaçtan performans veya cache başarısı uydurulmaz.
