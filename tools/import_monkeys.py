"""Import standing/moving Lupin and Zombie Lupin templates from GMS 83.

Run from any directory: python tools/import_monkeys.py
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.import_curse_eye import download

MONKEYS = (
    ("hou_zi", "猴子", "Lupin", 3210800),
    ("jiang_shi_hou_zi", "无魂猴子／僵尸猴子", "Zombie Lupin", 4230101),
)


def main():
    for folder, name_cn, name, mob_id in MONKEYS:
        api = f"https://maplestory.io/api/GMS/83/mob/{mob_id}"
        metadata = json.loads(download(api))
        if metadata.get("id") != mob_id or metadata.get("name") != name:
            raise ValueError(f"Unexpected monster metadata for {name}")
        dest = ROOT / "monster" / folder
        dest.mkdir(parents=True, exist_ok=True)
        frames = []
        for action in ("stand", "move"):
            count = metadata["framebooks"][action]
            if not isinstance(count, int) or not 1 <= count <= 30:
                raise ValueError(f"Unexpected frame count: {action}={count!r}")
            for frame in range(count):
                url = f"{api}/render/{action}/{frame}"
                data = download(url)
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError(f"Not a PNG: {url}")
                filename = f"{action}_{frame}.png"
                (dest / filename).write_bytes(data)
                frames.append({"file": filename, "url": url,
                               "sha256": hashlib.sha256(data).hexdigest()})
                print(f"Downloaded {folder}/{filename}: {len(data)} bytes", flush=True)
        manifest = {"name_cn": name_cn, "name": name, "id": mob_id,
                    "region": "GMS", "version": "83",
                    "wiki": f"https://maplestory.wiki/GMS/83/mob/{mob_id}",
                    "api": api, "framebooks": metadata["framebooks"], "frames": frames}
        (dest / "source.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Imported {len(frames)} frames into {dest}", flush=True)


if __name__ == "__main__":
    main()
