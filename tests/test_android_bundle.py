import base64
import gzip
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AndroidBundleTests(unittest.TestCase):
    def test_release_manifest_hashes_decoded_index(self):
        manifest = dict(
            line.split("=", 1)
            for line in (ROOT / "manifest.txt").read_text(encoding="utf-8").splitlines()
        )
        chunks = sorted((ROOT / "dist").glob("*.txt"))
        encoded = "".join(chunk.read_text(encoding="utf-8").strip() for chunk in chunks)
        index = gzip.decompress(base64.b64decode(encoded))
        self.assertEqual(int(manifest["chunks"]), len(chunks))
        self.assertEqual(manifest["sha256"], hashlib.sha256(index).hexdigest())

    def test_capacitor_uses_embedded_web_assets(self):
        config = json.loads((ROOT / "android-app" / "capacitor.config.json").read_text())
        self.assertEqual(config["webDir"], "www")
        self.assertNotIn("server", config)
        native_customizer = (ROOT / "android-app" / "customize_android.py").read_text()
        self.assertIn('addJavascriptInterface(new NativeSpeechBridge(), "NativeSpeech")', native_customizer)
        self.assertIn("TextToSpeech", native_customizer)

    def test_offline_bundle_contains_course_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            subprocess.run(
                ["python3", str(ROOT / "android-app" / "prepare_web.py"), "--output", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("window.CHINESE_STUDY_NATIVE = true", html)
            self.assertIn('src="curriculum-app.js?v=6.5"', html)
            self.assertNotIn("portal.netroman.ru", html)
            self.assertTrue((output / "ai-import.js").is_file())
            self.assertTrue((output / "curriculum-app.js").is_file())
            curriculum = json.loads((output / "curriculum" / "curriculum-v1.json").read_text())
            self.assertEqual(curriculum["version"], "1.2.0")


if __name__ == "__main__":
    unittest.main()
