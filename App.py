# yalda_webhook.py
# WSGI app (Flask) برای استقرار روی Render (یا هر PaaS)
import os
import logging
import openai
from flask import Flask, request, jsonify
import requests
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("لطفاً TELEGRAM_TOKEN و OPENAI_API_KEY را ست کن.")

openai.api_key = OPENAI_API_KEY
BOT_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)
CONVOS = {}
MAX_HISTORY = 12
SENSITIVE_PATTERNS = ["خودکُشی","آزار","تجاوز","کودک","suicide","self-harm"]

def append_msg(uid, role, text):
    c = CONVOS.setdefault(uid, [])
    c.append({"role": role, "content": text})
    if len(c) > MAX_HISTORY:
        CONVOS[uid] = c[-MAX_HISTORY:]

def check_sensitive(text):
    low = text.lower()
    for p in SENSITIVE_PATTERNS:
        if p in low:
            return True
    return False

def system_prompt():
    return (
        "تو یک ربات به نام یلدا هستی. بسیار مهربان، حساس و احساسی و تا جای ممکن عاشقانه "
        "با کاربر حرف بزن، ولی از تولید محتوای صریح جنسی یا تشویق به آسیب زدن به خود یا دیگران خودداری کن. "
        "در موضوعات حساس کاربر را به کمک حرفه‌ای هدایت کن."
    )

def ask_openai(user_id, user_text):
    if check_sensitive(user_text):
        return ("متأسفم، دربارهٔ این موضوع نمی‌تونم صحبت کنم. "
                "اگر در خطر هستی لطفاً فوراً با خدمات اورژانسی یا یک فرد قابل اعتماد تماس بگیر.")
    msgs = [{"role":"system","content": system_prompt()}] + CONVOS.get(user_id, [])
    msgs.append({"role":"user","content": user_text})
    append_msg(user_id, "user", user_text)
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=msgs,
            max_tokens=300,
            temperature=0.9
        )
        out = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("OpenAI error")
        out = "متأسفم، الان مشکلی پیش اومد و نمی‌تونم جواب بدم."
    append_msg(user_id, "assistant", out)
    return out

def send_message(chat_id, text):
    url = f"{BOT_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        logger.exception("Failed to send message")

@app.route("/healthz")
def health():
    return "ok"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "no json"}), 400

    # handle message updates
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]

        if not text:
            send_message(chat_id, "میشه لطفاً چیزی بنویسی؟")
            return jsonify({"ok": True})

        # process in background thread to return 200 quickly
        def worker():
            if check_sensitive(text):
                send_message(chat_id,
                    "متأسفم، دربارهٔ این موضوع نمی‌تونم صحبت کنم. اگر در خطر هستی با خدمات اورژانسی تماس بگیر.")
                return
            reply = ask_openai(user_id, text)
            if len(reply) > 4000:
                reply = reply[:3990] + "…"
            send_message(chat_id, reply)

        threading.Thread(target=worker).start()
        return jsonify({"ok": True})

    return jsonify({"ok": True})

# helper route to set webhook from server (optionally)
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    # expects env variable BASE_URL set to the public URL or use request.host_url
    base = os.getenv("BASE_URL") or request.host_url.rstrip('/')
    webhook_url = f"{base}/webhook"
    resp = requests.get(f"{BOT_API}/setWebhook?url={webhook_url}")
    return jsonify(resp.json())

if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
