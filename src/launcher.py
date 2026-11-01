"""Startup settings window. It sends no game input until Start is clicked."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.launcher_settings import (
    KEY_FIELDS, LOCAL_CONFIG, MONSTER_LABELS, build_settings, load_settings,
    save_settings, selected_monsters,
)
from src.utils.input_permissions import game_input_permission_issue
from src.utils.player_identity import identity_selection

MODE_LABELS = {"仅检测（不攻击）": "detect", "自动打怪": "hunt"}
ATTACK_LABELS = {"方向攻击": "directional", "范围技能": "aoe_skill"}
IDENTITY_POLICIES = {"任一命中即可定位（互补）": "any", "全部匹配才定位（联合核对）": "all"}


class Launcher:
    def __init__(self, root, config_path=LOCAL_CONFIG):
        self.root = root
        self.config_path = config_path
        self.cfg = load_settings(config_path)
        self.fields = {}
        self.process = None
        self.stop_file = None
        self.messages = queue.Queue()
        self.closing = False
        root.title("冒险岛 · 启动与设置")
        root.geometry("860x720")
        root.minsize(800, 670)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 5))
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(frame, text="冒险岛 · 怪物识别与打怪", font=("Microsoft YaHei UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="进入游戏 → 核对按键 → 先检测角色和怪物 → 再选择自动打怪", foreground="#526174").grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.notebook = ttk.Notebook(frame)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.tab_canvases = {}
        self.general_tab()
        self.keys_tab()
        self.detection_tab()
        self.route_tab()
        self.status = tk.StringVar(root, "尚未启动。请先核对游戏键位。")
        ttk.Label(frame, textvariable=self.status, foreground="#245da8").grid(row=3, column=0, sticky="w", pady=(10, 5))
        self.log = tk.Text(frame, height=4, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.grid(row=4, column=0, sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="查看使用说明", command=self.open_help).pack(side="left")
        self.save_button = ttk.Button(buttons, text="保存设置", command=self.save)
        self.save_button.pack(side="right", padx=(8, 0))
        self.stop_button = ttk.Button(buttons, text="停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(buttons, text="保存并启动", command=self.start)
        self.start_button.pack(side="right")
        self.root.bind("<MouseWheel>", self.scroll_settings, add="+")
        self.root.after(150, self.poll)

    def tab(self, label):
        container = ttk.Frame(self.notebook)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        frame = ttk.Frame(canvas, padding=14)
        frame.columnconfigure(1, weight=1)
        window = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        self.notebook.add(container, text=label)
        self.tab_canvases[str(container)] = canvas
        return frame

    def scroll_settings(self, event):
        canvas = self.tab_canvases.get(self.notebook.select())
        if canvas is None or not str(event.widget).startswith(str(canvas)):
            return
        bounds = canvas.bbox("all")
        if bounds and bounds[3] > canvas.winfo_height() and event.delta:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

    def entry(self, parent, row, label, name, value, width=30):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
        variable = tk.StringVar(self.root, str(value))
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", pady=5)
        self.fields[name] = variable

    def check(self, parent, row, label, name, value):
        variable = tk.BooleanVar(self.root, bool(value))
        ttk.Checkbutton(parent, text=label, variable=variable).grid(row=row, column=0, columnspan=2, sticky="w", pady=5)
        self.fields[name] = variable

    def choice(self, parent, row, label, name, options, current):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=5)
        variable = tk.StringVar(self.root, current)
        ttk.Combobox(parent, textvariable=variable, values=list(options), state="readonly").grid(row=row, column=1, sticky="ew", pady=5)
        self.fields[name] = variable

    def note(self, parent, row, text):
        ttk.Label(parent, text=text, foreground="#526174", wraplength=740, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))

    def general_tab(self):
        frame = self.tab("启动设置")
        self.entry(frame, 0, "游戏窗口标题", "window_title", self.cfg["game_window"]["title"])
        self.check(frame, 1, "精确匹配窗口标题（避免选中浏览器网页）", "exact_match", self.cfg["game_window"].get("exact_match", True))
        self.choice(frame, 2, "运行模式", "mode", MODE_LABELS, "仅检测（不攻击）")
        style = next(label for label, value in ATTACK_LABELS.items() if value == self.cfg["bot"]["attack"])
        self.choice(frame, 3, "攻击方式", "attack_style", ATTACK_LABELS, style)
        attack = self.cfg["directional_attack"]
        self.check(frame, 4, "找怪时边走边攻击（没有识别目标也会空挥）", "search_attack",
                   attack.get("search_attack_while_move", False))
        for row, label, name, value in (
            (5, "水平搜索距离（像素）", "range_x", attack["range_x"]),
            (6, "垂直搜索距离（像素）", "range_y", attack["range_y"]),
            (7, "技能水平有效距离（像素）", "attack_range_x", attack.get("attack_range_x", 100)),
            (8, "技能允许的高低差（像素）", "attack_range_y", attack.get("attack_range_y", 35)),
            (9, "攻击间隔（秒）", "attack_cd", attack.get("cooldown", 0.9)),
            (10, "范围内怪物达到几只时使用群攻", "aoe_count", attack.get("aoe_monster_count", 3)),
        ):
            self.entry(frame, row, label, name, value)
        self.check(frame, 11, "启用告警声音", "warning", self.cfg["bot"].get("warning", True))
        self.check(frame, 12, "录制检测画面与攻击指令（用于排查停攻原因）", "recording_enable",
                   self.cfg.get("recording", {}).get("enable", False))
        self.note(frame, 13, "录制保存到 recordings/本次时间目录，停止后打开 replay.html 回放；默认最多 10 分钟、512 MB，达到上限只停止录制。战士先用技能距离 100、高低差 35，再按实际技能调整。修改设置需停止后重新启动。")

    def keys_tab(self):
        frame = self.tab("按键与技能")
        for row, (key, label, default) in enumerate(KEY_FIELDS):
            self.entry(frame, row, label, key, self.cfg["key"].get(key, default))
        self.entry(frame, 8, "跳跃时同时按住上（秒，0 关闭）", "jump_up", self.cfg["key"].get("jump_hold_up_seconds", 0))
        buffs = self.cfg.get("buff_skill", {})
        text = ",".join(f"{key}:{seconds}" for key, seconds in zip(buffs.get("keys", []), buffs.get("cooldown", [])))
        self.entry(frame, 9, "自动 Buff（按键:间隔秒）", "buffs", text)
        self.check(frame, 10, "移动时自动拾取", "pickup_enable", self.cfg.get("pickup", {}).get("enable", False))
        self.note(frame, 11, "按键必须与游戏内一致，例如 x、alt、end、home。Buff 示例：2:120,3:180；不需要则留空。")

    def detection_tab(self):
        frame = self.tab("识别与补药")
        md = self.cfg["monster_detect"]
        targets = ttk.LabelFrame(frame, text="识别目标（可多选）", padding=6)
        targets.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        selected = selected_monsters(self.cfg)
        labels = dict(MONSTER_LABELS)
        labels.update({name: name for name in selected if name not in labels})
        self.monster_fields = {}
        for index, (name, label) in enumerate(labels.items()):
            variable = tk.BooleanVar(self.root, name in selected)
            ttk.Checkbutton(targets, text=label, variable=variable).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 16))
            self.monster_fields[name] = variable
        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, columnspan=2, sticky="nsew")
        controls.columnconfigure(1, weight=1)
        frame = controls
        self.entry(frame, 0, "怪物素材缩放", "scales", ",".join(str(v) for v in md["scales"]))
        self.entry(frame, 1, "怪物匹配阈值（越小越严格）", "threshold", md["diff_thres"])
        self.entry(frame, 2, "预览画面缩放", "display_scale", md["display_scale"])
        identity = self.cfg.get("player_identity", {})
        sources, policy = identity_selection(self.cfg)
        player = ttk.LabelFrame(frame, text="角色定位（至少选一项，可单独或组合使用）", padding=6)
        player.columnconfigure(1, weight=1)
        player.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)
        self.check(player, 0, f"按名字定位：{identity.get('name', '')}", "locate_name", "name" in sources)
        self.check(player, 1, "按勋章定位", "verify_medal", "medal" in sources)
        self.check(player, 2, "按外观定位（需先校准自己的外观模板）", "verify_appearance", "appearance" in sources)
        self.choice(player, 3, "多项组合方式", "identity_policy", list(IDENTITY_POLICIES),
                    next(label for label, value in IDENTITY_POLICIES.items() if value == policy))
        self.check(player, 4, "允许名字局部识别（宠物遮挡时）", "partial_name", identity.get("allow_partial_name", True))
        self.note(player, 5, "互补模式优先名字，名字被挡时可用勋章；联合核对要求所选特征同时对齐。同款勋章或相似外观可能认到别人。")
        hm = self.cfg["health_monitor"]
        self.check(frame, 4, "启用自动补药（检测模式也会补药）", "health_enable", hm["enable"])
        options = ttk.Frame(frame)
        options.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.check(options, 0, "自动补血", "hp_enable", hm.get("enable_hp", True))
        self.check(options, 1, "自动补蓝", "mp_enable", hm.get("enable_mp", True))
        self.entry(frame, 6, "血量低于多少 % 使用红药", "hp_percent", hm["add_hp_percent"])
        self.entry(frame, 7, "蓝量低于多少 % 使用蓝药", "mp_percent", hm["add_mp_percent"])
        for row, name, label in ((8, "hp", "HP 检测框 x,y,宽,高"), (9, "mp", "MP 检测框 x,y,宽,高")):
            rect = hm.get(f"{name}_bar_rect", []) if hm.get("fixed_bars") else []
            self.entry(frame, row, label, f"{name}_rect", ",".join(str(v) for v in rect))
        self.note(frame, 10, "只勾选当前地图的怪物可减少识别耗时。1.4 倍是风独眼兽的实测值，其他新增怪物需先检测确认。补药前先确认血蓝读数；检测框全部留空则自动寻找血蓝条。")

    def route_tab(self):
        frame = self.tab("地图路线")
        self.check(frame, 0, "自动打怪时沿已录制路线移动", "route_enable", self.cfg["bot"].get("enable_route", False))
        maps = sorted(path.name for path in (ROOT / "minimaps").iterdir() if path.is_dir() and (path / "map.png").is_file())
        self.choice(frame, 1, "已录制地图", "map_name", [""] + maps, self.cfg["bot"].get("map", ""))
        self.note(frame, 2, "没有开启路线时，角色按现有找怪逻辑左右移动。只有在当前地图的路线已录制并校准小地图后，才勾选路线。仓库自带地图不代表你的当前地图。")

    def form(self):
        values = {name: variable.get() for name, variable in self.fields.items()}
        values["mode"] = MODE_LABELS[values["mode"]]
        values["attack_style"] = ATTACK_LABELS[values["attack_style"]]
        values["identity_policy"] = IDENTITY_POLICIES[values["identity_policy"]]
        values["monsters"] = [name for name, variable in self.monster_fields.items() if variable.get()]
        return values

    def save(self):
        try:
            cfg = build_settings(self.cfg, self.form())
            save_settings(cfg, self.config_path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("设置未保存", str(exc), parent=self.root)
            return None
        self.cfg = cfg
        self.status.set("设置已保存。点击“保存并启动”后才会运行。")
        return cfg

    def start(self):
        if self.process is not None:
            return
        cfg = self.save()
        if cfg is None:
            return
        if self.config_path.parent != LOCAL_CONFIG.parent:
            messagebox.showerror("无法启动", "启动配置必须位于项目 config 文件夹。", parent=self.root)
            return
        permission_issue = game_input_permission_issue(cfg)
        if permission_issue:
            self.messages.put("[权限检查] " + permission_issue + "\n")
            if cfg["bot"]["mode"] == "hunt" or cfg.get("health_monitor", {}).get("enable"):
                self.status.set("权限不一致，请使用管理员启动入口。设置已保存。")
                messagebox.showerror("游戏与脚本权限不一致", permission_issue, parent=self.root)
                return
        suffix = self.config_path.stem.removeprefix("config_")
        log_dir = ROOT / "log"
        log_dir.mkdir(exist_ok=True)
        self.stop_file = log_dir / f"launcher-{uuid.uuid4().hex}.stop"
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PYGAME_HIDE_SUPPORT_PROMPT="1")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "src" / "main.py"), "--cfg", suffix, "--stop_file", str(self.stop_file)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            messagebox.showerror("启动失败", str(exc), parent=self.root)
            self.process = None
            return
        process = self.process

        def read_output():
            try:
                for line in process.stdout:
                    self.messages.put(line)
            finally:
                process.stdout.close()

        threading.Thread(target=read_output, daemon=True).start()
        self.start_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("脚本运行中。当前模式请看 NewMaple 右上角；F1 暂停按键。")

    def stop(self):
        if self.process is not None and self.stop_file is not None:
            try:
                self.stop_file.write_text("stop\n", encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("停止请求失败", str(exc), parent=self.root)
                return
            self.status.set("正在停止并释放按键……")
            self.stop_button.configure(state="disabled")

    def poll(self):
        lines = []
        for _ in range(300):
            try:
                lines.append(self.messages.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(lines))
            if int(self.log.index("end-1c").split(".")[0]) > 300:
                self.log.delete("1.0", "100.0")
            self.log.see("end")
            self.log.configure(state="disabled")
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            self.process = None
            if self.stop_file:
                self.stop_file.unlink(missing_ok=True)
            self.status.set("已停止。" if code == 0 else "启动或运行失败，请查看上方日志。")
            self.start_button.configure(state="normal")
            self.save_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        if self.closing and self.process is None:
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        self.closing = True
        if self.process is None:
            self.root.destroy()
        else:
            self.stop()

    def open_help(self):
        os.startfile(ROOT / "GETTING_STARTED_CN.md")


def main():
    os.chdir(ROOT)
    root = tk.Tk()
    try:
        Launcher(root)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        messagebox.showerror("设置窗口无法打开", str(exc), parent=root)
        root.destroy()
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
