#!/usr/bin/env bash
# Fast 1-line CPU load + RAM badge for zjstatus Watch Dogs ctOS top bar
read -r load1 _ < /proc/loadavg
cores=$(nproc 2>/dev/null || echo 8)
cpu_pct=$(awk -v l="$load1" -v c="$cores" 'BEGIN { p = (l / c) * 100; if (p > 100) p = 100; printf "%.0f%%", p }')
ram_str=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END { printf "%.1f/%.0fG", (t-a)/1048576, t/1048576 }' /proc/meminfo)
printf "CPU %s │ RAM %s" "$cpu_pct" "$ram_str"
