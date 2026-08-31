#!/usr/bin/env python3
"""MCP server exposing the WhatsApp automation's state.

LM Studio's chat cannot be driven from outside - nothing can push a message into
a conversation - so the monitor is wired the other way round: the chat asks this
server what the automation has been doing.

Read-only by default. The access policy is reported but never modified here;
changing it stays with the control panel, which the model cannot reach.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ACL_DIR = Path(os.environ.get("WHATSAPP_ACL_DIR", Path.home() / ".config" / "whatsapp-mcp"))
HOOK_LOG = ACL_DIR / "hook.log"
POLICY = ACL_DIR / "access.json"
BRIDGE = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8080")


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _receiver_running():
    try:
        out = subprocess.run(["pgrep", "-fa", "automation/hook.py"],
                             capture_output=True, text=True, timeout=5).stdout
        return bool(out.strip())
    except Exception:
        return False


def _webhooks():
    key = os.environ.get("API_KEY", "")
    if not key:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(f"{BRIDGE}/api/webhooks", headers={"X-API-Key": key})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()).get("data", [])
    except Exception:
        return None


def automation_status():
    pol = _read_json(POLICY, {})
    hooks = _webhooks()
    return {
        "receiver_running": _receiver_running(),
        "bridge_reachable": hooks is not None,
        "webhooks": [{"name": w.get("name"), "url": w.get("webhook_url"),
                      "enabled": w.get("enabled")} for w in (hooks or [])],
        "policy_mode": pol.get("mode"),
        "chats_readable": len(pol.get("jids") or []),
        "chats_sendable": len(pol.get("send_jids") or []),
        "model": os.environ.get("WA_MODEL", "google/gemma-4-e2b"),
        "trigger_prefix": os.environ.get("WA_TRIGGER_PREFIX") or None,
    }


def recent_activity(limit=20):
    try:
        lines = HOOK_LOG.read_text(errors="replace").strip().splitlines()
    except Exception:
        return {"events": [], "note": "no activity log yet"}
    limit = max(1, min(int(limit), 200))
    return {"events": [l for l in lines[-limit:]], "total_logged": len(lines)}


def access_summary():
    """What the automation is permitted to do, as configured by the operator."""
    pol = _read_json(POLICY, {})
    return {
        "mode": pol.get("mode"),
        "readable": pol.get("jids") or [],
        "sendable": pol.get("send_jids") or [],
        "updated_at": pol.get("updated_at"),
        "note": "Read-only view. The policy is changed only from the control "
                "panel, which is not reachable from here.",
    }


TOOLS = [
    {"name": "automation_status",
     "description": "Whether the WhatsApp auto-reply monitor is running, which webhooks are registered, and how many chats it may read or message.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "recent_activity",
     "description": "Recent messages the monitor received and what the handler did with them.",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer",
                                              "description": "How many log lines (default 20, max 200)"}}}},
    {"name": "access_summary",
     "description": "Which WhatsApp chats the automation is allowed to read and send to.",
     "inputSchema": {"type": "object", "properties": {}}},
]
DISPATCH = {"automation_status": lambda a: automation_status(),
            "recent_activity": lambda a: recent_activity(a.get("limit", 20)),
            "access_summary": lambda a: access_summary()}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "whatsapp-automation-monitor", "version": "1.0.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            fn = DISPATCH.get(params.get("name", ""))
            if not fn:
                send({"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": "unknown tool"}], "isError": True}})
                continue
            try:
                out = fn(params.get("arguments") or {})
                text = json.dumps(out, indent=2)
                err = False
            except Exception as e:
                text, err = f"error: {e}", True
            send({"jsonrpc": "2.0", "id": mid,
                  "result": {"content": [{"type": "text", "text": text}], "isError": err}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": f"unknown method {method}"}})


if __name__ == "__main__":
    main()
