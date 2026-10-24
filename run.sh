#!/bin/bash
# Loads .env and runs the bridge. Used for manual testing and as the
# target for a background service (launchd/systemd/etc.) once deployed.
cd "$(dirname "$0")"
set -a
[ -f .env ] && source .env
set +a
exec python3 -m uvicorn bridge:app --host 127.0.0.1 --port 8732
