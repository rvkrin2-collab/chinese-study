import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AndroidBundleTests(unittest.TestCase):
    def test_capacitor_uses_embedded_web_assets(self):
        config = json.loads((ROOT / "android-app" / "capacitor.config.json").read_text())
        self.assertEqual(config["webDir"], "www")
        self.assertNotIn("server", config)

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
            self.assertIn('src="curriculum-app.js?v=6.3"', html)
            self.assertNotIn("portal.netroman.ru", html)
            self.assertTrue((output / "ai-import.js").is_file())
            self.assertTrue((output / "curriculum-app.js").is_file())
            curriculum = json.loads((output / "curriculum" / "curriculum-v1.json").read_text())
            self.assertEqual(curriculum["version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()
