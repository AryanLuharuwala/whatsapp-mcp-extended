#!/usr/bin/env python3
"""Operator control panel for the WhatsApp bridge chat access policy.

This is the only thing that writes access.json. The bridge reads that file and
reloads it within a couple of seconds; the model never sees it, because the
policy directory sits outside any path exposed through an MCP filesystem
server.

Deliberate properties:
  * binds to 127.0.0.1 only, so nothing off-box can reach it;
  * every mutation is a POST carrying a per-run token, so a model with a
    GET-only web fetch tool cannot change the policy by visiting a URL;
  * it is never registered as an MCP server, so no tool call can reach it.
"""

import json
import os
import secrets
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ACL_DIR = Path(os.environ.get("WHATSAPP_ACL_DIR", Path.home() / ".config" / "whatsapp-mcp"))
POLICY_PATH = ACL_DIR / "access.json"
ROSTER_PATH = ACL_DIR / "roster.json"
HOST, PORT = "127.0.0.1", 8770
TOKEN = secrets.token_urlsafe(32)


def read_policy():
    try:
        p = json.loads(POLICY_PATH.read_text())
        if not isinstance(p, dict):
            raise ValueError
        return {"mode": p.get("mode", "allowlist"),
                "jids": list(p.get("jids") or []),
                "send_jids": list(p.get("send_jids") or [])}
    except Exception:
        # No policy yet: propose an empty allowlist, which grants nothing.
        return {"mode": "allowlist", "jids": [], "send_jids": []}


def _clean(jids):
    out, seen = [], set()
    for j in jids:
        j = str(j).strip()
        if j and j.lower() not in seen:
            seen.add(j.lower())
            out.append(j)
    return out


def write_policy(mode, jids, send_jids=()):
    if mode not in ("allowlist", "blocklist", "off"):
        raise ValueError(f"invalid mode: {mode!r}")
    clean = _clean(jids)
    # Sending is a subset of reading. Drop any send entry the read policy does
    # not cover, so the saved file cannot express "send somewhere unreadable"
    # even if the request asked for it.
    readable = {j.lower() for j in clean}
    send_clean = [j for j in _clean(send_jids)
                  if mode == "off" or j.lower() in readable]
    payload = {
        "mode": mode,
        "jids": clean,
        "send_jids": send_clean,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    ACL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = POLICY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(POLICY_PATH)
    return payload


def read_roster():
    try:
        data = json.loads(ROSTER_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send(200, json.dumps({
                "policy": read_policy(),
                "chats": read_roster(),
                "policy_path": str(POLICY_PATH),
                "roster_exists": ROSTER_PATH.exists(),
            }))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/policy":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise ValueError("payload too large")
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"error": f"bad request: {e}"}))
            return
        # Constant-time compare so the token cannot be guessed byte by byte.
        if not secrets.compare_digest(str(body.get("token", "")), TOKEN):
            self._send(403, json.dumps({"error": "bad or missing token"}))
            return
        try:
            saved = write_policy(body.get("mode", "allowlist"),
                                 body.get("jids") or [],
                                 body.get("send_jids") or [])
        except Exception as e:
            self._send(400, json.dumps({"error": str(e)}))
            return
        print(f"  policy saved: mode={saved['mode']} readable={len(saved['jids'])} "
              f"sendable={len(saved['send_jids'])}")
        self._send(200, json.dumps({"ok": True, "policy": saved}))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WhatsApp Access Control</title><style>
