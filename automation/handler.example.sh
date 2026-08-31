#!/usr/bin/env bash
# Example workflow. Full JSON payload arrives on stdin; key fields are in env.
# Anything printed to stdout is logged by hook.py.
set -euo pipefail

[ "$WA_IS_FROM_ME" = "1" ] && exit 0     # ignore your own messages

echo "got '${WA_CONTENT}' from ${WA_SENDER_NAME} in ${WA_CHAT_NAME}"

# e.g. ask the local model and reply:
# ANSWER=$(curl -s http://localhost:1234/v1/chat/completions \
#   -H 'Content-Type: application/json' \
#   -d "$(jq -n --arg m "$WA_CONTENT" '{model:"google/gemma-4-12b-qat",
#         messages:[{role:"user",content:$m}],max_tokens:200}')" \
#   | jq -r '.choices[0].message.content')
# curl -s -X POST http://127.0.0.1:8080/api/send \
#   -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
#   -d "$(jq -n --arg r "$WA_CHAT_JID" --arg m "$ANSWER" '{recipient:$r,message:$m}')"
