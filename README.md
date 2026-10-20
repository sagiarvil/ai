# Barış AI — Yerel yürütme paneli

Arayüz ve yürütme motoru aynı yerel sunucudan sunulur.
Modelin metin üretmesi görevin tamamlandığı anlamına gelmez.

## Başlatma

```bash
python3 baris_local.py start --shortcut
```

Başlatıcı mevcut Python ortamını kullanır; paket veya model indirmez.
49 çevrimdışı motor ve entegrasyon testini çalıştırır, yalnızca loopback adresinde sunucu
başlatır, motor kimliğini doğrular ve tarayıcıyı açar. Varsayılan port 5053'tür.
Masaüstüne Baris-AI.command kısayolu eklenir; sonraki açılışlarda aynı sunucu kullanılır.
Port başka uygulamadaysa süreç öldürülmez, açık hata verilir.

```bash
python3 baris_local.py status
python3 baris_local.py stop
```

Kayıtlar .baris_runtime/ altındadır. Oturum açılışında otomatik başlatma kurulmaz.
Durdurma yalnızca kimliği doğrulanmış yönetilen süreç için geçerlidir.

## Kalıcı görev motoru — local-ui-v6

Yetkili giriş `durable_api:app` uygulamasıdır; `baris_local.py` ve `server.py` bu motora bağlanır.
POST `/api/tasks` hemen 202 ve görev kimliği döndürür. GET `/api/tasks/{id}`
kayıtlı durum ve gerçek olayları verir. POST `/api/tasks/{id}/cancel` iptal ister.
`Idempotency-Key` aynı isteğin ikinci göreve dönüşmesini engeller; farklı içerikle
aynı anahtar 409 döndürür. Eski `/api/chat` en fazla beş saniye bekler, sonra aynı
görevin kimliğini döndürür. 202 yanıtı tamamlanma anlamına gelmez.

SQLite WAL kaydı ve ayrı çalışan süreç sayesinde sayfa yenileme, HTTP kopması ve
web sunucusu yeniden başlatma işi yeniden yürütmez. Tek model çağrısı, tek görev
çalışır; sekiz bekleyen/çalışan görev sınırı vardır. İşlem sırasında çöken çalışanın
yan etkisi belirsizse görev BLOCKED olur; komut körlemesine tekrarlanmaz.

İlk model çağrısı kısa plan üretir. Kod en fazla 700 karakterlik parçalarla ve hash önkoşullu
eklemelerle yazılır. Varsayılan toplam bütçe 900 saniye, model çağrısı en fazla
240 saniye, akış sessizliği 90 saniye, dış komut 90 saniyedir. Bunlar başarısızlığı
saklayan sonsuz beklemeler değildir. Tekrarlanan sonuçsuz işlemler durdurulur.
Model akışındaki kesik JSON veya `done_reason=length` çalıştırılmaz.

`expected_files` bağımsız disk kontrolünden geçmedikçe VERIFIED üretilmez.
Kabul koşulu olmayan genel görevler UNVERIFIED olarak sunulur. Yeni dosya testinde
birebir içerik, satır sonu ve SHA kaydedilir. İptal/zaman aşımında dış komutun süreç
grubu önce TERM, gerekirse KILL ile durdurulur. Komut çıktısı sınırlandırılır.

Arayüz görev kimliğini saklar, yenilenince aynı görevi izler, kısa planı ve gerçek
ilerlemeyi gösterir. Yeni görev yaratmadan belirsiz gönderimi aynı anahtarla uzlaştırır.
Dock uygulamasının bağlı olduğu kaynak dizin aynı kaldığında kısayol değişmez.

## Doğrulama ve sınırlar

```bash
python3 -m unittest -v test_execution_loop test_structured_actions test_acceptance_checks test_durable_runtime
node --check public/app.js
node --test test_local_ui.cjs
```

49 Python ve 9 Node testi geliştirme ortamında geçti. Yeni 20 entegrasyon testi
kalıcı veritabanını, gerçek dosyaları, gerçek alt süreçleri ve HTTP akışını kullanır;
model yanıtları programlanmış yerel HTTP sunucusundan gelir. Finans stres testi
CSV analizi, yedi gerçek komut, hatalı girişte önceki sonucu koruma ve tekrar
çalıştırma kontrollerini içerir. Bu testler canlı Mistral performans ölçümü değildir.
Mac ve Linux CI matrisi eklenmiştir; yerelde geçen test CI sonucunun yerine geçmez.

Shell yürütücüsü işletim sistemi sandbox'ı değildir. Python programları kullanıcının
sistem yetkileriyle çalışır. Sunucu loopback üzerinde kişisel kullanım içindir.
Çapraz origin engeli kimlik doğrulama yerine geçmez. SQLite dosyası yerel diskte
kalmalıdır. Başka uygulamaların Ollama çağrıları bu motorun kilidine uymaz.
Her görevde yüzde 100 başarı garantisi veya canlı Mac testi iddia edilmez.

Tasarım kaynakları: [Ollama akış API](https://docs.ollama.com/api/chat),
[yapılandırılmış çıktı](https://docs.ollama.com/capabilities/structured-outputs),
[bellek ve paralellik](https://docs.ollama.com/faq),
[SQLite WAL](https://www.sqlite.org/wal.html),
[Python süreç denetimi](https://docs.python.org/3/library/asyncio-subprocess.html).

## v6: Canlı modelde gözlenen zaman aşımı düzeltmesi

Canlı kayıtta CSV 86 saniyede üretildi; sonraki kod çağrısı üretim sürerken
240 saniyelik sınıra takıldı. Bu gözlem belleğin yetersiz olduğunu kanıtlamaz.
700 karakter sınırı hem JSON şemasında hem dosya aracında zorunludur; hata/kesilme
sonrası tek kontrollü deneme 350 karakterle yapılır. Başarılı küçük parçalar hash
önkoşullu append ile birleştirilir. Kısmi JSON hiçbir zaman kod olarak yürütülmez.
Toplam 900 saniye ve 40 tur sınırları korunur; büyük görevler bu sınırları aşabilir.

MODEL_INTERRUPTED olayı hata türü, süre, karakter sayısı ve çağrı sınırını kaydeder.
Bağlantı sessizliği, toplam çağrı sınırı ve kesik çıktı birbirinden ayrılır.
GET görev yanıtındaki latest_event gerçek son olayı, next_after ve has_more ise
100 kayıtlık olay sayfalamasını belirtir. Eski v5 görev sonuçları v6 arayüzünde
okunabilir; yeni görevler v6 motoru gerektirir.

Yeni testler gerçek HTTP akışını kısa bir süre sınırında keser; kısmi işlemin
yürütülmediğini doğrular. Tek onarım, ikinci hatada durma, 700/350 sınırları,
251 olayın sayfalanması ve eski sonuçların sürüm geçişinde okunması sınanır.
Canlı Mistral ile aynı stres görevinin tamamlandığı henüz iddia edilmez.
