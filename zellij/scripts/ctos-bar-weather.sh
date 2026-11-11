#!/usr/bin/env bash
# Fast, non-blocking Weather + Location badge for zjstatus top-right bar
# Output example: 25°C SUNNY · CLARK, PAMPANGA

CACHE_FILE="/tmp/zdev_weather_clark.json"
MAX_AGE=1200  # 20 minutes

refresh_cache() {
    local raw temp desc now
    raw=$(curl -s --max-time 4 -A "curl/7.88.1" "https://wttr.in/Clark,Pampanga?format=j1" 2>/dev/null || true)
    if [[ -n "$raw" ]]; then
        temp=$(printf '%s' "$raw" | jq -r '.current_condition[0].temp_C // empty' 2>/dev/null || true)
        desc=$(printf '%s' "$raw" | jq -r '.current_condition[0].weatherDesc[0].value // empty' 2>/dev/null || true)
        now=$(date +%s)
        if [[ -n "$temp" && -n "$desc" ]]; then
            jq -n \
                --arg temp "$temp" \
                --arg desc "$desc" \
                --arg loc "Clark, Pampanga" \
                --argjson ts "$now" \
                '{temp: $temp, desc: $desc, location: $loc, timestamp: $ts}' > "${CACHE_FILE}.tmp" 2>/dev/null \
                && mv -f "${CACHE_FILE}.tmp" "$CACHE_FILE"
        fi
    fi
}

now=$(date +%s)
if [[ -f "$CACHE_FILE" ]]; then
    ts=$(jq -r '.timestamp // 0 | floor' "$CACHE_FILE" 2>/dev/null || echo 0)
    if (( now - ts > MAX_AGE )); then
        (refresh_cache >/dev/null 2>&1 &)
    fi
else
    refresh_cache
fi

if [[ -f "$CACHE_FILE" ]]; then
    temp=$(jq -r '.temp // "25"' "$CACHE_FILE" 2>/dev/null || echo "25")
    desc=$(jq -r '.desc // "Sunny"' "$CACHE_FILE" 2>/dev/null | tr '[:lower:]' '[:upper:]')
    loc=$(jq -r '.location // "Clark, Pampanga"' "$CACHE_FILE" 2>/dev/null | tr '[:lower:]' '[:upper:]')
    [[ "$loc" == "CLARK" ]] && loc="CLARK, PAMPANGA"
    printf "%s°C %s · %s" "$temp" "$desc" "$loc"
else
    printf "25°C SUNNY · CLARK, PAMPANGA"
fi
