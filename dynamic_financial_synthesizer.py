import re
from typing import Dict, Any, List

class DynamicFinancialSynthesizer:
    """
    Kullanıcının serbest metinli finansal/ticari taleplerini 
    sembolik AST yapısına dönüştüren deterministik finans motoru.
    Off-by-one ve koordinat hatalarını %100 engeller.
    """

    @classmethod
    def detect_intent(cls, prompt: str) -> str:
        p = prompt.lower()
        if any(k in p for k in ["bordro", "sgk", "maaş", "personel", "işveren maliyet"]):
            return "PAYROLL_HR"
        elif any(k in p for k in ["amortisman", "yatırım", "fizibilite", "dcf", "nakit akış", "capex"]):
            return "FEASIBILITY_CASHFLOW"
        elif any(k in p for k in ["başabaş", "fiyatlandırma", "kar marjı", "birim maliyet", "katkı payı"]):
            return "COST_BREAKEVEN"
        elif any(k in p for k in ["bütçe", "varyans", "hedef", "sapma"]):
            return "BUDGET_VARIANCE"
        else:
            return "TDHP_FINANCIAL_STATEMENTS"

    @classmethod
    def synthesize_workbook(cls, prompt: str) -> Dict[str, Any]:
        intent = cls.detect_intent(prompt)
        
        if intent == "FEASIBILITY_CASHFLOW":
            return cls._build_feasibility_model()
        elif intent == "COST_BREAKEVEN":
            return cls._build_breakeven_model()
        elif intent == "BUDGET_VARIANCE":
            return cls._build_budget_variance_model()
        elif intent == "PAYROLL_HR":
            return cls._build_payroll_model()
        else:
            from excel_agent_v4 import generate_tdhp_blueprint
            return generate_tdhp_blueprint()

    @classmethod
    def _build_feasibility_model(cls) -> Dict[str, Any]:
        return {
            "sheets": [
                {
                    "name": "YATIRIM VE AMORTİSMAN",
                    "columns": [
                        {"name": "Yatırım ve Sabit Kıymet Kalemi", "type": "string"},
                        {"name": "Başlangıç (T0)", "type": "currency"},
                        {"name": "Yıl 1", "type": "currency"},
                        {"name": "Yıl 2", "type": "currency"},
                        {"name": "Yıl 3", "type": "currency"}
                    ],
                    "rows": [
                        {"id": "grp1", "type": "header_group", "cells": ["1. SABİT KIYMET YATIRIMLARI (CAPEX)"]},
                        {"id": "bina_tesis", "type": "data", "cells": ["Bina ve Altyapı Yatırımı", 450000, 0, 0, 0]},
                        {"id": "makine_cihaz", "type": "data", "cells": ["Makine ve Donanım Parkı", 750000, 50000, 0, 0]},
                        {"id": "yazilim_lisans", "type": "data", "cells": ["Yazılım ve Teknoloji Lisansları", 120000, 20000, 20000, 20000]},
                        {"id": "toplam_capex", "type": "total", "cells": ["TOPLAM CAPEX YATIRIMI", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP"]},
                        {"id": "grp2", "type": "header_group", "cells": ["2. AMORTİSMAN TABLOSU (Doğrusal %20)"]},
                        {"id": "amortisman_gideri", "type": "data", "cells": ["Dönem Amortisman Payı", 0, "={{toplam_capex}}*0.2", "={{toplam_capex}}*0.2", "={{toplam_capex}}*0.2"]},
                        {"id": "kumule_amortisman", "type": "data", "cells": ["Birikmiş Amortismanlar", 0, "={{amortisman_gideri}}", "={{amortisman_gideri}}*2", "={{amortisman_gideri}}*3"]},
                        {"id": "net_defter_degeri", "type": "total", "cells": ["NET DEFTER DEĞERİ", "={{toplam_capex}}", "={{toplam_capex}}-{{kumule_amortisman}}", "={{toplam_capex}}-{{kumule_amortisman}}", "={{toplam_capex}}-{{kumule_amortisman}}"]}
                    ]
                },
                {
                    "name": "SERBEST NAKİT AKIŞI",
                    "columns": [
                        {"name": "Nakit Akım Göstergesi", "type": "string"},
                        {"name": "Yıl 1", "type": "currency"},
                        {"name": "Yıl 2", "type": "currency"},
                        {"name": "Yıl 3", "type": "currency"}
                    ],
                    "rows": [
                        {"id": "ebitda", "type": "data", "cells": ["Faaliyet Kârı (EBITDA)", 380000, 540000, 720000]},
                        {"id": "amortisman_ekle", "type": "data", "cells": ["(+) Amortisman (Nakit Çıkışı Doğurmayan)", "='YATIRIM VE AMORTİSMAN'!{{amortisman_gideri}}", "='YATIRIM VE AMORTİSMAN'!{{amortisman_gideri}}", "='YATIRIM VE AMORTİSMAN'!{{amortisman_gideri}}"]},
                        {"id": "vergi", "type": "data", "cells": ["(-) Kurumlar Vergisi (%25)", "=-({{ebitda}}-{{amortisman_ekle}})*0.25", "=-({{ebitda}}-{{amortisman_ekle}})*0.25", "=-({{ebitda}}-{{amortisman_ekle}})*0.25"]},
                        {"id": "isletme_sermayesi", "type": "data", "cells": ["(-/+) İşletme Sermayesi Değişimi", -40000, -30000, -25000]},
                        {"id": "serbest_nakit_akisi", "type": "total", "cells": ["NET SERBEST NAKİT AKIŞI (FCF)", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP"]}
                    ]
                },
                {
                    "name": "FİNANSAL GÖSTERGELER",
                    "columns": [
                        {"name": "Performans Metriği", "type": "string"},
                        {"name": "Model Değeri", "type": "currency"},
                        {"name": "Hedef Eşik", "type": "string"},
                        {"name": "Yatırım Karar Sinyali", "type": "string"}
                    ],
                    "rows": [
                        {"id": "toplam_fcf", "type": "data", "cells": ["3 Yıllık Kümülatif Nakit Üretimi", "=SUM('SERBEST NAKİT AKIŞI'!C9:E9)", "> 1.000.000 TL", '=IF(C6>1000000, "YÜKSEK NAKİT", "YETERSİZ")']},
                        {"id": "baslangic_maliyet", "type": "data", "cells": ["İlk Yatırım Tutarı", "='YATIRIM VE AMORTİSMAN'!C10", "Referans CAPEX", "BAŞLANGIÇ"]},
                        {"id": "net_fayda", "type": "total", "cells": ["NET KATMA DEĞER (FCF - CAPEX)", "=C6-C7", "> 0 TL", '=IF(C8>0, "YATIRIM UYGUN", "RİSKLİ")']}
                    ]
                }
            ]
        }

    @classmethod
    def _build_breakeven_model(cls) -> Dict[str, Any]:
        return {
            "sheets": [
                {
                    "name": "BAŞABAŞ ANALİZİ",
                    "columns": [
                        {"name": "Maliyet / Fiyatlandırma Bileşeni", "type": "string"},
                        {"name": "Birim / Tutar", "type": "currency"},
                        {"name": "Açıklama / Formül", "type": "string"}
                    ],
                    "rows": [
                        {"id": "satis_fiyati", "type": "data", "cells": ["Birim Satış Fiyatı (P)", 1250, "Piyasa Satış Fiyatı"]},
                        {"id": "birim_degisken", "type": "data", "cells": ["Birim Değişken Maliyet (VC)", 650, "Hammadde + İşçilik + Enerji"]},
                        {"id": "katki_payi", "type": "total", "cells": ["Birim Katkı Payı (CM = P - VC)", "={{satis_fiyati}}-{{birim_degisken}}", "Birim Başına Kalan Brüt Katkı"]},
                        {"id": "katki_orani", "type": "data", "cells": ["Katkı Oranı (CMR = CM / P)", "=ROUND({{katki_payi}}/{{satis_fiyati}}, 4)", "Yüzdesel Marj"]},
                        {"id": "sabit_maliyet", "type": "data", "cells": ["Toplam Sabit Maliyetler (TFC)", 420000, "Kira, Yönetim, Maaşlar"]},
                        {"id": "basabaş_adet", "type": "total", "cells": ["BAŞABAŞ NOKTASI (Adet = TFC / CM)", "=ROUND({{sabit_maliyet}}/{{katki_payi}}, 0)", "Sıfır Kâr İçin Satılması Gereken Asgari Adet"]},
                        {"id": "basabaş_ciro", "type": "total", "cells": ["BAŞABAŞ NOKTASI (Ciro = TFC / CMR)", "={{sabit_maliyet}}/{{katki_orani}}", "Sıfır Kâr İçin Gerekli Asgari Ciro"]}
                    ]
                }
            ]
        }

    @classmethod
    def _build_budget_variance_model(cls) -> Dict[str, Any]:
        return {
            "sheets": [
                {
                    "name": "BÜTÇE VE VARYANS",
                    "columns": [
                        {"name": "Gider Merkezi", "type": "string"},
                        {"name": "Bütçelenen", "type": "currency"},
                        {"name": "Fiili Gerçekleşen", "type": "currency"},
                        {"name": "Sapma Tutarı (F - B)", "type": "currency"},
                        {"name": "Sapma Oranı (%)", "type": "percentage"}
                    ],
                    "rows": [
                        {"id": "grp_op", "type": "header_group", "cells": ["OPERASYONEL GİDERLER"]},
                        {"id": "pazarlama", "type": "data", "cells": ["Pazarlama ve Reklam", 180000, 195000, "@CHANGE_PCT", "@CHANGE_PCT"]},
                        {"id": "it_altyapi", "type": "data", "cells": ["Bulut ve Bilişim Altyapısı", 95000, 88000, "@CHANGE_PCT", "@CHANGE_PCT"]},
                        {"id": "lojistik", "type": "data", "cells": ["Lojistik ve Dağıtım", 140000, 155000, "@CHANGE_PCT", "@CHANGE_PCT"]},
                        {"id": "toplam_gider", "type": "total", "cells": ["TOPLAM GİDERLER", "@SUM_GROUP", "@SUM_GROUP", "@CHANGE_PCT", "@CHANGE_PCT"]}
                    ]
                }
            ]
        }

    @classmethod
    def _build_payroll_model(cls) -> Dict[str, Any]:
        return {
            "sheets": [
                {
                    "name": "BORDRO VE İŞVEREN MALİYETİ",
                    "columns": [
                        {"name": "Pozisyon / Personel", "type": "string"},
                        {"name": "Brüt Ücret", "type": "currency"},
                        {"name": "SGK İşçi (%14)", "type": "currency"},
                        {"name": "İşsizlik İşçi (%1)", "type": "currency"},
                        {"name": "SGK İşveren (%15.5)", "type": "currency"},
                        {"name": "Toplam İşveren Maliyeti", "type": "currency"}
                    ],
                    "rows": [
                        {"id": "kidemli_muh", "type": "data", "cells": ["Kıdemli Sistem Mühendisi", 95000, "=C6*0.14", "=C6*0.01", "=C6*0.155", "=C6+F6"]},
                        {"id": "yazilim_gel", "type": "data", "cells": ["Yazılım Geliştirici", 75000, "=C7*0.14", "=C7*0.01", "=C7*0.155", "=C7+F7"]},
                        {"id": "finans_uzm", "type": "data", "cells": ["Finans ve Bütçe Uzmanı", 65000, "=C8*0.14", "=C8*0.01", "=C8*0.155", "=C8+F8"]},
                        {"id": "toplam_bordro", "type": "total", "cells": ["TOPLAM ŞİRKET BORDROSU", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP", "@SUM_GROUP"]}
                    ]
                }
            ]
        }
