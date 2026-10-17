#!/bin/bash
set -e -o pipefail

# Check prerequisites before downloading anything.
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "Error: Python 3.10 or newer is required to run DaVinci Resolve AI Bridge." >&2
    echo "Please download and install Python from: https://www.python.org/downloads/" >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    echo "Error: curl or wget is required to download Resolve AI Bridge." >&2
    exit 1
fi

echo "==> Downloading and installing DaVinci Resolve AI Bridge..."
TMP_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE="https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp/archive/refs/heads/main.tar.gz"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$ARCHIVE" | tar -xz -C "$TMP_DIR"
else
    wget -qO- "$ARCHIVE" | tar -xz -C "$TMP_DIR"
fi

INSTALLERS=("$TMP_DIR"/*/install.py)
if [ "${#INSTALLERS[@]}" -ne 1 ] || [ ! -f "${INSTALLERS[0]}" ]; then
    echo "Error: the downloaded archive must contain exactly one project folder with install.py. Please download the complete repository and try again." >&2
    exit 1
fi
cd "$(dirname "${INSTALLERS[0]}")"

"$PYTHON" install.py "$@"
