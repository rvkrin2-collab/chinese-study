#!/usr/bin/env python3
"""Build the self-contained web bundle embedded in the Android application."""

import argparse
import base64
import gzip
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_TAGS = """<script>window.CHINESE_STUDY_NATIVE = true;</script>
<script src="ai-import.js?v=6.3"></script>
<script src="curriculum-app.js?v=6.3"></script>
"""


def build(output: Path) -> None:
    chunks = sorted((ROOT / "dist").glob("*.txt"))
    if not chunks:
        raise SystemExit("No encoded web client chunks found in dist/")
    encoded = "".join(chunk.read_text(encoding="utf-8").strip() for chunk in chunks)
    html = gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
    if "</body>" not in html:
        raise SystemExit("Decoded web client has no closing body tag")
    html = html.replace("</body>", SCRIPT_TAGS + "</body>")

    output.mkdir(parents=True, exist_ok=True)
    (output / "curriculum").mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(html, encoding="utf-8")
    shutil.copy2(ROOT / "ai-import.js", output / "ai-import.js")
    shutil.copy2(ROOT / "curriculum-app.js", output / "curriculum-app.js")
    shutil.copy2(
        ROOT / "curriculum" / "curriculum-v1.json",
        output / "curriculum" / "curriculum-v1.json",
    )
    print(f"Prepared offline Android web bundle in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "www",
        help="Destination directory (defaults to android-app/www)",
    )
    build(parser.parse_args().output.resolve())
