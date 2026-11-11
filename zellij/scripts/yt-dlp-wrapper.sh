#!/usr/bin/env bash
REAL="$HOME/.local/bin/yt-dlp.real"

has_client=0
for arg in "$@"; do
  if [[ "$arg" == *"player_client"* ]]; then
    has_client=1
    break
  fi
done

if [ "$has_client" -eq 1 ]; then
  exec "$REAL" "$@"
else
  exec "$REAL" --extractor-args "youtube:player_client=web_music,android" "$@"
fi
