#!/usr/bin/env python3
"""
ctOS 2.0 // DYMUS SESSION & VISUALIZER PERSISTENCE WRAPPER
Wraps `dymus` in a transparent pseudo-terminal (PTY) to:
1. Continuously persist the active YouTube Music track (title, artist, album, URL,
   track_id, playback position, volume) and active Now Playing sub-pane + visualizer
   style (spectrum, waveform, orbit, pulse, spectrogram, vectorscope, constellation,
   bars, braille bars) into ~/.config/dymus/last_session.json.
2. Automatically resume the last played track and restore the Now Playing view +
   exact last chosen visualizer style when starting or returning to `zdev`.
"""
import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty

SESSION_FILE = os.path.expanduser("~/.config/dymus/last_session.json")
FACEID_STATE_FILE = "/tmp/ctos_faceid_state.json"
DYMUS_BIN = os.path.expanduser("~/.local/bin/dymus")

# Ordered longest-first so "braille bars" matches before "bars" and "spectrogram" before "spectrum"
VIZ_STYLES = [
    "braille bars",
    "constellation",
    "spectrogram",
    "vectorscope",
    "waveform",
    "spectrum",
    "orbit",
    "pulse",
    "bars",
]

# Exact cycle order in dymus (0..8) when pressing 'm' or ']'
VIZ_CYCLE_ORDER = [
    "spectrum",
    "waveform",
    "orbit",
    "pulse",
    "spectrogram",
    "vectorscope",
    "constellation",
    "bars",
    "braille bars",
]

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")


def load_session() -> dict:
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_session(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        tmp = f"{SESSION_FILE}.tmp.{os.getpid()}"
        state["updated_at"] = int(time.time())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, SESSION_FILE)
    except Exception:
        pass


