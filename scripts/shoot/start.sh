#!/bin/bash
# Fortnite shoot: start the live overlay (frozen route, token HUD) on PS Remote Play and record that window + HUD
# at native resolution, 60 fps, with game sound, into ~/Brand/library/raw/<date>-fortnite-live/.
# Testing without a console: WINDOW_ID=<id> start.sh (ids: .venv/bin/python scripts/steering/live.py --list-windows).
set -u
REPO="$HOME/Developer/fortnite-chest-route"
STATE="$HOME/.cache/fortnite-shoot"
mkdir -p "$STATE"
cd "$REPO" || exit 1
if [ -f "$STATE/record.pid" ] && kill -0 "$(cat "$STATE/record.pid")" 2>/dev/null; then
  echo "Already recording. Double-click 'Fortnite shoot STOP' first."; exit 1
fi
DIR="$HOME/Brand/library/raw/$(date +%F)-fortnite-live"
mkdir -p "$DIR"
TAKE="$DIR/take-$(date +%H%M%S)"
echo "$TAKE" > "$STATE/take"
# the recorder (rebuilt only when its source changes)
BIN="$REPO/out/shoot/shoot-record"
mkdir -p "$REPO/out/shoot"
if [ ! -x "$BIN" ] || [ scripts/shoot/shoot_record.swift -nt "$BIN" ]; then
  echo "Building the recorder (first time only)..."; swiftc -O scripts/shoot/shoot_record.swift -o "$BIN" || exit 1
fi
if [ -n "${WINDOW_ID:-}" ]; then PICK=(--window-id "$WINDOW_ID"); else PICK=(--remote-play); fi
echo "Starting the overlay..."
.venv/bin/python scripts/steering/live.py "${PICK[@]}" --hud --headless --metrics "$TAKE-overlay.json" < /dev/null > "$TAKE-overlay.log" 2>&1 &
echo $! > "$STATE/overlay.pid"
for i in $(seq 1 60); do                       # wait for the HUD window (first run compiles it)
  sleep 1
  kill -0 "$(cat "$STATE/overlay.pid")" 2>/dev/null || { echo "Overlay stopped:"; tail -5 "$TAKE-overlay.log"; exit 1; }
  pgrep -f "out/steering/window-hud" >/dev/null && break
done
sleep 2
if [ -n "${WINDOW_ID:-}" ]; then RPICK=(--window-id "$WINDOW_ID"); else RPICK=(); fi
"$BIN" --out "$TAKE.mov" "${RPICK[@]}" --fps 60 < /dev/null > /dev/null 2> "$TAKE-record.log" &
echo $! > "$STATE/record.pid"
sleep 3
if ! kill -0 "$(cat "$STATE/record.pid")" 2>/dev/null; then echo "Recorder didn't start:"; cat "$TAKE-record.log"; exit 1; fi
cat "$TAKE-record.log"
echo
echo "RECORDING. Play. When you're done, double-click 'Fortnite shoot STOP'."
