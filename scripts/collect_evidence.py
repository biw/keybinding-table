#!/usr/bin/env python3
"""Collect versioned textarea shortcut observations with native OS input.

This program intentionally records raw evidence; it does not edit README.md.
The workflow runs it in disposable macOS and Windows environments, where the
browser's own shortcut routing is exercised rather than page-synthetic events.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform as host_platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = ROOT / "harness"

TARGETS = {
    ("macos", "safari"): {
        "target": "safari-macos",
        "source": "SAFARI-KEYBOARD",
        "browser": "Safari",
        "bundle": "com.apple.Safari",
    },
    ("macos", "chrome"): {
        "target": "chromium-macos",
        "source": "CHROME-KEYBOARD",
        "browser": "Google Chrome",
        "bundle": "com.google.Chrome",
    },
    ("macos", "firefox"): {
        "target": "firefox-macos",
        "source": "FF-KEYBOARD",
        "browser": "Firefox",
        "bundle": "org.mozilla.firefox",
    },
    ("windows", "chrome"): {
        "target": "chrome-windows",
        "source": "CHROME-KEYBOARD",
        "browser": "Google Chrome",
    },
    ("windows", "edge"): {
        "target": "edge-windows",
        "source": "EDGE-KEYBOARD",
        "browser": "Microsoft Edge",
    },
    ("windows", "firefox"): {
        "target": "firefox-windows",
        "source": "FF-KEYBOARD",
        "browser": "Firefox",
    },
}

WINDOWS_SCAN_CODES = {
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15,
    "z": 0x2C,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "-": 0x0C, "=": 0x0D, "[": 0x1A, "]": 0x1B, ";": 0x27,
    "'": 0x28, "`": 0x29, ",": 0x33, ".": 0x34, "/": 0x35,
}
WINDOWS_MODIFIER_SCAN_CODES = {"ctrl": 0x1D, "alt": 0x38, "meta": 0x5B}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def table_combos(readme: Path) -> list[str]:
    # Markdown represents a literal-backtick key as `` modifier→` ``; retain
    # that row instead of silently narrowing the evidence matrix.
    pattern = re.compile(r"^\|\s+\*\*(?:`([^`]+)`|``\s*([^`]+)`\s*``)\*\*", re.MULTILINE)
    combos = [normal or literal_backtick + "`" for normal, literal_backtick in pattern.findall(
        readme.read_text(encoding="utf-8")
    )]
    if not combos:
        raise RuntimeError(f"No keybinding rows found in {readme}")
    return combos


def select_combos(all_combos: list[str], selection: str) -> list[str]:
    if selection.strip().lower() == "all":
        return all_combos
    requested = [entry.strip() for entry in selection.split(",") if entry.strip()]
    unknown = sorted(set(requested) - set(all_combos))
    if unknown:
        raise RuntimeError(f"Unknown combo(s): {', '.join(unknown)}")
    return requested


def selected_states(selection: str) -> list[str]:
    if selection == "both":
        return ["textarea-caret", "textarea-selection"]
    return [f"textarea-{selection}"]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def assert_us_layout(platform_name: str) -> None:
    if platform_name == "macos":
        result = run(["defaults", "read", "com.apple.HIToolbox", "AppleSelectedInputSources"])
        # Fresh hosted macOS accounts commonly have no HIToolbox preference at
        # all. That is the system U.S. ANSI default, whereas a present
        # preference lets us reject a non-U.S. explicit configuration.
        if result.returncode != 0:
            return
        if "U.S." not in result.stdout:
            raise RuntimeError("The macOS runner does not report the required U.S. input source")
        return

    result = run([
        "powershell",
        "-NoProfile",
        "-Command",
        "(Get-WinUserLanguageList | ConvertTo-Json -Compress)",
    ])
    if result.returncode != 0 or "0409:00000409" not in result.stdout:
        raise RuntimeError("The Windows runner does not report the required U.S. keyboard layout")


def start_server() -> tuple[ThreadingHTTPServer, str]:
    handler = partial(QuietHandler, directory=str(HARNESS_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/textarea.html"


def webdriver_for(platform_name: str, browser: str, profile: Path):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    from webdriver_manager.microsoft import EdgeChromiumDriverManager

    if browser == "safari":
        return webdriver.Safari()
    if browser == "firefox":
        from selenium.webdriver.firefox.options import Options

        options = Options()
        options.add_argument("-no-remote")
        options.add_argument("-profile")
        options.add_argument(str(profile))
        return webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)

    if browser == "chrome":
        from selenium.webdriver.chrome.options import Options

        options = Options()
        if platform_name == "macos":
            # Selenium otherwise prefers the runner's bundled Chrome for
            # Testing, which may lag the current stable cask and mismatch the
            # ChromeDriver version selected by webdriver-manager.
            options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-sync")
        return webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    if browser == "edge":
        from selenium.webdriver.edge.options import Options

        options = Options()
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-sync")
        return webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=options)

    raise RuntimeError(f"Unsupported browser {browser} on {platform_name}")


def send_windows_key_events(events: list[tuple[int, bool]], *, scan_codes: bool = False) -> None:
    """Insert virtual-key or physical U.S. scan-code events through SendInput."""
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008

    def event(code: int, key_up: bool = False) -> INPUT:
        flags = (KEYEVENTF_KEYUP if key_up else 0) | (KEYEVENTF_SCANCODE if scan_codes else 0)
        return INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=0 if scan_codes else code,
                wScan=code if scan_codes else 0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    inputs = (INPUT * len(events))(*(event(code, key_up) for code, key_up in events))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise RuntimeError(f"SendInput inserted {sent}/{len(inputs)} events (winerror {ctypes.get_last_error()})")


def inject_windows_click(x: int, y: int) -> None:
    """Click a screen coordinate through SendInput to establish renderer focus."""
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if width <= 1 or height <= 1:
        raise RuntimeError("Windows virtual-screen dimensions are invalid")
    absolute_x = round((x - left) * 65535 / (width - 1))
    absolute_y = round((y - top) * 65535 / (height - 1))
    absolute_x = max(0, min(65535, absolute_x))
    absolute_y = max(0, min(65535, absolute_y))
    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

    def event(flags: int) -> INPUT:
        return INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(
                dx=absolute_x,
                dy=absolute_y,
                mouseData=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    inputs = (INPUT * 3)(
        event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
        event(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
        event(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
    )
    sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise RuntimeError(f"SendInput inserted {sent}/{len(inputs)} mouse events (winerror {ctypes.get_last_error()})")


def focus_windows_textarea(driver) -> dict[str, int]:
    """Use a native pointer click at the harness textarea's on-screen center."""
    geometry = driver.execute_script("""
      const target = document.querySelector('#target').getBoundingClientRect();
      return {
        targetLeft: target.left, targetTop: target.top,
        targetWidth: target.width, targetHeight: target.height,
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
        outerWidth: window.outerWidth, outerHeight: window.outerHeight,
        devicePixelRatio: window.devicePixelRatio
      };
    """)
    window = driver.get_window_rect()
    scale = float(geometry["devicePixelRatio"])
    chrome_left = (float(geometry["outerWidth"]) - float(geometry["innerWidth"])) / 2
    chrome_top = float(geometry["outerHeight"]) - float(geometry["innerHeight"])
    x = round(float(window["x"]) + (chrome_left + float(geometry["targetLeft"]) + float(geometry["targetWidth"]) / 2) * scale)
    y = round(float(window["y"]) + (chrome_top + float(geometry["targetTop"]) + float(geometry["targetHeight"]) / 2) * scale)
    inject_windows_click(x, y)
    return {"x": x, "y": y}


