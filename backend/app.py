import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()


def parse_cors_origins() -> List[str] | str:
    """Parse CORS allowlist from env, fallback to permissive for local dev."""
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return "*"

    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return origins or "*"


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": parse_cors_origins()}})

# ===== Static Configuration =====
OWNER_NAME = os.getenv("OWNER_NAME", "Chaitu").strip() or "Chaitu"
ALLOWED_MODES = {"STUDY", "CHILL", "PUBLIC"}
MAX_USER_INPUT_LEN = 600
MAX_RESPONSE_TOKENS = 180
GROQ_MODEL = "llama3-8b-8192"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Future-ready placeholders for expanding features.
MEMORY_STORE_PLACEHOLDER = {
    "enabled": False,
    "provider": "file_or_database",
}
FEATURE_TOGGLES = {
    "wake_word_detection": False,
    "continuous_listening": False,
    "emotion_detection": False,
    "user_auth_system": False,
}


@dataclass
class LyraContext:
    current_speaker: str = OWNER_NAME
    mode: str = "CHILL"


def sanitize_input(text: str) -> str:
    """Sanitize user input for basic safety and stable prompting."""
    clean = re.sub(r"[<>`$\\]", " ", str(text or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:MAX_USER_INPUT_LEN]


def parse_speaker_switch(message: str, current_speaker: str) -> str:
    """
    Logical (not biometric) speaker switch rules:
      - "XYZ wants to talk" -> switch to XYZ
      - "I am back" -> switch to owner
    """
    lower_msg = message.lower()

    if re.search(r"\bi am back\b", lower_msg):
        return OWNER_NAME

    match = re.search(r"\b([a-zA-Z][a-zA-Z\s\-']{0,40})\s+wants to talk\b", message, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        # Keep names human-friendly and bounded.
        return candidate[:42]

    return current_speaker or OWNER_NAME


def parse_mode_switch(message: str, current_mode: str, is_owner: bool) -> Tuple[str, str]:
    """
    Parse mode switch commands and enforce owner-only mode changes.
    Returns: (updated_mode, optional_guardrail_reply)
    """
    lower_msg = message.lower()

    mode_match = re.search(r"switch to\s+(study|chill|public)\s+mode", lower_msg)
    if not mode_match:
        return current_mode, ""

    requested_mode = mode_match.group(1).upper()
    if requested_mode not in ALLOWED_MODES:
        return current_mode, "I can only switch between study, chill, and public modes."

    if not is_owner:
        return current_mode, f"Only {OWNER_NAME} can change my mode."

    return requested_mode, f"Mode changed to {requested_mode}."


def is_sensitive_request(message: str) -> bool:
    """Block sensitive requests for non-owner speakers."""
    sensitive_patterns = [
        r"system status",
        r"hidden command",
        r"personality parameter",
        r"api key",
        r"secret",
        r"internal config",
        r"admin",
    ]
    return any(re.search(pattern, message, flags=re.IGNORECASE) for pattern in sensitive_patterns)


def build_system_prompt(mode: str, is_owner: bool) -> str:
    """Create LYRA personality + mode + access policy prompt."""
    mode_styles = {
        "STUDY": "Be concise, educational, focused, and avoid jokes.",
        "CHILL": "Be friendly, warm, slightly casual, and helpful.",
        "PUBLIC": "Be neutral, privacy-safe, and avoid sharing personal details.",
    }

    access_policy = (
        f"Owner speaker is {OWNER_NAME}. You may assist with system-level controls when requested."
        if is_owner
        else f"Current speaker is not owner ({OWNER_NAME}). Do not reveal private/sensitive details or admin controls."
    )

    return (
        "You are LYRA, a female Indian AI voice assistant. "
        "Tone: calm, intelligent, emotionally aware (not dramatic). "
        "You speak in short voice-friendly replies suitable for TTS. "
        "Do not use emojis. You can respond in English, Hindi, Marathi, or mixed language naturally. "
        f"Current behavior mode is {mode}. {mode_styles.get(mode, mode_styles['CHILL'])} "
        f"{access_policy}"
    )


def call_groq_api(user_message: str, context: LyraContext, is_owner: bool) -> str:
    """Call Groq chat completion API with robust fallback handling."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return "Configuration issue: GROQ_API_KEY is missing on server."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": build_system_prompt(context.mode, is_owner)},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.5,
        "max_tokens": MAX_RESPONSE_TOKENS,
    }

    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        body: Dict = response.json() if response.content else {}

        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices or not isinstance(choices, list):
            return "I am having trouble understanding the model response right now."

        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = (message.get("content") or "").strip()
        if not content:
            return "I could not generate a complete reply at the moment."

        return content[:900]

    except requests.Timeout:
        return "I am taking longer than usual to respond. Please try again in a moment."
    except requests.RequestException:
        return "I am unable to reach my intelligence service right now. Please try again soon."
    except ValueError:
        return "I received an unreadable response from the model service."


@app.get("/health")
def health() -> Tuple[str, int]:
    return jsonify({"status": "ok", "service": "LYRA backend", "owner": OWNER_NAME}), 200


@app.get("/testkey")
def test_key() -> Tuple[str, int]:
    has_key = bool(os.getenv("GROQ_API_KEY", "").strip())
    return jsonify({"groq_key_present": has_key, "owner": OWNER_NAME}), 200


@app.post("/lyra")
def lyra() -> Tuple[str, int]:
    data = request.get_json(silent=True) or {}

    message = sanitize_input(data.get("message", ""))
    incoming_speaker = sanitize_input(data.get("currentSpeaker", OWNER_NAME)) or OWNER_NAME
    incoming_mode = str(data.get("mode", "CHILL") or "CHILL").upper()
    if incoming_mode not in ALLOWED_MODES:
        incoming_mode = "CHILL"

    if not message:
        return jsonify({"error": "Message is required.", "reply": "Please say something for me to process."}), 400

    context = LyraContext(current_speaker=incoming_speaker, mode=incoming_mode)
    context.current_speaker = parse_speaker_switch(message, context.current_speaker)

    is_owner = context.current_speaker.strip().lower() == OWNER_NAME.lower()

    updated_mode, mode_guardrail = parse_mode_switch(message, context.mode, is_owner)
    context.mode = updated_mode

    if mode_guardrail:
        return (
            jsonify(
                {
                    "reply": mode_guardrail,
                    "currentSpeaker": context.current_speaker,
                    "mode": context.mode,
                }
            ),
            200,
        )

    if not is_owner and is_sensitive_request(message):
        return (
            jsonify(
                {
                    "reply": "I cannot share that information in the current access level.",
                    "currentSpeaker": context.current_speaker,
                    "mode": context.mode,
                }
            ),
            200,
        )

    reply = call_groq_api(message, context, is_owner)

    return (
        jsonify(
            {
                "reply": reply,
                "currentSpeaker": context.current_speaker,
                "mode": context.mode,
            }
        ),
        200,
    )


if __name__ == "__main__":
    # Render sets PORT env variable. Local fallback is 5000.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
