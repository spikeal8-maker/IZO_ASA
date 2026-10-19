"""Post-download failure cleanup with real extracted definitions and temporary SQLite."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from test_video_cancellation_fence import Harness

PRIVATE = "synthetic internal fault at /srv/private/provider-state.json"
PUBLIC = "Не удалось сохранить полученное видео."


class VideoResultCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="izo-video-result-cleanup-")
        self.addCleanup(self.temporary.cleanup)
        self.h = Harness(self.temporary.name)
        self.addCleanup(self.h.close)
        self.h.seed(provider="openrouter")
        self.h.release.set()
        self.h.state = {"status": "completed", "unsigned_urls": ["http://unused.invalid/cloud"]}

    def assert_retry_without_result(self, financial):
        current = self.h.row()
        settings = json.loads(current["settings_json"])
        self.assertEqual(current["status"], "pending")
        self.assertEqual(current["error_message"], PUBLIC)
        for key in ("localFile", "galleryVideoId", "finalizingAt", "finalizingToken"):
            self.assertNotIn(key, settings)
        self.assertEqual(list(Path(self.temporary.name).glob("*.mp4*")), [])
        self.assertEqual((self.h.ledger(), self.h.account()), financial)
        with self.h.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 0)

    async def test_bad_cloud_usage_cannot_accumulate_unique_claim_files_on_retry(self):
        self.h.state["usage"] = ["synthetic invalid usage"]
        financial = self.h.ledger(), self.h.account()
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                with self.assertRaises(AttributeError):
                    await self.h.runtime._refresh_video_job(self.h.row())
                self.assert_retry_without_result(financial)
        self.assertEqual(len(self.h.downloads), 2)
        self.assertEqual(len(set(self.h.downloads)), 2)

    async def test_postprocessing_failure_keeps_private_diagnostic_and_safe_public_retry(self):
        def fail(_snapshot, _cost):
            raise RuntimeError(PRIVATE)
        self.h.state["usage"] = {"cost": 1.25}
        self.h.runtime._refresh_video_job.__globals__["finalize_openrouter_billing_snapshot"] = fail
        financial = self.h.ledger(), self.h.account()
        with self.assertRaisesRegex(RuntimeError, "synthetic internal fault"):
            await self.h.runtime._refresh_video_job(self.h.row())
        self.assert_retry_without_result(financial)
        settings = json.loads(self.h.row()["settings_json"])
        self.assertEqual(settings["finalizingError"], PRIVATE)
        payload = self.h.runtime.get_persisted_job_response("video-owned", "owner")
        self.assertNotIn(PRIVATE, json.dumps(payload))
        self.assertEqual(payload["error"], PUBLIC)

    async def test_old_postprocessing_failure_cleans_only_loser_and_preserves_completed_winner(self):
        self.h.state["usage"] = ["synthetic invalid old usage"]
        self.h.download_release.clear()
        old = asyncio.create_task(self.h.runtime._refresh_video_job(self.h.row()))
        try:
            await asyncio.wait_for(self.h.download_entered.wait(), 1)
            row = self.h.row()
            settings = json.loads(row["settings_json"])
            settings["finalizingAt"] = "2020-01-01T00:00:00+00:00"
            with self.h.connect() as conn:
                conn.execute("UPDATE jobs SET settings_json=? WHERE id=?", (json.dumps(settings), row["id"]))
            self.h.state.pop("usage")
            winner = await self.h.runtime._refresh_video_job(self.h.row())
            self.assertEqual(winner["status"], "completed")
            winner_file = Path(self.temporary.name) / json.loads(winner["settings_json"])["localFile"]
            body, financial = winner_file.read_bytes(), (self.h.ledger(), self.h.account())
            self.h.download_release.set()
            with self.assertRaises(AttributeError):
                await asyncio.wait_for(old, 1)
            self.assertEqual(tuple(self.h.row()), tuple(winner))
            self.assertEqual(winner_file.read_bytes(), body)
            self.assertEqual(list(Path(self.temporary.name).glob("*.mp4")), [winner_file])
            self.assertNotEqual(*self.h.downloads)
            self.assertEqual((self.h.ledger(), self.h.account()), financial)
            with self.h.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 1)
            self.assertEqual(self.h.storage.download_filename(row["id"]), row["id"] + ".mp4")
        finally:
            self.h.download_release.set()
            if not old.done():
                old.cancel()
            await asyncio.gather(old, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
