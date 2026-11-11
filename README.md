# ctOS 2.0 // DedSec Terminal HUD (`zdev`)

<p align="center">
  <img src="https://raw.githubusercontent.com/princetonacelopez/watchdogs-terminal/main/zellij/assets/ace_photo.jpg" alt="ctOS Avatar" width="120" style="border-radius: 50%;" />
</p>

<p align="center">
  <b>A production-grade Watch Dogs (ctOS 2.0 / DedSec) cyber HUD for Ghostty + Zellij on Linux.</b><br/>
  Features live OpenCV V4L2 biometric FaceID, 7-pane tactical layout, Kitty Graphics Protocol photo rendering, synchronized static/blur glitch encryption transitions, real-time X feed, and multi-agent AI telemetry.
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#hud-layout">HUD Layout</a> •
  <a href="#installation">Installation</a> •
  <a href="#components">Components</a> •
  <a href="#shortcuts">Shortcuts</a> •
  <a href="#license">License</a>
</p>

---

## ⚡ Features

- **Biometric FaceID Camera Modal (`ctos-faceid-auth`)**:
  - Live hardware camera capture from `/dev/video0` via OpenCV V4L2.
  - Real-time face detection with CLAHE + Canny Edge + 2x4 Sub-Pixel Braille ASCII filtering.
  - Interactive retry button (`[R] / Enter`) on dark frames or authentication mismatch.
- **Synchronized Encryption & Decryption Shield (`ctos-panel-guard`)**:
  - Underlying terminal panels render an animated Watch Dogs scrambled/static encryption matrix while FaceID scans.
  - Synchronized TrueColor fade-in curtain decryption transition the moment FaceID completes.
- **Full X (Twitter) Feed with Native Images (`ctos-intel-feed` & `ctos-x-auth`)**:
  - 100% Free local Google Chrome session extraction (`auth_token` / `ct0`).
  - Reads tweets, author stats, and renders attached photos as **native high-resolution PNG bitmaps** using the **Kitty Graphics Protocol** (no blocky ASCII or half-blocks).
- **Persistent YouTube Music Stream & Visualizer (`ctos-dymus-persist`)**:
  - PTY & MPRIS-backed session wrapper around `dymus`.
  - Automatically restores your last played song, track position, volume, and visualizer mode upon reopening terminal sessions.
- **AI Agents Telemetry Panel (`ctos-ai-agents`)**:
  - Live system-level monitoring of active AI coding agents (Antigravity, Cursor AI, OpenCode, GitHub Copilot, LM Studio).
  - Pixel-art character avatars rendered natively via Kitty Graphics.
- **Interactive Workspace Launcher (`ctos-ghostty-welcome`)**:
  - Ghostty terminal startup screen displaying recent workspaces and project repositories with instant navigation and fuzzy searching.
- **CRT GLSL Scanline Shader (`ctos-hud.glsl`)**:
  - Custom GLSL post-processing shader with CRT scanlines, subtle vignette, and chromatic aberration.

---

## 🖥 HUD Layout

The primary workspace (`ctOS_HUD_MAIN`) is divided into a balanced 3-column tactical operations matrix:

```
┌─────────────────┬───────────────────────────────────┬───────────────────────────┐
│                 │                                   │                           │
│  ctOS //        │   DEDSEC_CORE //                  │   ctOS // AI_AGENTS       │
│  PROFILER_ID    │   FULLSTACK_CLI                   │   (Live Agent Telemetry)  │
│  (1:1 Avatar)   │   (Primary Dev Shell)             │                           │
│                 │                                   ├───────────────────────────┤
│                 │                                   │   JIRA_FEED //            │
├─────────────────┤                                   │   WEBIT_SPRINT            │
│                 ├───────────────────────────────────┼───────────────────────────┤
│  ctOS //        │                                   │                           │
│  X_FEED         │   AUDIO_STREAM // YT_MUSIC        │   BITBUCKET //            │
│  (Native Kitty  │   (dymus + Audio Visualizer)      │   WEBIT_PR_PIPELINE       │
│   Images)       │                                   │                           │
└─────────────────┴───────────────────────────────────┴───────────────────────────┘
```

---

## 🚀 Installation (Fedora 45 / Linux)

### 1. Clone the Repository

```bash
git clone https://github.com/princetonacelopez/watchdogs-terminal.git ~/watchdogs-terminal
cd ~/watchdogs-terminal
```

### 2. Run the Automated Installer

The installer automates installing packages, downloading binaries, fonts, configuring Ghostty and Zellij:

```bash
./install-fedora45.sh
```

#### Installer Flags:
- `--dry-run`: Preview all changes without touching the filesystem.
- `--skip-packages`: Deploy configurations, layouts, and scripts without reinstalling system packages.
- `--with-faceid-pam`: Also build and enable the system PAM FaceID module (`faceidctl`) for sudo/login.
- `--with-gnome-blur`: Install and configure GNOME "Blur my Shell" for glass effects.

---

## 🛠 Core Components & CLI Utilities

| Utility | Description |
| :--- | :--- |
| `zdev [dir]` | Launches the full 7-pane ctOS HUD in the specified directory |
| `zdev-window [dir]` | Opens `zdev` in a dedicated fullscreen ctOS Ghostty window |
| `ctos-faceid-auth` | Biometric FaceID camera modal with Braille ASCII live filter |
| `ctos-intel-feed` | High-fidelity X feed reader with Kitty Graphics protocol photos |
| `ctos-x-auth` | Extracts free local session cookies from Google Chrome |
| `ctos-ai-agents` | Monitors running AI coding assistants and renders avatar badges |
| `ctos-dymus-persist` | MPRIS/PTY wrapper ensuring YouTube Music session persistence |
| `ctos-ghostty-welcome` | Terminal workspace selector (Recent directories & Git projects) |
| `jira-project-board` | Dedicated sprint ticket board with active branch detection |
| `bitbucket-prs` | Reviewer and PR pipeline tracker |

---

## ⌨ Keybindings & Controls

### X Feed (`ctos-intel-feed`)
- `j / k` or `↑ / ↓`: Scroll tweets (strictly bounded to non-negative coordinates).
- `Space` or `f`: Toggle Focus/Zoom reader mode.
- `i`: Toggle Kitty Graphics Protocol inline images.
- `m`: Cycle through multiple images attached to a post.
- `t`: Toggle feed between algorithmic **FOR YOU** and chronological **FOLLOWING**.
- `Enter` / `o`: Open the post in Google Chrome.
- `a`: Re-authenticate session from local Google Chrome cookies.

### AI Agents (`ctos-ai-agents`)
- `j / k` or `↑ / ↓`: Select active AI agent.
- `Enter` / `o`: Launch the selected agent in the current workspace.
- `r`: Force instant process poll.

### FaceID Modal (`ctos-faceid-auth`)
- `r` or `Enter`: Retry authentication if lighting or angle failed.
- `q` or `Esc`: Bypass and dismiss modal.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — see the [LICENSE](LICENSE) file for details.
