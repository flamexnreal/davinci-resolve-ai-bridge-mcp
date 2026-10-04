#!/bin/bash
set -e -o pipefail

echo "==> Downloading and installing DaVinci Resolve AI Bridge..."
TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP_DIR"
elif command -v wget >/dev/null 2>&1; then
    wget -qO- "https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP_DIR"
else
    echo "Error: curl or wget is required to download Resolve AI Bridge." >&2
    exit 1
fi

INSTALLERS=("$TMP_DIR"/*/install.py)
if [ "${#INSTALLERS[@]}" -ne 1 ] || [ ! -f "${INSTALLERS[0]}" ]; then
    echo "Error: the downloaded archive must contain exactly one project folder with install.py. Please download the complete repository and try again." >&2
    exit 1
fi
cd "$(dirname "${INSTALLERS[0]}")"

if command -v python3 >/dev/null 2>&1; then
    python3 install.py "$@"
elif command -v python >/dev/null 2>&1; then
    python install.py "$@"
else
    echo "Error: Python 3.10 or newer is required to run DaVinci Resolve AI Bridge." >&2
    echo "Please download and install Python from: https://www.python.org/downloads/" >&2
    exit 1
fi
