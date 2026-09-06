#!/usr/bin/env bash
# Automated release script for davinci-resolve-ai-bridge-mcp
set -euo pipefail

VERSION=${1:-}
if [ -z "$VERSION" ]; then
  echo "Usage: ./scripts/release.sh <version> (e.g. ./scripts/release.sh 1.5.1)"
  exit 1
fi

python3 - "$VERSION" <<'CHECK_VERSION'
import json, sys
from pathlib import Path
from bridge.operations import AGENT_VERSION
expected = sys.argv[1]
package = json.loads(Path("package.json").read_text())
lock = json.loads(Path("package-lock.json").read_text())
if not (package["version"] == lock["version"] == lock["packages"][""]["version"] == AGENT_VERSION == expected):
    raise SystemExit("Version mismatch: synchronize package, lockfile and bridge before publishing.")
if 'version = "%s"' % expected not in Path("pyproject.toml").read_text():
    raise SystemExit("pyproject.toml version does not match.")
CHECK_VERSION

echo "=== Building Production Assets ==="
npm run build

echo "=== Regression and Package Checks ==="
python3 -m unittest discover -s tests -v
node tools/check-package.mjs

echo "=== Publishing to npm ==="
npm publish --access public

echo "=== Release $VERSION Complete & Live! ==="
