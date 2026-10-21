# Barış AI — Yerel görev yürütme motoru

Modelin yanıt üretmesi, dosya yazması ve görevin doğrulanması ayrı durumlardır.
Desteklenen uygulama `durable_api:app`, sürüm `local-ui-v10`.

## Başlatma

```bash
python3 baris_local.py start --shortcut
```

Mevcut Python ortamı kullanılır; başlatıcı paket veya model indirmez. Çevrimdışı
regresyonlar ve gerçek HTTP/süreç/disk kontrolü geçince yalnızca
`http://127.0.0.1:5053` üzerinde yönetilen sunucu açılır. Mevcut çalışan görev
varken sürüm değiştirilmez. Başka uygulamanın süreci öldürülmez.

Yeni sunucuyu durdurma, yalnızca başlatıcının sakladığı özel anahtarla sunucunun
kendi kendini kapatmasını ister. Anahtar motor bilgisi yanıtında bulunmaz ve görev
sürecine aktarılmaz. Eski sürüm yükseltmesinde süreç kimliği platform aracıyla
ayrıca doğrulanır.

```bash
python3 baris_local.py status
python3 baris_local.py stop
python3 baris_local.py doctor
```

`python3 server.py`, `python3 omni_chat_panel.py` ve masaüstü kısayolu aynı
başlatıcıya gider. `uvicorn server:app` ve `uvicorn omni_chat_panel:app` importları
da aynı uygulamayı sunar; yönetilen kullanım için `baris_local.py` tercih edilir.
`autonomous_agent.py "talimat"` aynı API'nin terminal istemcisidir. Bu istemci,
sonuç doğrulanmadığında sıfır çıkış kodu vermez.

## Mac üzerinde gerçek kabul

```bash
python3 baris_local.py verify-live --budget 900
```

Açık ve boş bir görev kuyruğu gerektirir. Her çalıştırma benzersiz yeni test dizini
kullanır. Önce modele birebir Türkçe dosya yazdırılır. Ardından modelden Decimal
ile CSV analiz programı yazıp gerçekten çalıştırması istenir. Dış test motoru bu
programı yedi ayrı komutla sınar: normal veri, kenar durumlar, boş veri, eksik
dosya, bozuk başlık, aynı girdi/çıktı yolu ve hata sonrası yeniden normal çalışma.
NaN, Infinity, yinelenen kimlik, sıfır tutar, iki ondalık ve dosyaların korunması
denetlenir. Modelin yazdığı rapor kanıt sayılmaz.

Gerçek komutlar, süreç çıkış kodları, stdout/stderr, model süreleri ve kontrol
sonuçları `.baris_runtime/canli-kabul-*.json` içinde kalır. Çıkış kodu 0 kabulün
geçtiğini, 1 tamamlanmadığını belirtir. Görevler için bütçe ayrı ayrı uygulanır.
900 saniye varsayılandır; açıkça seçilirse 30–1800 saniye aralığı desteklenir.
Bu test geçmeden canlı model için genel başarı veya üretime hazır olma iddiası
çıkarılmaz. Tek başarılı deneme bütün görevler için başarı yüzdesi vermez.

## Çalışma sözleşmesi

- POST `/api/tasks` hemen 202 ve görev kimliği döndürür; 202 tamamlanma değildir.
- GET `/api/tasks/{id}?after=N` gerçek olayları, son olayı ve kalan bütçeyi verir.
- POST `/api/tasks/{id}/cancel` yalnızca o görevi durdurur.
- `Idempotency-Key` aynı gönderimin ikinci işe dönüşmesini engeller; farklı
  içerikle aynı anahtar 409 alır.
- Eski `/api/chat` en fazla beş saniye bekler; sonra kalıcı görev kimliği verir.
- Durumlar: QUEUED, RUNNING, VERIFIED, UNVERIFIED, FAILED, CANCELLED, BLOCKED.

SQLite WAL ve ayrı çalışan süreç HTTP kopması ve sayfa yenilemesinden bağımsızdır.
Tek model/görev çalışır; sekiz bekleyen/çalışan görev sınırı vardır. Çöken komutun
sonucu belirsizse otomatik tekrar yapılmaz. Böyle bir BLOCKED komut sonraki
çalışmaları durdurur; yeni API gönderimi 503 döndürür.

Yürütme, web sunucusundan ayrı bir dosya kilidiyle korunur. Kilit, yeni çalışan
başlatılırken dosya tanıtıcısıyla devredilir; web süreci PID kaydından önce çökse
bile ikinci çalışan başlayamaz. Her deneme ayrı sahiplik anahtarı alır; önceki
denemenin olay, kontrol noktası ve sonuç yazıları reddedilir. Kilit, komutların
temizliği bitene kadar tutulur. Bu mekanizma yerel dosya sistemi ve bu protokole
uyan çalışanlar içindir; dağıtık kilit veya işletim sistemi izolasyonu değildir.

