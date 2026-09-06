"""
adb_control.py — Real touchscreen taps, swipes, and key presses for Jarvis.

Why this needs ADB (unlike phone.py):
    Android sandboxes normal apps from injecting fake touches/keys — that's
    a security boundary, not a Termux limitation. ADB (debug) access is the
    standard, official way around it, no root required. This uses Android's
    built-in Wireless Debugging feature (Android 11+).

One-time setup (per device — survives reboots once paired):
    1. Settings > About phone > tap "Build number" 7 times (enables Developer options)
    2. Settings > Developer options > enable "Wireless debugging"
    3. Tap "Wireless debugging" > "Pair device with pairing code"
       — note the IP:PORT and 6-digit code shown
    4. In Termux:
         pkg install android-tools
         adb pair <ip>:<pairing-port>
         (enter the 6-digit code when prompted)
    5. Back on the main "Wireless debugging" screen, note the IP:PORT shown
       there (different port than pairing) — that's the connect port.
    6. In Termux:
         adb connect <ip>:<connect-port>
         adb devices        # should list your device as "device" (not "unauthorized")

You'll need to reconnect (step 6 only) each time Termux restarts or the
phone's IP changes — pairing (steps 3-4) usually only needs doing once.
"""

import subprocess


class AdbError(Exception):
    pass


def _adb(args, timeout=15):
    try:
        result = subprocess.run(["adb"] + args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AdbError("adb not found — run: pkg install android-tools")
    except subprocess.TimeoutExpired:
        raise AdbError("adb command timed out")

    if result.returncode != 0:
        raise AdbError(result.stderr.strip() or "adb command failed")
    return result.stdout.strip()


def is_connected() -> bool:
    try:
        out = _adb(["devices"])
    except AdbError:
        return False
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("List of")]
    return any("\tdevice" in l for l in lines)


def tap(x: int, y: int):
    _adb(["shell", "input", "tap", str(x), str(y)])
    return f"Tapped ({x}, {y})"


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    _adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
    return f"Swiped ({x1},{y1}) -> ({x2},{y2})"


def type_text(text: str):
    # ADB's input text needs spaces escaped
    escaped = text.replace(" ", "%s")
    _adb(["shell", "input", "text", escaped])
    return f"Typed: {text}"


# Common Android keyevent codes
KEYEVENTS = {
    "back": 4,
    "home": 3,
    "tab": 61,
    "enter": 66,
    "up": 19,
    "down": 20,
    "left": 21,
    "right": 22,
    "delete": 67,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
    "recent_apps": 187,
}


def keyevent(name: str):
    code = KEYEVENTS.get(name.lower())
    if code is None:
        raise AdbError(f"Unknown key '{name}'. Known: {', '.join(KEYEVENTS)}")
    _adb(["shell", "input", "keyevent", str(code)])
    return f"Pressed {name}"


def screenshot(local_path: str = "/sdcard/jarvis_screen.png"):
    """Takes a screenshot on the device — useful for Jarvis to 'see' the screen later."""
    _adb(["shell", "screencap", "-p", local_path])
    return f"Screenshot saved on device at {local_path}"
