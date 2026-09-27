import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chinese_server", ROOT / "server.py")
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(SERVER)


class StateCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        SERVER.STATE_FILE = Path(self.tmp.name) / "state.json"
        SERVER.LIBRARY_FILE = Path(self.tmp.name) / "library.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_state_roundtrip_with_curriculum(self):
        incoming = {
            "customWords": [{"id": "old-word", "h": "测试"}],
            "customTopics": [{"id": "old-topic", "wordIds": ["old-word"]}],
            "materials": [{"id": "old-material", "wordIds": ["old-word"]}],
            "history": [{"ts": 1, "id": "old-word", "ok": True}],
            "words": {"old-word": {"seen": 2, "due": 3}},
            "curriculum": {
                "schemaVersion": 1,
                "startLevel": 3,
                "completed": {"h3-u1-l1": 10},
                "grammarSrs": {"h3-g01": {"reps": 1, "due": 20}},
                "updatedAt": 10,
            },
        }
        saved = SERVER.write_sync_state(incoming, 0)
        self.assertEqual(saved["rev"], 1)
        loaded = SERVER.read_sync_state()["state"]
        self.assertEqual(loaded["customWords"][0]["id"], "old-word")
        self.assertEqual(loaded["customTopics"][0]["id"], "old-topic")
        self.assertEqual(loaded["materials"][0]["id"], "old-material")
        self.assertEqual(loaded["history"][0]["id"], "old-word")
        self.assertEqual(loaded["curriculum"]["startLevel"], 3)
        self.assertIn("h3-u1-l1", loaded["curriculum"]["completed"])

    def test_library_merge_keeps_existing_materials(self):
        first = SERVER.merge_library({
            "materials": [{"id": "m1", "title": "Первый"}],
            "customWords": [{"id": "w1", "h": "一"}],
            "customTopics": [{"id": "t1", "title": "Тема"}],
        })
        second = SERVER.merge_library({
            "materials": [{"id": "m2", "title": "Второй"}],
            "customWords": [], "customTopics": [],
        })
        self.assertEqual({x["id"] for x in second["materials"]}, {"m1", "m2"})
        self.assertEqual(first["customWords"][0]["id"], "w1")
        self.assertEqual(second["customWords"][0]["id"], "w1")

    def test_old_updater_bootstraps_new_curriculum_assets(self):
        old_app = SERVER.APP
        old_sha = SERVER.RELEASE_ASSET_SHA256["curriculum-app.js"]
        SERVER.APP = Path(self.tmp.name) / "app"
        payload = b"window.CHINESE_CURRICULUM = {}; // no secret here\n"
        SERVER.RELEASE_ASSET_SHA256["curriculum-app.js"] = hashlib.sha256(payload).hexdigest()
        stale = SERVER.APP / "curriculum-app.js"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale curriculum client" * 20)

        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()

        try:
            with patch.object(SERVER.urllib.request, "urlopen", return_value=Response(payload)):
                target = SERVER.ensure_release_asset("/curriculum-app.js")
            self.assertIsNotNone(target)
            self.assertEqual(target.read_bytes(), payload)
            with patch.object(SERVER.urllib.request, "urlopen", side_effect=AssertionError("fresh asset must not be downloaded again")):
                self.assertEqual(SERVER.ensure_release_asset("/curriculum-app.js"), target)
        finally:
            SERVER.APP = old_app
            SERVER.RELEASE_ASSET_SHA256["curriculum-app.js"] = old_sha


if __name__ == "__main__":
    unittest.main()
