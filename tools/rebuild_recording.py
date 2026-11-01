"""Rebuild the offline viewer after a forced termination, without game capture/input."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.session_recorder import REPLAY_HTML
from src.utils.latency import recording_summary


def rebuild(directory):
    directory = Path(directory)
    events = []
    for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # Last JSONL line may have been interrupted mid-write.
        if isinstance(event, dict) and "id" in event and "event" in event:
            events.append(event)
    (directory / "replay.html").write_text(REPLAY_HTML, encoding="utf-8")
    (directory / "data.js").write_text(
        "window.RECORDING=" + json.dumps(events, ensure_ascii=False) + ";", encoding="utf-8")
    (directory / "latency_summary.json").write_text(
        json.dumps(recording_summary(events), ensure_ascii=False, indent=2), encoding="utf-8")
    return directory / "replay.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Recording session directory")
    print(rebuild(parser.parse_args().directory).resolve())
