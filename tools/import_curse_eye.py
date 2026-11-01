"""Download the standing/moving Curse Eye sprites documented by README.

Run from any directory: python tools/import_curse_eye.py
Only public asset requests are sent; no game or account data is uploaded.
"""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "monster" / "feng_du_yan_shou"
API = "https://maplestory.io/api/GMS/83/mob/3230100"


def download(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(1)


def main():
    metadata = json.loads(download(API))
    if metadata.get("id") != 3230100 or metadata.get("name") != "Curse Eye":
        raise ValueError("Unexpected monster metadata; refusing to import")
    DEST.mkdir(parents=True, exist_ok=True)
    frames = []
    for action in ("stand", "move"):
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
    manifest = {"name_cn": "风独眼兽", "name": metadata["name"],
                "id": 3230100, "region": "GMS", "version": "83",
                "wiki": "https://maplestory.wiki/GMS/83/mob/3230100",
                "api": API, "framebooks": metadata["framebooks"], "frames": frames}
    (DEST / "source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(frames)} frames into {DEST}")


if __name__ == "__main__":
    main()
