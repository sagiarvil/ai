import tempfile
import unittest
from pathlib import Path
from acceptance_checks import inspect_expected_files, AcceptanceGuard


class AcceptanceTests(unittest.TestCase):
    def test_exact_content_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "x").write_bytes("Merhaba Barış".encode())
            self.assertTrue(inspect_expected_files(
                directory, {"x": "Merhaba Barış"})["success"])

    def test_period_and_newline_are_visible_and_not_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "x"
            target.write_bytes("Merhaba Barış.\n".encode())
            result = inspect_expected_files(directory, {"x": "Merhaba Barış"})
            self.assertFalse(result["success"])
            self.assertEqual(result["files"]["x"]["first_difference"], len("Merhaba Barış"))
            self.assertEqual(result["files"]["x"]["actual_length"], len("Merhaba Barış.\n"))
            self.assertIn("\\n", result["files"]["x"]["actual_json"])
            self.assertEqual(target.read_bytes(), "Merhaba Barış.\n".encode())

    def test_missing_file_reports_expected_text(self):
        with tempfile.TemporaryDirectory() as directory:
            result = inspect_expected_files(directory, {"x": "abc"})
            self.assertFalse(result["success"])
            self.assertEqual(result["files"]["x"]["expected_json"], '"abc"')

    def test_outside_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = inspect_expected_files(directory, {"../outside": "x"})
            self.assertFalse(result["success"])
            self.assertIn("Çalışma alanı", result["files"]["../outside"]["error"])

    def test_crlf_is_not_silently_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "x").write_bytes(b"x\r\n")
            self.assertFalse(inspect_expected_files(directory, {"x": "x\n"})["success"])

    def test_repeated_mismatch_stops(self):
        guard = AcceptanceGuard()
        result = {"success": False, "files": {"x": {"actual_json": '"abc."'}}}
        guard.observe(result)
        guard.observe(result)
        with self.assertRaises(RuntimeError):
            guard.observe(result)

    def test_different_actual_content_is_not_same_failure(self):
        guard = AcceptanceGuard()
        for text in ("a", "ab", "abc"):
            guard.observe({"success": False, "actual": text})
        guard.observe({"success": True})


if __name__ == "__main__":
    unittest.main()