def get_faceid_state() -> str:
    try:
        with open(FACEID_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("state", "UNLOCKED")
    except Exception:
        return "UNLOCKED"


def get_dbus_dest(child_pid: int) -> str:
    try:
        res = subprocess.run(
            ["busctl", "--user", "list", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0:
            pid_str = str(child_pid)
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == pid_str and parts[0].startswith(":"):
                    return parts[0]
    except Exception:
        pass
    return "org.mpris.MediaPlayer2.dymus"


def busctl_get(dest: str, prop: str) -> str:
    try:
        res = subprocess.run(
            [
                "busctl",
                "--user",
                "get-property",
                dest,
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player",
                prop,
            ],
            capture_output=True,
            text=True,
            timeout=1.2,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def parse_mpris_metadata(raw: str) -> dict:
    info = {}
    if not raw or raw.startswith("a{sv} 0"):
        return info
    m_title = re.search(r'"xesam:title"\s+s\s+"((?:\\.|[^"\\])*)"', raw)
    if m_title:
        info["title"] = m_title.group(1).replace('\\"', '"').replace("\\\\", "\\")
    m_artist = re.search(r'"xesam:artist"\s+as\s+\d+\s+"((?:\\.|[^"\\])*)"', raw)
    if m_artist:
        info["artist"] = m_artist.group(1).replace('\\"', '"').replace("\\\\", "\\")
    m_album = re.search(r'"xesam:album"\s+s\s+"((?:\\.|[^"\\])*)"', raw)
    if m_album:
        info["album"] = m_album.group(1).replace('\\"', '"').replace("\\\\", "\\")
    m_url = re.search(r'"xesam:url"\s+s\s+"((?:\\.|[^"\\])*)"', raw)
    if m_url:
        info["url"] = m_url.group(1)
    m_tid = re.search(r'"mpris:trackid"\s+o\s+"((?:\\.|[^"\\])*)"', raw)
    if m_tid:
        info["track_id"] = m_tid.group(1)
    m_len = re.search(r'"mpris:length"\s+x\s+(-?\d+)', raw)
    if m_len:
        info["length_us"] = int(m_len.group(1))
    return info


def get_player_state(child_pid: int) -> dict:
    dest = get_dbus_dest(child_pid)
    meta = parse_mpris_metadata(busctl_get(dest, "Metadata"))
    status_raw = busctl_get(dest, "PlaybackStatus")
    m_stat = re.search(r'"([^"]+)"', status_raw)
    if m_stat:
        meta["playback_status"] = m_stat.group(1)
    pos_raw = busctl_get(dest, "Position")
    if pos_raw.startswith("x "):
        try:
            meta["position_us"] = int(pos_raw.split()[1])
        except Exception:
            pass
    vol_raw = busctl_get(dest, "Volume")
    if vol_raw.startswith("d "):
        try:
            meta["volume"] = round(float(vol_raw.split()[1]), 2)
        except Exception:
            pass
    return meta


def set_mpris_volume(child_pid: int, vol: float) -> None:
    dest = get_dbus_dest(child_pid)
    try:
        subprocess.run(
            [
                "busctl",
                "--user",
                "set-property",
                dest,
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player",
                "Volume",
                "d",
                str(max(0.0, min(1.0, float(vol)))),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.2,
        )
    except Exception:
        pass


def mpris_play(child_pid: int) -> None:
    dest = get_dbus_dest(child_pid)
    try:
        subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                dest,
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player",
                "Play",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.2,
        )
    except Exception:
        pass


def mpris_set_position(child_pid: int, track_id: str, pos_us: int) -> None:
    if not track_id or pos_us <= 0:
        return
    dest = get_dbus_dest(child_pid)
    try:
        subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                dest,
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player",
                "SetPosition",
                "ox",
                track_id,
                str(int(pos_us)),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.2,
        )
    except Exception:
        pass


def copy_winsize(src_fd: int, dst_fd: int, child_pid: int = 0) -> None:
    try:
        ws = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, ws)
        if child_pid > 0:
            os.kill(child_pid, signal.SIGWINCH)
    except Exception:
        pass


def main() -> None:
    session_state = load_session()
    if not session_state.get("visualizer_style"):
        session_state["visualizer_style"] = "braille bars"
    if not session_state.get("sub_pane"):
        session_state["sub_pane"] = "visualizer"
    if "now_playing_open" not in session_state:
        session_state["now_playing_open"] = True

    master_fd, slave_fd = pty.openpty()
    if sys.stdin.isatty():
        copy_winsize(sys.stdin.fileno(), master_fd)

    child_pid = os.fork()
    if child_pid == 0:
        os.setsid()
        os.close(master_fd)
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(DYMUS_BIN, [DYMUS_BIN] + sys.argv[1:])

    os.close(slave_fd)

    def on_sigwinch(signum, frame):
        if sys.stdin.isatty():
            copy_winsize(sys.stdin.fileno(), master_fd, child_pid)

    signal.signal(signal.SIGWINCH, on_sigwinch)

    shared = {
        "running": True,
        "first_output_ts": 0.0,
        "screen_tail": "",
        "detected_viz": None,
        "restoring": False,
        "restored_once": False,
        "lock": threading.Lock(),
    }

    def on_term_signal(signum, frame):
        shared["running"] = False
        try:
            save_session(session_state)
        except Exception:
            pass
        try:
            os.kill(child_pid, signum)
        except Exception:
            pass

    signal.signal(signal.SIGTERM, on_term_signal)
    signal.signal(signal.SIGHUP, on_term_signal)

    def pty_send(data: bytes) -> None:
        try:
            os.write(master_fd, data)
        except OSError:
            pass

    def restore_session_flow() -> None:
        with shared["lock"]:
            if shared["restoring"]:
                return
            shared["restoring"] = True

        try:
            saved = load_session()
            title = (saved.get("title") or "").strip()
            artist = (saved.get("artist") or "").strip()
            target_viz = saved.get("visualizer_style") or "braille bars"
            target_pane = saved.get("sub_pane") or "visualizer"
            want_now_playing = saved.get("now_playing_open", True)
            target_vol = saved.get("volume")

            if not title:
                return

            # Wait for dymus initial UI render
            for _ in range(40):
                if not shared["running"] or shared["first_output_ts"] > 0:
                    break
                time.sleep(0.1)
            time.sleep(0.75)

            # Check if dymus is already playing a track
            pstate = get_player_state(child_pid)
            if not pstate.get("title"):
                query = f"{title} {artist}".strip()
                # Open search bar ('/') and submit query
                pty_send(b"/")
                time.sleep(0.18)
                pty_send(query.encode("utf-8") + b"\r")

                # Wait for search results ("Enter play" in footer or timeout)
                t0 = time.time()
                while time.time() - t0 < 5.0 and shared["running"]:
                    time.sleep(0.2)
                    with shared["lock"]:
                        tail = shared["screen_tail"]
                    if "Enter play" in tail and "searching" not in tail.lower():
                        break
                time.sleep(0.35)

                # Press Enter to play top result
                pty_send(b"\r")

                # Wait for MPRIS Metadata / PlaybackStatus to confirm track loaded
                t1 = time.time()
                while time.time() - t1 < 9.0 and shared["running"]:
                    time.sleep(0.35)
                    pstate = get_player_state(child_pid)
                    if pstate.get("title") or pstate.get("playback_status") in ("Playing", "Paused"):
                        break

            if target_vol is not None:
                set_mpris_volume(child_pid, target_vol)

            saved_pos = int(saved.get("position_us") or 0)
            track_id = pstate.get("track_id") or saved.get("track_id") or ""
            length_us = int(pstate.get("length_us") or 0)
            if saved_pos > 5_000_000 and (length_us <= 0 or saved_pos < length_us - 10_000_000):
                mpris_set_position(child_pid, track_id, saved_pos)

            if want_now_playing:
                time.sleep(0.35)
                pty_send(b"t")
                time.sleep(0.30)
                if target_pane == "visualizer":
                    pty_send(b"v")
                    time.sleep(0.30)
                    # Cycle visualizer with 'm' until the detected style matches target_viz
                    for _ in range(len(VIZ_CYCLE_ORDER)):
                        with shared["lock"]:
                            cur_viz = shared["detected_viz"]
                        if cur_viz == target_viz:
                            break
                        pty_send(b"m")
                        time.sleep(0.20)
                elif target_pane == "lyrics":
                    pty_send(b"y")
                    time.sleep(0.20)

            mpris_play(child_pid)
        finally:
            with shared["lock"]:
                shared["restoring"] = False
                shared["restored_once"] = True

    def background_worker() -> None:
        last_faceid = get_faceid_state()
        # Trigger initial startup restore
        restore_session_flow()

        while shared["running"]:
            time.sleep(1.5)
            if not shared["running"]:
                break

            cur_faceid = get_faceid_state()
            # If user re-attached via zdev and just unlocked FaceID, ensure music continues
            if last_faceid != "UNLOCKED" and cur_faceid == "UNLOCKED":
                pstate = get_player_state(child_pid)
                if not pstate.get("title"):
                    threading.Thread(target=restore_session_flow, daemon=True).start()
                elif pstate.get("playback_status") == "Paused":
                    mpris_play(child_pid)
            last_faceid = cur_faceid

            with shared["lock"]:
                is_restoring = shared["restoring"]
            if is_restoring:
                continue

            pstate = get_player_state(child_pid)
            if pstate.get("title"):
                changed = False
                for k in ("title", "artist", "album", "url", "track_id", "playback_status", "position_us", "volume"):
                    if k in pstate and pstate[k] != session_state.get(k):
                        session_state[k] = pstate[k]
                        changed = True
                if changed:
                    save_session(session_state)

    worker = threading.Thread(target=background_worker, daemon=True)
    worker.start()

    old_tty = None
    if sys.stdin.isatty():
        try:
            old_tty = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())
        except Exception:
            old_tty = None

    try:
        stdin_fd = sys.stdin.fileno() if sys.stdin.isatty() else -1
        stdout_fd = sys.stdout.fileno()

        while True:
            rlist = [master_fd]
            if stdin_fd >= 0:
                rlist.append(stdin_fd)
            try:
                rfds, _, _ = select.select(rlist, [], [], 0.5)
            except select.error as e:
                if e.args and e.args[0] == errno.EINTR:
                    continue
                break

            if master_fd in rfds:
                try:
                    data = os.read(master_fd, 16384)
                except OSError:
                    break
                if not data:
                    break
                os.write(stdout_fd, data)

                clean = ANSI_RE.sub("", data.decode("utf-8", errors="ignore"))
                with shared["lock"]:
                    if shared["first_output_ts"] == 0.0:
                        shared["first_output_ts"] = time.time()
                    shared["screen_tail"] = (shared["screen_tail"] + clean)[-4096:]

                    # Detect active visualizer style rendered in Now Playing header
                    # Header format: "<style> · signal live · m / [ ]" or "<style> · ..."
                    for style in VIZ_STYLES:
                        if f"{style} ·" in clean or f"{style} \xb7" in clean:
                            shared["detected_viz"] = style
                            if not shared["restoring"]:
                                if (
                                    session_state.get("visualizer_style") != style
                                    or session_state.get("sub_pane") != "visualizer"
                                    or not session_state.get("now_playing_open")
                                ):
                                    session_state["visualizer_style"] = style
                                    session_state["sub_pane"] = "visualizer"
                                    session_state["now_playing_open"] = True
                                    save_session(session_state)
                            break

            if stdin_fd >= 0 and stdin_fd in rfds:
                try:
                    user_in = os.read(stdin_fd, 1024)
                except OSError:
                    break
                if not user_in:
                    break
                os.write(master_fd, user_in)
    finally:
        shared["running"] = False
        if old_tty is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
            except Exception:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.waitpid(child_pid, 0)
        except Exception:
            pass


if __name__ == "__main__":
    main()