def inject_windows(combo: str, *, scan_codes: bool) -> None:
    try:
        modifier, key = combo.split("→", maxsplit=1)
        if scan_codes:
            modifier_code = WINDOWS_MODIFIER_SCAN_CODES[modifier]
            key_code = WINDOWS_SCAN_CODES[key]
        else:
            modifier_code = {"ctrl": 0x11, "alt": 0x12, "meta": 0x5B}[modifier]
            key_code = {
                **{character: ord(character.upper()) for character in "abcdefghijklmnopqrstuvwxyz"},
                **{character: ord(character) for character in "0123456789"},
                ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE,
                "/": 0xBF, "`": 0xC0, "[": 0xDB, "]": 0xDD, "'": 0xDE,
            }[key]
    except (KeyError, ValueError) as error:
        raise RuntimeError(f"Unsupported Windows U.S. ANSI combo: {combo}") from error
    send_windows_key_events([
        (modifier_code, False),
        (key_code, False),
        (key_code, True),
        (modifier_code, True),
    ], scan_codes=scan_codes)


def activate_windows_browser(title: str) -> str:
    """Bring the harness's browser window to the interactive desktop foreground.

    A WebDriver click changes DOM focus, but does not reliably make a headed
    browser the foreground *OS* window on GitHub's Windows runners. SendInput
    deliberately follows OS foreground routing, so establish and record that
    routing before injecting a shortcut.
    """
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_callback, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def window_title(window: int) -> str:
        length = user32.GetWindowTextLengthW(window)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buffer, len(buffer))
        return buffer.value

    target = None
    deadline = time.monotonic() + 5
    while target is None and time.monotonic() < deadline:
        candidates: list[int] = []

        @enum_callback
        def collect(window, _):
            if user32.IsWindowVisible(window) and title in window_title(window):
                candidates.append(window)
            return True

        if not user32.EnumWindows(collect, 0):
            raise RuntimeError(f"EnumWindows failed (winerror {ctypes.get_last_error()})")
        if candidates:
            target = candidates[0]
            break
        time.sleep(0.1)
    if target is None:
        raise RuntimeError(f"Could not find a visible browser window titled {title!r}")

    # GitHub's ARM Windows image can open an unrelated Microsoft-account
    # onboarding dialog and then its Search panel after browser startup. Close
    # only these known transient host windows; do not dismiss arbitrary app
    # windows or infer browser behavior while one owns foreground input.
    foreground = user32.GetForegroundWindow()
    for _ in range(3):
        if not foreground or window_title(foreground) not in {"Microsoft account", "Search"}:
            break
        user32.PostMessageW(foreground, 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(0.3)
        foreground = user32.GetForegroundWindow()

    # SetForegroundWindow permits a process that received the last input to
    # activate its target. A down/up Alt pulse is sent through SendInput (the
    # same native OS path as the tested key), then no browser behavior is
    # sampled until foreground ownership is verified below.
    send_windows_key_events([(0x12, False), (0x12, True)])  # VK_MENU

    # The foreground-lock rules permit the active thread's input queue to be
    # attached temporarily to both the existing foreground queue and target
    # queue. This is the least invasive way to activate the browser; the test
    # never sends synthetic DOM events.
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(target, None)
    current_thread = kernel32.GetCurrentThreadId()
    attached_threads: list[int] = []
    for thread in (foreground_thread, target_thread):
        if thread and thread != current_thread and thread not in attached_threads:
            if user32.AttachThreadInput(current_thread, thread, True):
                attached_threads.append(thread)
    try:
        user32.ShowWindow(target, 9)  # SW_RESTORE
        user32.BringWindowToTop(target)
        user32.SetForegroundWindow(target)
    finally:
        for thread in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread, False)

    if user32.GetForegroundWindow() != target:
        actual = user32.GetForegroundWindow()
        raise RuntimeError(
            f"Could not foreground the browser window (foreground title: {window_title(actual)!r})"
        )
    return window_title(target)


