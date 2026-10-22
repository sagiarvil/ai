import sys
sys.path.insert(0, "/Users/macair1/projects/ai-yerel-d2c1017")
import task_worker

def test_single_line_table_formatting():
    raw_input = "Görev başarıyla tamamlandı. | Sınıf | Jeneratör Sayısı | Toplam Enerji (kWh) | Ortalama Üretim (kWh) | | :------ | :-------------: | :-----------------: | :--------------------: | | Class 1 | 210 | 99986180.00 kWh | 476124.67 kWh | | Class 2 | 257 | 124325343.00 kWh | 483756.20 kWh |"
    result = task_worker.format_human_reply(raw_input)
    assert "### Analiz ve Doğrulama Raporu" in result
    assert "| Class 1" in result
    assert "| Class 2" in result
    assert "✅" in result
    # Satirlar ayrilmis olmali
    lines = [l.strip() for l in result.splitlines() if l.strip().startswith("|")]
    assert len(lines) >= 4  # Header, ayirici, class 1, class 2

def test_json_formatting():
    raw_json = '{"discounted_product_count": 428, "total_discount_amount": 21418095.9, "total_revenue": 312415404.1}'
    result = task_worker.format_human_reply(raw_json)
    assert "### Yönetici Özeti ve Hesaplama Bulguları" in result
    assert "428 adet" in result
    assert "TL" in result
    assert "✅" in result

if __name__ == "__main__":
    test_single_line_table_formatting()
    test_json_formatting()
    print("ALL PRO FORMATTING TESTS PASSED!")
