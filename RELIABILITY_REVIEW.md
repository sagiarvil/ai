# Barış AI — Güvenilirlik ve öngörü denetimi

Tarih: 21 Ekim 2026. Sürüm: local-ui-v8.
Karar: GELİŞTİRME REGRESYONU GEÇTİ; CANLI MAC KABULÜ BEKLİYOR.
Kişisel yerel kullanım için korumalar eklenmiştir. Genel amaçlı, izole,
her görevi bitiren endüstriyel ajan sertifikasyonu yapılmamıştır.

## Kanıt türleri ve sınırlar

- Önceki canlı v5/v6 kayıtları: model gerçekten araç kullanıyor; uzun üretim,
  başlangıç sessizliği ve birikmiş dosyayı yeniden yazma hataları gözlendi.
- Geliştirme testleri gerçek SQLite, dosya, HTTP akışı ve süreç kullanır.
  Model yanıtları programlanmıştır; canlı Mistral yeterliliği ölçülmez.
- Yeni arıza testlerinde eşzamanlı iptal, disk/fsync arızası, hızlı çıktı
  taşması, geç gelen çalışan sonucu ve belirsiz komut kesintisi enjekte edilir.
- Bir test sayısı başarı yüzdesi değildir. Gerçek görev başarı oranı,
  p50/p95 gecikmesi, soğuk başlangıç ve uzun süreli kararlılık henüz ölçülmedi.

## Arıza matrisi

| Tetikleyici | Sonuç / önlem | Kanıt / kalan sınır |
|---|---|---|
| Model yalnızca metin üretir | Metin çalıştırılmaz; sahte başarı reddedilir | Mevcut yürütme testleri |
| Kod üretimi çağrı sınırını aşar | 700 karakter; bir denemede 350; kesik JSON atılır | Akış/sınır/onarım testleri |
| İlk yanıt gecikir | İlk yanıt toplam 240 saniyelik çağrı bütçesinde beklenir | Gecikmeli ilk yanıt testi |
| Başlamış akış susar | 90 saniyelik sessizlik sınırı, açık tanı | Sessizlik testi |
| Çok yavaş yerel model | Ölçülen model/context hız profili parçayı küçültür | Profil/adaptasyon testi; tamamlanma garantisi yok |
| Birikmiş dosyaya write seçilir | Create-only; mevcut dosya korunur | Canlı hatanın regresyonu |
| Eşzamanlı başka oluşturucu | Atomik create-if-absent mevcut dosyayı ezmez | Yarış testi |
| Eski hash, çoklu/boş yama hedefi | Yazma reddedilir | Patch sınır testleri |
| Düzenleme sırasında dış değişiklik | Commit öncesinde fark edilen değişiklik korunur | Enjekte dış düzenleme testi; OS çapında CAS/sandbox değildir |
| Commit öncesi yazma/fsync başarısız | Eski veri korunur; geçici dosya temizlenir | fsync hata testi; güç kesintisi deneyi yapılmadı |
| Dizin daha önce var | Yeni dizin gibi kabul edilmez | Dizin çakışma testi |
| Çift gönderim / belirsiz HTTP yanıtı | Aynı anahtar aynı görev; farklı içerik 409 | Idempotency ve UI testleri |
| İptal ve claim aynı anda | BEGIN IMMEDIATE ile sıralı durum geçişi | 12 eşzamanlı yarış denemesi |
| Model yanıtı sonrası iptal | Yeni araç öncesi ikinci kontrol | Araya iptal enjeksiyonu |
| Terminal görev için geç sonuç | Terminal kayıt değiştirilemez | Geç çalışan sonucu testi |
| İptal ile başarı yarışı | İptal korunur; VERIFIED yazılmaz | Bitiş yarışı testi |
| Normal timeout / iptal | Komut süreç grubu TERM/KILL | Gerçek süreç ve torun testleri |
| Çalışan SIGKILL/OOM ile ölür | Güvenli checkpoint veya BLOCKED; belirsiz komut tekrar edilmez | Recovery testleri; belirsiz çocuk varsa kuyruk tutulur |
| Belirsiz komut ve yeni görev | Yeni görev bekletilir; PID/komut izi korunur | Kuyruk engelleme testi; elle inceleme gerekir |
| Çıktı hızlıca 4 MB'ı aşar | Süreç çıktı boyutu bittikten sonra da sınanır | Hızlı biten süreç testi |
| Disk çalışma payı 64 MiB altına iner | Yeni görev 507 ile reddedilir | Disk yetersizliği testi; bu eşik her görev için kapasite garantisi değil |
| SQLite yeni işi kaydedemez | 503, kabul edilmiş gibi gösterilmez | Depolama hatası testi |
| Zamanlayıcı ölür | Yeni iş kabul edilmez; arayüz durumu bildirir | Zamanlayıcı arıza testi |
| macOS /var → /private/var veya başka bağlı kök | Tek kanonik servis kökü kullanılır | Gerçek API ve dosya yürütmesiyle bağlı kök regresyonu |
| Kabul yolu dışarı/iç kayıtlara gider | İstek 422; bu yollardan kabul okuması yok | API kapsam testleri |
| 100 olaydan fazlası var | latest_event ve next_after/has_more | 251 olay testi |
| Tarayıcı/sunucu yeniden başlar | Aynı görev izlenir; çalışan tekrarlanmaz | Yeniden başlatma testleri |
| Başarı/başarısızlık karışır | FAILED, CANCELLED, BLOCKED açık başlıklarla ayrılır | UI sözleşmesi |
| Bozuk/eksik yerel bağımlılık | Başlatıcı preflight durur; doctor ortamı gösterir | Mac Python ortamı canlı doğrulanmalı |