def inject_macos(injector: Path, bundle: str, combo: str) -> None:
    result = run([str(injector), "--bundle", bundle, "--combo", combo])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown CGEvent failure"
        raise RuntimeError(message)


def focus_macos_textarea(injector: Path, bundle: str, driver) -> dict[str, int]:
    """Activate the browser and focus its renderer with a Quartz mouse click."""
    geometry = driver.execute_script("""
      const target = document.querySelector('#target').getBoundingClientRect();
      return {
        targetLeft: target.left, targetTop: target.top,
        targetWidth: target.width, targetHeight: target.height,
        innerWidth: window.innerWidth, innerHeight: window.innerHeight,
        outerWidth: window.outerWidth, outerHeight: window.outerHeight
      };
    """)
    window = driver.get_window_rect()
    chrome_left = (float(geometry["outerWidth"]) - float(geometry["innerWidth"])) / 2
    chrome_top = float(geometry["outerHeight"]) - float(geometry["innerHeight"])
    x = round(float(window["x"]) + chrome_left + float(geometry["targetLeft"]) + float(geometry["targetWidth"]) / 2)
    y = round(float(window["y"]) + chrome_top + float(geometry["targetTop"]) + float(geometry["targetHeight"]) / 2)
    result = run([str(injector), "--bundle", bundle, "--click", f"{x},{y}"])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown Quartz mouse-input failure"
        raise RuntimeError(message)
    return {"x": x, "y": y}


