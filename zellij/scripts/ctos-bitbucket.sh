#!/usr/bin/env bash
# =============================================================================
# Watch Dogs ctOS Panel: Bitbucket Cloud Active PRs (webtechit workspace)
# Delegates to ~/.local/bin/bitbucket-prs:
#   - Workspace: webtechit
#   - Author UUID: {09f87d99-3b7c-4072-8489-84ffaf896456} (Princeton Lopez)
#   - Auth: BITBUCKET_TOKEN, ~/.config/dev/secrets.env, or ~/.git-credentials
#   - Repos: ~/Projects/* + areal, buxton-real-estate, dataonce,
#     highland-property-website, hodges-real-estate, listonce, nelson-alexander,
#     noel-jones, prd, property-pass, rt-edgar-website
# =============================================================================
set -euo pipefail

if [[ -x "$HOME/.local/bin/bitbucket-prs" ]]; then
    exec "$HOME/.local/bin/bitbucket-prs" "$@"
fi
