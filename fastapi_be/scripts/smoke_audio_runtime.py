"""Verify actual production audio decoders and the absence of network protocols."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True, help="Directory containing the six synthetic tone files")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from app.ai.audio_files import AUDIO_FORMATS, inspect_audio

    results = {}
    for extension in AUDIO_FORMATS:
        path = args.fixtures / ("tone" + extension)
        result = inspect_audio(path, extension)
        if not 400 <= result["duration_ms"] <= 800 or result["channels"] != 1:
            raise SystemExit(f"Unexpected synthetic audio metadata for {extension}")
        results[extension] = result
    version = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    expected = json.loads((ROOT / "ffmpeg-source.json").read_text())["version"]
    if not version.startswith("ffmpeg version " + expected + " "):
        raise SystemExit("FFmpeg version differs from the verified upstream source")
    raw = subprocess.check_output(["ffmpeg", "-hide_banner", "-protocols"], text=True)
    protocols = {line.strip() for line in raw.splitlines() if re.fullmatch(r"\s+[a-z][a-z0-9]+", line)}
    if protocols != {"file", "pipe"}:
        raise SystemExit(f"Unexpected compiled protocols: {sorted(protocols)}")
    print(json.dumps({"version": version, "protocols": sorted(protocols), "formats": results}, indent=2))


if __name__ == "__main__":
    main()
