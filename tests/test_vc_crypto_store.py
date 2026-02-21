from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vc_platform.crypto_store import AESGCM, VCCryptoStore


@unittest.skipIf(AESGCM is None, "cryptography is not installed")
class TestVCCryptoStore(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VCCryptoStore(Path(tmp) / "vc_keys.json")
            plaintext = b"hello vc"
            envelope = store.encrypt_for_startup("acme", plaintext, aad=b"col-1")
            recovered = store.decrypt_for_startup("acme", envelope, aad=b"col-1")
            self.assertEqual(recovered, plaintext)

    def test_cross_tenant_key_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VCCryptoStore(Path(tmp) / "vc_keys.json")
            envelope = store.encrypt_for_startup("acme", b"secret")
            with self.assertRaises(Exception):
                store.decrypt_for_startup("other", envelope)

    def test_rotate_key_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VCCryptoStore(Path(tmp) / "vc_keys.json")
            first = store.rotate_key("acme")
            second = store.rotate_key("acme")
            self.assertGreater(second["version"], first["version"])


if __name__ == "__main__":
    unittest.main()

