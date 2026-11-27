#!/bin/bash
# Fortnite shoot: finish the recording file and stop the overlay.
STATE="$HOME/.cache/fortnite-shoot"
TAKE="$(cat "$STATE/take" 2>/dev/null)"
for name in record overlay; do
  pid="$(cat "$STATE/$name.pid" 2>/dev/null)"
  [ -n "$pid" ] && kill -INT "$pid" 2>/dev/null
  for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  rm -f "$STATE/$name.pid"
done
[ -n "$TAKE" ] || { echo "Nothing was recording."; exit 0; }
cat "$TAKE-record.log" 2>/dev/null | tail -2
if [ -s "$TAKE.mov" ]; then
  /opt/homebrew/bin/ffprobe -v error -show_entries stream=codec_type,width,height,avg_frame_rate -show_entries format=duration -of compact "$TAKE.mov" 2>/dev/null
  echo "Saved: $TAKE.mov"
  open -R "$TAKE.mov"
else
  echo "No video file was written. See $TAKE-record.log"
fi
