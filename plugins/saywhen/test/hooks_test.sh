#!/bin/bash
# Test suite for saywhen hook commands
# Run with: bash test/hooks_test.sh

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

assert_equals() {
    local expected="$1"
    local actual="$2"
    local msg="$3"
    if [ "$expected" = "$actual" ]; then
        echo -e "${GREEN}PASS${NC}: $msg"
        ((PASS++))
    else
        echo -e "${RED}FAIL${NC}: $msg"
        echo "  Expected: '$expected'"
        echo "  Actual:   '$actual'"
        ((FAIL++))
    fi
}

# Setup test environment
TEST_CONFIG_DIR=$(mktemp -d)
mkdir -p "$TEST_CONFIG_DIR"

cleanup() {
    rm -rf "$TEST_CONFIG_DIR"
}
trap cleanup EXIT

echo "=== SayWhen Hook Command Tests ==="
echo "Using test config dir: $TEST_CONFIG_DIR"
echo ""

# The path extraction logic that hooks should use
# This mirrors what should be in hooks.json
get_project_name() {
    local config_dir="$1"
    local prefix_file="$config_dir/prefix"
    local prefix
    if [ -f "$prefix_file" ]; then
        prefix=$(cat "$prefix_file")
        pwd | sed "s|^.*/$prefix/||"
    else
        # Fallback: just use current directory name
        basename "$(pwd)"
    fi
}

# Test 1: Path extraction with 'dev' prefix
echo "--- Test: Path extraction with 'dev' prefix ---"
echo "dev" > "$TEST_CONFIG_DIR/prefix"
# Simulate being in /Users/malcolm/dev/myproject
cd /tmp && mkdir -p dev/myproject && cd dev/myproject
RESULT=$(get_project_name "$TEST_CONFIG_DIR")
assert_equals "myproject" "$RESULT" "Should extract 'myproject' from path with 'dev' prefix"

# Test 2: Path extraction with nested project
echo ""
echo "--- Test: Path extraction with nested path ---"
cd /tmp && mkdir -p dev/myproject/subdir && cd dev/myproject/subdir
RESULT=$(get_project_name "$TEST_CONFIG_DIR")
assert_equals "myproject/subdir" "$RESULT" "Should preserve nested path after prefix"

# Test 3: Path extraction with username prefix
echo ""
echo "--- Test: Path extraction with username prefix ---"
echo "$USER" > "$TEST_CONFIG_DIR/prefix"
cd "$HOME" && mkdir -p testproject123 && cd testproject123
RESULT=$(get_project_name "$TEST_CONFIG_DIR")
assert_equals "testproject123" "$RESULT" "Should extract project name using username prefix"
rmdir "$HOME/testproject123"

# Test 4: Fallback when no config exists
echo ""
echo "--- Test: Fallback when no config ---"
rm -f "$TEST_CONFIG_DIR/prefix"
cd /tmp/dev/myproject
RESULT=$(get_project_name "$TEST_CONFIG_DIR")
assert_equals "myproject" "$RESULT" "Should fallback to basename when no config"

# Test 5: Mute file check
echo ""
echo "--- Test: Mute file check ---"
MUTE_FILE="$TEST_CONFIG_DIR/mute"
# Mute should not exist initially
if [ ! -f "$MUTE_FILE" ]; then
    echo -e "${GREEN}PASS${NC}: Mute file does not exist by default"
    ((PASS++))
else
    echo -e "${RED}FAIL${NC}: Mute file should not exist by default"
    ((FAIL++))
fi

# Create mute file
touch "$MUTE_FILE"
if [ -f "$MUTE_FILE" ]; then
    echo -e "${GREEN}PASS${NC}: Mute file can be created"
    ((PASS++))
else
    echo -e "${RED}FAIL${NC}: Mute file creation failed"
    ((FAIL++))
fi

# Cleanup test directories
rm -rf /tmp/dev

# Summary
echo ""
echo "=== Test Summary ==="
echo -e "Passed: ${GREEN}$PASS${NC}"
echo -e "Failed: ${RED}$FAIL${NC}"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
