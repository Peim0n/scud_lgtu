"""Тесты кодера/декодера QR-кодов."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scud_lgtu.qr_encoder import encode_qr, build_payload
from scud_lgtu.qr_decoder import QRDecoder


KEY_DIR = os.path.join(os.path.dirname(__file__), "..", "key")


class TestQREncoder(unittest.TestCase):
    """Базовые проверки генерации и декодирования QR."""

    def test_build_payload(self):
        """Payload собирается корректно."""
        payload = build_payload(timestamp=1752510000, max_id=12345)
        # size=6, type=0, uint32 timestamp; size=10, type=1, int64 max_id
        self.assertEqual(payload[0], 6)
        self.assertEqual(payload[1], 0)
        self.assertEqual(payload[6], 10)
        self.assertEqual(payload[7], 1)

    def test_encode_decode(self):
        """Сгенерированный QR корректно декодируется."""
        key_id = 167
        timestamp = 1752510000
        max_id = 12345

        private_path = os.path.join(KEY_DIR, f"private_key.{key_id}")
        shared_path = os.path.join(KEY_DIR, f"shared_key.{key_id}")
        if not os.path.exists(private_path) or not os.path.exists(shared_path):
            self.skipTest("Keys not found")

        with open(private_path, "rb") as f:
            private_key_pem = f.read()
        with open(shared_path, "rb") as f:
            shared_key_raw = f.read()

        url = encode_qr(key_id, timestamp, max_id, private_key_pem, shared_key_raw)
        self.assertTrue(url.startswith("https://pass.lipetsk.ru/?"))

        decoder = QRDecoder(KEY_DIR)
        result = decoder.decode_url(url)
        self.assertEqual(result["timestamp"], timestamp)
        self.assertEqual(result["max_id"], max_id)


if __name__ == "__main__":
    unittest.main()
