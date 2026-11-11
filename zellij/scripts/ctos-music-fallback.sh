#!/usr/bin/env bash
# =============================================================================
# Watch Dogs ctOS Panel: YouTube Music Stream Fallback / Launcher
# Location: ~/.config/zellij/scripts/ctos-music-fallback.sh
# =============================================================================

CYAN='\033[38;2;0;240;255m'
MAGENTA='\033[38;2;255;0;85m'
GREEN='\033[38;2;0;255;156m'
DIM='\033[38;2;90;115;140m'
WHITE='\033[38;2;226;241;255m'
RESET='\033[0m'

clear
echo -e "${CYAN}┌──[ ctOS // AUDIO_STREAM :: YT_MUSIC ]───────────────────────────┐${RESET}"
echo -e "  ${GREEN}▶ NOW_PLAYING:${RESET} ${WHITE}DedSec // Hudson Mohawke - Watch Dogs OST${RESET}"
echo -e "  ${DIM}02:14 [━━━━━━━━━━━━━━●───────────] 03:48  VOL: 85% [PIPEWIRE]${RESET}"
echo ""
echo -e "  ${CYAN}▁ ▃ ▅ ▇ █ ▆ ▄ ▂ ▁ ▄ ▆ █ ▅ ▃ ▂ ▅ ▇ █ ▄ ▂ ▁ ▃ ▆ ▇ ▄ ▂${RESET}"
echo ""
echo -e "  ${DIM}>> Enter search query to stream from YouTube Music (via yt-dlp + mpv):${RESET}"
while true; do
    read -rp "  [ctOS_AUDIO]> " query
    if [[ -n "$query" ]]; then
        mpv --no-video "ytdl://ytsearch1:${query}"
    fi
done
