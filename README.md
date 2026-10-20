# Barış AI — Yerel yürütme paneli

Arayüz ve yürütme motoru aynı yerel sunucudan sunulur.
Modelin metin üretmesi görevin tamamlandığı anlamına gelmez.

## Başlatma

```bash
python3 baris_local.py start --shortcut
```

Başlatıcı mevcut Python ortamını kullanır; paket veya model indirmez.
29 çevrimdışı motor testini çalıştırır, yalnızca loopback adresinde sunucu
başlatır, motor kimliğini doğrular ve tarayıcıyı açar. Varsayılan port 5053'tür.
Masaüstüne Baris-AI.command kısayolu eklenir; sonraki açılışlarda aynı sunucu kullanılır.
Port başka uygulamadaysa süreç öldürülmez, açık hata verilir.

```bash
python3 baris_local.py status
python3 baris_local.py stop
```

Kayıtlar .baris_runtime/ altındadır. Oturum açılışında otomatik başlatma kurulmaz.
Durdurma yalnızca kimliği doğrulanmış yönetilen süreç için geçerlidir.

## Arayüz doğrulaması

“Dosya yazmayı sına” düğmesi benzersiz dosya yolu ve tam içerik beklentisi
gönderir; dosya gerçekten okunarak kontrol edilir. Genel görevlerde bağımsız
kabul kontrolü yoksa sonuç UNVERIFIED gösterilir; başarı uydurulmaz.
İşlem kanıtları açılır bölümde, dosya okuma sonuçları metin olarak gösterilir.
Çift gönderim arayüzde ve API'de engellenir. İstemci hatasında otomatik tekrar yoktur.

## Kanıt ve sınırlar

Kullanıcının 7838c946 sürümündeki canlı Mistral testi bir dosyayı tek araç çağrısıyla
yazmış ve bağımsız içerik kontrolünü geçmiştir. Bu bütün görevlerde başarı garantisi
değildir. Yeni arayüz/başlatıcı için canlı Mac testi ayrıca yapılmalıdır.

```bash
python3 -m unittest -v test_execution_loop test_structured_actions test_acceptance_checks
node --test test_local_ui.cjs
```

Python testleri programlanmış model yanıtları kullanır; Node testleri sahte DOM ve
HTTP yanıtlarıyla arayüz/API sözleşmesini sınar. Canlı tarayıcı veya model testi değildir.

Shell yürütücüsü işletim sistemi sandbox'ı değildir. Sunucu yalnızca kişisel yerel
kullanım içindir. Başka tarayıcı origin'lerinden görev gönderimi reddedilir; bu,
kimlik doğrulama veya süreç izolasyonu yerine geçmez. Görev zaman aşımı model
bekleyişini keser; iş parçacığında başlayan dış komutun mutlaka durduğunu garanti etmez.

Eski DeepSeek/Qwen masaüstü uygulamasının kaynakları bu repoda bulunmuyor.
Bu başlatıcı repodaki yerel paneli çalışan motora bağlar; başka uygulamaları değiştirmez.
