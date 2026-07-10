#!/usr/bin/env bash
# Shared helpers for bin/ scripts. Sourced, not executed.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIRMWARE_ROOT="$REPO_ROOT/firmware"
DEFAULT_HOST="192.168.4.1"

die() { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*" >&2; }

resolve_subproject() {
    local sub="${1:-}"
    [[ -z "$sub" ]] && die "subproject required: can-logger or wifi-bridge"
    [[ -d "$FIRMWARE_ROOT/$sub" ]] || die "no such firmware subproject: $sub (expected $FIRMWARE_ROOT/$sub)"
    echo "$FIRMWARE_ROOT/$sub"
}

default_env_for() {
    case "$1" in
        can-logger) echo "logger" ;;
        wifi-bridge) echo "wifi-bridge" ;;
        *) die "no default env known for '$1'" ;;
    esac
}

detect_usb_port() {
    local ports=(/dev/tty.usbmodem*)
    [[ -e "${ports[0]}" ]] || die "no /dev/tty.usbmodem* found — is the ESP32 plugged into the USB port (not UART)?"
    if [[ ${#ports[@]} -gt 1 ]]; then
        info "multiple USB ports present: ${ports[*]}"
        info "using ${ports[0]} — pass --port to override"
    fi
    echo "${ports[0]}"
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' not on PATH${2:+ — $2}"
}