def browser_version(capabilities: dict[str, Any]) -> str:
    value = capabilities.get("browserVersion") or capabilities.get("version")
    return str(value) if value else "unavailable"


def terminate_browser(platform_name: str, browser: str) -> None:
    """Ensure a close/quit shortcut cannot leak state into the next case."""
    if platform_name == "windows":
        image = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}[browser]
        run(["taskkill", "/F", "/T", "/IM", image])
        return
    name = {"safari": "Safari", "chrome": "Google Chrome", "firefox": "firefox"}[browser]
    run(["pkill", "-x", name])


def snapshot(driver) -> dict[str, Any]:
    state = driver.execute_script("return window.__keybindingEvidence.snapshot()")
    state["url"] = driver.current_url
    state["windowHandles"] = len(driver.window_handles)
    return state


def changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ("value", "selectionStart", "selectionEnd", "scrollTop", "activeElement", "url", "windowHandles"):
        if before.get(key) != after.get(key):
            return True
    return False


def safe_name(combo: str, state: str) -> str:
    return f"{combo.replace('→', '_').replace('/', 'slash')}_{state.replace('textarea-', '')}"


def observation_for_case(
    platform_name: str,
    browser: str,
    combo: str,
    state: str,
    harness_url: str,
    output_dir: Path,
    runner_image: str,
    artifact: str,
    mac_injector: Path | None,
) -> dict[str, Any]:
    target = TARGETS[(platform_name, browser)]
    source_ids = [target["source"]]
    if platform_name == "windows" and combo.startswith("meta→"):
        source_ids.append("WIN-KEYBOARD")
    if platform_name == "macos" and combo.startswith(("ctrl→", "alt→")):
        source_ids.append("MAC-KEYBOARD")

    environment = {
        "browser": target["browser"],
        "browserVersion": "unavailable",
        "os": host_platform.platform(),
        "runnerImage": runner_image,
        "inputLayout": "U.S.",
        "cleanProfile": True,
    }
    result: dict[str, Any] = {
        "kind": "injector-failure",
        "summary": "Browser was not started.",
        "before": None,
        "after": None,
        "error": None,
    }
    record = {
        "combo": combo,
        "target": target["target"],
        "state": state,
        "result": result,
        "environment": environment,
        "sources": source_ids,
        "artifact": artifact,
        "capturedAt": now(),
    }
    screenshot = output_dir / "screenshots" / f"{safe_name(combo, state)}.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)

    driver = None
    with tempfile.TemporaryDirectory(prefix="keybinding-profile-") as profile_directory:
        try:
            driver = webdriver_for(platform_name, browser, Path(profile_directory))
            driver.set_page_load_timeout(15)
            driver.get(harness_url)
            driver.find_element("id", "target").click()
            if platform_name == "macos":
                if mac_injector is None:
                    raise RuntimeError("macOS injector was not supplied")
                result["nativePointerFocus"] = focus_macos_textarea(mac_injector, target["bundle"], driver)
            # Preserve Chromium's renderer focus, then foreground its browser
            # window without directing focus to the top-level native frame.
            if platform_name == "windows" and not combo.startswith("meta→"):
                result["foregroundWindow"] = activate_windows_browser(driver.title)
                if browser in {"chrome", "edge"}:
                    result["nativePointerFocus"] = focus_windows_textarea(driver)
                    # SendInput is asynchronous relative to the WebDriver
                    # control channel. Let the real click settle before the
                    # passive harness resets its sentinel state.
                    time.sleep(0.2)
            driver.execute_script("window.__keybindingEvidence.setState(arguments[0])", state)
            time.sleep(0.2)
            environment["browserVersion"] = browser_version(driver.capabilities)
            before = snapshot(driver)
            result["before"] = before

            if platform_name == "windows" and combo.startswith("meta→"):
                result["kind"] = "os-level"
                result["summary"] = "Windows-logo shortcut was not injected; its OS-level behavior is sourced from WIN-KEYBOARD."
                result["after"] = before
            else:
                if platform_name == "windows":
                    inject_windows(combo, scan_codes=browser in {"chrome", "edge"})
                else:
                    if mac_injector is None:
                        raise RuntimeError("macOS injector was not supplied")
                    inject_macos(mac_injector, target["bundle"], combo)
                time.sleep(0.75)
                try:
                    after = snapshot(driver)
                    result["after"] = after
                    if changed(before, after):
                        result["kind"] = "observed"
                        result["summary"] = "Textarea state, browser focus, URL, or window count changed after real OS input."
                    else:
                        result["kind"] = "observed-no-effect"
                        result["summary"] = "No textarea, focus, URL, or window-count change was observed after real OS input."
                except Exception as error:  # Browser-chrome command may replace the tested page.
                    result["kind"] = "observed"
                    result["summary"] = "The tested page became unavailable after real OS input; inspect the screenshot and driver error."
                    result["error"] = f"Postcondition unavailable: {error}"
        except Exception as error:
            result["kind"] = "injector-failure"
            result["summary"] = "The browser, native injector, or postcondition probe failed; no behavior was inferred."
            result["error"] = str(error)
        finally:
            if driver is not None:
                try:
                    driver.save_screenshot(str(screenshot))
                except Exception as error:
                    result["error"] = (result["error"] + "; " if result["error"] else "") + f"Screenshot failed: {error}"
                try:
                    driver.quit()
                except Exception:
                    pass
            terminate_browser(platform_name, browser)
    return record


