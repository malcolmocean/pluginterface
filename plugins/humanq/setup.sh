#!/bin/bash
# HumanQ setup - configure Roam Research connection
set -euo pipefail

CONFIG_DIR="$HOME/.config/pluginterface/humanq"
mkdir -p "$CONFIG_DIR"

echo "=== HumanQ Setup ==="
echo ""
echo "This plugin posts tasks to a Roam Research page when Claude Code"
echo "needs you to do something it can't (register OAuth clients, etc)."
echo ""

# Graph name
read -p "Roam graph name: " GRAPH_NAME
echo "$GRAPH_NAME" > "$CONFIG_DIR/graph"

# API token
echo ""
echo "Get your API token from Roam: Settings > Graph > API Tokens"
read -p "Roam API token: " API_TOKEN
echo "$API_TOKEN" > "$CONFIG_DIR/token"

# Page UID
echo ""
echo "You need a page in Roam to receive tasks (e.g. 'HumanQ')."
echo "Create it if it doesn't exist, then find its UID."
echo "(Click the page title > Copy block reference > extract the UID)"
read -p "Page UID: " PAGE_UID
echo "$PAGE_UID" > "$CONFIG_DIR/page_uid"

echo ""
echo "Setup complete! Config saved to $CONFIG_DIR"
echo "Test with: /humanq:test"
