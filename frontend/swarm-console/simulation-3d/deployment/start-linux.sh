#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SITE_DIR="$SCRIPT_DIR/site"
PORT="${PORT:-5179}"
BIND="${BIND:-127.0.0.1}"

if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "site/index.html was not found. Extract the complete offline package first." >&2
  exit 1
fi

echo "Serving $SITE_DIR"
echo "URL: http://$BIND:$PORT/"
echo "Press Ctrl+C to stop."
exec python3 -m http.server "$PORT" --bind "$BIND" --directory "$SITE_DIR"

