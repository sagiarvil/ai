
# ==============================================================================
# V3.5 YÜKSELTMESİ: DETERMINİSTİK MUHASEBE DENKLİK ÇÖZÜCÜSÜ & PARALEL DAG MOTORU
# ==============================================================================
import asyncio

def enforce_accounting_identity(sheet_obj: dict) -> dict:
    """
    14B modelin Bilanço üretiminde Aktif != Pasif aritmetik sapmasını
    Excel'e basmadan önce Python katmanında deterministik olarak dengeler.
    """
    name_upper = sheet_obj.get("name", "").replace("i", "İ").upper()
    if "BİLANÇO" not in name_upper and "BILANCO" not in name_upper:
        return sheet_obj

    rows = sheet_obj.get("rows", [])
    num_cols = len(sheet_obj.get("columns", []))
    if num_cols < 2 or not rows:
        return sheet_obj

    # Hangi satırların Aktif (1 ve 2 grubu), hangilerinin Pasif (3, 4, 5 grubu) olduğunu tespit et
    in_pasif = False
    aktif_indices = []
    pasif_indices = []
    sermaye_idx = None

    for idx, r in enumerate(rows):
        label = str(r.get("cells", [""])[0]).upper()
        rtype = r.get("type", "data")
        if any(k in label for k in ["PASİF", "YABANCI KAYNAK", "ÖZKAYNAK", "300", "320", "III."]):
            in_pasif = True
        if rtype == "data":
            if not in_pasif:
                aktif_indices.append(idx)
            else:
                pasif_indices.append(idx)
                if any(k in label for k in ["500", "SERMAYE", "540", "YEDEK"]):
                    sermaye_idx = idx

    if not aktif_indices or not pasif_indices:
        return sheet_obj

    if sermaye_idx is None:
        sermaye_idx = pasif_indices[-1]

    # Her para birimi sütunu için Aktif toplamı ile Pasif toplamını eşitle
    for col_i in range(1, num_cols):
        col_type = sheet_obj["columns"][col_i].get("type", "")
        if col_type != "currency":
            continue

        aktif_sum = sum(
            float(rows[i]["cells"][col_i])
            for i in aktif_indices
            if col_i < len(rows[i]["cells"]) and isinstance(rows[i]["cells"][col_i], (int, float))
        )
        pasif_sum = sum(
            float(rows[i]["cells"][col_i])
            for i in pasif_indices
            if col_i < len(rows[i]["cells"]) and isinstance(rows[i]["cells"][col_i], (int, float))
        )

        diff = round(aktif_sum - pasif_sum, 2)
        if abs(diff) > 0.01 and col_i < len(rows[sermaye_idx]["cells"]):
            curr_val = rows[sermaye_idx]["cells"][col_i]
            if isinstance(curr_val, (int, float)):
                rows[sermaye_idx]["cells"][col_i] = round(curr_val + diff, 2)

    return sheet_obj
