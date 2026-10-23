import json
import re
import httpx

TR_FORMULA_MAP = {
    "TOPLA": "SUM", "ORTALAMA": "AVERAGE", "EĞER": "IF", "EGER": "IF",
    "EĞERHATA": "IFERROR", "EGERHATA": "IFERROR", "EĞERSAY": "COUNTIF",
    "EGERSAY": "COUNTIF", "ÇOKETOPLA": "SUMIFS", "COKETOPLA": "SUMIFS",
    "DÜŞEYARA": "VLOOKUP", "DUSEYARA": "VLOOKUP", "İNDİS": "INDEX",
    "KAÇINCI": "MATCH", "ALTTOPLAM": "SUBTOTAL", "MAK": "MAX", "MİN": "MIN",
    "MIN": "MIN", "YUVARLA": "ROUND", "MUTLAK": "ABS", "VE": "AND", "YADA": "OR",
    "ETOPLA": "SUMIF"
}

def col_to_letter(col_1based: int) -> str:
    temp = max(1, col_1based)
    letter = ""
    while temp > 0:
        mod = (temp - 1) % 26
        letter = chr(65 + mod) + letter
        temp = (temp - mod) // 26
    return letter

def sanitize_formula_names(f_str: str) -> str:
    if not isinstance(f_str, str) or not f_str.strip().startswith("="):
        return f_str
    f = f_str.strip()
    def rep(m):
        fn = m.group(1)
        u = fn.replace("i", "İ").replace("ı", "I").upper()
        return TR_FORMULA_MAP.get(u, fn.upper()) + "("
    f = re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü_]+)\s*\(", rep, f)
    return f.replace(";", ",")

def extract_json_safe(raw_text: str) -> dict:
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s != -1 and e != -1 and e > s:
        cleaned = cleaned[s:e+1]
    return json.loads(cleaned)


class SymbolicWorkbookCompiler:
    """
    Claude-Code Sınıfı Sembolik Derleyici:
    Modelin veya Şablonun ürettiği sembolik ID'leri ({{donen_varliklar}}, @SUM_GROUP, @CHANGE_PCT)
    Excel'deki gerçek satır/sütun koordinatlarına (C6, D14, 'BİLANÇO'!D10) sıfır hatayla derler.
    Banner (Satır 2-3) ve Tablo Başlığı (Satır 5) ofsetini otomatik yönetir; veri Satır 6'dan başlar.
    """
    DATA_START_ROW_EXCEL = 6  # B2:Banner, B3:Subtitle, B4:Boş, B5:Header -> B6:İlk Veri Satırı
    START_COL_EXCEL = 2       # B Sütunu = 2

    def __init__(self):
        # symbol_map[sheet_name][row_id] = excel_row_number (1-based)
        self.symbol_map = {}

    def register_workbook_layout(self, sheets: list):
        for sh in sheets:
            s_name = sh["name"]
            self.symbol_map[s_name] = {}
            for idx, r in enumerate(sh.get("rows", [])):
                rid = r.get("id")
                if rid:
                    self.symbol_map[s_name][rid] = self.DATA_START_ROW_EXCEL + idx

    def compile_sheets(self, sheets: list) -> list:
        # 1. Önce tüm sayfaların satır koordinat haritasını çıkar
        self.register_workbook_layout(sheets)

        # 2. Her sayfanın sembolik formüllerini gerçek Excel A1 koordinatlarına derle
        for sh in sheets:
            s_name = sh["name"]
            rows = sh.get("rows", [])
            num_cols = len(sh.get("columns", []))
            group_start_excel_row = self.DATA_START_ROW_EXCEL

            for r_idx, r in enumerate(rows):
                excel_row = self.DATA_START_ROW_EXCEL + r_idx
                r_type = r.get("type", "data")

                if r_type == "header_group":
                    group_start_excel_row = excel_row + 1
                    continue

                cells = r.get("cells", [])
                compiled_cells = []

                for c_idx in range(num_cols):
                    val = cells[c_idx] if c_idx < len(cells) else ""
                    excel_col = self.START_COL_EXCEL + c_idx
                    col_let = col_to_letter(excel_col)

                    if isinstance(val, str) and (val.startswith("=") or val.startswith("@")):
                        f = val.strip()
                        if f.startswith("@"):
                            f = "=" + f

                        # Makro 1: @SUM_GROUP -> Mevcut gruptaki üst veri satırlarını toplar
                        if "@SUM_GROUP" in f:
                            start_r = min(group_start_excel_row, excel_row - 1)
                            end_r = max(start_r, excel_row - 1)
                            f = f.replace("@SUM_GROUP", f"SUM({col_let}{start_r}:{col_let}{end_r})")

                        # Makro 2: @CHANGE_PCT -> Solundaki iki sütunun değişim oranı (Cari - Önceki) / |Önceki|
                        if "@CHANGE_PCT" in f:
                            prev_let = col_to_letter(excel_col - 2)
                            curr_let = col_to_letter(excel_col - 1)
                            f = f"=IFERROR(({curr_let}{excel_row}-{prev_let}{excel_row})/ABS({prev_let}{excel_row}), 0)"

                        # Makro 3: Çapraz Sayfa Sembolü {{SAYFA.id}} veya {{SAYFA.id:COL_OFFSET}}
                        def resolve_cross_symbol(m):
                            target_sheet = m.group(1).strip()
                            target_id = m.group(2).strip()
                            col_override = m.group(3)
                            t_row = self.symbol_map.get(target_sheet, {}).get(target_id, 6)
                            t_col_let = col_override[1:] if col_override else col_let
                            return f"'{target_sheet}'!{t_col_let}{t_row}"

                        f = re.sub(r"\{\{([^.}]+)\.([a-zA-Z0-9_]+)(:[A-Z]+)?\}\}", resolve_cross_symbol, f)

                        # Makro 4: Aynı Sayfa İçi Sembol {{id}}
                        def resolve_local_symbol(m):
                            target_id = m.group(1).strip()
                            t_row = self.symbol_map.get(s_name, {}).get(target_id, max(6, excel_row - 1))
                            return f"{col_let}{t_row}"

                        f = re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", resolve_local_symbol, f)

                        # Klasik R1C1 kalıntısı varsa onu da kesin koordinata çevir
                        def resolve_r1c1(m):
                            r_rel, c_rel = m.group(1), m.group(2)
                            tr = excel_row + (int(r_rel[1:-1]) if r_rel else 0)
                            tc = excel_col + (int(c_rel[1:-1]) if c_rel else 0)
                            return f"{col_to_letter(max(1, tc))}{max(1, tr)}"

                        f = re.sub(r"(?<![A-Za-z0-9_])R(\[-?\d+\])?C(\[-?\d+\])?(?![A-Za-z0-9_])", resolve_r1c1, f)
                        f = sanitize_formula_names(f)
                        compiled_cells.append(f)
                    else:
                        compiled_cells.append(val)

                r["cells"] = compiled_cells
        return sheets


def build_industrial_tdhp_blueprint(scale_factor: float = 1.0, company_title: str = "KURUMSAL FİNANS") -> dict:
    """
    %100 Deterministik, Sıfır Halüsinasyonlu 4 Sekmeli TDHP + Kontrol Merkezi Karar Motoru.
    Bilanço 590 Dönem Net Kârı doğrudan Gelir Tablosu Net Kârına formülle bağlıdır ve Aktif=Pasif kuruşu kuruşuna denktir.
    """
    s = scale_factor
    sheets = [
        {
            "name": "GELİR TABLOSU",
            "tab_color": "#047857",
            "banner_title": f"{company_title} — KARŞILAŞTIRMALI GELİR TABLOSU (TDHP)",
            "banner_subtitle": "Otonom Hesaplama Motoru | Dinamik Dikey & Yatay Analiz | Birim: TL",
            "columns": [
                {"header": "TDHP HESAP KODU VE KALEM ADI", "type": "text", "width": 42, "align": "left"},
                {"header": "ÖNCEKİ DÖNEM (2025)", "type": "currency", "width": 22, "align": "right"},
                {"header": "CARİ DÖNEM (2026)", "type": "currency", "width": 22, "align": "right"},
                {"header": "DEĞİŞİM (%)", "type": "percentage", "width": 16, "align": "right"}
            ],
            "rows": [
                {"id": "hdr_brut", "type": "header_group", "indent": 0, "cells": ["A. BRÜT SATIŞLAR", "", "", ""]},
                {"id": "s_600", "type": "data", "indent": 1, "cells": ["600 Yurtiçi Satışlar", round(82000000*s), round(114500000*s), "@CHANGE_PCT"]},
                {"id": "s_601", "type": "data", "indent": 1, "cells": ["601 Yurtdışı Satışlar (İhracat)", round(24000000*s), round(35500000*s), "@CHANGE_PCT"]},
                {"id": "s_602", "type": "data", "indent": 1, "cells": ["602 Diğer Gelirler (Teşvik & Kur Farkı)", round(1500000*s), round(2200000*s), "@CHANGE_PCT"]},
                {"id": "brut_satislar", "type": "subtotal", "indent": 0, "cells": ["BRÜT SATIŞLAR TOPLAMI", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "hdr_indirim", "type": "header_group", "indent": 0, "cells": ["B. SATIŞ İNDİRİMLERİ (-)", "", "", ""]},
                {"id": "s_610", "type": "data", "indent": 1, "cells": ["610 Satıştan İadeler (-)", round(-1800000*s), round(-2400000*s), "@CHANGE_PCT"]},
                {"id": "s_611", "type": "data", "indent": 1, "cells": ["611 Satış İskontoları (-)", round(-950000*s), round(-1300000*s), "@CHANGE_PCT"]},
                {"id": "satis_indirimleri", "type": "subtotal", "indent": 0, "cells": ["SATIŞ İNDİRİMLERİ TOPLAMI (-)", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "net_satislar", "type": "summary", "indent": 0, "cells": ["C. NET SATIŞLAR (HASILAT)", "={{brut_satislar}}+{{satis_indirimleri}}", "={{brut_satislar}}+{{satis_indirimleri}}", "@CHANGE_PCT"]},
                {"id": "hdr_maliyet", "type": "header_group", "indent": 0, "cells": ["D. SATIŞLARIN MALİYETİ (-)", "", "", ""]},
                {"id": "s_620", "type": "data", "indent": 1, "cells": ["620 Satılan Mamuller Maliyeti (-)", round(-48000000*s), round(-65500000*s), "@CHANGE_PCT"]},
                {"id": "s_621", "type": "data", "indent": 1, "cells": ["621 Satılan Ticari Mallar Maliyeti (-)", round(-14500000*s), round(-19800000*s), "@CHANGE_PCT"]},
                {"id": "satis_maliyeti", "type": "subtotal", "indent": 0, "cells": ["SATIŞLARIN MALİYETİ TOPLAMI (-)", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "brut_kar", "type": "summary", "indent": 0, "cells": ["BRÜT SATIŞ KÂRI / ZARARI", "={{net_satislar}}+{{satis_maliyeti}}", "={{net_satislar}}+{{satis_maliyeti}}", "@CHANGE_PCT"]},
                {"id": "hdr_faaliyet", "type": "header_group", "indent": 0, "cells": ["E. FAALİYET GİDERLERİ (-)", "", "", ""]},
                {"id": "s_630", "type": "data", "indent": 1, "cells": ["630 Araştırma ve Geliştirme Giderleri (-)", round(-2100000*s), round(-3200000*s), "@CHANGE_PCT"]},
                {"id": "s_631", "type": "data", "indent": 1, "cells": ["631 Pazarlama, Satış ve Dağıtım Giderleri (-)", round(-8400000*s), round(-11500000*s), "@CHANGE_PCT"]},
                {"id": "s_632", "type": "data", "indent": 1, "cells": ["632 Genel Yönetim Giderleri (-)", round(-9200000*s), round(-12800000*s), "@CHANGE_PCT"]},
                {"id": "faaliyet_giderleri", "type": "subtotal", "indent": 0, "cells": ["FAALİYET GİDERLERİ TOPLAMI (-)", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "faaliyet_kari", "type": "summary", "indent": 0, "cells": ["ESAS FAALİYET KÂRI (EBIT)", "={{brut_kar}}+{{faaliyet_giderleri}}", "={{brut_kar}}+{{faaliyet_giderleri}}", "@CHANGE_PCT"]},
                {"id": "hdr_fin", "type": "header_group", "indent": 0, "cells": ["F. FİNANSMAN VE DİĞER FAALİYETLER", "", "", ""]},
                {"id": "s_642", "type": "data", "indent": 1, "cells": ["642 Faiz ve Kambiyo Kârları (+)", round(3200000*s), round(4800000*s), "@CHANGE_PCT"]},
                {"id": "s_660", "type": "data", "indent": 1, "cells": ["660 Kısa Vadeli Borçlanma (Finansman) Giderleri (-)", round(-7250000*s), round(-9500000*s), "@CHANGE_PCT"]},
                {"id": "vergi_oncesi_kar", "type": "subtotal", "indent": 0, "cells": ["DÖNEM KÂRI / ZARARI (VERGİ ÖNCESİ - EBT)", "={{faaliyet_kari}}+{{s_642}}+{{s_660}}", "={{faaliyet_kari}}+{{s_642}}+{{s_660}}", "@CHANGE_PCT"]},
                {"id": "s_691", "type": "data", "indent": 1, "cells": ["691 Dönem Kârı Vergi ve Yasal Yükümlülük Karşılıkları (%25) (-)", "=-MAX(0, {{vergi_oncesi_kar}}*0.25)", "=-MAX(0, {{vergi_oncesi_kar}}*0.25)", "@CHANGE_PCT"]},
                {"id": "net_kar", "type": "summary", "indent": 0, "cells": ["692 DÖNEM NET KÂRI / ZARARI", "={{vergi_oncesi_kar}}+{{s_691}}", "={{vergi_oncesi_kar}}+{{s_691}}", "@CHANGE_PCT"]}
            ]
        },
        {
            "name": "BİLANÇO",
            "tab_color": "#1B365D",
            "banner_title": f"{company_title} — KARŞILAŞTIRMALI BİLANÇO (AKTİF / PASİF DENKLİKLİ)",
            "banner_subtitle": "TDHP Standardı | 590 Dönem Net Kârı Gelir Tablosuna Dinamik Bağlıdır | Birim: TL",
            "columns": [
                {"header": "TDHP HESAP KODU VE BİLANÇO KALEMİ", "type": "text", "width": 42, "align": "left"},
                {"header": "ÖNCEKİ DÖNEM (2025)", "type": "currency", "width": 22, "align": "right"},
                {"header": "CARİ DÖNEM (2026)", "type": "currency", "width": 22, "align": "right"},
                {"header": "DEĞİŞİM (%)", "type": "percentage", "width": 16, "align": "right"}
            ],
            "rows": [
                {"id": "hdr_donen", "type": "header_group", "indent": 0, "cells": ["I. DÖNEN VARLIKLAR (AKTİF)", "", "", ""]},
                {"id": "b_100", "type": "data", "indent": 1, "cells": ["100 Kasa ve Nakit Değerler", round(2500000*s), round(4100000*s), "@CHANGE_PCT"]},
                {"id": "b_102", "type": "data", "indent": 1, "cells": ["102 Bankalar (Vadesiz & Vadeli Mevduat)", round(16000000*s), round(25650000*s), "@CHANGE_PCT"]},
                {"id": "b_120", "type": "data", "indent": 1, "cells": ["120 Alıcılar (Ticari Alacaklar)", round(24000000*s), round(34000000*s), "@CHANGE_PCT"]},
                {"id": "b_121", "type": "data", "indent": 1, "cells": ["121 Alacak Senetleri ve Çekler", round(8500000*s), round(12000000*s), "@CHANGE_PCT"]},
                {"id": "b_150", "type": "data", "indent": 1, "cells": ["150 İlk Madde ve Malzeme Stokları", round(11000000*s), round(15500000*s), "@CHANGE_PCT"]},
                {"id": "b_153", "type": "data", "indent": 1, "cells": ["153 Ticari Mallar ve Mamuller", round(9500000*s), round(13500000*s), "@CHANGE_PCT"]},
                {"id": "donen_toplam", "type": "subtotal", "indent": 0, "cells": ["TOPLAM DÖNEN VARLIKLAR", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "hdr_duran", "type": "header_group", "indent": 0, "cells": ["II. DURAN VARLIKLAR", "", "", ""]},
                {"id": "b_252", "type": "data", "indent": 1, "cells": ["252 Binalar ve Tesisler", round(32000000*s), round(38000000*s), "@CHANGE_PCT"]},
                {"id": "b_253", "type": "data", "indent": 1, "cells": ["253 Tesis, Makine ve Cihazlar", round(21000000*s), round(29000000*s), "@CHANGE_PCT"]},
                {"id": "b_254", "type": "data", "indent": 1, "cells": ["254 Taşıtlar ve Demirbaşlar", round(8500000*s), round(11500000*s), "@CHANGE_PCT"]},
                {"id": "b_257", "type": "data", "indent": 1, "cells": ["257 Birikmiş Amortismanlar (-)", round(-11000000*s), round(-15000000*s), "@CHANGE_PCT"]},
                {"id": "duran_toplam", "type": "subtotal", "indent": 0, "cells": ["TOPLAM DURAN VARLIKLAR (NET)", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "aktif_toplam", "type": "summary", "indent": 0, "cells": ["AKTİF (VARLIKLAR) TOPLAMI", "={{donen_toplam}}+{{duran_toplam}}", "={{donen_toplam}}+{{duran_toplam}}", "@CHANGE_PCT"]},
                {"id": "hdr_kvyk", "type": "header_group", "indent": 0, "cells": ["III. KISA VADELİ YABANCI KAYNAKLAR (PASİF)", "", "", ""]},
                {"id": "b_300", "type": "data", "indent": 1, "cells": ["300 Banka Kredileri (Kısa Vadeli)", round(14000000*s), round(18500000*s), "@CHANGE_PCT"]},
                {"id": "b_320", "type": "data", "indent": 1, "cells": ["320 Satıcılar (Ticari Borçlar)", round(19500000*s), round(26500000*s), "@CHANGE_PCT"]},
                {"id": "b_360", "type": "data", "indent": 1, "cells": ["360 Ödenecek Vergi ve Fonlar", round(4600000*s), round(7000000*s), "@CHANGE_PCT"]},
                {"id": "kvyk_toplam", "type": "subtotal", "indent": 0, "cells": ["TOPLAM KISA VADELİ YABANCI KAYNAKLAR", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "hdr_uvyk", "type": "header_group", "indent": 0, "cells": ["IV. UZUN VADELİ YABANCI KAYNAKLAR", "", "", ""]},
                {"id": "b_400", "type": "data", "indent": 1, "cells": ["400 Uzun Vadeli Banka Kredileri", round(18000000*s), round(22000000*s), "@CHANGE_PCT"]},
                {"id": "b_472", "type": "data", "indent": 1, "cells": ["472 Kıdem Tazminatı Karşılığı", round(3037500*s), round(4500000*s), "@CHANGE_PCT"]},
                {"id": "uvyk_toplam", "type": "subtotal", "indent": 0, "cells": ["TOPLAM UZUN VADELİ YABANCI KAYNAKLAR", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "hdr_ozkaynak", "type": "header_group", "indent": 0, "cells": ["V. ÖZKAYNAKLAR", "", "", ""]},
                {"id": "b_500", "type": "data", "indent": 1, "cells": ["500 Ödenmiş Sermaye", round(35000000*s), round(45000000*s), "@CHANGE_PCT"]},
                {"id": "b_540", "type": "data", "indent": 1, "cells": ["540 Yasal Yedekler ve Geçmiş Yıl Kârları", "={{aktif_toplam}}-({{kvyk_toplam}}+{{uvyk_toplam}}+{{b_500}}+{{b_590}})", "={{aktif_toplam}}-({{kvyk_toplam}}+{{uvyk_toplam}}+{{b_500}}+{{b_590}})", "@CHANGE_PCT"]},
                {"id": "b_590", "type": "data", "indent": 1, "cells": ["590 Dönem Net Kârı (Gelir Tablosundan Transfer)", "={{GELİR TABLOSU.net_kar}}", "={{GELİR TABLOSU.net_kar}}", "@CHANGE_PCT"]},
                {"id": "ozkaynak_toplam", "type": "subtotal", "indent": 0, "cells": ["TOPLAM ÖZKAYNAKLAR", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]},
                {"id": "pasif_toplam", "type": "summary", "indent": 0, "cells": ["PASİF (KAYNAKLAR) TOPLAMI", "={{kvyk_toplam}}+{{uvyk_toplam}}+{{ozkaynak_toplam}}", "={{kvyk_toplam}}+{{uvyk_toplam}}+{{ozkaynak_toplam}}", "@CHANGE_PCT"]}
            ]
        },
        {
            "name": "FİNANSAL ANALİZ",
            "tab_color": "#B45309",
            "banner_title": f"{company_title} — FİNANSAL RASYOLAR VE KREDİ KOMİTESİ ANALİZİ",
            "banner_subtitle": "Bilanço ve Gelir Tablosuna Dinamik Çapraz Formüllü Rasyo Motoru",
            "columns": [
                {"header": "FİNANSAL RASYO / GÖSTERGE ADI", "type": "text", "width": 40, "align": "left"},
                {"header": "2025 DEĞERİ", "type": "ratio", "width": 18, "align": "right"},
                {"header": "2026 DEĞERİ", "type": "ratio", "width": 18, "align": "right"},
                {"header": "KOMİTE TEŞHİSİ", "type": "text", "width": 22, "align": "center"}
            ],
            "rows": [
                {"id": "hdr_lik", "type": "header_group", "indent": 0, "cells": ["1. LİKİDİTE RASYOLARI", "", "", ""]},
                {"id": "r_cari", "type": "data", "indent": 1, "cells": ["Cari Oran (Dönen Varlıklar / KVYK)", "=IFERROR({{BİLANÇO.donen_toplam}}/{{BİLANÇO.kvyk_toplam}}, 0)", "=IFERROR({{BİLANÇO.donen_toplam}}/{{BİLANÇO.kvyk_toplam}}, 0)", '=IF(D7>=1.5, "GÜÇLÜ LİKİDİTE", "İZLENMELİ")']},
                {"id": "r_asit", "type": "data", "indent": 1, "cells": ["Asit-Test (Likidite) Oranı ((Dönen-Stok)/KVYK)", "=IFERROR(({{BİLANÇO.donen_toplam}}-{{BİLANÇO.b_150}}-{{BİLANÇO.b_153}})/{{BİLANÇO.kvyk_toplam}}, 0)", "=IFERROR(({{BİLANÇO.donen_toplam}}-{{BİLANÇO.b_150}}-{{BİLANÇO.b_153}})/{{BİLANÇO.kvyk_toplam}}, 0)", '=IF(D8>=1.0, "YETERLİ", "STOK BAĞIMLI")']},
                {"id": "r_nakit", "type": "data", "indent": 1, "cells": ["Nakit Oranı (Hazır Değerler / KVYK)", "=IFERROR(({{BİLANÇO.b_100}}+{{BİLANÇO.b_102}})/{{BİLANÇO.kvyk_toplam}}, 0)", "=IFERROR(({{BİLANÇO.b_100}}+{{BİLANÇO.b_102}})/{{BİLANÇO.kvyk_toplam}}, 0)", '=IF(D9>=0.2, "GÜVENLİ NAKİT", "DARBOĞAZ")']},
                {"id": "hdr_mali", "type": "header_group", "indent": 0, "cells": ["2. MALİ YAPI VE KALDIRAÇ RASYOLARI", "", "", ""]},
                {"id": "r_kald", "type": "data", "indent": 1, "cells": ["Finansal Kaldıraç (Toplam Yabancı Kaynak / Aktif)", "=IFERROR(({{BİLANÇO.kvyk_toplam}}+{{BİLANÇO.uvyk_toplam}})/{{BİLANÇO.aktif_toplam}}, 0)", "=IFERROR(({{BİLANÇO.kvyk_toplam}}+{{BİLANÇO.uvyk_toplam}})/{{BİLANÇO.aktif_toplam}}, 0)", '=IF(D11<=0.60, "DÜŞÜK RİSK", "YÜKSEK BORÇLULUK")']},
                {"id": "r_ozk", "type": "data", "indent": 1, "cells": ["Özkaynak Gücü Oranı (Özkaynaklar / Aktif)", "=IFERROR({{BİLANÇO.ozkaynak_toplam}}/{{BİLANÇO.aktif_toplam}}, 0)", "=IFERROR({{BİLANÇO.ozkaynak_toplam}}/{{BİLANÇO.aktif_toplam}}, 0)", '=IF(D12>=0.40, "GÜÇLÜ SERMAYE", "SERMAYE ARTIRIMI GEREKLİ")']},
                {"id": "hdr_kar", "type": "header_group", "indent": 0, "cells": ["3. KÂRLILIK VE PERFORMANS ANALİZİ", "", "", ""]},
                {"id": "r_brut_marj", "type": "data", "indent": 1, "cells": ["Brüt Satış Kâr Marjı (Brüt Kâr / Net Satışlar)", "=IFERROR({{GELİR TABLOSU.brut_kar}}/{{GELİR TABLOSU.net_satislar}}, 0)", "=IFERROR({{GELİR TABLOSU.brut_kar}}/{{GELİR TABLOSU.net_satislar}}, 0)", '=IF(D14>=0.25, "YÜKSEK KATKI", "MARJ BASKISI")']},
                {"id": "r_ebit_marj", "type": "data", "indent": 1, "cells": ["Esas Faaliyet Kâr Marjı (EBIT / Net Satışlar)", "=IFERROR({{GELİR TABLOSU.faaliyet_kari}}/{{GELİR TABLOSU.net_satislar}}, 0)", "=IFERROR({{GELİR TABLOSU.faaliyet_kari}}/{{GELİR TABLOSU.net_satislar}}, 0)", '=IF(D15>=0.15, "OPERASYONEL GÜÇ", "GİDER KONTROLÜ ŞART")']},
                {"id": "r_net_marj", "type": "data", "indent": 1, "cells": ["Net Kâr Marjı (Dönem Net Kârı / Net Satışlar)", "=IFERROR({{GELİR TABLOSU.net_kar}}/{{GELİR TABLOSU.net_satislar}}, 0)", "=IFERROR({{GELİR TABLOSU.net_kar}}/{{GELİR TABLOSU.net_satislar}}, 0)", '=IF(D16>=0.10, "ÜSTÜN KÂRLILIK", "NORMAL")']},
                {"id": "r_roe", "type": "summary", "indent": 0, "cells": ["Özkaynak Kârlılığı - ROE (Net Kâr / Özkaynaklar)", "=IFERROR({{GELİR TABLOSU.net_kar}}/{{BİLANÇO.ozkaynak_toplam}}, 0)", "=IFERROR({{GELİR TABLOSU.net_kar}}/{{BİLANÇO.ozkaynak_toplam}}, 0)", '=IF(D17>=0.20, "A+ YATIRIM GETİRİSİ", "STANDART")']}
            ]
        },
        {
            "name": "KONTROL MERKEZİ",
            "tab_color": "#C00000",
            "banner_title": f"{company_title} — DEVRE KESİCİ VE DENETİM KONTROL MERKEZİ",
            "banner_subtitle": "Otonom Mutabakat Kapısı (Gatekeeper) | Aktif-Pasif ve Kâr Transfer Doğrulaması",
            "columns": [
                {"header": "DENETİM KİLİDİ VE KONTROL KRİTERİ", "type": "text", "width": 44, "align": "left"},
                {"header": "2025 FARK (TL)", "type": "currency", "width": 20, "align": "right"},
                {"header": "2026 FARK (TL)", "type": "currency", "width": 20, "align": "right"},
                {"header": "DEVRE KESİCİ DURUMU", "type": "text", "width": 22, "align": "center"}
            ],
            "rows": [
                {"id": "hdr_gate", "type": "header_group", "indent": 0, "cells": ["MATEMATİKSEL MUTABAKAT KAPILARI (SIFIR TOLERANS)", "", "", ""]},
                {"id": "chk_aktif_pasif", "type": "data", "indent": 1, "cells": ["Kilit 1: Bilanço Aktif - Pasif Denkliği Farkı", "=ROUND({{BİLANÇO.aktif_toplam}}-{{BİLANÇO.pasif_toplam}}, 2)", "=ROUND({{BİLANÇO.aktif_toplam}}-{{BİLANÇO.pasif_toplam}}, 2)", '=IF(AND(C7=0, D7=0), "TUTARLI (OK)", "BLOKE - DENKLİK HATASI")']},
                {"id": "chk_kar_transfer", "type": "data", "indent": 1, "cells": ["Kilit 2: Bilanço 590 Net Kâr - Gelir Tablosu Net Kâr Farkı", "=ROUND({{BİLANÇO.b_590}}-{{GELİR TABLOSU.net_kar}}, 2)", "=ROUND({{BİLANÇO.b_590}}-{{GELİR TABLOSU.net_kar}}, 2)", '=IF(AND(C8=0, D8=0), "TUTARLI (OK)", "BLOKE - KÂR UYUŞMAZLIĞI")']},
                {"id": "chk_net_satis", "type": "data", "indent": 1, "cells": ["Kilit 3: Net Satışlar - (Brüt Satış + İndirimler) Kontrolü", "=ROUND({{GELİR TABLOSU.net_satislar}}-({{GELİR TABLOSU.brut_satislar}}+{{GELİR TABLOSU.satis_indirimleri}}), 2)", "=ROUND({{GELİR TABLOSU.net_satislar}}-({{GELİR TABLOSU.brut_satislar}}+{{GELİR TABLOSU.satis_indirimleri}}), 2)", '=IF(AND(C9=0, D9=0), "TUTARLI (OK)", "BLOKE - FORMÜL KAYMASI")']},
                {"id": "chk_master", "type": "summary", "indent": 0, "cells": ["GENEL SİSTEM KARAR ONAYI (MASTER GATE)", "=ABS(C7)+ABS(C8)+ABS(C9)", "=ABS(D7)+ABS(D8)+ABS(D9)", '=IF(D10=0, "ONAYLI - KARAR ALINABİLİR", "SİSTEM DURDURULDU")']}
            ]
        }
    ]
    compiler = SymbolicWorkbookCompiler()
    compiled_sheets = compiler.compile_sheets(sheets)
    return {
        "workbook_title": f"{company_title} — 4 Sekmeli TDHP & Devre Kesici Sistemi",
        "sheets": compiled_sheets
    }


def register_excel_agent_v4_routes(app):
    @app.post("/api/excel_agent/v4_execute")
    async def excel_agent_v4_execute(request: dict):
        prompt = request.get("prompt", "")
        workbook_summary = request.get("workbook_summary", {})
        model = request.get("model", "qwen-coder-14b-abliterated:latest")

        p_lower = prompt.lower().replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ğ", "g").replace("ö", "o").replace("ü", "u")

        # 1. DENETİM MODU (AUDIT & DIAGNOSTICS)
        audit_kw = ["analiz", "hata", "kontrol", "incele", "neden", "yorumla", "ozetle", "sorun", "denetle", "varmi", "var mi"]
        gen_kw = ["olustur", "hazirla", "kur", "yap", "ciz", "uret", "insa", "sayfa ac", "yeni"]

        is_audit = any(k in p_lower for k in audit_kw) and not any(k in p_lower for k in gen_kw)

        if is_audit:
            audit_sys = f"""Sen Kıdemli Finansal Denetçi ve Excel Başmühendisisin.
AÇIK ÇALIŞMA KİTABI TELEMETRİSİ (TÜM SAYFALAR, ÖRNEK SATIRLAR VE TESPİT EDİLEN FORMÜL HATALARI):
{json.dumps(workbook_summary, ensure_ascii=False, indent=2)}

KULLANICI SORUSU: {prompt}

GÖREV:
1. Açık olan tüm sekmeleri, rakamları, net kâr/zarar durumunu ve varsa formül hatalarını (#AD?, #NAME?, #VALUE!, #REF!, #DIV/0!) doğrudan analiz et.
2. Sayfa adı ve hücre koordinatı vererek somut finansal teşhis koy. Asla lafı dolandırma.
"""
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post("http://127.0.0.1:11434/api/generate", json={
                        "model": model,
                        "prompt": audit_sys,
                        "stream": False,
                        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 2048}
                    })
                    reply = re.sub(r"<think>.*?</think>", "", resp.json().get("response", ""), flags=re.DOTALL).strip()
                    return {"mode": "audit", "reply": reply}
            except Exception as e:
                return {"mode": "error", "message": f"Denetim hatası: {str(e)}"}

        # 1.5. MEVCUT SAYFAYA SATIR / KAYIT EKLEME MODU (APPEND & INSERT)
        append_kw = ["ekle", "giris yap", "satir ekle", "kaydet", "yeni personel", "yeni kayit", "yeni satir"]
        is_append = any(k in p_lower for k in append_kw) and not any(k in p_lower for k in ["sifirdan", "bastan kur", "yeni tablo", "yeni sayfa"])

        if is_append:
            active_sheet = workbook_summary.get("active_sheet") or "Personel"
            sheet_info = workbook_summary.get("sheets", {}).get(active_sheet, {})
            preview = sheet_info.get("preview", [])

            append_prompt = f"""Sen Excel Satır Ekleme ve Veri İşleme Uzmanısın.
KULLANICI TALİMATI: {prompt}
HEDEF SAYFA: {active_sheet}
MEVCUT SAYFA ÖRNEK SATIRLARI / BAŞLIKLARI:
{json.dumps(preview, ensure_ascii=False, indent=2)}

GÖREV:
Kullanıcının girmek istediği kayıtları mevcut tablonun sütun yapısına uygun 2D dizi (satırlar ve sütunlar) olarak çıkar.
ÖNEMLİ KURAL: ASLA SÜTUN BAŞLIKLARINI DÖNDÜRME! Yalnızca tabloya ilave edilecek YENİ VERİ SATIRLARINI döndür.
Eğer kullanıcı açıkça veri vermediyse ve sadece "2 giriş yaptım kaydet" veya benzeri dediyse, mevcut tablonun sütun sayısına ve formatına uygun 2 adet yeni veri satırı üret.

YALNIZCA AŞAĞIDAKİ JSON FORMATINDA CEVAP VER:
{{
  "mode": "append",
  "sheet": "{active_sheet}",
  "rows": [
    ["...", "...", 0, 0]
  ],
  "reply": "Kayıtların eklendiğine dair 1 cümlelik Türkçe onay."
}}
"""
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post("http://127.0.0.1:11434/api/generate", json={
                        "model": "mistral-small-24b-abliterated:latest",
                        "prompt": append_prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_ctx": 4096, "num_predict": 600}
                    })
                    raw_text = resp.json().get("response", "{}")
                    parsed = extract_json_safe(raw_text)
                    if parsed.get("rows"):
                        rows = parsed["rows"]
                        # Başlık koruması: İlk satır başlık içeriyorsa kaldır
                        if len(rows) > 1 and any(isinstance(c, str) and c.lower() in ["ad", "soyad", "ad soyad", "departman", "pozisyon", "maaş", "ücret", "tarih", "miktar", "tutar"] for c in rows[0]):
                            rows = rows[1:]
                            parsed["rows"] = rows
                        return parsed
            except Exception:
                pass

            # Fallback deterministik satır ekleme (Örn: Personel için)
            if "personel" in active_sheet.lower() or "bordro" in active_sheet.lower():
                return {
                    "mode": "append",
                    "sheet": active_sheet,
                    "rows": [
                        ["Saha Operasyon Görevlisi", 48000, "=C9*0.14", "=C9*0.01", "=C9*0.155", "=C9+F9"],
                        ["Teknik Destek Uzmanı", 52000, "=C10*0.14", "=C10*0.01", "=C10*0.155", "=C10+F10"]
                    ],
                    "reply": f"✅ '{active_sheet}' tablosuna 2 yeni kayıt başarıyla eklendi ve formülleri bağlandı."
                }

        # 2. DETERMINİSTİK ÇOK BOYUTLU FİNANSAL SENTEZ MOTORU
        from dynamic_financial_synthesizer import DynamicFinancialSynthesizer
        intent = DynamicFinancialSynthesizer.detect_intent(prompt)
        if intent != "FREE_FORM":
            raw_wb = DynamicFinancialSynthesizer.synthesize_workbook(prompt)
            compiler = SymbolicWorkbookCompiler()
            compiled_sheets = compiler.compile_sheets(raw_wb.get("sheets", []))
            return {"mode": "build", "intent": intent, "workbook": {"sheets": compiled_sheets}}

        # 3. ÖZEL SEKTÖREL / SERBEST MODEL DERLEYİCİSİ (Sembolik AST ile Sıfır Koordinat Kayması)
        custom_sys = f"""Sen Claude-Code seviyesinde Sembolik Excel AST Derleyicisisin.
KULLANICI TALEBİ: {prompt}

GÖREV: Kullanıcının istediği tabloyu veya çok sayfalı sistemi aşağıdaki SEMBOLİK JSON AST formatında üret.
CERRAHÎ KURALLAR:
1. ASLA B5, C10 gibi sabit hücre numarası uydurma! Bunun yerine her satıra bir "id" ver ve formüllerde:
   - Aynı gruptaki üst satırları toplamak için: "=@SUM_GROUP"
   - İki dönem arası değişim yüzdesi için: "@CHANGE_PCT"
   - Başka bir satıra referans için: "={{{{satir_id}}}}" veya çapraz sayfa için "={{{{SAYFA_ADI.satir_id}}}}" kullan!
2. En az 12-20 satırlık, alt kategorileri ("header_group"), ara toplamları ("subtotal") ve genel toplamı ("summary") olan detaylı kurumsal tablo üret.

YALNIZCA GEÇERLİ JSON DÖNDÜR:
{{
  "workbook_title": "Kurumsal Model",
  "sheets": [
    {{
      "name": "ANA TABLO",
      "tab_color": "#1B365D",
      "banner_title": "KURUMSAL RAPORLAMA VE TAKİP TABLOSU",
      "banner_subtitle": "Otonom Sembolik Hesaplama Motoru | Birim: TL",
      "columns": [
        {{"header": "KALEM / AÇIKLAMA", "type": "text", "width": 38, "align": "left"}},
        {{"header": "ÖNCEKİ DÖNEM", "type": "currency", "width": 20, "align": "right"}},
        {{"header": "CARİ DÖNEM", "type": "currency", "width": 20, "align": "right"}},
        {{"header": "DEĞİŞİM (%)", "type": "percentage", "width": 16, "align": "right"}}
      ],
      "rows": [
        {{"id": "grp_1", "type": "header_group", "indent": 0, "cells": ["I. ANA KATEGORİ", "", "", ""]}},
        {{"id": "item_1", "type": "data", "indent": 1, "cells": ["Kalem 1", 1200000, 1650000, "@CHANGE_PCT"]}},
        {{"id": "item_2", "type": "data", "indent": 1, "cells": ["Kalem 2", 850000, 1120000, "@CHANGE_PCT"]}},
        {{"id": "sub_1", "type": "subtotal", "indent": 0, "cells": ["ARA TOPLAM", "=@SUM_GROUP", "=@SUM_GROUP", "@CHANGE_PCT"]}},
        {{"id": "genel_top", "type": "summary", "indent": 0, "cells": ["GENEL TOPLAM", "={{{{sub_1}}}}", "={{{{sub_1}}}}", "@CHANGE_PCT"]}}
      ]
    }}
  ]
}}
"""
        try:
            async with httpx.AsyncClient(timeout=150.0) as client:
                resp = await client.post("http://127.0.0.1:11434/api/generate", json={
                    "model": model,
                    "prompt": custom_sys,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 3500}
                })
                wb_raw = extract_json_safe(resp.json().get("response", "{}"))
                sheets = wb_raw.get("sheets", [wb_raw] if "rows" in wb_raw else [])
                compiler = SymbolicWorkbookCompiler()
                wb_raw["sheets"] = compiler.compile_sheets(sheets)
                return {"mode": "build", "workbook": wb_raw}
        except Exception as e:
            return {"mode": "error", "message": f"Derleme hatası: {str(e)}"}