def write_summary(records: list[dict[str, Any]], path: Path, title: str) -> None:
    counts: dict[str, int] = {}
    for record in records:
        kind = record["result"]["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    lines = [f"# {title}", "", f"Captured: {now()}", "", "## Result counts", ""]
    for kind in sorted(counts):
        lines.append(f"- `{kind}`: {counts[kind]}")
    failures = [record for record in records if record["result"]["kind"] == "injector-failure"]
    if failures:
        lines.extend(["", "## Injector failures", ""])
        for record in failures:
            lines.append(f"- `{record['combo']}` / `{record['state']}`: {record['result']['error']}")
    lines.extend(["", "Review raw JSON and screenshots before copying any outcome into README.md.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["macos", "windows"], required=True)
    parser.add_argument("--browser", choices=["safari", "chrome", "edge", "firefox"], required=True)
    parser.add_argument("--combos", default="all", help="all or comma-separated canonical combos")
    parser.add_argument("--states", choices=["both", "caret", "selection"], default="both")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--mac-injector", type=Path)
    args = parser.parse_args()

    if (args.platform, args.browser) not in TARGETS:
        parser.error(f"{args.browser} is not a {args.platform} test target")
    if args.platform == "macos" and (args.mac_injector is None or not args.mac_injector.is_file()):
        parser.error("--mac-injector must point to the compiled macos-keypress helper")

    assert_us_layout(args.platform)
    combos = select_combos(table_combos(ROOT / "README.md"), args.combos)
    states = selected_states(args.states)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    server, harness_url = start_server()
    try:
        records = [
            observation_for_case(
                args.platform,
                args.browser,
                combo,
                state,
                harness_url,
                args.output.parent,
                args.runner_image,
                args.artifact,
                args.mac_injector,
            )
            for combo in combos
            for state in states
        ]
    finally:
        server.shutdown()
        server.server_close()

    document = {
        "schemaVersion": 1,
        "metadata": {
            "platform": args.platform,
            "browser": args.browser,
            "runnerImage": args.runner_image,
            "inputLayout": "U.S.",
            "cleanProfile": True,
            "generatedAt": now(),
        },
        "observations": records,
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    write_summary(records, args.summary, f"{args.platform} {args.browser} keybinding evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
