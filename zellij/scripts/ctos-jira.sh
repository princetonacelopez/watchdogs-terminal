#!/usr/bin/env bash
# =============================================================================
# Watch Dogs ctOS Panel: WebIT Project-Aware Jira Sprint Board
# Delegates to ~/.local/bin/jira-project-board (BUX, AREAL, HP, HRE, BUXDATA,
# LO, NA, NJ, PASS, RTE, PRD) with auto-detection from .jira-project / git branch
# =============================================================================
set -euo pipefail

if [[ -x "$HOME/.local/bin/jira-project-board" ]]; then
    exec "$HOME/.local/bin/jira-project-board" "$@"
fi

# Direct fallback using the same WebIT project-detection logic
PROJ_DIR="${1:-$PWD}"
cd "$PROJ_DIR" 2>/dev/null || true

KEY=""
[[ -f ".jira-project" ]] && KEY="$(tr -d '[:space:]' < .jira-project)"
if [[ -z "$KEY" ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    BRANCH="$(git branch --show-current 2>/dev/null || true)"
    KEY="$(echo "$BRANCH" | grep -oP '[A-Z]{2,10}(?=-\d+)' | head -1 || true)"
fi
if [[ -z "$KEY" ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    KEY="$(git log -n 10 --oneline 2>/dev/null | grep -oP '[A-Z]{2,10}(?=-\d+)' | head -1 || true)"
fi
if [[ -z "$KEY" ]]; then
    case "$(basename "$PWD")" in
        *buxton*)        KEY="BUX" ;;
        *areal*)         KEY="AREAL" ;;
        *highland*)      KEY="HP" ;;
        *hodges*)        KEY="HRE" ;;
        *dataonce*)      KEY="BUXDATA" ;;
        *listonce*)      KEY="LO" ;;
        *nelson*)        KEY="NA" ;;
        *noel*)          KEY="NJ" ;;
        *property-pass*) KEY="PASS" ;;
        *rt-edgar*)      KEY="RTE" ;;
        *prd*)           KEY="PRD" ;;
    esac
fi

STATUS_FILTER="status NOT IN (Deployed, Resolved, Closed)"
if [[ -n "$KEY" ]]; then
    exec jira issue list -p "$KEY" -q "assignee = currentUser() AND $STATUS_FILTER"
else
    exec jira issue list -q "assignee = currentUser() AND $STATUS_FILTER"
fi