:root{--bg:#f6f6f7;--card:#fff;--fg:#18181b;--mut:#71717a;--bd:#e4e4e7;--ac:#2563eb;--ok:#15803d;--warn:#b45309;--danger:#b91c1c}
@media(prefers-color-scheme:dark){:root{--bg:#0f0f11;--card:#18181b;--fg:#f4f4f5;--mut:#a1a1aa;--bd:#27272a;--ac:#60a5fa;--ok:#4ade80;--warn:#fbbf24;--danger:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:16px;margin-bottom:16px}
.note{border-left:3px solid var(--warn);padding-left:12px;color:var(--mut);font-size:13px}
.modes{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px}
.modes label{border:1px solid var(--bd);border-radius:8px;padding:8px 12px;cursor:pointer;display:flex;gap:8px;align-items:center}
.modes label:has(input:checked){border-color:var(--ac);background:color-mix(in srgb,var(--ac) 10%,transparent)}
.hint{color:var(--mut);font-size:13px;margin-top:8px}
.row{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid var(--bd)}
.row:last-child{border-bottom:0}.row .nm{flex:1;min-width:0}
.nm b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm span{color:var(--mut);font-size:12px;font-family:ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}
.tag{font-size:11px;padding:2px 7px;border-radius:99px;border:1px solid var(--bd);color:var(--mut);white-space:nowrap}
.tag.g{color:var(--ac);border-color:var(--ac)}
.st{font-size:12px;white-space:nowrap;min-width:74px;text-align:right}
.st.y{color:var(--ok)}.st.n{color:var(--mut)}
input[type=search]{width:100%;padding:9px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);color:var(--fg);margin-bottom:8px}
.bar{position:sticky;bottom:0;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 16px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
button{background:var(--ac);color:#fff;border:0;border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer;font-weight:500}
button.sec{background:transparent;color:var(--mut);border:1px solid var(--bd)}
button:disabled{opacity:.5;cursor:default}
.msg{font-size:13px}.msg.ok{color:var(--ok)}.msg.err{color:var(--danger)}
.empty{color:var(--mut);padding:24px 4px;text-align:center}
.snd{font-size:12px;color:var(--mut);display:flex;align-items:center;gap:4px;white-space:nowrap;min-width:60px}
.snd.off{opacity:.35}
.snd:has(input:checked){color:var(--warn);font-weight:500}
code{background:var(--bg);border:1px solid var(--bd);border-radius:4px;padding:1px 5px;font-size:12px}
</style></head><body><div class="wrap">
<h1>WhatsApp Access Control</h1>
<p class="sub">What the model is allowed to read. Only this page can change it.</p>

<div class="card"><div class="note">
The model cannot edit this policy. It is written only from this page, stored outside
the project directory the model can reach, and never exposed as a tool.
Chats you exclude are dropped before they are written to disk, so they never exist
for the model to read. Ticking <b>send</b> additionally lets the model message that
chat; sending requires reading, so untick a chat and it can no longer be written to.
</div></div>

<div class="card">
  <strong>Policy mode</strong>
  <div class="modes">
    <label><input type="radio" name="mode" value="allowlist"> Allowlist <span class="tag">recommended</span></label>
    <label><input type="radio" name="mode" value="blocklist"> Blocklist</label>
    <label><input type="radio" name="mode" value="off"> Off <span class="tag">stores everything</span></label>
  </div>
  <div class="hint" id="modeHint"></div>
</div>

<div class="card">
  <input type="search" id="q" placeholder="Search chats and groups...">
  <div id="list"><div class="empty">Loading...</div></div>
</div>

<div class="bar">
  <div><span class="msg" id="msg"></span></div>
  <div style="display:flex;gap:8px">
    <button class="sec" id="reload">Reload</button>
    <button id="save" disabled>Save policy</button>
  </div>
</div>
</div><script>
const TOKEN="__TOKEN__";
let chats=[],policy={mode:"allowlist",jids:[],send_jids:[]},sel=new Set(),snd=new Set(),dirty=false;
const $=id=>document.getElementById(id);
const key=j=>(j||"").toLowerCase();

const HINTS={
 allowlist:"Only the chats you tick are stored. Anything not ticked - including new chats and groups you get added to - is discarded. This is the safe default.",
 blocklist:"Everything is stored except the chats you tick. New chats you are added to are stored automatically, so this fails open.",
 off:"Every chat is stored and readable by the model. No filtering at all."};

function setDirty(d){dirty=d;$("save").disabled=!d;if(d)msg("Unsaved changes","");}
function msg(t,c){const m=$("msg");m.textContent=t;m.className="msg "+(c||"");}

function render(){
  const q=$("q").value.trim().toLowerCase();
  const mode=policy.mode;
  $("modeHint").textContent=HINTS[mode]||"";
  const shown=chats.filter(c=>!q||(c.name||"").toLowerCase().includes(q)||(c.jid||"").toLowerCase().includes(q));
  if(!chats.length){
    $("list").innerHTML='<div class="empty">No chats seen yet.<br>Start the bridge and let a message arrive, then press Reload.</div>';
    return;}
  if(!shown.length){$("list").innerHTML='<div class="empty">Nothing matches that search.</div>';return;}
  $("list").innerHTML=shown.map(c=>{
    const on=sel.has(key(c.jid));
    let readable,cls;
    if(mode==="off"){readable=true;}
    else if(mode==="allowlist"){readable=on;}
    else{readable=!on;}
    cls=readable?"y":"n";
    const label=readable?"readable":"hidden";
    const canSend=snd.has(key(c.jid));
    return `<div class="row">
      <input type="checkbox" data-jid="${c.jid}" ${on?"checked":""} ${mode==="off"?"disabled":""} title="model may read">
      <div class="nm"><b>${(c.name||"(no name)").replace(/[<>&]/g,"")}</b><span>${c.jid}</span></div>
      ${c.is_group?'<span class="tag g">group</span>':'<span class="tag">direct</span>'}
      <span class="st ${cls}">${label}</span>
      <label class="snd ${readable?"":"off"}" title="${readable?"model may send here":"allow reading first"}">
        <input type="checkbox" class="sendbox" data-jid="${c.jid}" ${canSend?"checked":""} ${readable?"":"disabled"}> send
      </label></div>`;}).join("");
  $("list").querySelectorAll("input[type=checkbox]:not(.sendbox)").forEach(cb=>{
    cb.onchange=()=>{const k=key(cb.dataset.jid);
      if(cb.checked){sel.add(k);}else{sel.delete(k);snd.delete(k);}  // unreadable implies unsendable
      setDirty(true);render();};});
  $("list").querySelectorAll("input.sendbox").forEach(cb=>{
    cb.onchange=()=>{const k=key(cb.dataset.jid);cb.checked?snd.add(k):snd.delete(k);setDirty(true);render();};});
}

async function load(){
  const r=await fetch("/api/state");const s=await r.json();
  chats=s.chats||[];policy=s.policy||policy;
  sel=new Set((policy.jids||[]).map(key));
  snd=new Set((policy.send_jids||[]).map(key));
  document.querySelectorAll("input[name=mode]").forEach(x=>x.checked=(x.value===policy.mode));
  setDirty(false);msg(chats.length?`${chats.length} chats known`:"","");
  render();
}
document.querySelectorAll("input[name=mode]").forEach(x=>x.onchange=()=>{policy.mode=x.value;setDirty(true);render();});
$("q").oninput=render;
$("reload").onclick=()=>load();
$("save").onclick=async()=>{
  $("save").disabled=true;msg("Saving...","");
  const jids=chats.map(c=>c.jid).filter(j=>sel.has(key(j)));
  // keep any listed JID that is not in the roster yet
  (policy.jids||[]).forEach(j=>{if(sel.has(key(j))&&!jids.some(x=>key(x)===key(j)))jids.push(j);});
  const send_jids=chats.map(c=>c.jid).filter(j=>snd.has(key(j)));
  (policy.send_jids||[]).forEach(j=>{if(snd.has(key(j))&&!send_jids.some(x=>key(x)===key(j)))send_jids.push(j);});
  try{
    const r=await fetch("/api/policy",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({token:TOKEN,mode:policy.mode,jids,send_jids})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||r.status);
    policy=d.policy;setDirty(false);
    msg(`Saved - ${policy.mode}, ${policy.jids.length} readable, ${(policy.send_jids||[]).length} sendable. Bridge picks this up within ~2s.`,"ok");
  }catch(e){msg("Save failed: "+e.message,"err");$("save").disabled=false;}
};
load();
</script></body></html>"""


def main():
    ACL_DIR.mkdir(parents=True, exist_ok=True)
    url = f"http://{HOST}:{PORT}/"
    print(f"WhatsApp access control panel")
    print(f"  policy : {POLICY_PATH}")
    print(f"  roster : {ROSTER_PATH}" + ("" if ROSTER_PATH.exists() else "  (none yet - start the bridge)"))
    print(f"  url    : {url}")
    print(f"  bound to {HOST} only; edits require a POST with this run's token")
    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        HTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
