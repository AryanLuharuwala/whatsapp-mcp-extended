#!/usr/bin/env bash
# Start the webhook receiver and register it with the bridge.
# Run AFTER the bridge is up with the current binary.
set -euo pipefail
set -a; . ~/.config/whatsapp-mcp/env; set +a

export WHATSAPP_HOOK_HANDLER="${WHATSAPP_HOOK_HANDLER:-$HOME/whatsapp-mcp-extended/automation/handler.agent.sh}"
export WA_MODEL="${WA_MODEL:-google/gemma-4-12b-qat}"
export WA_AGENT_MODE="${WA_AGENT_MODE:-plain}"
export WA_TRIGGER_PREFIX="${WA_TRIGGER_PREFIX:-}"

python3 "$HOME/whatsapp-mcp-extended/automation/hook.py" &
HOOK=$!
trap 'kill $HOOK 2>/dev/null' EXIT
sleep 2

# Replace any previous registration so repeated runs do not stack up webhooks.
for id in $(curl -s http://127.0.0.1:8080/api/webhooks -H "X-API-Key: $API_KEY" \
            | jq -r '.data[]? | select(.name=="local-automation") | .id'); do
  curl -s -X DELETE "http://127.0.0.1:8080/api/webhooks/$id" -H "X-API-Key: $API_KEY" >/dev/null || true
done

TRIG='[{"trigger_type":"all","trigger_value":"","match_type":"exact","enabled":true}]'
RES=$(curl -s -X POST http://127.0.0.1:8080/api/webhooks -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg s "$WHATSAPP_HOOK_SECRET" --argjson t "$TRIG" \
        '{name:"local-automation",webhook_url:"http://127.0.0.1:8781/",
          secret_token:$s,enabled:true,triggers:$t}')")

if [ "$(printf '%s' "$RES" | jq -r '.success // false')" != "true" ]; then
  echo "registration failed: $(printf '%s' "$RES" | jq -r '.error // .')" >&2
  exit 1
fi
echo "webhook registered. mode=$WA_AGENT_MODE model=$WA_MODEL prefix='${WA_TRIGGER_PREFIX:-<none>}'"
echo "waiting for messages (Ctrl+C to stop)..."
wait $HOOK
