#!/usr/bin/env bash
# =============================================================================
# Watch Dogs (ctOS 2.0 // DedSec) + Rex Glass Fullstack Terminal Setup
# Target OS: Fedora 45 (and Fedora 43/44+)
#
# Automates 100% of your terminal setup on a new machine:
#   1. System Packages (dnf): ghostty, zellij, cava, zoxide, fzf, jq, fd-find,
#      ripgrep, bat, eza, git-delta, mpv, ffmpeg-free, v4l-utils, python3-opencv,
#      python3-pillow, python3-psutil, python3-secretstorage, python3-cryptography
#   2. Python Packages (pip): pixelart-py, dbus-next, requests
#   3. CLI Binaries (~/.local/bin):
#      - lazygit, lazydocker, jira-cli (jira), dymus (YouTube Music TUI),
#        yt-dlp (+ web_music/android wrapper), starship, zjstatus.wasm
#   4. Fonts (~/.local/share/fonts):
#      - JetBrainsMono Nerd Font Mono + Watch Dogs HACKED.ttf
#   5. Watch Dogs ctOS 2.0 HUD (zdev / zdev-window):
#      - 7-Pane 3-Column Zellij layout (dev.kdl & watchdogs.kdl) with:
#        * Live Camera Biometric FaceID Modal (ctos-faceid-auth)
#        * Synchronized Panel Blur/Static Lock & Post-Modal Fade-In (ctos-panel-guard)
#        * 1:1 Portrait Profiler with WebIT | Offsure badge (ctos-profiler-ace)
#        * Full X (Twitter) Feed with Native Kitty Graphics Images (ctos-intel-feed & ctos-x-auth)
#        * Fullstack Developer CLI + Persistent YouTube Music & Visualizer (ctos-dymus-persist)
#        * AI Agents Squad Panel with Open-Source Character Avatars (ctos-ai-agents)
#        * WebIT Jira Sprint Board (jira-project-board) & Bitbucket PR Pipeline (bitbucket-prs)
#      - Ghostty Startup Workspace Launcher (ctos-ghostty-welcome)
#      - Custom GLSL CRT Scanline Shader (ctos-hud.glsl)
#   6. Rex Glass Setup (zrex) + PAM Biometric FaceID (optional via flags)
#   7. Shell Integration (~/.bashrc & ~/.bashrc.d) + Desktop Launchers
#
# Usage:
#   ./install-fedora45.sh                  # Full interactive/automated setup
#   ./install-fedora45.sh --skip-packages  # Skip dnf/binary downloads (configs & scripts only)
#   ./install-fedora45.sh --with-faceid-pam # Also compile & install system PAM FaceID
#   ./install-fedora45.sh --with-gnome-blur # Also install GNOME Blur my Shell for Rex
#   ./install-fedora45.sh --dry-run        # Preview all actions without modifying system
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DRY_RUN=0
SKIP_PACKAGES=0
WITH_FACEID_PAM=0
WITH_GNOME_BLUR=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)         DRY_RUN=1 ;;
    --skip-packages)   SKIP_PACKAGES=1 ;;
    --with-faceid-pam) WITH_FACEID_PAM=1 ;;
    --with-gnome-blur) WITH_GNOME_BLUR=1 ;;
    -h|--help)
      sed -n '2,37p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

C_CYAN="\033[38;2;0;240;255m"
C_GREEN="\033[38;2;0;255;156m"
C_YELLOW="\033[38;2;255;214;0m"
C_RED="\033[38;2;255;0;85m"
C_BOLD="\033[1m"
C_RESET="\033[0m"

info()  { printf "${C_CYAN}${C_BOLD}[ctOS // SETUP]${C_RESET} %s\n" "$*"; }
ok()    { printf "${C_GREEN}${C_BOLD}[  ✔  ONLINE  ]${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_YELLOW}${C_BOLD}[  !  NOTICE  ]${C_RESET} %s\n" "$*"; }
err()   { printf "${C_RED}${C_BOLD}[  ✖  ERROR   ]${C_RESET} %s\n" "$*" >&2; }

