#!/usr/bin/env python3
"""Receive WhatsApp webhooks from the bridge and run a handler script.

The bridge POSTs a JSON payload for every message matching a trigger, signed
with HMAC-SHA256 over the raw body in X-Webhook-Signature. This verifies that
signature and hands the payload to a handler on stdin, so the workflow itself is
an ordinary script in any language.

    WHATSAPP_HOOK_SECRET=... WHATSAPP_HOOK_HANDLER=./handler.sh hook.py

Only messages for chats the access policy allows ever reach here: the bridge
fires webhooks after the policy check, not before.
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = os.environ.get("WHATSAPP_HOOK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WHATSAPP_HOOK_PORT", "8781"))
SECRET = os.environ.get("WHATSAPP_HOOK_SECRET", "")
HANDLER = os.environ.get("WHATSAPP_HOOK_HANDLER", "")
LOG = os.path.expanduser("~/.config/whatsapp-mcp/hook.log")
MAX_BODY = 4 * 1024 * 1024


def log(line):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {line}", flush=True)
    try:
        with open(LOG, "a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except Exception:
        pass


def run_handler(payload):
    """Run the handler with the payload on stdin and useful fields in the env."""
    if not HANDLER:
        return
    msg = payload.get("message", {}) or {}
    env = dict(os.environ)
    env.update({
        "WA_CHAT_JID": str(msg.get("chat_jid", "")),
        "WA_CHAT_NAME": str(msg.get("chat_name", "")),
        "WA_SENDER": str(msg.get("sender", "")),
        "WA_SENDER_NAME": str(msg.get("sender_name", "")),
        "WA_CONTENT": str(msg.get("content", "")),
        "WA_IS_FROM_ME": "1" if msg.get("is_from_me") else "0",
        "WA_MEDIA_TYPE": str(msg.get("media_type", "")),
        "WA_MESSAGE_ID": str(msg.get("id", "")),
    })
    try:
        p = subprocess.run([HANDLER], input=json.dumps(payload), text=True,
                           env=env, capture_output=True, timeout=120)
        if p.returncode != 0:
            # Report both streams: a handler that fails often explains itself on
            # stdout, and logging only stderr loses the reason entirely.
            detail = " | ".join(x for x in ((p.stdout or "").strip(),
                                            (p.stderr or "").strip()) if x)
            log(f"  handler exit {p.returncode}: {detail[:300] or '(no output)'}")
        elif p.stdout.strip():
            log(f"  handler: {p.stdout.strip()[:200]}")
    except subprocess.TimeoutExpired:
        log("  handler timed out after 120s")
    except Exception as e:
        log(f"  handler failed: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            self.send_response(400)
            self.end_headers()
            return
        raw = self.rfile.read(n)

        # Verify before parsing: an unsigned body is never worth interpreting.
        if SECRET:
            expected = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
            got = self.headers.get("X-Webhook-Signature", "")
            if not hmac.compare_digest(expected, got):
                log("rejected: bad signature")
                self.send_response(401)
                self.end_headers()
                return

        try:
            payload = json.loads(raw)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        # Acknowledge immediately; the bridge retries on a slow or failed reply,
        # and a workflow must not be re-run just because it took a while.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

        msg = payload.get("message", {}) or {}
        who = msg.get("sender_name") or msg.get("sender") or "?"
        log(f"{msg.get('chat_name','?')} | {who}: {str(msg.get('content',''))[:80]!r}")
        threading.Thread(target=run_handler, args=(payload,), daemon=True).start()


def main():
    log(f"listening on http://{HOST}:{PORT}  handler={HANDLER or '(none)'}  "
        f"signature={'required' if SECRET else 'NOT CHECKED'}")
    if not SECRET:
        log("  warning: no WHATSAPP_HOOK_SECRET set, anything can post here")
    try:
        HTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()
