"""Read-only Windows checks for game/input process elevation mismatches."""
import os
import sys


def process_is_elevated(pid):
    """Return True/False, or None if the token cannot be queried."""
    if sys.platform != "win32":
        return None
    import pywintypes
    import win32api
    import win32con
    import win32security

    process = token = None
    try:
        process = win32api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
        return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
    except (OSError, pywintypes.error):
        return None
    finally:
        if token is not None:
            token.Close()
        if process is not None:
            process.Close()


def game_input_permission_issue(cfg):
    """Describe a confirmed mismatch; unknown/missing windows are not mismatches."""
    if sys.platform != "win32":
        return None
    import pywintypes
    import win32gui
    import win32process
    from src.utils.common import get_game_window_title_by_token

    window = cfg.get("game_window", {})
    try:
        title = get_game_window_title_by_token(
            window.get("title", ""), exact_match=window.get("exact_match", False))
        if not title:
            return None
        hwnd = win32gui.FindWindow(None, title)
        if not hwnd:
            return None
        game_pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        game_elevated = process_is_elevated(game_pid)
        script_elevated = process_is_elevated(os.getpid())
    except (OSError, pywintypes.error):
        return None
    if game_elevated is True and script_elevated is False:
        return (
            "游戏以管理员权限运行，当前脚本为普通权限，Windows 会限制向游戏发送按键。\n\n"
            "请关闭此设置窗口，双击 start_feng_du_yan_shou_admin.cmd，"
            "在 Windows 权限提示中确认，再选择自动打怪并启动。已有按键设置会保留。"
        )
    return None
