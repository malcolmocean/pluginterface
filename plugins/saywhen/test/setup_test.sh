#!/bin/bash
# Test suite for saywhen setup script
# Run with: bash test/setup_test.sh

# Don't use set -e because ((var++)) returns 1 when var is 0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

# Test helpers
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

assert_file_exists() {
    local file="$1"
    local msg="$2"
    if [ -f "$file" ]; then
        echo -e "${GREEN}PASS${NC}: $msg"
        ((PASS++))
    else
        echo -e "${RED}FAIL${NC}: $msg"
        echo "  File does not exist: $file"
        ((FAIL++))
    fi
}

assert_file_not_exists() {
    local file="$1"
    local msg="$2"
    if [ ! -f "$file" ]; then
        echo -e "${GREEN}PASS${NC}: $msg"
        ((PASS++))
    else
        echo -e "${RED}FAIL${NC}: $msg"
        echo "  File should not exist: $file"
        ((FAIL++))
    fi
}

assert_dir_exists() {
    local dir="$1"
    local msg="$2"
    if [ -d "$dir" ]; then
        echo -e "${GREEN}PASS${NC}: $msg"
        ((PASS++))
    else
        echo -e "${RED}FAIL${NC}: $msg"
        echo "  Directory does not exist: $dir"
        ((FAIL++))
    fi
}

# Setup test environment
TEST_CONFIG_DIR=$(mktemp -d)
export SAYWHEN_CONFIG_DIR="$TEST_CONFIG_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/setup.sh"

cleanup() {
    rm -rf "$TEST_CONFIG_DIR"
}
trap cleanup EXIT

echo "=== SayWhen Setup Script Tests ==="
echo "Using test config dir: $TEST_CONFIG_DIR"
echo ""

# Test 1: Setup creates config directory
echo "--- Test: Config directory creation ---"
bash "$SETUP_SCRIPT" --prefix "dev" --non-interactive
assert_dir_exists "$TEST_CONFIG_DIR" "Config directory should be created"

# Test 2: Setup writes prefix file
echo ""
echo "--- Test: Prefix file creation ---"
assert_file_exists "$TEST_CONFIG_DIR/prefix" "Prefix file should be created"
ACTUAL_PREFIX=$(cat "$TEST_CONFIG_DIR/prefix")
assert_equals "dev" "$ACTUAL_PREFIX" "Prefix should be 'dev'"

# Test 3: Setup with different prefix
echo ""
echo "--- Test: Custom prefix ---"
rm -rf "$TEST_CONFIG_DIR"/*
bash "$SETUP_SCRIPT" --prefix "code" --non-interactive
ACTUAL_PREFIX=$(cat "$TEST_CONFIG_DIR/prefix")
assert_equals "code" "$ACTUAL_PREFIX" "Prefix should be 'code'"

# Test 4: Setup with username (home folder case)
echo ""
echo "--- Test: Username prefix ---"
rm -rf "$TEST_CONFIG_DIR"/*
bash "$SETUP_SCRIPT" --prefix "malcolm" --non-interactive
ACTUAL_PREFIX=$(cat "$TEST_CONFIG_DIR/prefix")
assert_equals "malcolm" "$ACTUAL_PREFIX" "Prefix should be 'malcolm'"

# Test 5: get_prefix function returns stored prefix
echo ""
echo "--- Test: get_prefix returns stored value ---"
echo "myprefix" > "$TEST_CONFIG_DIR/prefix"
RESULT=$(bash "$SETUP_SCRIPT" --get-prefix)
assert_equals "myprefix" "$RESULT" "get_prefix should return stored value"

# Test 6: get_prefix returns empty when no config exists
echo ""
echo "--- Test: get_prefix returns empty when no config ---"
rm -f "$TEST_CONFIG_DIR/prefix"
RESULT=$(bash "$SETUP_SCRIPT" --get-prefix)
EXIT_CODE=$?
# Should return empty string and exit 0
if [ $EXIT_CODE -eq 0 ] && [ -z "$RESULT" ]; then
    echo -e "${GREEN}PASS${NC}: get_prefix handles missing config gracefully (returns empty)"
    ((PASS++))
else
    echo -e "${RED}FAIL${NC}: get_prefix should return empty when no config"
    echo "  Exit code: $EXIT_CODE, Result: '$RESULT'"
    ((FAIL++))
fi

# Test 7: Mute file location
echo ""
echo "--- Test: Mute file location ---"
rm -rf "$TEST_CONFIG_DIR"/*
bash "$SETUP_SCRIPT" --prefix "dev" --non-interactive
MUTE_PATH=$(bash "$SETUP_SCRIPT" --get-mute-path)
assert_equals "$TEST_CONFIG_DIR/mute" "$MUTE_PATH" "Mute path should be in config dir"

# Summary
echo ""
echo "=== Test Summary ==="
echo -e "Passed: ${GREEN}$PASS${NC}"
echo -e "Failed: ${RED}$FAIL${NC}"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
