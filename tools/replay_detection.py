"""Replay saved frames without capture or real keyboard input; compare JSON timings."""
import argparse
import copy
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.engine.MonsterDetector import MonsterDetector


class Decisions:
    def __init__(self):
        self.rows = []

    def elapsed_ms(self):
        return time.perf_counter() * 1000

    def decision(self, image, **data):
        self.rows.append(data)
        return len(self.rows)

    def event(self, *args, **kwargs):
        pass


def replay(directory, output):
    logging.disable(logging.CRITICAL)
    directory = directory.resolve()
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    frames = {e["decision_id"]: e["path"] for e in events if e["event"] == "frame_saved"}
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    config["disable_viz"] = True
    recorder = Decisions()
    detector = MonsterDetector(copy.deepcopy(config), recorder=recorder)
    assert detector.load_monster_images()
    detector._kb = Mock(is_enable=True, _had_focus=True)
    detector._detect_minimap = Mock(return_value=None)
    detector.is_show_debug = False
    import cv2
    for event in events:
        if event["event"] != "decision" or event["id"] not in frames:
            continue
        image = cv2.imread(str(directory / frames[event["id"]]))
        assert image is not None
        detector.get_img_frame = lambda: image
        detector.run_once()
        recorder.rows[-1]["original_id"] = event["id"]
    summary = {}
    for key in ("identity_ms", "monster_ms", "analysis_ms"):
        samples = [r["timings_ms"][key] for r in recorder.rows]
        summary[key] = {"mean": statistics.mean(samples), "median": statistics.median(samples), "max": max(samples)}
    result = {"recording": str(directory), "summary": summary, "decisions": recorder.rows}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                 default=lambda x: x.item()), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print("Decisions:", [(r["original_id"], r["command"], len(r["monsters"])) for r in recorder.rows])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    replay(args.directory, args.output)