## Yapılmayan şeyler / yayın engelleri

1. **OS sandbox yok.** Genel Python/shell kullanıcının yetkileriyle çalışır;
   dosya aracı korumaları bu komutları otomatik olarak sınırlandırmaz.
   Hassas veya güvenilmeyen görev için ayrı kullanıcı/izole çalışma ortamı
   kurulmadan geniş yetkili üretim kullanımı kabul edilmez.
2. **Gerçek model yeterliliği açık.** 12 kontrolün canlı araç kayıtlarıyla
   tamamlanması, ardından en az 10 görev ve 3 soğuk başlangıç örneği gerekir.
   Bunlar başlangıç örneklemidir; yüzde 100 güvenilirlik kanıtı değildir.
3. **Kaynak/bağlam kapasitesi açık.** Ollama context ve paralellik RAM'i etkiler.
   Başka uygulamaların Ollama çağrıları bu motorun kilidine uymaz. 24 GB Mac'te
   swap, yükleme ve prompt süreleri ölçülmeden CPU/GPU darboğazı teşhisi konmaz.
   Tokenizer olmadan karakter sayısı tam token sınırı olarak sunulmaz.
4. **İş büyüklüğü sınırlı.** 900 saniye / 40 tur varsayılanı, uzun görevlerin
   bitmesini garanti etmez. Süre dolması güvenli başarısızlıktır. İleri çözüm
   bütçeli alt görev kabul sözleşmeleridir; sınırları gizlice sonsuza uzatmak değildir.
5. **Güç kesintisi ve disk bozulması testi yok.** fsync ve SQLite FULL/WAL,
   bozuk donanım veya her dosya sistemi için mutlak garanti değildir.
6. **Genel görev kabulü sınırlı.** expected_files yalnızca tam dosya içeriğini
   doğrular. Modelin kendi yazdığı rapor, 12 işlevsel testin bağımsız hakemi değildir.
   Finans/kurulum gibi işler için kullanıcıdan bağımsız kabul programı gerekir.
7. **Belirsiz dış komut otomatik temizlenmez.** PID yeniden kullanılabilir.
   İncelemeden süreç öldürmek veya komutu tekrar etmek veri kaybı yaratabilir.
   BLOCKED durumunda doctor kaydı incelenmeden kuyruk açılmaz.
8. **CI ve gerçek tarayıcı/Mac testi ayrı.** Geliştirme konteyneri PASS,
   macOS CI PASS veya canlı cihaz PASS olarak yeniden etiketlenmez.

## Kalıcı gelişim kuralı

Yeni arıza: gerçek kanıt → kök neden → önce tekrarlanabilir test → hedefli
koruma → regresyon → canlı kabul. Hata imzası bu matrise eklenir.
Yerel hız profili kontrollü uyarlamadır; LLM ağırlıkları eğitilmez, ham kullanıcı
verisi başka servise gönderilmez. Daha fazla ajan eklemek tek başına güvenilirlik
sağlamaz; kanıtlanmamış ek servisler bu sürüme eklenmemiştir.

## Çalıştırma ve teşhis

```bash
python3 -m unittest -v test_execution_loop test_structured_actions test_acceptance_checks test_durable_runtime test_reliability
node --check public/app.js
node --test test_local_ui.cjs
python3 -m py_compile *.py
python3 baris_local.py doctor
```

Doctor kontroller başarısızsa çıkış kodu 1 verir. Salt okunur teşhis verir; Ollama ayarını değiştirmez, bozuk DB onarmaz,
canlı görevin tamamlandığını ileri sürmez. Model ölçümleri model/context bazındadır;
aynı model etiketi altında ağırlık değişirse eski profil geçici olarak yanıltabilir.
Profil yalnızca güvenli sınırlar içindeki parça boyutunu küçültür.

## Araştırma kaynakları

- [Ollama Chat API — done, yükleme/prompt/üretim süreleri](https://docs.ollama.com/api/chat)
- [Ollama FAQ — context, paralellik ve bellek](https://docs.ollama.com/faq)
- [SQLite işlemleri — tek yazıcı ve BEGIN IMMEDIATE](https://www.sqlite.org/lang_transaction.html)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite atomik commit ve güç kesintisi sınırları](https://www.sqlite.org/atomiccommit.html)
- [Python subprocess — timeout ve süreç yönetimi](https://docs.python.org/3/library/subprocess.html)
- [Python os — dosya ve süreç işlemleri](https://docs.python.org/3/library/os.html)

## v8 kanonik yol regresyonu

Yeni test önce eski sürümde aynı `422 != 202` hatasıyla KALDI. Kanonik servis
kökü düzeltildikten sonra test, görev kabulünü ve gerçek yazma/doğrulamayı GEÇTİ.
İkinci test, bağlı kökten dışarı çıkan symlink yolunun hâlâ reddedildiğini sınar.
Geliştirme toplamı 74 Python ve 10 Node testidir. Mac çalıştırması ayrı kalır.
