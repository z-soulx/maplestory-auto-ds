"""Bounded diagnostic sessions: raw frames, correlated events and offline replay."""
import json
import math
import os
import hashlib
import sys
from pathlib import Path
import queue
import threading
import time
from datetime import datetime
from uuid import uuid4

import cv2

from src.utils.logger import logger
from src.utils.latency import recording_summary


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


class SessionRecorder:
    """Frame compression runs off the detection thread; event IDs join inputs to decisions."""

    @classmethod
    def from_config(cls, cfg):
        if not cfg.get("recording", {}).get("enable", False):
            return None
        try:
            return cls(cfg)
        except Exception as exc:
            logger.error(f"[Recording] 无法开始录制：{exc}；检测继续运行。")
            return None

    def __init__(self, cfg):
        options = cfg.get("recording", {})
        self.max_seconds = float(options.get("max_seconds", 600))
        self.max_bytes = int(float(options.get("max_mb", 512)) * 1024 * 1024)
        self.fps = float(options.get("fps", 5))
        if not (math.isfinite(self.max_seconds) and self.max_seconds > 0
                and self.max_bytes >= 1024 * 1024 and math.isfinite(self.fps) and 0 < self.fps <= 30):
            raise ValueError("录制时长、容量和采样帧率无效")
        name = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}_{uuid4().hex[:6]}"
        self.directory = Path(options.get("directory", "recordings")) / name
        self.directory.mkdir(parents=True)
        (self.directory / "frames").mkdir()
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=8)
        self._start = time.perf_counter()
        self._last_frame = -math.inf
        self._events = []
        self._reserved = 65536  # Replay page, latency summary and final event.
        self._closed = False
        self.active = True
        self.stop_reason = None
        self._stream = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        try:
            config_text = json.dumps(_plain(cfg), ensure_ascii=False, indent=2, allow_nan=False)
            (self.directory / "config.json").write_text(config_text, encoding="utf-8")
            self._reserved += len(config_text.encode("utf-8"))
            (self.directory / "replay.html").write_text(REPLAY_HTML, encoding="utf-8")
            self.event("session_start", pid=os.getpid(), schema_version=2,
                       frame_fps_limit=self.fps, max_seconds=self.max_seconds,
                       max_mb=self.max_bytes / 1024 / 1024,
                       executable=sys.executable, argv=sys.argv,
                       source_sha256=self._source_hashes())
            self._thread = threading.Thread(target=self._write_frames, name="session-recorder", daemon=True)
            self._thread.start()
        except Exception:
            self._stream.close()
            raise
        logger.info(f"[Recording] 录制目录：{self.directory.resolve()}；停止后打开 replay.html 回放。")

    def elapsed_ms(self):
        return round((time.perf_counter() - self._start) * 1000, 3)

    @staticmethod
    def _source_hashes():
        root = Path(__file__).resolve().parents[2]
        paths = ("src/main.py", "src/engine/MonsterDetector.py", "src/input/KeyBoardController.py",
                 "src/utils/player_identity.py", "src/utils/session_recorder.py")
        paths += ("src/input/GameWindowCapturor.py", "src/utils/latency.py")
        return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}

    def _append(self, kind, fields):
        event = dict(_plain(fields), event=kind, id=len(self._events) + 1,
                     elapsed_ms=self.elapsed_ms(), timestamp=datetime.now().astimezone().isoformat(timespec="milliseconds"))
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        self._stream.write(line + "\n")
        self._stream.flush()  # Keep events readable even after a forced engine termination.
        self._events.append(event)
        self._reserved += 2 * len((line + "\n").encode("utf-8"))  # JSONL + replay data.
        return event["id"]

    def _finish(self, reason):
        if self.active:
            self.active = False
            self.stop_reason = reason
            self._append("session_end", {"reason": reason})
            logger.info(f"[Recording] 录制停止：{reason}；检测与按键继续运行。")

    def _failed(self, exc):
        self.active = False
        self.stop_reason = "write_error"
        logger.error(f"[Recording] 写入失败：{exc}；检测与按键继续运行。")

    def event(self, kind, **fields):
        with self._lock:
            if self._closed or not self.active:
                return None
            try:
                if self.elapsed_ms() >= self.max_seconds * 1000:
                    self._finish("duration_limit")
                    return None
                size = len(json.dumps(_plain(fields), ensure_ascii=False).encode("utf-8"))
                if self._reserved + 2 * size + 2048 >= self.max_bytes:
                    self._finish("size_limit")
                    return None
                return self._append(kind, fields)
            except Exception as exc:
                self._failed(exc)
                return None

    def decision(self, image, **fields):
        """Record every decision; sample raw images without blocking on compression/disk."""
        with self._lock:
            event_id = self.event("decision", **fields)
            if event_id is None or image is None:
                return event_id
            now = time.perf_counter()
            if now - self._last_frame < 1 / self.fps:
                return event_id
            self._last_frame = now
            try:
                self._queue.put_nowait((event_id, image.copy()))
            except queue.Full:
                self.event("frame_dropped", decision_id=event_id, reason="queue_full")
            return event_id

    def _write_frames(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                event_id, image = item
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    raise OSError("JPEG encoding failed")
                relative = f"frames/{event_id:07d}.jpg"
                with self._lock:
                    if self.stop_reason in ("size_limit", "write_error"):
                        continue
                    if self._reserved + encoded.nbytes + 2048 >= self.max_bytes:
                        self._finish("size_limit")
                        continue
                    self._reserved += encoded.nbytes
                (self.directory / relative).write_bytes(encoded.tobytes())
                with self._lock:
                    self._append("frame_saved", {"decision_id": event_id, "path": relative})
            except Exception as exc:
                with self._lock:
                    self._failed(exc)
            finally:
                self._queue.task_done()

    def close(self):
        with self._lock:
            if self._closed:
                return
            try:
                self._finish("stopped")
            except Exception as exc:
                self._failed(exc)
            self._closed = True
        # No producer can enqueue after _closed is set. Drain accepted frames.
        self._queue.put(None)
        self._thread.join()
        try:
            payload = json.dumps(self._events, ensure_ascii=False, allow_nan=False)
            # External JS works with file://; no server or browser fetch permission needed.
            (self.directory / "data.js").write_text("window.RECORDING=" + payload + ";", encoding="utf-8")
            (self.directory / "latency_summary.json").write_text(
                json.dumps(recording_summary(self._events), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error(f"[Recording] 回放索引写入失败：{exc}；可检查 events.jsonl 与 frames。")
        finally:
            self._stream.close()


REPLAY_HTML = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>检测与攻击录制回放</title>
<style>body{background:#101720;color:#dae5ef;font:15px system-ui;margin:20px}button,input,select{margin:6px;padding:6px}canvas{max-width:100%;background:#000}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1b2938;padding:12px}#seek{width:65%}.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}h2{font-size:17px}</style>
<h1>检测与攻击录制回放</h1>
<p>画面按实际采样时间回放。绿色：角色，黄色：搜索框，红色：怪物。sent 表示发送 API 成功，需结合画面确认游戏效果。</p>
<button id="play">播放</button><button id="prev">上一帧</button><button id="next">下一帧</button>
<select id="speed"><option value="0.5">0.5 倍</option><option value="1" selected>1 倍</option><option value="2">2 倍</option></select>
<label><input type="checkbox" id="boxes" checked>显示检测标记</label><span id="status">停止引擎后生成回放数据；强制结束时可检查 events.jsonl 和 frames。</span>
<div><input id="seek" type="range" min="0" max="0" value="0" step="1"><span id="clock"></span></div>
<p id="latency-current" style="background:#1b2938;padding:12px"></p><details><summary>展开延迟诊断统计（毫秒，P50 / P95 / 最大）</summary><div id="latency-summary"></div>
<p>采集＝截屏及转数组；帧等待＝截屏完成至检测线程取走；分析＝取帧后至决策完成；派发等待＝键盘锁等待；发送包含按住按键的时长。指令接收→发送也可能包含冷却、转身、F1 暂停等主动等待，需结合等待原因判断。离线图片无实时采集指标。帧序号跳过表示取最新画面，不能据此判断队列积压；这些指标不包含游戏服务器、网络和画面真正响应的延迟。</p></details>
<canvas id="screen"></canvas><div class="cols"><section><h2>本帧检测与最终指令</h2><pre id="decision"></pre></section><section><h2>截至下一采样帧之前的键盘输出 / 等待原因</h2><pre id="keys"></pre></section></div>
<script src="data.js"></script><script>
const events=window.RECORDING||[], byId=new Map(events.map(e=>[e.id,e]));
const frames=events.filter(e=>e.event==='frame_saved'&&byId.has(e.decision_id)).map(e=>({...e,d:byId.get(e.decision_id)})).sort((a,b)=>a.d.elapsed_ms-b.d.elapsed_ms);
const $=id=>document.getElementById(id), canvas=$('screen'), ctx=canvas.getContext('2d');
let index=0, playing=false, timer=null, token=0;
const metricNames={capture_ms:'采集',capture_interval_ms:'采集间隔',frame_wait_ms:'帧等待',get_frame_ms:'取帧/转色',preprocess_ms:'预处理/小地图',identity_ms:'角色定位',monster_ms:'怪物识别',decision_ms:'决策',analysis_ms:'分析总计',frame_to_decision_ms:'采集开始→决策',frame_age_at_decision_ms:'决策时画面年龄',dispatch_lock_wait_ms:'派发锁等待',decision_to_command_ms:'决策→指令接收',command_to_send_ms:'指令接收→发送',decision_to_send_ms:'决策→发送',send_ms:'发送及按键保持',frame_to_send_ms:'采集开始→发送',frame_to_send_complete_ms:'采集开始→发送完成',record_and_dispatch_ms:'录制提交及派发',post_dispatch_ms:'派发后处理/绘制',cycle_work_ms:'本轮处理总计',cycle_interval_ms:'处理轮次间隔'};
metricNames.send_lock_wait_ms='按键发送锁等待';
const columns={};for(const e of events){const sample=['decision','frame_complete'].includes(e.event)?e.timings_ms:['attack_output','command_accepted'].includes(e.event)?e.latency_ms:null;for(const [k,v]of Object.entries(sample||{})){if(Number.isFinite(v))(columns[k]??=[]).push(v);}}
const rows=[];for(const [k,vs]of Object.entries(columns)){vs.sort((a,b)=>a-b);const p=q=>{const i=(vs.length-1)*q,l=Math.floor(i);return vs[l]+(vs[Math.min(l+1,vs.length-1)]-vs[l])*(i-l);};rows.push([metricNames[k]||k,vs.length,p(.5).toFixed(1),p(.95).toFixed(1),vs[vs.length-1].toFixed(1)]);}
const table=document.createElement('table');table.style.cssText='border-collapse:collapse;width:100%;max-width:900px';
for(const row of [['阶段','样本','P50','P95','最大'],...rows]){const tr=table.insertRow();for(const val of row){const td=tr.insertCell();td.textContent=val;td.style.cssText='padding:5px 12px;border-bottom:1px solid #35495d';}}
$('latency-summary').append(table);if(!rows.length)$('latency-summary').textContent='该录制没有阶段耗时数据（旧版录制仍可正常回放）。';
function showLatency(d){const t=d.timings_ms||{},text=[];for(const k of ['capture_ms','frame_wait_ms','identity_ms','monster_ms','analysis_ms','frame_to_decision_ms'])if(Number.isFinite(t[k]))text.push(metricNames[k]+' '+t[k].toFixed(1)+' ms');const stages=['preprocess_ms','identity_ms','monster_ms','decision_ms'].filter(k=>Number.isFinite(t[k]));if(stages.length){const largest=stages.reduce((a,b)=>t[a]>=t[b]?a:b);text.push('本帧分析中耗时最多：'+metricNames[largest]);}if(d.capture?.reused_frame)text.push('本帧重复使用同一采集帧');$('latency-current').textContent=text.join(' ｜ ')||'本帧无耗时数据';}
const inputEvents=events.filter(e=>['attack_output','attack_wait','input_state','key_output','capture_failed','processing_error','frame_dropped'].includes(e.event));
function render(){if(!frames.length){$('status').textContent=events.length?'本次未保存画面，请查看下方事件或 events.jsonl。':$('status').textContent;$('keys').textContent=inputEvents.map(e=>JSON.stringify(e)).join('\n');return;}const f=frames[index],d=f.d,version=++token,img=new Image();
showLatency(d);
img.onload=()=>{if(version!==token)return;canvas.width=img.width;canvas.height=img.height;ctx.drawImage(img,0,0);
if($('boxes').checked){ctx.lineWidth=2;ctx.font='16px sans-serif';
const box=(x,y,w,h,color,label)=>{ctx.strokeStyle=color;ctx.fillStyle=color;ctx.strokeRect(x,y,w,h);if(label)ctx.fillText(label,x,Math.max(18,y-5));};
if(d.search_box){let [x,y,x1,y1]=d.search_box;box(x,y,x1-x,y1-y,'#ffe066','search');}
if(d.player_valid&&d.player){let [x,y]=d.player;box(x-9,y-9,18,18,'#30ff80','PLAYER');}
for(const m of d.monsters||[]){let [x,y]=m.position,[h,w]=m.size;box(x,y,w,h,'#ff5050',m.name+' '+Number(m.score).toFixed(3));}}};img.src=f.path;
$('seek').value=index;$('clock').textContent=(d.elapsed_ms/1000).toFixed(2)+' 秒 / 帧 '+d.frame;
$('decision').textContent=JSON.stringify(d,null,2);
const until=index+1<frames.length?frames[index+1].d.elapsed_ms:Infinity;
const recent=inputEvents.filter(e=>e.elapsed_ms<until).slice(-16);
$('keys').textContent=recent.map(e=>JSON.stringify(e)).join('\n');
const end=events.find(e=>e.event==='session_end');$('status').textContent=frames.length+' 帧 · '+events.length+' 事件 · '+(end?end.reason:'未正常结束');}
function pause(){playing=false;clearTimeout(timer);$('play').textContent='播放';}
function tick(){if(!playing)return;if(index>=frames.length-1){pause();return;}const delay=Math.max(1,(frames[index+1].d.elapsed_ms-frames[index].d.elapsed_ms)/Number($('speed').value));timer=setTimeout(()=>{index++;render();tick();},delay);}
$('play').onclick=()=>{if(playing){pause();return;}if(!frames.length)return;if(index>=frames.length-1)index=0;playing=true;$('play').textContent='暂停';render();tick();};
$('seek').max=Math.max(0,frames.length-1);$('seek').oninput=()=>{pause();index=Number($('seek').value);render();};
$('prev').onclick=()=>{pause();index=Math.max(0,index-1);render();};$('next').onclick=()=>{pause();index=Math.min(frames.length-1,index+1);render();};
$('boxes').onchange=render;$('speed').onchange=()=>{if(playing){clearTimeout(timer);tick();}};render();
</script></html>'''
