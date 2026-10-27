# WhatsApp Reply Bot

A WhatsApp bridge that replies to trusted senders using Claude, with real memory across messages — not a stateless one-liner bot, a genuine ongoing conversation.

## How it works

1. Someone on an allowed number sends a WhatsApp message to the bot's Twilio number.
2. Twilio POSTs it to this bot's `/whatsapp` endpoint.
3. The bot verifies the request's signature (proves it really came from Twilio, not a forged POST to a guessed webhook URL) and checks the sender against a trusted-number allowlist.
4. If trusted, the message goes to a persistent Claude Agent SDK session — the same session resumes across messages, so the bot remembers the conversation instead of starting fresh every text.
5. The reply goes back out via Twilio's REST API.

## Why this design

- **Trusted-sender allowlist, not "reply to everyone."** Anyone not on the list is silently ignored — logged, never replied to. There's nobody reviewing replies in real time on an automated service, so the safe default for an unknown sender is silence, not a guess.
- **Signature verification on every request.** Without this, anyone who found the webhook URL could post fake messages and get real Claude-generated replies sent out under the bot's number.
- **Session continuity.** Most WhatsApp bot demos are stateless — ask it something, it answers, it forgets you existed a message later. This one resumes the same Claude session, so a follow-up message has the context of everything said before.
- **Clean failure handling.** A generation failure or a Twilio delivery failure never surfaces as a 5xx to Twilio (which would trigger a retry and risk a duplicate reply) — it logs the failure and returns 200 cleanly either way.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your Twilio credentials and trusted numbers

./run.sh
```

Then point your Twilio WhatsApp sender's inbound webhook at `https://<your-public-url>/whatsapp` (a tool like Cloudflare Tunnel or ngrok works for exposing a local server during development).

## Status

Built and tested against simulated WhatsApp webhook requests: the signature check, the trusted-sender allowlist, session memory across messages and the failure handling all run as described. It has not been run against a live WhatsApp number. The provider-specific parts (signature check and sending the reply) sit in two short blocks of the webhook handler (the signature check and the send), so pointing it at another WhatsApp provider is a small change, not a rewrite.

## Stack

Python · FastAPI · Twilio WhatsApp API · Claude Agent SDK (session-resume for cross-message memory)

---
Part of a small portfolio of tested automation/AI builds — see [ParishSynthMind](https://github.com/ParishSynthMind) for the others.