run() {
  if ((DRY_RUN)); then
    printf "${C_YELLOW}[dry-run]${C_RESET} %s\n" "$*"
  else
    "$@"
  fi
}

install_templated() {
  # Copy file while replacing hardcoded /home/princetonacelopez or __HOME__ with target $HOME
  local src="$1" dst="$2" mode="${3:-644}"
  if ((DRY_RUN)); then
    printf "${C_YELLOW}[dry-run]${C_RESET} install %s -> %s (%s)\n" "$src" "$dst" "$mode"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  local tmp
  tmp="$(mktemp)"
  sed -e "s|/home/princetonacelopez|$HOME|g" -e "s|__HOME__|$HOME|g" "$src" > "$tmp"
  install -m "$mode" "$tmp" "$dst"
  rm -f "$tmp"
}

echo ""
printf "${C_CYAN}${C_BOLD}╔══════════════════════════════════════════════════════════════════════════╗${C_RESET}\n"
printf "${C_CYAN}${C_BOLD}║   ⌁ ctOS 2.0 // DEDSEC FULLSTACK WORKSTATION INSTALLER (FEDORA 45) ⌁    ║${C_RESET}\n"
printf "${C_CYAN}${C_BOLD}╚══════════════════════════════════════════════════════════════════════════╝${C_RESET}\n"
echo ""

# =============================================================================
# STEP 1: DIRECTORY STRUCTURE
# =============================================================================
info "Creating directory structure under $HOME..."
run mkdir -p \
  "$HOME/.local/bin" \
  "$HOME/.local/share/fonts" \
  "$HOME/.local/share/applications" \
  "$HOME/.config/ghostty/shaders" \
  "$HOME/.config/zellij/layouts" \
  "$HOME/.config/zellij/themes" \
  "$HOME/.config/zellij/plugins" \
  "$HOME/.config/zellij/scripts" \
  "$HOME/.config/zellij/assets/agents" \
  "$HOME/.config/dymus" \
  "$HOME/.config/lazygit" \
  "$HOME/.config/lazydocker" \
  "$HOME/.config/cava" \
  "$HOME/.config/dev" \
  "$HOME/.bashrc.d" \
  "$HOME/Projects"

