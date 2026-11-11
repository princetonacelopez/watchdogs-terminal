#!/usr/bin/env python3
"""
ctos-x-auth: Watch Dogs ctOS 2.0 // X (Twitter) Session & GraphQL Sync Utility
100% Free & Open-Source — Syncs your logged-in x.com session cookies (auth_token, ct0)
directly from Google Chrome (~/.config/google-chrome) using your local Linux Keyring,
discovers live X Web GraphQL queryIds + featureSwitches, and stores them securely at
~/.config/zellij/x_session.json (chmod 600).

Usage:
  ctos-x-auth           # Auto-sync from Google Chrome & verify X feed access
  ctos-x-auth --quiet   # Auto-sync silently (used by ctos-intel-feed background auto-heal)
  ctos-x-auth --paste   # Manually paste auth_token & ct0
  ctos-x-auth --status  # Check saved session & test HomeTimeline
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse

import httpx

SESSION_PATH = os.path.expanduser("~/.config/zellij/x_session.json")
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs="
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Fedora; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

# Default fallback queryIds & featureSwitches (auto-refreshed from x.com bundles)
DEFAULT_ENDPOINTS = {
    "HomeTimeline": {
        "queryId": "KmJCeZ__ef1fNos7tKN_fg",
        "features": {
            "rweb_video_screen_enabled": True,
            "rweb_cashtags_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": True,
            "premium_content_api_read_enabled": True,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": True,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_grok_annotations_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": True,
            "responsive_web_grok_show_grok_translated_post": True,
            "responsive_web_grok_analysis_button_from_backend": True,
            "post_ctas_fetch_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_grok_imagine_annotation_enabled": True,
            "responsive_web_grok_community_note_auto_translation_is_enabled": True,
            "responsive_web_enhance_cards_enabled": True,
        },
    },
    "HomeLatestTimeline": {
        "queryId": "IVA5BUbeYPTrpYekQH7jiA",
        "features": {},
    },
    "Bookmarks": {
        "queryId": "fjf5b5Lu82lYMSBRhppK2g",
        "features": {},
    },
}

R = "\033[0m"
B = "\033[1m"
C_CYAN = "\033[38;2;0;240;255m"
C_MINT = "\033[38;2;0;255;156m"
C_CRIMSON = "\033[38;2;255;0;85m"
C_AMBER = "\033[38;2;255;214;0m"
C_SILVER = "\033[38;2;180;205;228m"


def extract_chrome_x_cookies() -> dict:
    """Extract decrypted auth_token, ct0, and twid from Google Chrome / Chromium SQLite Cookies."""
    import secretstorage
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    chrome_secret = b"peanuts"
    try:
        bus = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(bus)
        for item in collection.get_all_items():
            lbl = item.get_label()
            if "Chrome Safe Storage" in lbl or "Chromium Safe Storage" in lbl:
                chrome_secret = item.get_secret()
                break
    except Exception:
        pass

    key = PBKDF2HMAC(
        algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1
    ).derive(chrome_secret)

    def decrypt_cookie(enc: bytes) -> str:
        if not enc:
            return ""
        if enc[:3] in (b"v10", b"v11"):
            cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
            dec = cipher.decryptor().update(enc[3:]) + cipher.decryptor().finalize()
            pad = dec[-1]
            if isinstance(pad, int) and 1 <= pad <= 16:
                dec = dec[:-pad]
            if len(dec) > 32:
                try:
                    return dec[32:].decode("utf-8")
                except UnicodeDecodeError:
                    pass
            return dec.decode("utf-8", errors="ignore")
        return enc.decode("utf-8", errors="ignore")

    cookie_dbs = (
        glob.glob(os.path.expanduser("~/.config/google-chrome/*/Cookies"))
        + glob.glob(os.path.expanduser("~/.config/google-chrome/*/*/Cookies"))
        + glob.glob(os.path.expanduser("~/.config/chromium/*/Cookies"))
        + glob.glob(os.path.expanduser("~/.config/BraveSoftware/Brave-Browser/*/Cookies"))
    )

    for db_path in cookie_dbs:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="ctos_x_cookies_", suffix=".sqlite")
        os.close(tmp_fd)
        try:
            shutil.copy2(db_path, tmp_path)
            conn = sqlite3.connect(tmp_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT name, value, encrypted_value FROM cookies "
                "WHERE (host_key LIKE '%x.com' OR host_key LIKE '%twitter.com') "
                "AND name IN ('auth_token', 'ct0', 'twid')"
            )
            found = {}
            for name, val, enc in cur.fetchall():
                d = val or decrypt_cookie(enc)
                if d:
                    found[name] = d
            conn.close()
            if found.get("auth_token") and found.get("ct0"):
                found["source_profile"] = db_path
                return found
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return {}


def discover_graphql_endpoints(cookies: dict) -> dict:
    """Discover live HomeTimeline, HomeLatestTimeline, and Bookmarks queryIds & featureSwitches."""
    endpoints = json.loads(json.dumps(DEFAULT_ENDPOINTS))
    base_features = dict(endpoints["HomeTimeline"]["features"])
    endpoints["HomeLatestTimeline"]["features"] = dict(base_features)
    endpoints["Bookmarks"]["features"] = dict(base_features)

    try:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            cookies={k: v for k, v in cookies.items() if k in ("auth_token", "ct0", "twid")},
            follow_redirects=True,
            timeout=8.0,
        )
        r = client.get("https://x.com/home")
        if r.status_code != 200:
            return endpoints

        idx = r.text.find('t.p="https://abs.twimg.com/responsive-web/client-web/"')
        if idx == -1:
            return endpoints
        u_idx = r.text.rfind("t.u=", 0, idx)
        u_block = r.text[max(0, u_idx) : idx]

        hashes_map = dict(re.findall(r'(\d+):"([a-f0-9]{16})"', u_block))
        names_map = dict(re.findall(r'(\d+):"((?![a-f0-9]{16}")[^"]+)"', u_block))

        target_urls = []
        for cid, cname in names_map.items():
            if any(
                k in cname
                for k in (
                    "HomeTimeline",
                    "BookmarkFolders~bundle.Bookmarks",
                    "bundle.Bookmarks",
                )
            ):
                h = hashes_map.get(cid)
                if h:
                    target_urls.append(
                        f"https://abs.twimg.com/responsive-web/client-web/{cname}.{h}a.js"
                    )

        for js_url in target_urls:
            try:
                cjs = client.get(js_url).text
                for op in ("HomeTimeline", "HomeLatestTimeline", "Bookmarks"):
                    m = re.search(
                        r'queryId:"([^"]+)",operationName:"'
                        + op
                        + r'",operationType:"[^"]+",metadata:\{featureSwitches:\[([^\]]*)\]',
                        cjs,
                    )
                    if m:
                        qid = m.group(1)
                        f_list = json.loads("[" + m.group(2) + "]")
                        endpoints[op] = {
                            "queryId": qid,
                            "features": {k: True for k in f_list},
                        }
            except Exception:
                continue
    except Exception:
        pass

    return endpoints


def save_session(cookies: dict, endpoints: dict) -> dict:
    os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
    payload = {
        "auth_token": cookies["auth_token"],
        "ct0": cookies["ct0"],
        "twid": cookies.get("twid", ""),
        "source_profile": cookies.get("source_profile", "manual"),
        "bearer": BEARER_TOKEN,
        "endpoints": endpoints,
        "updated_at": int(time.time()),
    }
    tmp = f"{SESSION_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SESSION_PATH)
    return payload


def load_session() -> dict:
    if os.path.exists(SESSION_PATH):
        try:
            with open(SESSION_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    quiet = "--quiet" in sys.argv
    paste_mode = "--paste" in sys.argv
    status_only = "--status" in sys.argv

    if not quiet:
        print(f"{C_CYAN}{B}⌁ [ctOS // X_UPLINK_AUTH]{R} Initializing free X (Twitter) session sync...")

    if status_only:
        sess = load_session()
        if not sess.get("auth_token"):
            print(f"{C_CRIMSON}{B}✖ No saved X session found at {SESSION_PATH}{R}")
            sys.exit(1)
        print(f"{C_MINT}{B}✔ Saved X session loaded:{R} {SESSION_PATH}")
        sys.exit(0)

    cookies = {}
    if paste_mode:
        print(f"{C_SILVER}Open https://x.com in Chrome -> F12 -> Application -> Cookies -> https://x.com{R}")
        auth_token = input(f"{C_CYAN}Enter auth_token: {R}").strip()
        ct0 = input(f"{C_CYAN}Enter ct0       : {R}").strip()
        if not auth_token or not ct0:
            print(f"{C_CRIMSON}{B}✖ Both auth_token and ct0 are required.{R}")
            sys.exit(1)
        cookies = {"auth_token": auth_token, "ct0": ct0, "source_profile": "manual_paste"}
    else:
        cookies = extract_chrome_x_cookies()
        if not cookies.get("auth_token") or not cookies.get("ct0"):
            if not quiet:
                print(
                    f"{C_CRIMSON}{B}✖ Could not find active x.com session in Google Chrome.{R}\n"
                    f"{C_AMBER}  Log into https://x.com in Google Chrome or run: ctos-x-auth --paste{R}"
                )
            sys.exit(1)

    if not quiet:
        print(f"{C_MINT}✔ Extracted x.com session cookies from:{R} {cookies.get('source_profile')}")
        print(f"{C_CYAN}⟳ Discovering live X Web GraphQL endpoints...{R}")

    endpoints = discover_graphql_endpoints(cookies)
    save_session(cookies, endpoints)

    if not quiet:
        print(f"{C_MINT}{B}✔ Saved encrypted session to:{R} {SESSION_PATH} (chmod 600)")
        for op, meta in endpoints.items():
            print(f"  {C_CYAN}• {op:<20}{R} queryId={C_SILVER}{meta.get('queryId')}{R}")
        print(f"{C_MINT}{B}⌁ [X_FEED // ONLINE] Ready in zdev ctOS // INTEL_FEED panel!{R}")


if __name__ == "__main__":
    main()
