"""Read-only acceptance diagnostics; never repairs or normalizes user files."""
import hashlib
import json
from pathlib import Path


def inspect_expected_files(root, expected_files):
    root = Path(root).resolve()
    if not expected_files or len(expected_files) > 100:
        return {"success": False, "error": "Geçerli kabul koşulu yok."}
    results = {}
    for name, expected in expected_files.items():
        try:
            target = (root / name).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Çalışma alanı dışında dosya.")
            if target.stat().st_size > 100_000:
                raise ValueError("Kabul kontrolü dosya sınırı 100 KB.")
            actual = target.read_bytes().decode("utf-8")
            matched = actual == expected
            offset = next((i for i, (a, b) in enumerate(zip(actual, expected))
                           if a != b), min(len(actual), len(expected)))
            results[name] = {
                "success": matched,
                "expected_json": json.dumps(expected, ensure_ascii=False)[:2400],
                "actual_json": json.dumps(actual, ensure_ascii=False)[:2400],
                "expected_length": len(expected),
                "actual_length": len(actual),
                "actual_sha256": hashlib.sha256(actual.encode("utf-8")).hexdigest(),
                "first_difference": None if matched else offset,
                "repair": None if matched else (
                    "Dosyayı expected_json içindeki metinle birebir yeniden yaz. "
                    "JSON tırnakları içeriğe dahil değil. Nokta, boşluk veya satır sonu ekleme."
                ),
            }
        except (OSError, ValueError, UnicodeError) as exc:
            results[name] = {
                "success": False, "error": str(exc),
                "expected_json": json.dumps(expected, ensure_ascii=False)[:2400],
            }
    return {"success": all(r["success"] for r in results.values()), "files": results}


class AcceptanceGuard:
    def __init__(self, limit=3):
        self.limit = limit
        self.counts = {}

    def observe(self, result):
        if result.get("success") is True:
            return
        fingerprint = json.dumps(result, sort_keys=True, ensure_ascii=False)
        self.counts[fingerprint] = self.counts.get(fingerprint, 0) + 1
        if self.counts[fingerprint] >= self.limit:
            raise RuntimeError(
                "Aynı kabul hatası 3 kez tekrarlandı; ilerleme olmadığı için durduruldu.")