# =============================================================================
# STEP 2: FEDORA 45 SYSTEM PACKAGES (DNF) & PYTHON LIBRARIES
# =============================================================================
if (( ! SKIP_PACKAGES )); then
  info "Checking & installing Fedora 45 system packages via dnf..."
  # Enable COPR for ghostty / zellij if not already in official Fedora 45 repos
  if ! rpm -q ghostty >/dev/null 2>&1 && ! dnf list --available ghostty >/dev/null 2>&1; then
    run sudo dnf copr enable -y pgdev/ghostty || true
  fi
  if ! rpm -q zellij >/dev/null 2>&1 && ! dnf list --available zellij >/dev/null 2>&1; then
    run sudo dnf copr enable -y varlad/zellij || true
  fi

  DNF_PKGS=(
    ghostty
    zellij
    cava
    zoxide
    fzf
    jq
    fd-find
    ripgrep
    bat
    eza
    git-delta
    mpv
    ffmpeg-free
    libv4l
    v4l-utils
    opencv
    opencv-data
    python3-pip
    python3-opencv
    python3-pillow
    python3-psutil
    python3-secretstorage
    python3-cryptography
    python3-gobject
    python3-dbus
    python3-requests
    pre-commit
    wl-clipboard
    curl
    unzip
    tar
  )
  MISSING_DNF=()
  for pkg in "${DNF_PKGS[@]}"; do
    if ! rpm -q "$pkg" >/dev/null 2>&1; then
      MISSING_DNF+=("$pkg")
    fi
  done
  if (( ${#MISSING_DNF[@]} > 0 )); then
    info "Installing missing RPM packages: ${MISSING_DNF[*]}"
    run sudo dnf install -y --skip-unavailable "${MISSING_DNF[@]}"
  else
    ok "All Fedora 45 RPM dependencies are already installed."
  fi

  # Ensure user is in the 'video' group so /dev/video0 works for FaceID
  if ! id -nG "$USER" | grep -qw "video"; then
    info "Adding $USER to 'video' group for webcam (/dev/video0) access..."
    run sudo usermod -aG video "$USER" || true
  fi

  info "Installing Python user libraries (pixelart-py, dbus-next, requests)..."
  run python3 -m pip install --user --quiet --upgrade pixelart-py dbus-next requests || \
  run python3 -m pip install --user --break-system-packages --quiet pixelart-py dbus-next requests || true
fi

# =============================================================================
# STEP 3: STANDALONE CLI BINARIES (lazygit, lazydocker, jira, dymus, yt-dlp, starship)
# =============================================================================
if (( ! SKIP_PACKAGES )); then
  ARCH="$(uname -m)"
  # 3a. lazygit
  if [[ ! -x "$HOME/.local/bin/lazygit" ]] && ! command -v lazygit >/dev/null 2>&1; then
    info "Downloading latest lazygit binary to ~/.local/bin/lazygit..."
    if (( ! DRY_RUN )); then
      LG_VER="$(curl -fsSL https://api.github.com/repos/jesseduffield/lazygit/releases/latest | jq -r '.tag_name' | sed 's/^v//')"
      curl -fsSL "https://github.com/jesseduffield/lazygit/releases/download/v${LG_VER}/lazygit_${LG_VER}_Linux_x86_64.tar.gz" | tar -xz -C "$HOME/.local/bin" lazygit
      chmod +x "$HOME/.local/bin/lazygit"
    fi
  fi

  # 3b. lazydocker
  if [[ ! -x "$HOME/.local/bin/lazydocker" ]] && ! command -v lazydocker >/dev/null 2>&1; then
    info "Downloading latest lazydocker binary to ~/.local/bin/lazydocker..."
    if (( ! DRY_RUN )); then
      LD_VER="$(curl -fsSL https://api.github.com/repos/jesseduffield/lazydocker/releases/latest | jq -r '.tag_name' | sed 's/^v//')"
      curl -fsSL "https://github.com/jesseduffield/lazydocker/releases/download/v${LD_VER}/lazydocker_${LD_VER}_Linux_x86_64.tar.gz" | tar -xz -C "$HOME/.local/bin" lazydocker
      chmod +x "$HOME/.local/bin/lazydocker"
    fi
  fi

  # 3c. jira-cli (ankitpokhrel/jira-cli)
  if [[ ! -x "$HOME/.local/bin/jira" ]] && ! command -v jira >/dev/null 2>&1; then
    info "Downloading jira-cli binary to ~/.local/bin/jira..."
    if (( ! DRY_RUN )); then
      JIRA_VER="$(curl -fsSL https://api.github.com/repos/ankitpokhrel/jira-cli/releases/latest | jq -r '.tag_name' | sed 's/^v//')"
      TMP_JIRA="$(mktemp -d)"
      curl -fsSL "https://github.com/ankitpokhrel/jira-cli/releases/download/v${JIRA_VER}/jira_${JIRA_VER}_linux_x86_64.tar.gz" | tar -xz -C "$TMP_JIRA"
      find "$TMP_JIRA" -name "jira" -type f -exec install -m 755 {} "$HOME/.local/bin/jira" \;
      rm -rf "$TMP_JIRA"
    fi
  fi

  # 3d. yt-dlp.real + YouTube Music player_client wrapper
  if [[ ! -x "$HOME/.local/bin/yt-dlp.real" ]]; then
    info "Downloading latest yt-dlp binary to ~/.local/bin/yt-dlp.real..."
    if (( ! DRY_RUN )); then
      curl -fsSL "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux" -o "$HOME/.local/bin/yt-dlp.real"
      chmod +x "$HOME/.local/bin/yt-dlp.real"
    fi
  fi
  install_templated "$SCRIPT_DIR/zellij/scripts/yt-dlp-wrapper.sh" "$HOME/.local/bin/yt-dlp" 755

  # 3e. dymus (YouTube Music TUI Client)
  if [[ ! -x "$HOME/.local/bin/dymus" ]] && ! command -v dymus >/dev/null 2>&1; then
    info "Installing dymus (YouTube Music TUI) to ~/.local/bin/dymus..."
    if (( ! DRY_RUN )); then
      DYMUS_URL="$(curl -fsSL https://api.github.com/repos/inzaniak/dymus/releases/latest 2>/dev/null | jq -r '.assets[]?.browser_download_url | select(test("linux.*(x86_64|amd64)"))' | head -n 1 || true)"
      if [[ -n "$DYMUS_URL" ]]; then
        TMP_DYM="$(mktemp -d)"
        curl -fsSL "$DYMUS_URL" | tar -xz -C "$TMP_DYM" 2>/dev/null || curl -fsSL "$DYMUS_URL" -o "$HOME/.local/bin/dymus"
        find "$TMP_DYM" -name "dymus" -type f -exec install -m 755 {} "$HOME/.local/bin/dymus" \; 2>/dev/null || true
        chmod +x "$HOME/.local/bin/dymus" 2>/dev/null || true
        rm -rf "$TMP_DYM"
      elif command -v cargo >/dev/null 2>&1; then
        cargo install --git https://github.com/inzaniak/dymus --root "$HOME/.local" || true
      fi
    fi
  fi

  # 3f. starship prompt
  if [[ ! -x "$HOME/.local/bin/starship" ]] && ! command -v starship >/dev/null 2>&1; then
    info "Installing starship prompt to ~/.local/bin/starship..."
    if (( ! DRY_RUN )); then
      curl -fsSL https://starship.rs/install.sh | sh -s -- -y -b "$HOME/.local/bin" >/dev/null 2>&1 || true
    fi
  fi
fi

# =============================================================================
# STEP 4: FONTS (Watch Dogs HACKED.ttf + JetBrainsMono Nerd Font)
# =============================================================================
info "Installing Watch Dogs HACKED.ttf & JetBrainsMono Nerd Font..."
install_templated "$SCRIPT_DIR/ghostty/fonts/HACKED.ttf" "$HOME/.local/share/fonts/HACKED.ttf" 644

if (( ! SKIP_PACKAGES )) && [[ ! -d "$HOME/.local/share/fonts/JetBrainsMono" ]] && ! fc-list | grep -qi "JetBrainsMono Nerd Font"; then
  info "Downloading JetBrainsMono Nerd Font..."
  if (( ! DRY_RUN )); then
    mkdir -p "$HOME/.local/share/fonts/JetBrainsMono"
    curl -fsSL "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.tar.xz" | tar -xJ -C "$HOME/.local/share/fonts/JetBrainsMono" || true
  fi
fi
run fc-cache -f "$HOME/.local/share/fonts"

# =============================================================================
# STEP 5: DEPLOY WATCH DOGS ctOS 2.0 SCRIPTS, ZELLIJ LAYOUTS, THEMES & ASSETS
# =============================================================================
info "Deploying Watch Dogs ctOS 2.0 HUD scripts to ~/.local/bin..."
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-ai-agents.py"       "$HOME/.local/bin/ctos-ai-agents"       755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-bar-metrics.sh"     "$HOME/.local/bin/ctos-bar-metrics"     755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-bar-weather.sh"     "$HOME/.local/bin/ctos-bar-weather"     755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-dymus-persist.py"   "$HOME/.local/bin/ctos-dymus-persist"   755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-faceid-auth.py"     "$HOME/.local/bin/ctos-faceid-auth"     755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-ghostty-welcome.py" "$HOME/.local/bin/ctos-ghostty-welcome" 755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-intel-feed.py"      "$HOME/.local/bin/ctos-intel-feed"      755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-panel-guard.py"     "$HOME/.local/bin/ctos-panel-guard"     755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-profiler-ace.py"    "$HOME/.local/bin/ctos-profiler-ace"    755
install_templated "$SCRIPT_DIR/zellij/scripts/ctos-x-auth.py"          "$HOME/.local/bin/ctos-x-auth"          755
install_templated "$SCRIPT_DIR/zellij/scripts/jira-project-board.py"   "$HOME/.local/bin/jira-project-board"   755
install_templated "$SCRIPT_DIR/zellij/scripts/bitbucket-prs.py"        "$HOME/.local/bin/bitbucket-prs"        755
install_templated "$SCRIPT_DIR/zellij/scripts/zdev"                    "$HOME/.local/bin/zdev"                 755
install_templated "$SCRIPT_DIR/zellij/scripts/zdev-window"             "$HOME/.local/bin/zdev-window"          755
install_templated "$SCRIPT_DIR/zellij/scripts/bb"                      "$HOME/.local/bin/bb"                   755
install_templated "$SCRIPT_DIR/zellij/scripts/jb"                      "$HOME/.local/bin/jb"                   755
install_templated "$SCRIPT_DIR/zellij/scripts/dev"                     "$HOME/.local/bin/dev"                  755
install_templated "$SCRIPT_DIR/zellij/scripts/jira-open"               "$HOME/.local/bin/jira-open"            755
run ln -sf "$HOME/.local/bin/bitbucket-prs" "$HOME/.local/bin/zdev-bitbucket-prs"

info "Deploying Zellij config, plugins (zjstatus.wasm), layouts, themes, and avatars..."
install_templated "$SCRIPT_DIR/zellij/config.kdl"                  "$HOME/.config/zellij/config.kdl"                  644
install_templated "$SCRIPT_DIR/zellij/layouts/dev.kdl"             "$HOME/.config/zellij/layouts/dev.kdl"             644
install_templated "$SCRIPT_DIR/zellij/layouts/watchdogs.kdl"       "$HOME/.config/zellij/layouts/watchdogs.kdl"       644
install_templated "$SCRIPT_DIR/zellij/themes/watchdogs-ctos.kdl"   "$HOME/.config/zellij/themes/watchdogs-ctos.kdl"   644
install_templated "$SCRIPT_DIR/zellij/themes/zdev-hud.kdl"         "$HOME/.config/zellij/themes/zdev-hud.kdl"         644

if [[ -f "$SCRIPT_DIR/zellij/plugins/zjstatus.wasm" ]]; then
  run cp -f "$SCRIPT_DIR/zellij/plugins/zjstatus.wasm" "$HOME/.config/zellij/plugins/zjstatus.wasm"
elif (( ! SKIP_PACKAGES && ! DRY_RUN )); then
  curl -fsSL "https://github.com/dj95/zjstatus/releases/latest/download/zjstatus.wasm" -o "$HOME/.config/zellij/plugins/zjstatus.wasm"
fi

run cp -f "$SCRIPT_DIR/zellij/assets/ace_photo.jpg" "$HOME/.config/zellij/assets/ace_photo.jpg"
run cp -rf "$SCRIPT_DIR/zellij/assets/agents/"* "$HOME/.config/zellij/assets/agents/"

# =============================================================================
# STEP 6: DEPLOY GHOSTTY CONFIGS, SHADERS & TOOL CONFIGS
# =============================================================================
info "Deploying Ghostty configs, CRT GLSL shader, and tool configurations..."
install_templated "$SCRIPT_DIR/ghostty/config.ghostty"        "$HOME/.config/ghostty/config.ghostty"        644
install_templated "$SCRIPT_DIR/ghostty/ctos.ghostty"          "$HOME/.config/ghostty/ctos.ghostty"          644
install_templated "$SCRIPT_DIR/ghostty/shaders/ctos-hud.glsl" "$HOME/.config/ghostty/shaders/ctos-hud.glsl" 644

install_templated "$SCRIPT_DIR/configs/dymus/config.toml"           "$HOME/.config/dymus/config.toml"           644
install_templated "$SCRIPT_DIR/configs/lazygit/config.yml"          "$HOME/.config/lazygit/config.yml"          644
install_templated "$SCRIPT_DIR/configs/lazydocker/config.yml"       "$HOME/.config/lazydocker/config.yml"       644
install_templated "$SCRIPT_DIR/configs/cava/config"                 "$HOME/.config/cava/config"                 644
install_templated "$SCRIPT_DIR/configs/dev/pre-commit-config.yaml"  "$HOME/.config/dev/pre-commit-config.yaml"  644
install_templated "$SCRIPT_DIR/configs/bashrc.d/50-dev.sh"          "$HOME/.bashrc.d/50-dev.sh"                 644
install_templated "$SCRIPT_DIR/configs/bashrc.d/60-custom.sh"       "$HOME/.bashrc.d/60-custom.sh"              755

# Create template ~/.config/dev/secrets.env if it doesn't exist yet
if [[ ! -f "$HOME/.config/dev/secrets.env" ]] && (( ! DRY_RUN )); then
  cat > "$HOME/.config/dev/secrets.env" <<'EOF'
# WebIT Jira & Bitbucket API Credentials (chmod 600)
export JIRA_URL="https://webitau.atlassian.net"
export JIRA_EMAIL="princeton@webit.com.au"
export JIRA_API_TOKEN=""
export BITBUCKET_TOKEN=""
EOF
  chmod 600 "$HOME/.config/dev/secrets.env"
  warn "Created template ~/.config/dev/secrets.env — fill in JIRA_API_TOKEN and BITBUCKET_TOKEN."
fi

# =============================================================================
# STEP 7: INSTALL REX GLASS SETUP ALONGSIDE zdev
# =============================================================================
if [[ -x "$SCRIPT_DIR/install-rex.sh" ]]; then
  info "Installing Rex Glass Terminal setup alongside zdev..."
  REX_ARGS=()
  ((DRY_RUN)) && REX_ARGS+=(--dry-run)
  ((WITH_GNOME_BLUR)) && REX_ARGS+=(--with-blur)
  "$SCRIPT_DIR/install-rex.sh" "${REX_ARGS[@]}"
fi

# =============================================================================
# STEP 8: SHELL INTEGRATION (~/.bashrc)
# =============================================================================
info "Configuring ~/.bashrc with ctOS FaceID panel guard & Ghostty startup launcher..."
if (( ! DRY_RUN )); then
  touch "$HOME/.bashrc"
  # Remove any older block if re-running installer
  python3 - "$HOME/.bashrc" <<'PYEOF'
import sys, re
path = sys.argv[1]
with open(path, "r") as f:
    content = f.read()

# Clean up any legacy or duplicate ctOS blocks before appending canonical block
pattern = re.compile(
    r"# Watch Dogs ctOS FaceID blurred/static.*?(?:launcher_menu\nfi\n?)",
    re.DOTALL
)
content = pattern.sub("", content).rstrip() + "\n\n"

block = """# Watch Dogs ctOS FaceID blurred/static + fade-in transition for Zellij CLI pane
if [[ -n "${ZELLIJ:-}" && "${ZELLIJ_SESSION_NAME:-}" != rex-* && $- == *i* && -x "$HOME/.local/bin/ctos-panel-guard" ]]; then
  "$HOME/.local/bin/ctos-panel-guard" --inline || true
fi

# Watch Dogs ctOS Ghostty Startup Launcher (Recent Folders & Project Folders Selection)
welcome() {
  local act_file="/tmp/ctos_welcome_action.$$"
  rm -f "$act_file"
  "$HOME/.local/bin/ctos-ghostty-welcome" --out-file "$act_file" || true
  if [[ -f "$act_file" ]]; then
    local line action target
    line="$(cat "$act_file")"
    rm -f "$act_file"
    action="${line%%|*}"
    target="${line#*|}"
    if [[ -n "$target" && -d "$target" ]]; then
      case "$action" in
        zdev)
          # open the ctOS-styled window (zdev-window) and close this plain launcher window
          if command -v zdev-window >/dev/null 2>&1 && [[ "${TERM_PROGRAM:-}" == "ghostty" ]]; then
            setsid zdev-window "$target" >/dev/null 2>&1 < /dev/null &
            disown 2>/dev/null; exit 0
          fi
          cd "$target" && exec "$HOME/.local/bin/zdev" "$target"
          ;;
        cd)
          cd "$target" || true
          ;;
        antigravity)
          cd "$target" || true
          nohup "$HOME/.local/bin/antigravity" "$target" >/dev/null 2>&1 &
          ;;
        cursor)
          cd "$target" || true
          nohup cursor "$target" >/dev/null 2>&1 &
          ;;
      esac
    fi
  fi
}
alias start='welcome'

# Ghostty opens as a plain, unstyled window. Choose a workspace style:
#   1/z = zdev (ctOS HUD, new styled window)   2/r = zrex (glass, new styled window)   3/Enter = plain shell
launcher_menu() {
  local k
  printf '\\n  \\033[1mGhostty\\033[0m  —  choose a workspace\\n\\n'
  printf '   \\033[1m1\\033[0m  zdev   ctOS HUD (Watch Dogs)\\n'
  printf '   \\033[1m2\\033[0m  zrex   Rex-style glass\\n'
  printf '   \\033[1m3\\033[0m  plain shell  \\033[2m(default)\\033[0m\\n\\n  > '
  read -rsn1 k || return 0
  printf '\\n'
  case "$k" in
    1|z|Z) welcome ;;
    2|r|R)
      if command -v zrex >/dev/null 2>&1; then
        zrex pick --window && exit 0
      fi ;;
    *) : ;;
  esac
}

if [[ "${TERM_PROGRAM:-}" == "ghostty" && -z "${ZELLIJ:-}" && $- == *i* && -z "${CTOS_WELCOME_SHOWN:-}" ]]; then
  export CTOS_WELCOME_SHOWN=1
  launcher_menu
fi
"""
with open(path, "w") as f:
    f.write(content + block)
PYEOF
fi

# =============================================================================
# STEP 9: OPTIONAL SYSTEM PAM FACEID MODULE (--with-faceid-pam)
# =============================================================================
if (( WITH_FACEID_PAM )) && [[ -x "$SCRIPT_DIR/faceid/install-faceid.sh" ]]; then
  info "Installing system PAM Biometric FaceID + GNOME Dynamic Island extension..."
  run "$SCRIPT_DIR/faceid/install-faceid.sh"
fi

# =============================================================================
# STEP 10: AUTO-SYNC X (TWITTER) SESSION IF GOOGLE CHROME IS LOGGED IN
# =============================================================================
if (( ! DRY_RUN )) && [[ -x "$HOME/.local/bin/ctos-x-auth" ]]; then
  info "Checking local Google Chrome session for X (Twitter) feed cookies..."
  "$HOME/.local/bin/ctos-x-auth" >/dev/null 2>&1 && ok "X (Twitter) session synced from Google Chrome!" || \
    warn "Log into x.com in Google Chrome and run 'ctos-x-auth' (or press [a] in the X_FEED panel)."
fi

echo ""
printf "${C_GREEN}${C_BOLD}╔══════════════════════════════════════════════════════════════════════════╗${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   ✔ WATCH DOGS (ctOS 2.0 // DEDSEC) & REX SETUP COMPLETE!                ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}╠══════════════════════════════════════════════════════════════════════════╣${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Launch Ghostty       -> Interactive Workspace Picker (1=zdev, 2=zrex)║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Run 'welcome'        -> Recent Folders & Project Folders Matrix      ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Run 'zdev'           -> Launch Watch Dogs ctOS 2.0 7-Pane HUD        ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Run 'zdev-window'    -> Open zdev in dedicated ctOS Ghostty window   ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Run 'ctos-x-auth'    -> Sync free X.com feed from Google Chrome      ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}║   • Run 'jira init'      -> Authenticate WebIT Jira CLI (once)           ║${C_RESET}\n"
printf "${C_GREEN}${C_BOLD}╚══════════════════════════════════════════════════════════════════════════╝${C_RESET}\n"
