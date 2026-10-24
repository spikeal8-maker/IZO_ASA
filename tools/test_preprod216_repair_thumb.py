"""Deterministic, synthetic private-thumbnail repair regressions."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprod216_repair_thumb import media_path, repair


class Preprod216ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self._owned_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._owned_temp.cleanup)
        root = Path(self._owned_temp.name)
        self.media = root / "media"
        self.media.mkdir()
        own = self.media / "private"
        own.mkdir()
        self.image = own / "available.webp"
        Image.new("RGB", (128, 128), (45, 72, 122)).save(self.image, "WEBP")
        self.database = root / "test.sqlite3"
        with sqlite3.connect(self.database) as db:
            db.execute(
                """CREATE TABLE images (
                   id TEXT PRIMARY KEY, user_id TEXT, thumbnail_url TEXT,
                   deleted_at TEXT)"""
            )
            db.execute(
                """CREATE TABLE image_sources (
                   image_id TEXT, user_id TEXT, thumb_url TEXT,
                   thumb_width INTEGER, thumb_height INTEGER,
                   library_deleted_at TEXT)"""
            )
            db.execute(
                """INSERT INTO images VALUES
                   ('qa-test-image', 'qa-test-user',
                    '/api/media/private/available.webp?userId=qa-test-user', NULL)"""
            )
            db.execute(
                """INSERT INTO image_sources VALUES
                   ('qa-test-image', 'qa-test-user',
                    '/api/media/private/missing.webp?userId=qa-test-user', 64, 64, NULL)"""
            )
        self.target = own / "missing.webp"

    def test_dry_run_performs_no_mutation(self):
        result = repair(self.database, self.media, False)
        self.assertEqual(result["expected_missing"], 1)
        self.assertEqual(result["target_size"], [64, 64])
        self.assertFalse(result["applied"])
        self.assertFalse(self.target.exists())

    def test_atomic_repair_and_existing_file_fail_closed(self):
        before = sha256(self.image.read_bytes()).hexdigest()
        result = repair(self.database, self.media, True)
        self.assertTrue(result["applied"])
        self.assertTrue(self.target.is_file())
        self.assertEqual(result["sha256"], sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(before, sha256(self.image.read_bytes()).hexdigest())
        with Image.open(self.target) as image:
            self.assertEqual(image.size, (64, 64))
        with self.assertRaisesRegex(RuntimeError, "EXPECTED_ONE_MISSING"):
            repair(self.database, self.media, True)

    def test_local_private_receipt_is_valid_json_and_not_overwritten(self):
        import json
        receipt = Path(self._owned_temp.name) / "thumb-repair.json"
        outcome = repair(self.database, self.media, True, receipt)
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertTrue(saved["derived_from_existing_same_owner_thumbnail"])
        self.assertEqual(saved["sha256"], outcome["sha256"])
        self.assertEqual(saved["relative_media_path"], "private/missing.webp")
        self.assertEqual(saved["target_size"], [64, 64])
        self.assertTrue(receipt.is_file())

    def test_other_user_source_and_original_not_modified(self):
        with sqlite3.connect(self.database) as db:
            db.execute(
                "UPDATE image_sources SET user_id='qa-foreign-user'"
            )
        with self.assertRaisesRegex(RuntimeError, "EXPECTED_ONE_MISSING_THUMBNAIL|UNSAFE_THUMBNAIL_OWNERSHIP"):
            repair(self.database, self.media, True)
        self.assertFalse(self.target.exists())

    def test_private_query_requires_matching_owner(self):
        good = "/api/media/private/available.webp?userId=qa-test-user"
        self.assertEqual(
            media_path(self.media, good, owner="qa-test-user"), self.image
        )
        self.assertIsNone(media_path(self.media, good))
        self.assertIsNone(media_path(self.media, good, owner="qa-foreign-user"))
        self.assertIsNone(media_path(
            self.media, good + "&userId=qa-test-user", owner="qa-test-user"
        ))
        self.assertIsNone(media_path(
            self.media, "/api/media/private/available.webp?token=not-authorized",
            owner="qa-test-user"
        ))

    def test_encoded_traversal_and_external_media_url_denied(self):
        forbidden = [
            "/api/media/%2e%2e/secret.webp",
            "/api/media/private/%252e%252e/secret.webp",
            "/api/media/private/../../secret.webp",
            "http://attacker.invalid/api/media/private/pic.webp",
            "/api/media/private/file.webp?token=abc",
            "/api/media/private\\escape.webp",
        ]
        for value in forbidden:
            with self.subTest(value=value):
                self.assertIsNone(media_path(self.media, value))


if __name__ == "__main__":
    unittest.main()
