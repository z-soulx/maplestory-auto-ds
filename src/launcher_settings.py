"""Configuration IO/validation for the desktop launcher (no game input)."""
import copy
import math
from pathlib import Path

import yaml

from src.utils.player_identity import migrate_legacy_identity

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / "config" / "config_local.yaml"
MONSTER_LABELS = {
    "feng_du_yan_shou": "风独眼兽",
    "hou_zi": "猴子",
    "jiang_shi_hou_zi": "无魂猴子 / 僵尸猴子",
    "hei_e_yu": "黑鳄鱼",
    "ci_mo_gu": "刺蘑菇",
}
KEY_FIELDS = (
    ("directional_attack", "主要攻击技能", "w"),
    ("aoe_skill", "群攻技能", "q"),
    ("jump", "跳跃", "alt"),
    ("teleport", "位移 / 瞬移", "e"),
    ("pickup", "拾取", "z"),
    ("add_hp", "红药", "end"),
    ("add_mp", "蓝药", "home"),
    ("return_home", "回城", "insert"),
)


def merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def load_settings(path=LOCAL_CONFIG):
    with (ROOT / "config" / "config_default.yaml").open(encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)
    with (ROOT / "config" / "config_feng_du_yan_shou.yaml").open(encoding="utf-8") as stream:
        merge(cfg, yaml.safe_load(stream))
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            override = yaml.safe_load(stream)
        if not isinstance(override, dict):
            raise ValueError("本机设置文件格式不正确，请检查 config/config_local.yaml。")
        merge(cfg, override)
        # This is a selection, so removed monsters must stay removed on restart.
        if "monsters" in override.get("monster_detect", {}):
            cfg["monster_detect"]["monsters"] = copy.deepcopy(override["monster_detect"]["monsters"])
    else:
        # The detection profile uses a wide observation region, not a skill's range.
        cfg["directional_attack"].update(range_x=300, range_y=70)
        cfg["key"].update(pickup="z", return_home="insert")
    # Opening the settings window never resumes hunting automatically.
    migrate_legacy_identity(cfg)
    cfg["bot"]["mode"] = "detect"
    return cfg


def selected_monsters(cfg):
    specified = cfg["monster_detect"].get("monsters", [])
    if specified:
        return list(specified)
    return sorted(path.name for path in (ROOT / "monster").iterdir()
                  if path.is_dir() and any(path.glob("*.png")))


def number(value, label, low, high, integer=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}必须是数字。") from None
    if not math.isfinite(result) or not low <= result <= high or (integer and not result.is_integer()):
        raise ValueError(f"{label}必须在 {low}～{high} 之间" + ("，且为整数。" if integer else "。"))
    return int(result) if integer else result


def key_name(value, label):
    key = str(value).strip().lower()
    aliases = {"空格": "space", "回车": "enter", "左alt": "altleft", "右alt": "altright",
               "esc": "esc", "control": "ctrl", "return": "enter"}
    key = aliases.get(key, key)
    named = {"alt", "altleft", "altright", "ctrl", "ctrlleft", "ctrlright", "shift", "shiftleft",
             "shiftright", "space", "enter", "tab", "esc", "home", "end", "insert", "delete",
             "pageup", "pagedown", "up", "down", "left", "right", "capslock", "backspace"}
    # F1/F2/F3/F11/F12 belong to this application's global controls.
    named.update(f"f{i}" for i in range(4, 11))
    if (len(key) == 1 and key.isascii() and key.isprintable() and key != " ") or key in named:
        return key
    raise ValueError(f"{label}按键无效：请填写单键，如 x、alt、end；F1/F2/F3/F11/F12 已被脚本占用。")


