#!/usr/bin/env bash
# Phase 1 verification — check 6: idempotency replay.
#
# Sends the same payload twice with an identical idempotency_key against a
# conversation. The DB must end up with exactly one user turn carrying the
# key (the second POST replays the original instead of producing a new turn).
#
# Usage:
#   JWT="<paste-clerk-token>" CONV="<conversation-uuid>" bash scripts/check-idempotency.sh
#
# Grab the JWT from the chat page in DevTools console:
#   copy(await window.Clerk.session.getToken())
#
# Clerk dev tokens expire in 60s — run this within ~30s of pasting.

set -eo pipefail

: "${JWT:?Set JWT to a Clerk session token}"
: "${CONV:?Set CONV to a conversation UUID you own}"
API="${API:-http://localhost:8000}"

KEY="dup-$(date +%s%N)"
BODY="$(printf '{"content":[{"type":"text","text":"idempotency check %s"}],"idempotency_key":"%s"}' "$KEY" "$KEY")"

echo "key=$KEY  conv=$CONV"
echo

echo "--- first POST (creates user + assistant turns) ---"
curl -sN -X POST "$API/conversations/$CONV/messages" \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d "$BODY" | head -c 1500
echo
echo

echo "--- second POST, same idempotency_key (must REPLAY, not create) ---"
curl -sN -X POST "$API/conversations/$CONV/messages" \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d "$BODY" | head -c 1500
echo
echo

echo "--- DB rows tagged with this key (must be exactly 1, role=user) ---"
docker compose exec -T postgres psql -U synq -d synq_dev -c \
  "SELECT turn_index, role, idempotency_key
   FROM messages
   WHERE idempotency_key='$KEY';"

echo "--- assistant turn at turn_index+1 (must be exactly 1) ---"
docker compose exec -T postgres psql -U synq -d synq_dev -c \
  "SELECT COUNT(*) AS assistant_replies
   FROM messages
   WHERE conversation_id='$CONV'
     AND turn_index = (
       SELECT turn_index + 1
       FROM messages
       WHERE idempotency_key='$KEY'
     )
     AND role='assistant';"

echo "--- VERDICT ---"
hits=$(docker compose exec -T postgres psql -U synq -d synq_dev -tA -c \
  "SELECT COUNT(*) FROM messages WHERE idempotency_key='$KEY';")
if [ "$hits" = "1" ]; then
  echo "PASS — exactly 1 row carries the idempotency_key. Second POST was a replay."
else
  echo "FAIL — expected 1 row with the key, got $hits."
  exit 1
fi
