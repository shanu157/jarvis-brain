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


@app.route("/api/status")
def status():
    return jsonify({"memory_kb": round(memory.db_size_kb(), 1)})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "empty message"}), 400

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return jsonify({"error": "GROQ_API_KEY not set on the server"}), 500

    memory.add_message("user", user_input)

    # Phone commands short-circuit the LLM entirely, same as the CLI
    phone_result = jarvis.try_phone_command(user_input)
    if phone_result is not None:
        memory.add_message("assistant", phone_result)
        return jsonify({"reply": phone_result, "type": "action"})

    messages = jarvis.build_messages(user_input)
    try:
        reply = jarvis.call_groq(messages, api_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    memory.add_message("assistant", reply)
    return jsonify({"reply": reply, "type": "chat"})


if __name__ == "__main__":
    memory.init_db()
    app.run(host="0.0.0.0", port=5000)
