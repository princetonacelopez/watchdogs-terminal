#!/usr/bin/env bash
# =============================================================================
# Watch Dogs ctOS Panel: Clark Ground Station Weather & Telemetry
# Delegates to ~/.local/bin/zdev-dashboard (Clark, Pampanga 15.18°N, 120.55°E)
# =============================================================================
set -euo pipefail

if [[ -x "$HOME/.local/bin/zdev-dashboard" ]]; then
    exec "$HOME/.local/bin/zdev-dashboard" "$@"
fi
