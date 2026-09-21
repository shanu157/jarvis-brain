import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
"""
app.py — Flask web GUI for Jarvis.

Reuses everything from jarvis.py, memory.py, phone.py — no logic duplicated.
Run:
    pip install flask --break-system-packages
    export GROQ_API_KEY="gsk_..."
    python app.py
Then open http://127.0.0.1:5000 in your phone's browser.
Once open, use the browser menu > "Add to Home screen" to install it as an app.
"""

import os
from flask import Flask, request, jsonify, send_from_directory

import memory
import jarvis

app = Flask(__name__, static_folder="static", static_url_path="/static")


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/.well-known/assetlinks.json")
def assetlinks():
    # Must be served at the domain root — Android's Digital Asset Link
    # verifier checks exactly this path, not /static/.well-known/...
    return send_from_directory("static/.well-known", "assetlinks.json")


@app.route("/api/status")
def status():
    return jsonify({"memory_kb": round(memory.db_size_kb(), 1)})


@app.route("/api/chat", methods=["POST"])
def chat():
    image_bytes = None
    image_mime = None
    image_name = None

    # ---------------------------------------------------------
    # PHOTO REQUEST = multipart/form-data
    # NORMAL REQUEST = application/json
    # ---------------------------------------------------------

    if request.files:
        user_input = (request.form.get("message") or "").strip()
        image = request.files.get("image")

        if image and image.filename:
            image_bytes = image.read()
            image_mime = image.mimetype or "image/jpeg"
            image_name = image.filename

            if not image_bytes:
                return jsonify({
                    "error": "The image upload was empty."
                }), 400

            if not image_mime.startswith("image/"):
                return jsonify({
                    "error": "Please send an image file."
                }), 400

            if len(image_bytes) > 20 * 1024 * 1024:
                return jsonify({
                    "error": "That image is too large. Please use a photo under 20 MB."
                }), 400

    else:
        data = request.get_json(force=True) or {}
        user_input = (data.get("message") or "").strip()

    # Allow photo-only messages.
    if not user_input and image_bytes:
        user_input = (
            "Look at this photo carefully and tell me what you see. "
            "Answer naturally and directly."
        )

    if not user_input:
        return jsonify({"error": "empty message"}), 400

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        return jsonify({
            "error": "GROQ_API_KEY not set on the server"
        }), 500

    memory.add_message("user", user_input)

    # ---------------------------------------------------------
    # GROQ VISION for photos
    # GROQ TEXT for normal messages
    # ---------------------------------------------------------

    try:
        if image_bytes:
            reply = jarvis.call_groq_vision(
                user_input,
                image_bytes,
                image_mime,
                api_key
            )
        else:
            messages = jarvis.build_messages(user_input)
            reply = jarvis.call_groq(messages, api_key)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 502

    memory.add_message("assistant", reply)

    return jsonify({
        "reply": reply,
        "type": "chat",
        "image": bool(image_bytes),
        "filename": image_name
    })


memory.init_db()  # must run on import too, not just direct execution — WSGI servers import this module rather than running it as __main__



@app.route("/api/plan", methods=["POST"])
def plan():
    """
    Jarvis V5 planner.

    The cloud Brain understands natural language and returns
    structured actions. Android remains responsible for actually
    executing phone actions.
    """

    try:
        data = request.get_json(force=True) or {}

        user_input = (
            data.get("message")
            or data.get("text")
            or ""
        ).strip()

        if not user_input:
            return jsonify({
                "error": "empty message"
            }), 400

        conversation = data.get(
            "conversation",
            []
        )

        memories = data.get(
            "memories",
            []
        )

        timezone_name = (
            data.get("timezone")
            or "Asia/Kolkata"
        )

        locale_name = (
            data.get("locale")
            or "en-IN"
        )

        try:
            now = datetime.now(
                ZoneInfo(timezone_name)
            )
        except Exception:
            now = datetime.now()

        conversation_text = json.dumps(
            conversation,
            ensure_ascii=False
        )

        memories_text = json.dumps(
            memories,
            ensure_ascii=False
        )

        system_prompt = """
You are JARVIS V5, a natural-language intent planner.

Your job is to understand what the user wants and return
STRICT JSON only.

You DO NOT execute phone commands.

Android will execute the actions you return.

Return this structure:

{
  "reply": "short natural response",
  "actions": []
}

Each action must be one of:

alarm:
{
  "type": "alarm",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "label": "text",
  "requires_confirmation": false
}

reminder:
{
  "type": "reminder",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "label": "text",
  "requires_confirmation": false
}

exam_reminder:
{
  "type": "exam_reminder",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "label": "text",
  "requires_confirmation": false
}

timer:
{
  "type": "timer",
  "seconds": 60,
  "label": "text",
  "requires_confirmation": false
}

torch:
{
  "type": "torch",
  "enabled": true,
  "requires_confirmation": false
}

call:
{
  "type": "call",
  "number": "phone number",
  "contact": "contact name",
  "requires_confirmation": true
}

sms:
{
  "type": "sms",
  "number": "phone number",
  "message": "message",
  "requires_confirmation": true
}

open_url:
{
  "type": "open_url",
  "url": "https://...",
  "requires_confirmation": false
}

open_app:
{
  "type": "open_app",
  "package": "package.name",
  "requires_confirmation": false
}

IMPORTANT RULES:

1. Never return shell commands.
2. Never return Termux commands.
3. Never invent a phone number.
4. Never invent a date or time if it cannot be inferred.
5. Use the supplied current date/time and timezone.
6. "tomorrow" means the next calendar day.
7. "today" means the current calendar day.
8. Multiple requests in one sentence may produce multiple actions.
9. For an exam, use exam_reminder.
10. Calls and SMS require confirmation.
11. Forgetting/deleting memories should be handled by Android.
12. Normal questions with no phone action should return:
   {
     "reply": "...",
     "actions": []
   }
13. Output JSON only. No markdown.
"""

        user_prompt = (
            "CURRENT DATETIME: "
            + now.isoformat()
            + "\nTIMEZONE: "
            + timezone_name
            + "\nLOCALE: "
            + locale_name
            + "\n\nRECENT CONVERSATION:\n"
            + conversation_text
            + "\n\nSAVED MEMORIES:\n"
            + memories_text
            + "\n\nUSER MESSAGE:\n"
            + user_input
        )

        api_key = os.environ.get(
            "GROQ_API_KEY"
        )

        if not api_key:
            return jsonify({
                "error":
                    "GROQ_API_KEY not set on the server"
            }), 500

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        raw = jarvis.call_groq(
            messages,
            api_key
        )

        text = raw.strip()

        # Remove accidental markdown fences.
        if text.startswith("```"):
            text = re.sub(
                r"^```(?:json)?\s*",
                "",
                text,
                flags=re.IGNORECASE
            )

            text = re.sub(
                r"\s*```$",
                "",
                text
            )

        # Extract JSON if the model added surrounding text.
        start = text.find("{")
        end = text.rfind("}")

        if start >= 0 and end > start:
            text = text[start:end + 1]

        result = json.loads(text)

        if not isinstance(result, dict):
            raise ValueError(
                "Planner returned invalid JSON."
            )

        if "actions" not in result:
            result["actions"] = []

        if not isinstance(
                result["actions"],
                list
        ):
            result["actions"] = []

        if "reply" not in result:
            result["reply"] = "Done."

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

