#!/usr/bin/env python3
"""
jarvis.py — Private on-device assistant with chunked memory.

Run:
    export GROQ_API_KEY="gsk_..."
    python jarvis.py

Web search: uses DuckDuckGo's free HTML results page — no signup, no API
key, no card required. Only triggers on messages that look time-sensitive.

How memory works here (see memory.py for details):
    - Every turn is saved to SQLite immediately (cheap, small).
    - Only the last N turns ("active chunk") are sent to the model by default.
    - If your message looks like it's referencing something old
      ("remember when...", "what did I say about...", "earlier..."),
      Jarvis searches old chunks via FTS5 and injects just the matches —
      it never resends the whole history.
"""

import os
import sys
import re
import json
import time
import urllib.request
import memory
import phone
import adb_control

GROQ_MODEL = "openai/gpt-oss-120b"  # groq/compound (web search) currently throws spurious 413 errors — reverted to stable model
ACTIVE_CHUNK_SIZE = 10  # smaller window keeps request size safely under limits
MAX_MESSAGE_CHARS = 4000  # truncate any single stored message before resending it
SEARCH_TRIGGERS = ("latest", "news", "today", "current", "right now", "score", "who won",
                    "price of", "weather", "this week", "2027", "2026")

SYSTEM_PROMPT = (
    "You are Jarvis, a private, on-device assistant for the user. "
    "Be concise, direct, and practical. If OLDER CONTEXT is provided below, "
    "use it only if relevant to the current message. If SEARCH RESULTS are provided, "
    "answer using only those results and say so — do not invent facts, dates, scores, "
    "or details beyond what the search results state. If the results don't answer the "
    "question, say you couldn't find it rather than guessing."
)


def duckduckgo_search(query: str, max_results: int = 5):
    """
    Free web search with zero signup and zero API key — scrapes DuckDuckGo's
    lightweight HTML results page. No account, no card, no key required.
    """
    import re
    from urllib.parse import quote, unquote

    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DuckDuckGo HTTP {e.code}") from None

    # Each result sits in a <a class="result__a" href="...">Title</a> plus a snippet div
    results = []
    link_pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snippet_pattern = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)
    tag_strip = re.compile(r'<[^>]+>')

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(links[:max_results]):
        clean_title = tag_strip.sub("", title).strip()
        clean_snippet = tag_strip.sub("", snippets[i]).strip() if i < len(snippets) else ""
        # DuckDuckGo wraps real URLs in a redirect param
        real_url = href
        if "uddg=" in href:
            real_url = unquote(href.split("uddg=")[-1].split("&")[0])
        results.append((clean_title, clean_snippet, real_url))

    return results


def wants_search(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in SEARCH_TRIGGERS)


RECALL_TRIGGERS = ("remember", "earlier", "before", "what did i", "you said", "we talked", "last time")

# Friendly name -> Android package name, so "open whatsapp" works without knowing package IDs.
# Add more of your own apps here as you find their package names (Settings > Apps > [app] > Advanced).
APP_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "facebook": "com.facebook.katana",
    "instagram": "com.instagram.android",
    "gmail": "com.google.android.gm",
    "play store": "com.android.vending",
    "settings": "com.android.settings",
    "camera": "com.android.camera",
    "gallery": "com.android.gallery3d",
    "maps": "com.google.android.apps.maps",
    "spotify": "com.spotify.music",
    "termux": "com.termux",
}


def call_groq(messages, api_key):
    # Groq's API is OpenAI-compatible: chat.completions format, system is a normal message
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": full_messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "jarvis-cli/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    return data["choices"][0]["message"]["content"]


def wants_recall(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in RECALL_TRIGGERS)


def build_messages(user_input: str):
    """Active chunk + (optionally) on-demand loaded old chunks + real search results."""
    history = memory.get_active_chunk(ACTIVE_CHUNK_SIZE)
    messages = [
        {"role": r, "content": c[:MAX_MESSAGE_CHARS]} for r, c in history
    ]

    if wants_recall(user_input):
        hits = memory.search_old_chunks(user_input, limit=5)
        if hits:
            recalled = "\n".join(f"[{day}] {role}: {content}" for day, role, content in hits)
            messages.append({
                "role": "user",
                "content": f"OLDER CONTEXT (retrieved from memory, may or may not be relevant):\n{recalled}"
            })

    if wants_search(user_input):
        try:
            results = duckduckgo_search(user_input)
            if results:
                formatted = "\n\n".join(f"[{title}]({url})\n{content}" for title, content, url in results)
                messages.append({
                    "role": "user",
                    "content": f"SEARCH RESULTS (live, from the web just now):\n{formatted}"
                })
            else:
                print("[search returned no results]")
        except Exception as e:
            print(f"[search unavailable: {e}]")

    messages.append({"role": "user", "content": user_input})
    return messages


