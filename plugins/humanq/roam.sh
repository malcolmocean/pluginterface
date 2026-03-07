#!/bin/bash
# Roam Research API helper that handles the redirect dance
# Usage:
#   roam.sh q '{"query": "[:find ...]"}'
#   roam.sh write '{"action": "create-block", ...}'

set -euo pipefail

CONFIG_DIR="$HOME/.config/pluginterface/humanq"

if [ ! -f "$CONFIG_DIR/token" ] || [ ! -f "$CONFIG_DIR/graph" ]; then
  echo "Error: HumanQ not configured. Run /humanq:setup first." >&2
  exit 1
fi

ROAM_API_TOKEN=$(cat "$CONFIG_DIR/token")
GRAPH=$(cat "$CONFIG_DIR/graph")
BASE_URL="https://api.roamresearch.com/api/graph/$GRAPH"
AUTH_HEADERS=(
  -H "Content-Type: application/json; charset=utf-8"
  -H "Authorization: Bearer $ROAM_API_TOKEN"
  -H "x-authorization: Bearer $ROAM_API_TOKEN"
)

endpoint="$1"  # "q" or "write"
body="$2"

# Step 1: get redirect URL (Roam API does a 308 redirect to a peer)
REDIRECT_URL=$(curl -s -o /dev/null -w '%{redirect_url}' \
  -X POST "$BASE_URL/$endpoint" \
  "${AUTH_HEADERS[@]}" \
  -d "$body")

# Step 2: hit the peer directly with auth headers
if [ -n "$REDIRECT_URL" ]; then
  curl -s -X POST "$REDIRECT_URL" "${AUTH_HEADERS[@]}" -d "$body"
else
  curl -s -X POST "$BASE_URL/$endpoint" "${AUTH_HEADERS[@]}" -d "$body"
fi
