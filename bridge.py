#!/usr/bin/env python3
"""WhatsApp <-> Claude reply bot. Two-way, live, trusted-sender only.

Twilio POSTs an inbound WhatsApp message to /whatsapp. This verifies the
request really came from Twilio (signature check) and really came from an
allowed number, feeds the message to a persistent Claude Agent SDK session
so the conversation has real memory across messages (not amnesia between
texts), and replies via Twilio's REST API.

Every exchange is also appended to whatsapp-log.md as a plain-text record,
independent of the SDK's own session state.

Env vars required:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_WHATSAPP_NUMBER       whatsapp:+<E.164>, the Twilio sender
  TRUSTED_WHATSAPP_NUMBERS     comma-separated whatsapp:+<E.164> numbers
                                allowed to use the bot - anyone else is
                                silently ignored, never replied to
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import PlainTextResponse
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

HERE = Path(__file__).parent
SESSION_FILE = HERE / ".session_id"
LOG_FILE = HERE / "whatsapp-log.md"

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]
TRUSTED_NUMBERS = {
    n.strip() for n in os.environ.get("TRUSTED_WHATSAPP_NUMBERS", "").split(",") if n.strip()
}

TEXT_DISCIPLINE = (
    "WHATSAPP SESSION (this is a live text conversation on someone's "
    "phone, not a terminal session): reply like a text message, not a "
    "report. Short, direct, conversational - a few sentences is almost "
    "always enough, go longer only when the question genuinely needs "
    "detail. WhatsApp supports *bold* and _italic_ (single asterisk/ "
    "underscore, not markdown's double-asterisk) - fine to use sparingly, "
    "but no headers, no tables, no multi-level bullet lists, nothing that "
    "only renders properly in a desktop markdown viewer. Skip any startup "
    "sequence or welcome line; just answer."
)


def log_exchange(direction: str, text: str):
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with open(LOG_FILE, "a") as f:
        f.write(f"\n**{ts} - {direction}:**\n{text}\n")


async def ask_claude(message: str) -> str:
    """One-shot query against a resumed (or fresh) persistent session."""
    resume_id = None
    if SESSION_FILE.exists():
        resume_id = SESSION_FILE.read_text().strip() or None

    def make_options(resume):
        return ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code", "append": TEXT_DISCIPLINE},
            permission_mode="default",
            resume=resume,
        )

    client = ClaudeSDKClient(options=make_options(resume_id))
    try:
        await client.connect()
    except Exception:
        # stale/invalid saved session_id - fall back to a fresh one
        SESSION_FILE.unlink(missing_ok=True)
        client = ClaudeSDKClient(options=make_options(None))
        await client.connect()

    try:
        await client.query(message)
        reply_text = ""
        new_session_id = None
        async for msg in client.receive_response():
            t = type(msg).__name__
            if t == "AssistantMessage":
                for block in getattr(msg, "content", []):
                    if type(block).__name__ == "TextBlock":
                        reply_text += block.text
            elif t == "ResultMessage":
                new_session_id = getattr(msg, "session_id", None)
        if new_session_id:
            SESSION_FILE.write_text(new_session_id)
        return reply_text.strip() or "(no text response)"
    finally:
        await client.disconnect()


app = FastAPI()


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request, Body: str = Form(...), From: str = Form(...)):
    # 1. Verify this request genuinely came from Twilio, not a forged POST
    # to a guessed/leaked webhook URL.
    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    url = str(request.url)
    if not validator.validate(url, dict(form), signature):
        return Response(status_code=403, content="invalid signature")

    # 2. Only trusted senders. Anyone else gets silently ignored - never
    # answered, never logged as a real exchange. Safe default for an
    # unattended service: silence, not a guess at who's safe to reply to.
    if From.strip() not in TRUSTED_NUMBERS:
        return Response(status_code=200)  # 200 so Twilio doesn't retry

    log_exchange("Incoming", Body)
    try:
        reply = await ask_claude(Body)
        log_exchange("Reply", reply)
    except Exception as e:
        # Never let a failure here surface as a 5xx - Twilio retries failed
        # webhooks, which would re-trigger a second (possibly duplicate)
        # run on the same message. Log and bail out clean.
        log_exchange("ERROR (generation failed, no reply sent)", str(e))
        return Response(status_code=200)

    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=From,
            body=reply,
        )
    except Exception as e:
        # The reply was generated and is sitting safely in whatsapp-log.md
        # even though delivery failed - never lose the content silently.
        log_exchange("ERROR (Twilio send failed, reply logged above only)", str(e))
    return Response(status_code=200)


@app.get("/health")
async def health():
    return PlainTextResponse("ok")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8732)
