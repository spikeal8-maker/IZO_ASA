"""Actual durable response mapping; no ASGI or provider execution is claimed."""
from __future__ import annotations

import json
import sqlite3
import unittest

from test_local_video_boundaries import CANARY, DIAGNOSTICS, definitions


class LocalVideoJobHistory(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, user_id TEXT, mode TEXT, provider TEXT,
                status TEXT, progress INTEGER, prompt_original TEXT, settings_json TEXT,
                created_at TEXT, completed_at TEXT, error_message TEXT, result_image_id TEXT);
            CREATE TABLE images (id TEXT PRIMARY KEY, user_id TEXT, job_id TEXT, url TEXT,
                thumbnail_url TEXT, width INTEGER, height INTEGER, settings_json TEXT,
                deleted_at TEXT, created_at TEXT);
            INSERT INTO jobs VALUES ('owned-video','owner','text_to_video','local_ltx',
                'failed',100,'Owned abstract scene','{"tokenCost":1}',
                '2026-01-01T00:00:00Z','2026-01-01T00:00:01Z',NULL,NULL);
        """)
        presentation = definitions("app/services/video_presentation.py")
        self.public_video_error = presentation.public_video_error_message
        self.jobs = definitions("app/services/generation_jobs.py", include={
            "PUBLIC_SERVER_ERROR", "_PRIVATE_ERROR_DETAILS", "public_generation_error_message",
            "_row_get", "_safe_json_load", "job_response_from_row", "get_persisted_job_response",
        }, bindings={"public_video_error_message": self.public_video_error})

    def get(self, job_id="owned-video", owner="owner"):
        return self.jobs.get_persisted_job_response(self.conn, job_id, owner, model_display_name=str)

    def test_historical_local_errors_are_private_in_legacy_detail_and_read_only(self):
        for diagnostic in DIAGNOSTICS:
            with self.subTest(diagnostic=diagnostic):
                self.conn.execute("UPDATE jobs SET error_message=?", (diagnostic,))
                writes = self.conn.total_changes
                response = self.get()
                self.assertIsNone(self.get(owner="foreign"))
                self.assertEqual(self.conn.total_changes, writes)
                self.assertEqual(response["id"], "owned-video")
                self.assertEqual(response["error"], self.public_video_error(diagnostic, provider="local_ltx"))
                self.assertEqual(response["message"], response["error"])
                encoded = json.dumps(response)
                for private in (CANARY, "ltx.invalid", "fixture-token"):
                    self.assertNotIn(private, encoded)

    def test_known_local_error_and_empty_queued_status_remain_useful(self):
        safe = "Не удалось сохранить полученное видео."
        self.conn.execute("UPDATE jobs SET error_message=?", (safe,))
        self.assertEqual(self.get()["error"], safe)
        self.conn.execute("UPDATE jobs SET error_message=NULL,status='queued',progress=10")
        response = self.get()
        self.assertNotIn("error", response)
        self.assertEqual(response["message"], "queued")
        self.assertEqual(response["tokenCost"], 1)

    def test_normal_image_payload_and_sanitizer_contract_are_unchanged(self):
        safe = "Проверьте размеры изображения."
        self.conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            "owned-image", "owner", "t2i", "comfyui", "failed", 100, "Owned still life",
            json.dumps({"tokenCost": 3}), "2026-01-01T00:00:00Z", None, safe, "result-image"))
        self.conn.execute("INSERT INTO images VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "result-image", "owner", "owned-image", "/api/media/image.png", "/api/media/thumb.png",
            512, 768, json.dumps({"modelProfile": "fixture-image", "generationTimeMs": 9}), None,
            "2026-01-01T00:00:00Z"))
        response = self.get("owned-image")
        expected = {"mode": "t2i", "provider": "comfyui", "status": "failed", "message": safe,
            "error": safe, "width": 512, "height": 768, "resultImageId": "result-image",
            "resultUrl": "/api/media/image.png", "thumbnailUrl": "/api/media/thumb.png",
            "modelProfile": "fixture-image", "generationTimeMs": 9, "tokenCost": 3}
        self.assertEqual({key: response[key] for key in expected}, expected)
        self.conn.execute("UPDATE jobs SET error_message=? WHERE id='owned-image'", ("ComfyUI endpoint refused",))
        self.assertEqual(self.get("owned-image")["error"], self.jobs.PUBLIC_SERVER_ERROR)
        self.assertIsNone(self.get("owned-image", "foreign"))


if __name__ == "__main__":
    unittest.main()
