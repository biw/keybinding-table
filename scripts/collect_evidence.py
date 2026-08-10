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

WINDOWS_KEY_CODES = {
    **{character: ord(character.upper()) for character in "abcdefghijklmnopqrstuvwxyz"},
    **{character: ord(character) for character in "0123456789"},
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "]": 0xDD,
    "'": 0xDE,
}
WINDOWS_MODIFIERS = {"ctrl": 0x11, "alt": 0x12, "meta": 0x5B}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def table_combos(readme: Path) -> list[str]:
    pattern = re.compile(r"^\|\s+\*\*`([^`]+)`\*\*", re.MULTILINE)
    combos = pattern.findall(readme.read_text(encoding="utf-8"))
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
        if result.returncode != 0 or "U.S." not in result.stdout:
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

    if browser == "safari":
        return webdriver.Safari()
    if browser == "firefox":
        from selenium.webdriver.firefox.options import Options

        options = Options()
        options.add_argument("-no-remote")
        options.add_argument("-profile")
        options.add_argument(str(profile))
        return webdriver.Firefox(options=options)

    if browser == "chrome":
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-sync")
        return webdriver.Chrome(options=options)

    if browser == "edge":
        from selenium.webdriver.edge.options import Options

        options = Options()
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-sync")
        return webdriver.Edge(options=options)

    raise RuntimeError(f"Unsupported browser {browser} on {platform_name}")


def inject_windows(combo: str) -> None:
    try:
        modifier, key = combo.split("→", maxsplit=1)
        modifier_code = WINDOWS_MODIFIERS[modifier]
        key_code = WINDOWS_KEY_CODES[key]
    except (KeyError, ValueError) as error:
        raise RuntimeError(f"Unsupported Windows U.S. ANSI combo: {combo}") from error

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    def event(code: int, key_up: bool = False) -> INPUT:
        return INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=code,
                wScan=0,
                dwFlags=KEYEVENTF_KEYUP if key_up else 0,
                time=0,
                dwExtraInfo=0,
            ),
        )

    inputs = (INPUT * 4)(event(modifier_code), event(key_code), event(key_code, True), event(modifier_code, True))
    sent = ctypes.windll.user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    if sent != 4:
        raise RuntimeError(f"SendInput inserted {sent}/4 events (winerror {ctypes.get_last_error()})")


def inject_macos(injector: Path, bundle: str, combo: str) -> None:
    result = run([str(injector), "--bundle", bundle, "--combo", combo])
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown CGEvent failure"
        raise RuntimeError(message)


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
                    inject_windows(combo)
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