_pending_whatsapp = None  # holds {'candidates': [...], 'message': str} between turns
# when a contact name matches multiple people — set by try_phone_command,
# consumed by the very next message if it's a bare number selection.


def _try_auto_complete_whatsapp():
    """
    After opening a WhatsApp chat with a pre-filled message, this auto-taps
    Send and switches back to the browser — but ONLY if ADB is currently
    connected. If it isn't (no WiFi, not paired this session, etc.), this
    quietly does nothing and the message stays pre-filled for a manual tap,
    exactly like before ADB existed. Never breaks the base feature.
    """
    if not adb_control.is_connected():
        return ""
    try:
        time.sleep(2.5)  # give WhatsApp a moment to open and load the chat
        adb_control.tap_element("send")
        time.sleep(0.5)
        adb_control.bring_app_to_front("com.android.chrome")
        return " — sent automatically, and switched back here"
    except adb_control.AdbError:
        return " (auto-send attempted but failed — tap Send manually)"


def try_phone_command(text: str):
    """
    Checks if the input is a direct phone-control command and executes it.
    Returns a result string if handled, or None if this wasn't a phone command
    (in which case the message falls through to the normal LLM path).
    Rule-based on purpose: phone actions should never be guessed by the LLM —
    either a real command runs, or nothing does.
    """
    global _pending_whatsapp
    t = text.lower().strip()

    # If we're waiting on a contact pick from the last turn, check that first.
    if _pending_whatsapp is not None:
        sel = re.fullmatch(r"\D*(\d{1,2})\D*", t)  # "2", "number 2", "option 2", "2nd"...
        pending = _pending_whatsapp
        _pending_whatsapp = None  # always clear — a stale pick should never silently reapply later
        if sel:
            idx = int(sel.group(1)) - 1
            candidates = pending["candidates"]
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                try:
                    return phone.send_whatsapp(chosen.get("number", ""), pending["message"])
                except phone.PhoneError as e:
                    return f"[phone error] {e}"
            return f"[phone error] '{sel.group(1)}' isn't one of the listed options (1-{len(candidates)})."
        # else: they said something else — treat as a normal new message below,
        # falling through to the rest of the dispatcher / LLM as usual.

    try:
        # Flashlight
        # Flashlight — matches any phrasing/order: "turn on flashlight", "flashlight on
        # please", "torch on", "switch off torch", etc. Check "off" first since a
        # message could otherwise falsely match "on" inside another word.
        if re.search(r"\b(flashlight|torch)\b", t):
            if re.search(r"\boff\b", t):
                return phone.torch(False)
            if re.search(r"\bon\b", t):
                return phone.torch(True)

        # Battery
        if "battery" in t:
            b = phone.battery_status()
            return f"Battery: {b['percentage']}% ({b['status']})"

        # Volume: "set music volume to 8" / "volume up"
        m = re.search(r"set (\w+) volume to (\d+)", t)
        if m:
            return phone.set_volume(m.group(1), int(m.group(2)))

        # Brightness: "set brightness to 150"
        m = re.search(r"set brightness to (\d+|auto)", t)
        if m:
            val = m.group(1)
            return phone.set_brightness(val if val == "auto" else int(val))

        # Call
        m = re.search(r"\bcall (\+?\d[\d\s-]{5,})", t)
        if m:
            return phone.make_call(m.group(1).strip())

        # SMS: "send sms to 12345 saying hello there"
        m = re.search(r"send (?:an )?sms to (\+?\d[\d\s-]{5,}) saying (.+)", t)
        if m:
            return phone.send_sms(m.group(1).strip(), m.group(2).strip())

        # Location
        if re.search(r"\b(where am i|my location|current location)\b", t):
            loc = phone.get_location()
            return f"Location: lat {loc.get('latitude')}, lon {loc.get('longitude')}"

        # Notification: "notify me: title | message"
        m = re.search(r"notify me[:\s]+(.+)", t, re.I)
        if m:
            content = m.group(1)
            if "|" in content:
                title, body = content.split("|", 1)
            else:
                title, body = "Jarvis", content
            return phone.notify(title.strip(), body.strip())

        # Open app: friendly name first ("open whatsapp"), then raw package name fallback
        m = re.search(r"^open (?:app )?(.+)$", t)
        if m:
            name = m.group(1).strip()
            if name in APP_PACKAGES:
                return phone.open_app(APP_PACKAGES[name])
            if "." in name:  # looks like a raw package name
                return phone.open_app(name)

        # WhatsApp message: "message <name/number> on whatsapp: <text>"
        #                    "whatsapp <name/number> saying <text>"
        #                    "send whatsapp to <name/number> saying <text>"
        m = re.search(r"^message (.+?) on whatsapp[:\s]+(.+)$", t)
        if not m:
            m = re.search(r"^whatsapp (.+?) saying (.+)$", t)
        if not m:
            m = re.search(r"^send whatsapp(?: message)? to (.+?) saying (.+)$", t)
        if m:
            recipient, msg_text = m.group(1).strip(), m.group(2).strip()
            if phone.looks_like_number(recipient):
                return phone.send_whatsapp(recipient, msg_text)
            matches = phone.find_contact(recipient)
            if not matches:
                return f"[phone error] No contact found matching '{recipient}'"
            if len(matches) == 1:
                return phone.send_whatsapp(matches[0].get("number", ""), msg_text)
            # Multiple matches — show a numbered picker and wait for the next message to pick one
            _pending_whatsapp = {"candidates": matches, "message": msg_text}
            lines = [f"{i+1}. {c['name']} — {c.get('number', '?')}" for i, c in enumerate(matches[:8])]
            return "Multiple contacts match '{}':\n{}\nReply with a number to send.".format(
                recipient, "\n".join(lines)
            )

        # Vibrate
        if "vibrate" in t:
            return phone.vibrate()

        # Alarm/reminder: "set alarm for 7am" / "set alarm for 7:30am wake up"
        #                  "remind me at 3:30pm to call mom"
        m = re.search(r"remind me at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+to (.+)", t)
        if not m:
            m2 = re.search(r"set (?:an? )?alarm for (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to |for )?(.*)", t)
            if m2:
                m = m2
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            ampm = m.group(3)
            label = m.group(4).strip() if m.group(4) else "Jarvis reminder"
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return phone.set_alarm(hour, minute, label or "Jarvis reminder")

        # Media control
        if re.search(r"\b(play|pause)\b.*\bmusic\b|\bplay.?pause\b", t) or t in ("play", "pause"):
            return phone.media_play_pause()
        if re.search(r"\bnext (song|track)\b", t) or t == "skip":
            return phone.media_next()
        if re.search(r"\b(previous|last) (song|track)\b", t):
            return phone.media_previous()

        # WiFi / Bluetooth toggle
        if "wifi" in t and re.search(r"\b(on|off|toggle)\b", t):
            return phone.wifi_toggle()
        if "bluetooth" in t and re.search(r"\b(on|off|toggle)\b", t):
            return phone.bluetooth_toggle()

        # Screenshot + read screen text (OCR)
        if re.search(r"\b(read|what.?s on) (my |the )?screen\b", t) or t == "screenshot":
            return phone.take_screenshot_and_read()

        # Speak: "say hello" / "speak hello"
        m = re.search(r"^(?:say|speak) (.+)", t)
        if m:
            phone.speak(m.group(1))
            return f"Spoke: {m.group(1)}"

        # Listen: "listen" triggers mic capture, returned to caller as new input
        if t in ("listen", "listen to me", "voice input"):
            heard = phone.listen()
            return f"[heard]: {heard}" if heard else "[heard nothing]"

        # Clipboard
        if t in ("read clipboard", "what's in my clipboard"):
            return phone.clipboard_get()

        # --- ADB touch/key control (requires wireless debugging paired — see adb_control.py) ---

        # Tap: "tap 500 800"
        m = re.search(r"^tap (\d+)[,\s]+(\d+)$", t)
        if m:
            return adb_control.tap(int(m.group(1)), int(m.group(2)))

        # Swipe: "swipe 100 800 100 200"
        m = re.search(r"^swipe (\d+)[,\s]+(\d+)[,\s]+(\d+)[,\s]+(\d+)$", t)
        if m:
            return adb_control.swipe(*[int(g) for g in m.groups()])

        # Key press: "press back" / "press tab" / "press enter"
        m = re.search(r"^press (\w+)$", t)
        if m:
            return adb_control.keyevent(m.group(1))

        # Type text on-screen: "type on screen: hello there"
        m = re.search(r"^type on screen[:\s]+(.+)$", t)
        if m:
            return adb_control.type_text(m.group(1))

    except phone.PhoneError as e:
        return f"[phone error] {e}"
    except adb_control.AdbError as e:
        return f"[adb error] {e} — is adb connected? Run 'adb devices' in Termux to check."

    return None  # not a phone command — fall through to LLM


def main():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Set GROQ_API_KEY first: export GROQ_API_KEY='gsk_...'")
        sys.exit(1)

    memory.init_db()
    print(f"Jarvis online. Memory: {memory.db_size_kb():.1f} KB on disk. Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJarvis offline.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Jarvis offline.")
            break

        memory.add_message("user", user_input)

        phone_result = try_phone_command(user_input)
        if phone_result is not None:
            print(f"jarvis> {phone_result}\n")
            memory.add_message("assistant", phone_result)
            continue

        messages = build_messages(user_input)

        try:
            reply = call_groq(messages, api_key)
        except Exception as e:
            print(f"[error] {e}")
            continue

        memory.add_message("assistant", reply)
        print(f"jarvis> {reply}\n")


if __name__ == "__main__":
    main()
