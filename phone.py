"""
phone.py — Real phone control for Jarvis via Termux:API.

Requires:
  pkg install termux-api
  + the Termux:API companion app installed and opened once (for permissions)

Everything here shells out to the termux-* binaries that Termux:API provides.
No root needed for any of this.
"""

import json
import re
import subprocess
import time


class PhoneError(Exception):
    pass


def _run(cmd, timeout=15):
    """Run a termux-api command and return its stdout, raising PhoneError on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise PhoneError(
            f"'{cmd[0]}' not found — is Termux:API installed? Run: pkg install termux-api"
        )
    except subprocess.TimeoutExpired:
        raise PhoneError(f"'{cmd[0]}' timed out")

    if result.returncode != 0 and not result.stdout.strip():
        raise PhoneError(result.stderr.strip() or f"{cmd[0]} failed")
    return result.stdout.strip()


# ---------- Communication ----------

def send_sms(number: str, message: str):
    _run(["termux-sms-send", "-n", number, message])
    return f"SMS sent to {number}"


def make_call(number: str):
    _run(["termux-telephony-call", number])
    return f"Calling {number}"


# ---------- Hardware ----------

def torch(on: bool):
    _run(["termux-torch", "on" if on else "off"])
    return f"Flashlight {'on' if on else 'off'}"


def set_volume(stream: str, level: int):
    # stream: call, system, ring, music, alarm, notification
    _run(["termux-volume", stream, str(level)])
    return f"{stream} volume set to {level}"


def set_brightness(level: int):
    # 0-255, or "auto"
    _run(["termux-brightness", str(level)])
    return f"Brightness set to {level}"


def battery_status():
    out = _run(["termux-battery-status"])
    return json.loads(out)


def vibrate(duration_ms: int = 500):
    _run(["termux-vibrate", "-d", str(duration_ms)])
    return "Vibrated"


# ---------- Notifications ----------

def notify(title: str, content: str):
    _run(["termux-notification", "--title", title, "--content", content])
    return "Notification sent"


# ---------- Location ----------

def get_location():
    out = _run(["termux-location", "-p", "network"], timeout=30)
    return json.loads(out)


# ---------- Apps ----------

def open_app(package: str):
    """Launch an installed app by its package name, e.g. com.whatsapp"""
    activity = _run([
        "sh", "-c",
        f"cmd package resolve-activity --brief {package} | tail -1"
    ])
    if not activity or "No activity found" in activity:
        raise PhoneError(f"Could not resolve launch activity for '{package}'")
    _run(["am", "start", "-n", activity])
    return f"Opened {package}"


def open_url(url: str):
    _run(["termux-open-url", url])
    return f"Opened {url}"


# ---------- Voice ----------

def speak(text: str):
    _run(["termux-tts-speak", text], timeout=30)
    return "Spoken"


def listen(timeout=15) -> str:
    """Voice-to-text: prompts the mic and returns transcribed text."""
    out = _run(["termux-speech-to-text"], timeout=timeout)
    return out.strip()


# ---------- Clipboard ----------

def clipboard_get():
    return _run(["termux-clipboard-get"])


def clipboard_set(text: str):
    _run(["termux-clipboard-set", text])
    return "Copied to clipboard"


# ---------- Contacts & WhatsApp ----------

def get_contacts():
    out = _run(["termux-contact-list"], timeout=20)
    return json.loads(out)


def find_contact(name: str):
    """Case-insensitive substring match against saved contact names, deduplicated —
    Android often has the same person saved twice (e.g. phone + WhatsApp sync)."""
    contacts = get_contacts()
    needle = name.lower()
    matches = [c for c in contacts if needle in c.get("name", "").lower()]

    seen = set()
    deduped = []
    for c in matches:
        key = (c.get("name", "").strip().lower(), re.sub(r"[^\d+]", "", c.get("number", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def looks_like_number(s: str) -> bool:
    digits = re.sub(r"[^\d+]", "", s)
    return len(digits) >= 7


def send_whatsapp(number: str, message: str):
    """
    Opens a WhatsApp chat with a KNOWN number, message pre-filled.
    Use this directly once a contact has already been resolved (e.g. after
    the user picked one from a disambiguation list) — no contact lookup here.

    Note: Android does not allow apps to auto-send WhatsApp messages
    (anti-spam protection) — this pre-fills the text; you still tap
    Send yourself.
    """
    from urllib.parse import quote

    clean = re.sub(r"[^\d+]", "", number).lstrip("+")
    if not clean:
        raise PhoneError(f"'{number}' doesn't look like a valid number")
    url = f"https://wa.me/{clean}?text={quote(message)}"
    _run(["termux-open-url", url])

    if auto_send_enabled():
        trigger_macrodroid("send_whatsapp")
        return f"Opened WhatsApp chat for {number} — auto-sending via MacroDroid..."
    return f"Opened WhatsApp chat for {number} with your message pre-filled — tap Send to deliver it"


def whatsapp_message(recipient: str, message: str):
    """
    Convenience wrapper: resolves a name or number in one call.
    Raises PhoneError on no-match or ambiguous-match (multiple contacts) —
    for interactive disambiguation (numbered picker), use find_contact() +
    send_whatsapp() directly instead, as jarvis.py's dispatcher does.
    """
    if looks_like_number(recipient):
        return send_whatsapp(recipient, message)

    matches = find_contact(recipient)
    if not matches:
        raise PhoneError(f"No contact found matching '{recipient}'")
    if len(matches) > 1:
        names = ", ".join(f"{m['name']} ({m.get('number', '?')})" for m in matches[:5])
        raise PhoneError(f"Multiple contacts match '{recipient}': {names}. Be more specific.")
    number = matches[0].get("number", "")
    if not number:
        raise PhoneError(f"Found '{matches[0]['name']}' but they have no saved number")
    return send_whatsapp(number, message)


# ---------- MacroDroid auto-send trigger (no root, no ADB, no WiFi required) ----------
#
# Jarvis can't tap WhatsApp's Send button itself (Android blocks that for any
# app without root or ADB). Instead, this writes a small "trigger file" to
# shared storage. A MacroDroid macro on your phone watches that file via its
# Accessibility permission and does the actual tap + switch back to the
# browser — entirely on-device, no network involved.
#
# Setup required once:
#   1. In Termux: termux-setup-storage   (grants Termux access to /sdcard)
#   2. Install MacroDroid, set up the macro described in the project README
# Off by default — set JARVIS_AUTO_SEND=1 to enable once your macro is ready.

import os

TRIGGER_DIR = os.path.expanduser("~/storage/shared/jarvis_triggers")


def auto_send_enabled() -> bool:
    return os.environ.get("JARVIS_AUTO_SEND") == "1"


def trigger_macrodroid(action: str = "send_whatsapp"):
    """
    Writes/updates a small file MacroDroid watches for. The content (a
    timestamp) changes every call so MacroDroid's "file modified" trigger
    fires reliably even if the file already existed.
    """
    try:
        os.makedirs(TRIGGER_DIR, exist_ok=True)
        path = os.path.join(TRIGGER_DIR, f"{action}.trigger")
        with open(path, "w") as f:
            f.write(str(time.time()))
        return True
    except OSError as e:
        raise PhoneError(f"Could not write MacroDroid trigger file: {e}")


# ---------- Alarms & reminders (native Android intent — no MacroDroid needed) ----------

def set_alarm(hour: int, minute: int, label: str = "Jarvis reminder"):
    """
    Creates a real alarm using Android's built-in SET_ALARM intent — every
    clock app supports this, no extra setup required. Some clock apps
    (including Vivo's stock one) may briefly show a confirmation screen
    instead of saving silently; that's normal, just tap confirm once.
    """
    _run([
        "am", "start",
        "-a", "android.intent.action.SET_ALARM",
        "--ei", "android.intent.extra.alarm.HOUR", str(hour),
        "--ei", "android.intent.extra.alarm.MINUTES", str(minute),
        "--es", "android.intent.extra.alarm.MESSAGE", label,
        "--ez", "android.intent.extra.alarm.SKIP_UI", "true",
    ])
    return f"Alarm set for {hour:02d}:{minute:02d} — \"{label}\""


# ---------- Media, WiFi/Bluetooth, Screenshot (MacroDroid triggers) ----------
#
# Same trigger-file pattern as WhatsApp auto-send. Each of these needs ONE
# new MacroDroid macro (simpler than the WhatsApp one — no element-ID
# clicking, just a single built-in MacroDroid action per macro):
#
#   media_play_pause  -> trigger file -> MacroDroid action: Media > Play/Pause
#   media_next        -> trigger file -> MacroDroid action: Media > Next Track
#   media_previous     -> trigger file -> MacroDroid action: Media > Previous Track
#   wifi_toggle        -> trigger file -> MacroDroid action: Device Settings > Wifi > Toggle
#   bluetooth_toggle   -> trigger file -> MacroDroid action: Device Settings > Bluetooth > Toggle
#   screenshot         -> trigger file -> MacroDroid action: Device Actions > Take Screenshot
#                          (save path: /storage/emulated/0/jarvis_triggers/screenshot.png)
#
# All of these are silently skipped (raise PhoneError) if you haven't
# built that specific macro yet — build them one at a time as you need them.

def media_play_pause():
    trigger_macrodroid("media_play_pause")
    return "Toggled play/pause"


def media_next():
    trigger_macrodroid("media_next")
    return "Skipped to next track"


def media_previous():
    trigger_macrodroid("media_previous")
    return "Went to previous track"


def wifi_toggle():
    trigger_macrodroid("wifi_toggle")
    return "Toggled WiFi"


def bluetooth_toggle():
    trigger_macrodroid("bluetooth_toggle")
    return "Toggled Bluetooth"


SCREENSHOT_PATH = os.path.expanduser("~/storage/shared/jarvis_triggers/screenshot.png")


def take_screenshot_and_read():
    """
    Triggers MacroDroid to capture a screenshot, waits for it to land,
    then OCRs it locally with tesseract (fully offline, no network).
    Requires: pkg install tesseract
    """
    if os.path.exists(SCREENSHOT_PATH):
        os.remove(SCREENSHOT_PATH)  # so we can tell a fresh one arrived

    trigger_macrodroid("screenshot")

    for _ in range(20):  # wait up to ~4s for MacroDroid to save the file
        if os.path.exists(SCREENSHOT_PATH):
            break
        time.sleep(0.2)
    else:
        raise PhoneError("Screenshot didn't arrive — is the 'screenshot' MacroDroid macro set up?")

    result = subprocess.run(
        ["tesseract", SCREENSHOT_PATH, "stdout"],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise PhoneError(f"OCR failed: {result.stderr.strip() or 'is tesseract installed? pkg install tesseract'}")
    text = result.stdout.strip()
    return text if text else "(screenshot captured, but no readable text found)"
