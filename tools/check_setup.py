r"""Validate templates and optionally run a bounded live capture/detection check.

No keyboard controller/listener is started, and no game input is sent.
Run from the project root: .venv\Scripts\python.exe tools/check_setup.py --live
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from src.engine.MonsterDetector import MonsterDetector
from src.utils.common import load_yaml, override_cfg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cfg", default="feng_du_yan_shou")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--window_title", default="")
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error("--seconds must be between 0 and 60")
    # The project loads assets relative to the working directory.
    import os
    os.chdir(ROOT)
    cfg = override_cfg(load_yaml("config/config_default.yaml"),
                       load_yaml(f"config/config_{args.cfg}.yaml"))
    cfg["bot"].update(mode="detect", enable_route=False, warning=False)
    cfg["health_monitor"]["enable"] = False
    # Every diagnostic frame must describe its own detections, not cached boxes.
    cfg["monster_detect"]["detection_interval"] = 1
    if args.window_title:
        cfg["game_window"]["title"] = args.window_title
    detector = MonsterDetector(cfg)
    try:
        if not detector.load_monster_images():
            raise RuntimeError("Monster templates failed to load")
        validated = {}
        for name in detector.monsters_info:
            template_dir = ROOT / "monster" / name
            manifest_path = template_dir / "source.json"
            if not manifest_path.is_file():
                validated[name] = {"source_validation": "no_manifest"}
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for frame in manifest["frames"]:
                path = template_dir / frame["file"]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == frame["sha256"], path
                sprite = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                assert sprite is not None and sprite.ndim == 3 and sprite.shape[2] == 4, path
                assert np.any(sprite[:, :, 3] == 0) and np.any(sprite[:, :, 3] > 128), path
            validated[name] = {"templates": len(manifest["frames"]), "source_validation": "passed"}
        prefix = "curse_eye" if args.cfg == "feng_du_yan_shou" else args.cfg
        result = {"templates": sum(len(images) // 2 for images in detector.monsters_info.values()),
                  "monsters": validated, "template_validation": "passed",
                  "mode": "live" if args.live else "templates_only"}
        if args.live:
            detector.start_capture()
            deadline = time.monotonic() + args.seconds
            frames, max_count, lowest_score = 0, 0, 1.0
            while time.monotonic() < deadline:
                detector.run_once()
                if detector.img_frame is not None:
                    frames += 1
                    max_count = max(max_count, len(detector.monsters))
                    lowest_score = min(lowest_score, float(detector.best_score))
                time.sleep(0.1)
            if not frames:
                raise RuntimeError("No frames processed")
            out = ROOT / "screenshot"
            out.mkdir(exist_ok=True)
            cv2.imwrite(str(out / f"{prefix}_raw.png"), detector.img_frame)
            cv2.imwrite(str(out / f"{prefix}_detection.png"), detector.img_display)
            result.update(window=detector.capture.window_title, frames=frames,
                          frame_size=list(detector.img_frame.shape[:2][::-1]),
                          max_monsters=max_count, lowest_match_score=lowest_score,
                          player_position=list(detector.loc_player),
                          title_similarity=detector.title_sim,
                          last_monsters=[{"name": m["name"],
                                          "position": [int(v) for v in m["position"]],
                                          "score": float(m["score"])} for m in detector.monsters],
                          raw_image=str(out / f"{prefix}_raw.png"),
                          detection_image=str(out / f"{prefix}_detection.png"))
            (out / f"{prefix}_check.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        detector.cleanup()


if __name__ == "__main__":
    main()
