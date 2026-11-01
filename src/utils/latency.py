"""High-resolution monotonic pipeline measurements and compact summaries.

Use perf_counter throughout capture, analysis and recording: on Windows the
ordinary monotonic clock can quantize short stages into ~16 ms steps.
"""
from collections import deque
import math
import time


def milliseconds(start, end=None):
    return round(max(0.0, (time.perf_counter() if end is None else end) - start) * 1000, 3)


def summarize(samples):
    columns = {}
    for sample in samples:
        for key, value in sample.items():
            if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
                columns.setdefault(key, []).append(value)
    result = {}
    for key, values in columns.items():
        values.sort()
        def percentile(p):
            pos = (len(values) - 1) * p
            low = int(pos)
            high = min(low + 1, len(values) - 1)
            return round(values[low] + (values[high] - values[low]) * (pos - low), 3)
        result[key] = {"count": len(values), "mean": round(sum(values) / len(values), 3),
                       "p50": percentile(.5), "p95": percentile(.95), "max": round(values[-1], 3)}
    return result


def recording_summary(events):
    samples = [e.get("timings_ms", {}) for e in events if e["event"] in ("decision", "frame_complete")]
    samples += [e.get("latency_ms", {}) for e in events if e["event"] in ("attack_output", "command_accepted")]
    return {"unit": "ms", "metrics": summarize(samples),
            "decisions": sum(e["event"] == "decision" for e in events),
            "attack_attempts": sum(e["event"] == "attack_output" for e in events),
            "note": "采集时间仅来自实时截屏；静态图片对应指标为空。发送完成不代表游戏已响应。"}


class LatencyMonitor:
    def __init__(self):
        self.samples = deque(maxlen=300)
        self.last_log = -math.inf
        self.latest = {}

    def observe(self, timings):
        self.latest = dict(timings)
        self.samples.append(self.latest)
        now = time.perf_counter()
        if now - self.last_log < 5:
            return None
        self.last_log = now
        stats = summarize(self.samples)
        parts = []
        for key, label in (("capture_ms", "capture"), ("frame_wait_ms", "frame_wait"),
                           ("get_frame_ms", "read"), ("identity_ms", "identity"),
                           ("monster_ms", "monster"), ("analysis_ms", "analysis"),
                           ("frame_to_decision_ms", "frame_to_decision")):
            if key in stats:
                s = stats[key]
                parts.append(f"{label}={s['p50']:.1f}/{s['p95']:.1f}/{s['max']:.1f}")
        return "[Latency] ms p50/p95/max " + " ".join(parts)