Eski sürümden kalmış bir çalışanın kimliği okunamıyorsa süreç ölü sayılmaz ve
körlemesine sinyal gönderilmez. Eski kayıtta çalışan kimliği de yoksa
`WORKER_OWNERSHIP_UNCERTAIN` ile BLOCKED olur ve kuyruk durur. Yeni çalışanların
iptali, PID denetimi çalışmasa da model/komut bekleyişindeki periyodik kontrolle
uygulanır. Bir dosya yazmasının ortasında iptal, o atomik işlemi geri almaz.

Model JSON şemasıyla tek işlem üretir; native tool-call şablonuna bağımlı değildir.
Konuşma gerçek system/user/assistant turlarıyla gönderilir. Kod parçaları 700 veya
350 karakterdir. Kısa parçalara geçiş hem ilk yanıt süresini hem üretim hızını
hesaba katar. Bu ölçümler model eğitimi değildir.

İş başına varsayılan 900 sn, model çağrısı en fazla 240 sn, akış başladıktan sonra
sessizlik 90 sn, komut en fazla 90 sn ile sınırlıdır. Toplam bütçe bitişi
`TASK_BUDGET_EXHAUSTED` olarak ayrılır; yeni deneme başlatılmaz. Kesik JSON ve
üretim sınırına takılmış kısmi komut çalıştırılmaz. Ekrandaki ilerleme, bağlantı
kaybı ve bütçe göstergeleri ayrı durumlardır.

Yeni dosya oluşturma mevcut içeriği ezmez. Append/patch güncel SHA gerektirir;
aynı içerikte yalnızca tek yama hedefi kabul edilir. Dosya işlemleri 100 KB,
istek gövdesi 256 KiB, komut çıktısı 4 MB sınırındadır. Çıktı aşımı sonradan da
kontrol edilir; kısa süreli disk yazması için bu sayı işletim sistemi kotası değildir.
Komutun ana süreci çıktıktan sonra kalan aynı süreç grubundaki alt süreçler de
kapatılır. Kapatma doğrulanamazsa görev BLOCKED olur.

`expected_files` sadece belirtilen dosyaların birebir içeriğini doğrular.
`verification_scope=exact_files` bunun açık kaydıdır. Arayüz bu sonucu
**DOSYA KABULÜ DOĞRULANDI** diye gösterir. Bu kontrol programın bütün davranışlarını
doğrulamaz; `verify-live` ayrıca dışarıdan program çalıştırır. Bağımsız kabulü
olmayan genel görev UNVERIFIED kalır ve `execution_completed=false` döndürür.

## Tekrarlanabilir geliştirme ortamı

Temiz bir sanal ortam için sınanmış doğrudan ve dolaylı bağımlılıklar
`requirements-runtime.lock` içindedir. Eski `requirements.txt` tarihsel ek araçlar
üzerine kuruludur; yerel motorun tekrar üretilebilir bağımlılık listesi değildir.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.lock
.venv/bin/python -m unittest discover -v
node --test test_local_ui.cjs
```

CI Linux/macOS ve Python 3.12/3.14 matrisini tanımlar. Bir workflow dosyasının
bulunması CI'nin geçtiği anlamına gelmez; gerçek sonuç ayrıca kontrol edilir.
Çevrimdışı testlerde kontrollü HTTP model yanıtları kullanılır. Bunlar modelin
muhakeme başarısını ölçmez.

## Kapsam ve açık sınırlar

Desteklenen motor tek seçili modeli kullanır; DeepSeek/Qwen/Mistral arasında gerçek
çoklu ajan yöneticisi içermez. Model `BARIS_MODEL`, Ollama uç noktası
`BARIS_OLLAMA_CHAT_URL` ile seçilir. Bunlar yüklenmiş modelleri değiştirir; indirme
veya otomatik donanım ayarı yapılmaz.

Python komutları işletim sistemi düzeyinde sandbox içinde değildir.
`os_sandbox=false` API'de bildirilir. Komutlar kullanıcının dosya erişim yetkileriyle
çalışır; çalışma dizini ve ortam temizliği tam erişim izolasyonu sağlamaz.
Süreç grubundan bilinçli olarak ayrılan süreçler bu grup denetiminin dışındadır.
8192 token bağlam için kesin tokenizer tabanlı kapasite denetimi yoktur; çok uzun
talimatlar ve büyüyen kod için canlı kapasite ölçümü gereklidir.

Eski Tor/Chrome/Slither/kurulum yolu `legacy_omni_chat_panel.py` içinde korunur ve
varsayılan olarak kapalıdır. Desteklenen uygulama onu import etmez. Eski dış servis
testleri açıkça seçilmedikçe atlanır. Eski sistem değiştirme betiği bayrak verilmeden
hiçbir ayar yazmaz. Bu eski bileşenler yeni motorun kalite belgesine dahil değildir.

Mac Dock paketi, uyku/uyanma, Metal bellek baskısı, gerçek güç kaybı ve uzun süreli
canlı model dayanıklılığı burada Linux testleriyle doğrulanmış sayılamaz.
[Bulgular ve yayın kapıları](REPO_AUDIT.md), [gerçek test kanıtı](AUDIT_EVIDENCE.json)
ve [önceki güvenilirlik incelemesi](RELIABILITY_REVIEW.md) ayrı kayıtlardır.
