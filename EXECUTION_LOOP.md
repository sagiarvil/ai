# Araç yürütme döngüsü

Bu değişiklik mevcut /api/chat yoluna bağlıdır; ayrı bir demo değildir.

- Araçsız ilk yanıt en fazla iki devam isteği alır.
- Araç hataları modele yapılandırılmış olarak döner.
- API hatası ve bütçe bitimi VERIFIED durumuna çevrilmez.
- Dosya okuma/yazma proje köküyle sınırlandırılır; yazma sonrası yeniden okunur.
- Bloklayan shell ve dosya işleri API olay döngüsünden ayrı iş parçacığında çalışır.
- Aynı çağrı kimliği tek yürütme içinde tekrar çalıştırılmaz.
- Kullanıcıya dönen durum açıklamaları Türkçedir; ham model son yanıtı gösterilmez.
- Repo kurulumu gerçek test komutu olmadan aktifleştirilmez.
- Model ve çalışma dizini BARIS_MODEL, BARIS_MODEL_API_URL ve BARIS_WORKSPACE ile değiştirilebilir.

## Kabul kontrolü

Araç başarısı görevin tamamlandığını kanıtlamaz. /api/chat isteğine expected_files
alanı verilirse belirtilen dosyaların tam içerikleri modelden bağımsız okunur.
Örnek:

```json
{
  "message": "deneme.txt içine tam olarak Merhaba Barış yaz; satır sonu ekleme.",
  "expected_files": {"deneme.txt": "Merhaba Barış"}
}
```

Dosya kontrolü yalnızca belirtilen koşulları kanıtlar. Servis sağlığı veya kurulum
kabulü için execute_verified_task üzerinden güvenilir verify_task_fn gerekir.
Kabul kontrolü olmayan yürütme UNVERIFIED döner.

## Doğrulama

```bash
python3 -m unittest -v test_execution_loop
```

14 regresyon testi programlanmış model yanıtlarıyla çalışır; bir test gerçek geçici
dosya yazıp yeniden okur. Bunlar canlı Mistral, Ollama, Mac veya internet testi değildir.
Canlı modelin araç çağrısı desteği ayrıca doğrulanmalıdır.

## Sınırlar

Bu sürüm kalıcı görevden devam, süreçler arası tekilleştirme, çoklu ajan veya işletim
sistemi sandbox izolasyonu sağlamaz. Mevcut shell yürütücüsü kullanıcı yetkileriyle
çalışır; cwd ve ortam süzme bir güvenlik sınırı değildir.
Araç çıktıları hassas içerik barındırabilir; görev kayıtları dışarı yayımlanmamalıdır.
Mevcut kimlik doğrulama fonksiyonu yanlış anahtarı da kabul eder; servis güvenilmeyen
ağlara açılmamalıdır. Bu değişiklik kimlik doğrulama davranışını değiştirmez.

Geri alma: değişiklik commit'ini revert edin; mevcut görev ve kullanıcı dosyalarını
silmeden önce inceleyin.
