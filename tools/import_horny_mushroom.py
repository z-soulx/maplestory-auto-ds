"""Import Horny Mushroom (刺蘑菇) templates from GMS 83.

Run from any directory: python tools/import_horny_mushroom.py
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.import_curse_eye import download

DEST = ROOT / "monster" / "ci_mo_gu"
API = "https://maplestory.io/api/GMS/83/mob/2110200"


def main():
    metadata = json.loads(download(API))
    if metadata.get("id") != 2110200 or metadata.get("name") != "Horny Mushroom":
        raise ValueError("Unexpected monster metadata; refusing to import")
    DEST.mkdir(parents=True, exist_ok=True)
    frames = []
    for action in ("stand", "move", "hit1"):
        count = metadata["framebooks"][action]
        if not isinstance(count, int) or not 1 <= count <= 30:
            raise ValueError(f"Unexpected frame count: {action}={count!r}")
        for frame in range(count):
            url = f"{API}/render/{action}/{frame}"
            data = download(url)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Not a PNG: {url}")
            filename = f"{action}_{frame}.png"
            (DEST / filename).write_bytes(data)
            frames.append({"file": filename, "url": url,
                           "sha256": hashlib.sha256(data).hexdigest()})
            print(f"Downloaded {filename}: {len(data)} bytes", flush=True)
    manifest = {"name_cn": "刺蘑菇", "name": metadata["name"],
                "id": 2110200, "region": "GMS", "version": "83",
                "wiki": "https://maplestory.wiki/GMS/83/mob/2110200",
                "api": API, "framebooks": metadata["framebooks"], "frames": frames}
    (DEST / "source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(frames)} frames into {DEST}")


if __name__ == "__main__":
    main()
