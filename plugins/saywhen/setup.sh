#!/bin/bash
# SayWhen setup script
# Configures the parent folder prefix for path stripping in notifications

set -e

# Config directory - can be overridden for testing
CONFIG_DIR="${SAYWHEN_CONFIG_DIR:-$HOME/.config/pluginterface/saywhen}"
PREFIX_FILE="$CONFIG_DIR/prefix"
MUTE_FILE="$CONFIG_DIR/mute"

# Parse arguments
PREFIX=""
NON_INTERACTIVE=false
ACTION="setup"

while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        --get-prefix)
            ACTION="get-prefix"
            shift
            ;;
        --get-mute-path)
            ACTION="get-mute-path"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Get prefix from file
get_prefix() {
    if [ -f "$PREFIX_FILE" ]; then
        cat "$PREFIX_FILE"
    else
        echo ""
    fi
}

# Get mute file path
get_mute_path() {
    echo "$MUTE_FILE"
}

# Run setup
run_setup() {
    # Create config directory
    mkdir -p "$CONFIG_DIR"

    # Get prefix interactively if not provided
    if [ -z "$PREFIX" ] && [ "$NON_INTERACTIVE" = false ]; then
        echo "SayWhen Setup"
        echo "============="
        echo ""
        echo "This configures how project names appear in voice notifications."
        echo "Your current directory is: $(pwd)"
        echo ""
        echo "What's your parent development folder?"
        echo "Examples:"
        echo "  - 'dev' for ~/dev/project -> 'project'"
        echo "  - 'code' for ~/code/project -> 'project'"
        echo "  - '$USER' for ~/project -> 'project'"
        echo ""
        read -p "Enter folder name: " PREFIX
    fi

    # Write prefix file
    if [ -n "$PREFIX" ]; then
        echo "$PREFIX" > "$PREFIX_FILE"
        if [ "$NON_INTERACTIVE" = false ]; then
            echo ""
            echo "Configuration saved!"
            echo "Prefix: $PREFIX"
            echo "Config: $PREFIX_FILE"
        fi
    fi
}

# Execute based on action
case $ACTION in
    get-prefix)
        get_prefix
        ;;
    get-mute-path)
        get_mute_path
        ;;
    setup)
        run_setup
        ;;
esac
