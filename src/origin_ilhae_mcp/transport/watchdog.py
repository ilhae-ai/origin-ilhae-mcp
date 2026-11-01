"""Origin을 막고 있는 대화상자 탐지·닫기 (Windows 전용, ctypes만 사용해 pywin32 불필요).

COM/브리지 호출이 시간 초과되면 대부분 Origin이 띄운 모달 대화상자 때문이다.
대화상자 제목과 본문을 한국어 오류 메시지에 넣어 사용자가 무엇을 눌러야 할지 알게 한다.
"""
from __future__ import annotations

import sys
from typing import Any

DIALOG_CLASS = "#32770"  # Windows 표준 대화상자 창 클래스
ORIGIN_EXES = ("origin64.exe", "origin.exe", "originpro64.exe", "origin64u.exe")


def find_blocking_dialogs() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    found: list[dict[str, Any]] = []

    def _text(hwnd: int) -> str:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _class(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _exe(pid: int) -> str:
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            kernel32.CloseHandle(h)

    body_parts: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _child(hwnd, _):  # noqa: ANN001
        if _class(hwnd) == "Static":
            t = _text(hwnd).strip()
            if t:
                body_parts.append(t)
        return True

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _top(hwnd, _):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd) or _class(hwnd) != DIALOG_CLASS:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _exe(pid.value)
        if exe in ORIGIN_EXES or exe.startswith("origin"):
            body_parts.clear()
            user32.EnumChildWindows(hwnd, _child, 0)
            found.append({"hwnd": int(hwnd), "title": _text(hwnd), "text": " / ".join(body_parts)[:500],
                          "exe": exe})
        return True

    user32.EnumWindows(_top, 0)
    return found


def dismiss(dialogs: list[dict[str, Any]]) -> int:
    """대화상자에 WM_CLOSE를 보낸다(대개 '취소'와 같다). 닫은 개수 반환."""
    if sys.platform != "win32" or not dialogs:
        return 0
    import ctypes

    user32 = ctypes.WinDLL("user32")
    n = 0
    for d in dialogs:
        if user32.PostMessageW(d["hwnd"], 0x0010, 0, 0):  # WM_CLOSE
            n += 1
    return n


def describe(dialogs: list[dict[str, Any]]) -> str:
    if not dialogs:
        return "Origin에서 열린 대화상자를 찾지 못했습니다. Origin이 긴 계산 중이거나 응답하지 않을 수 있습니다."
    parts = [f"'{d['title']}'" + (f" ({d['text']})" if d["text"] else "") for d in dialogs]
    return "Origin 대화상자가 작업을 막고 있습니다: " + ", ".join(parts)
