from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vc_platform.classifier import classify_document


class TestVCClassifier(unittest.TestCase):
    def test_filename_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "사업자등록증_2026.pdf"
            path.write_bytes(b"dummy")
            doc_type, confidence = classify_document(path, include_ocr=False)
            self.assertEqual(doc_type, "business_registration")
            self.assertGreaterEqual(confidence, 0.55)

    def test_text_fallback_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("이번 달 세금계산서 발행 내역", encoding="utf-8")
            doc_type, confidence = classify_document(path, include_ocr=True)
            self.assertEqual(doc_type, "tax_invoice")
            self.assertGreater(confidence, 0.0)

    def test_unknown_without_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "random.bin"
            path.write_bytes(b"abc")
            doc_type, confidence = classify_document(path, include_ocr=False)
            self.assertEqual(doc_type, "unknown")
            self.assertEqual(confidence, 0.0)


if __name__ == "__main__":
    unittest.main()