def build_settings(base, form):
    cfg = copy.deepcopy(base)
    mode = form["mode"]
    if mode not in ("detect", "hunt"):
        raise ValueError("请选择检测或自动打怪模式。")
    title = form["window_title"].strip()
    if not title:
        raise ValueError("请填写游戏窗口标题。")
    cfg["game_window"].update(title=title, exact_match=bool(form["exact_match"]))
    cfg["bot"].update(mode=mode, attack=form["attack_style"], warning=bool(form["warning"]))
    cfg["bot"]["require_foreground"] = True
    recording = cfg.setdefault("recording", {})
    recording["enable"] = bool(form.get("recording_enable", recording.get("enable", False)))
    if form["attack_style"] not in ("directional", "aoe_skill"):
        raise ValueError("请选择攻击方式。")
    for key, label, _ in KEY_FIELDS:
        cfg["key"][key] = key_name(form[key], label)
    cfg["key"]["jump_hold_up_seconds"] = number(form["jump_up"], "跳跃抓绳时长", 0, 10)
    attack = cfg["directional_attack"]
    attack["range_x"] = number(form["range_x"], "水平搜索距离", 20, 2500, True)
    attack["range_y"] = number(form["range_y"], "垂直搜索距离", 10, 1500, True)
    attack["attack_range_x"] = number(form.get("attack_range_x", attack.get("attack_range_x", 100)),
                                      "技能水平有效距离", 1, 2500, True)
    attack["attack_range_y"] = number(form.get("attack_range_y", attack.get("attack_range_y", 35)),
                                      "技能允许的高低差", 1, 1500, True)
    if attack["attack_range_x"] > attack["range_x"] or attack["attack_range_y"] > attack["range_y"]:
        raise ValueError("技能有效距离不能超过对应的搜索距离，请先扩大搜索范围。")
    attack["search_attack_while_move"] = bool(form.get("search_attack", attack.get("search_attack_while_move", False)))
    attack["cooldown"] = number(form["attack_cd"], "攻击间隔", 0.05, 30)
    attack["aoe_monster_count"] = number(form["aoe_count"], "切换群攻的怪物数量", 1, 100, True)
    cfg["aoe_skill"]["range_x"] = attack["range_x"] * 2
    cfg["aoe_skill"]["range_y"] = attack["range_y"] * 2
    cfg["aoe_skill"]["cooldown"] = attack["cooldown"]
    cfg["pickup"] = {"enable": bool(form["pickup_enable"]), "cooldown": 0.3}
    buffs, cooldowns = [], []
    for item in form["buffs"].replace("，", ",").split(","):
        if not item.strip():
            continue
        parts = item.strip().split(":")
        if len(parts) != 2:
            raise ValueError("Buff 请按“按键:间隔秒”填写，例如 2:120,3:180。")
        buffs.append(key_name(parts[0], "Buff"))
        cooldowns.append(number(parts[1], "Buff 间隔", 1, 86400))
    cfg["buff_skill"].update(keys=buffs, cooldown=cooldowns, startup_delay=2)
    scales = [number(item.strip(), "素材缩放", 0.2, 4)
              for item in form["scales"].replace("，", ",").split(",")]
    threshold = number(form["threshold"], "怪物匹配阈值", 0.001, 1)
    md = cfg["monster_detect"]
    md.update(scales=scales, diff_thres=threshold,
              display_scale=number(form["display_scale"], "预览缩放", 0.2, 1))
    monsters = form.get("monsters", selected_monsters(base))
    if not isinstance(monsters, (list, tuple)) or not monsters:
        raise ValueError("请至少勾选一种要识别的怪物。")
    previous = md.get("monsters", {})
    selected = {}
    for name in monsters:
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise ValueError("怪物目录名称无效。")
        directory = ROOT / "monster" / name
        if not directory.is_dir() or not any(directory.glob("*.png")):
            raise ValueError(f"缺少怪物素材：{name}。")
        options = previous.get(name, {}) if isinstance(previous, dict) else {}
        options = copy.deepcopy(options) if isinstance(options, dict) else {}
        options.update(scales=scales, diff_thres=threshold)
        options.setdefault("min_color_spread", 30)
        selected[name] = options
    md["monsters"] = selected
    hm = cfg["health_monitor"]
    hm.update(enable=bool(form["health_enable"]), enable_hp=bool(form["hp_enable"]),
              enable_mp=bool(form["mp_enable"]), bar_count=2,
              add_hp_percent=number(form["hp_percent"], "红药触发血量", 1, 99),
              add_mp_percent=number(form["mp_percent"], "蓝药触发蓝量", 1, 99))
    hm["hp_rearm_percent"] = min(100, hm["add_hp_percent"] + 5)
    hm["mp_rearm_percent"] = min(100, hm["add_mp_percent"] + 5)
    rects = []
    for name, label in (("hp", "HP"), ("mp", "MP")):
        text = form[f"{name}_rect"].strip()
        if text:
            parts = text.replace("，", ",").split(",")
            if len(parts) != 4:
                raise ValueError(f"{label} 检测框请填写 x,y,宽,高 四个整数。")
            rect = [number(v.strip(), f"{label} 检测框", 0, 10000, True) for v in parts]
            if rect[2] == 0 or rect[3] == 0:
                raise ValueError(f"{label} 检测框宽、高必须大于 0。")
            hm[f"{name}_bar_rect"] = rect
            rects.append(rect)
    if len(rects) == 1:
        raise ValueError("固定检测框需要同时填写 HP 和 MP；两者留空则自动寻找血蓝条。")
    hm["fixed_bars"] = len(rects) == 2
    map_name = form["map_name"].strip()
    route_enabled = bool(form["route_enable"])
    if route_enabled:
        map_dir = ROOT / "minimaps" / map_name
        if not map_name or Path(map_name).name != map_name or not (map_dir / "map.png").is_file() or not list(map_dir.glob("route*.png")):
            raise ValueError("开启路线前，请选择已有 map.png 和 route*.png 的地图。")
    cfg["bot"].update(map=map_name, enable_route=route_enabled and mode == "hunt")
    identity = cfg.get("player_identity", {})
    if "locate_name" in form:
        sources = [source for source, field in (("name", "locate_name"),
                                                ("medal", "verify_medal"),
                                                ("appearance", "verify_appearance")) if form.get(field, False)]
        if not sources:
            raise ValueError("请至少选择一种角色定位方式：名字、勋章或外观。")
        policy = form.get("identity_policy", "any")
        if policy not in ("any", "all"):
            raise ValueError("请选择有效的角色定位组合方式。")
        paths = {
            "name": [item["template"] for item in identity.get("templates", [])
                     if not item.get("partial", False) or form.get("partial_name", True)],
            "medal": [cfg["title"].get("template", "character/title.png")],
            "appearance": [cfg.get("appearance", {}).get("template", "character/fashi.png")],
        }
        for source in sources:
            if not paths[source] or not any((ROOT / path).is_file() for path in paths[source]):
                label = {"name": "名字", "medal": "勋章", "appearance": "外观"}[source]
                raise ValueError(f"缺少{label}定位模板，请先校准对应模板。")
        identity.update(enable=True, sources=sources, match_policy=policy,
                        require_medal=policy == "all" and "medal" in sources,
                        require_appearance=policy == "all" and "appearance" in sources,
                        allow_partial_name=bool(form.get("partial_name", True)))
        cfg["player_identity"] = identity
        cfg["title"]["enable"] = "medal" in sources
        cfg.setdefault("appearance", {})["enable"] = "appearance" in sources
    elif identity.get("enable"):
        identity["require_medal"] = bool(form.get("verify_medal", identity.get("require_medal", False)))
        identity["require_appearance"] = bool(form.get("verify_appearance", identity.get("require_appearance", False)))
        identity["allow_partial_name"] = bool(form.get("partial_name", identity.get("allow_partial_name", True)))
        cfg["title"]["enable"] = identity["require_medal"]
    else:
        cfg["title"]["enable"] = bool(form["title_enable"])
    if mode == "hunt" and not identity.get("enable") and not cfg["title"]["enable"] and not cfg.get("appearance", {}).get("enable"):
        raise ValueError("自动打怪需要开启并校准角色称号或外观定位。")
    return cfg


def save_settings(cfg, path=LOCAL_CONFIG):
    text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
