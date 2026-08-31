#!/usr/bin/env bash
# Answer an incoming WhatsApp message with the local model, then reply.
#
# Two modes:
#   plain  - a normal completion. Works today.
#   tools  - lets the model use mcp.json servers during the turn. Needs
#            "Allow calling servers from mcp.json" enabled in LM Studio's
#            Developer > Server Settings.
set -euo pipefail

MODEL="${WA_MODEL:-google/gemma-4-12b-qat}"
LMS="${LMS_URL:-http://localhost:1234}"
BRIDGE="${BRIDGE_URL:-http://127.0.0.1:8080}"
MODE="${WA_AGENT_MODE:-plain}"
TRIGGER="${WA_TRIGGER_PREFIX:-}"

[ -z "${WA_CONTENT:-}" ] && exit 0

# Optional prefix gate, so not every message wakes the model.
if [ -n "$TRIGGER" ]; then
  case "$WA_CONTENT" in "$TRIGGER"*) ;; *) exit 0 ;; esac
fi

# Answering your own messages risks a loop, because the reply is also from you.
# A trigger prefix breaks that: the reply never starts with it, so it cannot
# re-trigger. Without a prefix there is nothing to stop the cycle, so refuse.
if [ "${WA_IS_FROM_ME:-0}" = "1" ] && [ -z "$TRIGGER" ]; then
  exit 0
fi

# Strip the prefix so the model is not asked to interpret "!bot".
PROMPT="$WA_CONTENT"
if [ -n "$TRIGGER" ]; then
  PROMPT="${WA_CONTENT#"$TRIGGER"}"
  PROMPT="${PROMPT# }"
fi
[ -z "$PROMPT" ] && exit 0

# jq -n --arg keeps the message as data. It is attacker-controlled text and
# must never be interpolated into JSON or a shell command by hand.
# Gemma emits a reasoning block before the message, and it is billed against
# the same budget. Too small a limit is spent entirely on thinking and returns
# no message at all, so keep this generous.
BUDGET="${WA_MAX_TOKENS:-800}"

if [ "$MODE" = "tools" ]; then
  REQ=$(jq -n --arg m "$MODEL" --arg i "$PROMPT" --argjson b "$BUDGET" \
    '{model:$m, input:$i, max_output_tokens:$b, integrations:["mcp/whatsapp"]}')
else
  REQ=$(jq -n --arg m "$MODEL" --arg i "$PROMPT" --argjson b "$BUDGET" \
    '{model:$m, input:$i, max_output_tokens:$b}')
fi

RESP=$(curl -sS -m 600 -X POST "$LMS/v1/responses" \
  -H "Authorization: Bearer ${LM_API_TOKEN:?LM_API_TOKEN not set}" \
  -H 'Content-Type: application/json' -d "$REQ")

ERR=$(printf '%s' "$RESP" | jq -r '.error.message // empty')
[ -n "$ERR" ] && { echo "model error: $ERR"; exit 1; }

# Take only message output; the reasoning block is internal and must not be sent.
REPLY=$(printf '%s' "$RESP" | jq -r '[.output[]? | select(.type=="message") | .content[]? | .text] | join("\n")')

[ -z "$REPLY" ] || [ "$REPLY" = "null" ] && { echo "no reply produced"; exit 0; }

# The bridge re-checks its own send policy, so this cannot message a chat the
# operator has not authorised even if the handler is wrong.
curl -sS -m 60 -X POST "$BRIDGE/api/send" \
  -H "X-API-Key: ${API_KEY:?API_KEY not set}" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg r "$WA_CHAT_JID" --arg m "$REPLY" '{recipient:$r,message:$m}')" \
  | jq -r 'if .success then "replied to '"$WA_CHAT_NAME"'" else "send refused: \(.error)" end'
