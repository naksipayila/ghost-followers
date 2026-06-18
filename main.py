import pickle
import random
import re
import sys
import time
from colorama import init, Fore, Style
from getpass import getpass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

import instaloader

init(autoreset=True)

# --- Color shortcuts ---
C = Fore.CYAN + Style.BRIGHT    # info [*]
G = Fore.GREEN + Style.BRIGHT   # success [+]
R = Fore.RED + Style.BRIGHT     # error [-]
Y = Fore.YELLOW + Style.BRIGHT  # warning [!]
M = Fore.MAGENTA + Style.BRIGHT # title / separator
B = Style.BRIGHT                # bold
RESET = Style.RESET_ALL

# --- Constants ---
POST_LIMIT = 30
MAX_RETRIES = 3
FOLLOWER_BATCH_SIZE = 12
FOLLOWER_COOLDOWN_BATCH_SIZE = 120
FOLLOWERS_FILE = "followers.txt"
PARTIAL_FOLLOWERS_FILE = "followers.partial.txt"
FOLLOWER_STATE_FILE = "followers.state.pkl"
RESULT_FILE = "ghost_followers.txt"
REPORT_FILE = "scan_report.txt"

SETTINGS_FILE = "settings.txt"
REQUIRED_COOKIES = ("sessionid", "csrftoken", "ds_user_id")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")
INSTAGRAM_STOP_MESSAGES = (
    "feedback_required",
    "checkpoint_required",
    "challenge_required",
    "please wait a few minutes",
    "too many requests",
    "rate limit",
    "429",
    "401 unauthorized",
)

# Normal mode delays (seconds)
FOLLOWER_PAGE_DELAY = (10.0, 20.0)
FOLLOWER_COOLDOWN_DELAY = (60.0, 120.0)
FOLLOWER_RETRY_DELAY = (5.0, 10.0)
POST_DELAY = (2.0, 5.0)
# Slow mode delays (seconds)
SLOW_FOLLOWER_PAGE_DELAY = (75.0, 150.0)
SLOW_FOLLOWER_COOLDOWN_DELAY = (300.0, 600.0)
SLOW_FOLLOWER_RETRY_DELAY = (20.0, 40.0)
SLOW_POST_DELAY = (30.0, 90.0)
SLOW_PRE_FETCH_DELAY = (10.0, 20.0)


def normalize_username(username):
    return username.strip().lstrip("@").lower()


def is_valid_username(username):
    return bool(USERNAME_PATTERN.fullmatch(username))


def is_instagram_stop_error(exc):
    message = str(exc).lower()
    return any(stop_message in message for stop_message in INSTAGRAM_STOP_MESSAGES)


def prompt_secret(prompt):
    try:
        return getpass(prompt)
    except Exception:
        return input(prompt)


def extract_cookie_text(raw_cookie):
    raw_cookie = raw_cookie.strip().strip('"').strip("'")
    if not raw_cookie:
        return ""

    lines = [line.strip() for line in raw_cookie.replace("\r", "\n").split("\n") if line.strip()]
    for line in lines:
        if line.lower().startswith("cookie:"):
            return line.split(":", 1)[1].strip()

    if raw_cookie.lower().startswith("cookie:"):
        return raw_cookie.split(":", 1)[1].strip()

    return raw_cookie


def parse_cookie_input(raw_cookie):
    cookie_text = extract_cookie_text(raw_cookie)

    if not cookie_text:
        return {}

    if "=" not in cookie_text:
        return {"sessionid": cookie_text}

    cookie = SimpleCookie()
    try:
        cookie.load(cookie_text)
    except CookieError:
        cookie = SimpleCookie()

    parsed = {key: morsel.value for key, morsel in cookie.items() if morsel.value}

    if parsed:
        return parsed

    for part in cookie_text.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value

    return parsed


def missing_required_cookies(cookies):
    return [name for name in REQUIRED_COOKIES if not cookies.get(name)]


def create_loader(username, cookies):
    loader = instaloader.Instaloader(
        sleep=True,
        quiet=False,
        max_connection_attempts=3,
    )
    loader.context.load_session(username, cookies)
    loader.context.user_id = int(cookies["ds_user_id"])
    return loader


def get_logged_in_user(loader, expected_username, expected_user_id):
    data = loader.context.graphql_query("d6f4427fbe92d846298cf93df0b937d3", {})
    user = data.get("data", {}).get("user")

    if not isinstance(user, dict):
        raise RuntimeError("Cookie did not return a valid Instagram session.")

    actual_username = user.get("username")
    if not actual_username:
        raise RuntimeError("Session verified but username could not be read.")

    if normalize_username(actual_username) != normalize_username(expected_username):
        raise RuntimeError(
            "Cookie appears to belong to a different account: "
            f"@{actual_username}. Expected: @{expected_username}."
        )

    user_id = str(user.get("id") or user.get("pk") or expected_user_id)
    if user_id != str(expected_user_id):
        raise RuntimeError(
            "Cookie ds_user_id does not match the session user id. "
            "Copy a fresh full Cookie header from your browser."
        )

    user_node = dict(user)
    user_node["id"] = user_id
    user_node["username"] = actual_username
    loader.context.username = actual_username
    loader.context.user_id = int(user_id)

    return user_node


def build_followers_iterator(context, user_id, username):
    return instaloader.NodeIterator(
        context=context,
        query_hash="37479f2b8209594dde7facb0d904896a",
        edge_extractor=lambda data: data["data"]["user"]["edge_followed_by"],
        node_wrapper=lambda node: instaloader.Profile(context, node),
        query_variables={"id": str(user_id)},
        query_referer=f"https://www.instagram.com/{username}/",
    )


def build_posts_iterator(context, username):
    return instaloader.NodeIterator(
        context=context,
        query_hash=None,
        edge_extractor=lambda data: data["data"]["xdt_api__v1__feed__user_timeline_graphql_connection"],
        node_wrapper=lambda node: instaloader.Post.from_iphone_struct(context, node),
        query_variables={
            "data": {
                "count": 12,
                "include_relationship_info": True,
                "latest_besties_reel_media": True,
                "latest_reel_media": True,
            },
            "username": username,
        },
        query_referer=f"https://www.instagram.com/{username}/",
        is_first=lambda post, first: first is None or post.date_local > first.date_local,
        doc_id="7898261790222653",
    )


def build_likes_iterator(context, shortcode):
    return instaloader.NodeIterator(
        context=context,
        query_hash="1cb6ec562846122743b61e492c85999f",
        edge_extractor=lambda data: data["data"]["shortcode_media"]["edge_liked_by"],
        node_wrapper=lambda node: node,
        query_variables={"shortcode": shortcode},
        query_referer=f"https://www.instagram.com/p/{shortcode}/",
    )


def build_parent_comments_iterator(context, shortcode):
    return instaloader.NodeIterator(
        context=context,
        query_hash="97b41c52301f77ce508f55e66d17620e",
        edge_extractor=lambda data: data["data"]["shortcode_media"]["edge_media_to_parent_comment"],
        node_wrapper=lambda node: node,
        query_variables={"shortcode": shortcode},
        query_referer=f"https://www.instagram.com/p/{shortcode}/",
    )


def build_child_comments_iterator(context, shortcode, comment_id):
    return instaloader.NodeIterator(
        context=context,
        query_hash="51fdd02b67508306ad4484ff574a0b62",
        edge_extractor=lambda data: data["data"]["comment"]["edge_threaded_comments"],
        node_wrapper=lambda node: node,
        query_variables={"comment_id": comment_id},
        query_referer=f"https://www.instagram.com/p/{shortcode}/",
    )


def username_from_node(node):
    if not isinstance(node, dict):
        return None

    username = node.get("username")
    if username:
        return username

    owner = node.get("owner") or node.get("user")
    if isinstance(owner, dict):
        return owner.get("username")

    return None


def count_from_nested(node, *keys):
    current = node
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]

    return current if isinstance(current, int) else None


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_post_like_count(post):
    node = getattr(post, "_node", {})
    return count_from_nested(node, "edge_media_preview_like", "count")


def get_post_comment_count(post):
    node = getattr(post, "_node", {})

    if isinstance(node.get("comments"), int):
        return node["comments"]

    for key in ("edge_media_to_parent_comment", "edge_media_to_comment"):
        count = count_from_nested(node, key, "count")
        if count is not None:
            return count

    return None


def get_user_follower_count(user_node):
    if user_node.get("follower_count") is not None:
        return safe_int(user_node.get("follower_count"), None)

    return count_from_nested(user_node, "edge_followed_by", "count")


def add_usernames(target, usernames):
    for username in usernames:
        normalized = normalize_username(username)
        if normalized:
            target[normalized] = username


def expected_count_text(count):
    return "unknown" if count is None else str(count)


def fetch_with_retries(label, fetcher):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetcher(), None
        except Exception as exc:
            last_error = exc
            if is_instagram_stop_error(exc):
                print(f"     {Y}[!]{RESET} {label} temporarily restricted by Instagram: {exc}")
                return ([], 0), last_error

            print(f"     {Y}[!]{RESET} {label} failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(random.uniform(4.0, 8.0))

    return ([], 0), last_error


def collect_followers(context, user_id, username, slow_mode=False, expected_count=None):
    last_error = None
    page_delay = SLOW_FOLLOWER_PAGE_DELAY if slow_mode else FOLLOWER_PAGE_DELAY
    cooldown_delay = SLOW_FOLLOWER_COOLDOWN_DELAY if slow_mode else FOLLOWER_COOLDOWN_DELAY
    retry_delay = SLOW_FOLLOWER_RETRY_DELAY if slow_mode else FOLLOWER_RETRY_DELAY
    seed_followers, seed_error = load_followers_from_file(PARTIAL_FOLLOWERS_FILE)
    if seed_error:
        print(f"{Y}[!]{RESET} Could not read {PARTIAL_FOLLOWERS_FILE}: {seed_error}")

    follower_state = None
    if seed_followers:
        follower_state, state_error = load_follower_state(FOLLOWER_STATE_FILE)
        print(f"{C}[*]{RESET} Loaded {len(seed_followers)} partial followers from {PARTIAL_FOLLOWERS_FILE}.")
        if state_error:
            print(f"{Y}[!]{RESET} Could not read {FOLLOWER_STATE_FILE}: {state_error}")

    for attempt in range(1, MAX_RETRIES + 1):
        followers = dict(seed_followers)
        follower_iterator = build_followers_iterator(context, user_id, username)

        if follower_state is not None:
            try:
                follower_iterator.thaw(follower_state)
                print(f"{C}[*]{RESET} Resuming follower collection from saved cursor.")
            except Exception as exc:
                print(f"{Y}[!]{RESET} Could not resume saved follower cursor: {exc}")
                follower_state = None

        try:
            for fetched_count, follower in enumerate(follower_iterator, 1):
                followers[normalize_username(follower.username)] = follower.username
                follower_count = len(followers)

                if fetched_count % FOLLOWER_BATCH_SIZE == 0 and (
                    expected_count is None or follower_count < expected_count
                ):
                    save_error = write_followers_to_file(PARTIAL_FOLLOWERS_FILE, followers)
                    if save_error:
                        print(f"{Y}[!]{RESET} Could not save {PARTIAL_FOLLOWERS_FILE}: {save_error}")

                    state_error = write_follower_state(FOLLOWER_STATE_FILE, follower_iterator)
                    if state_error:
                        print(f"{Y}[!]{RESET} Could not save {FOLLOWER_STATE_FILE}: {state_error}")

                    if fetched_count % FOLLOWER_COOLDOWN_BATCH_SIZE == 0:
                        delay_range = cooldown_delay
                        wait_text = "cooling down"
                    else:
                        delay_range = page_delay
                        wait_text = "waiting"

                    print(f"{C}[*]{RESET} Collected {follower_count} followers; {wait_text} before continuing...")
                    time.sleep(random.uniform(*delay_range))

            if expected_count is not None and len(followers) < expected_count:
                save_error = write_followers_to_file(PARTIAL_FOLLOWERS_FILE, followers)
                if save_error:
                    print(f"{Y}[!]{RESET} Could not save {PARTIAL_FOLLOWERS_FILE}: {save_error}")
            else:
                remove_error = remove_file(FOLLOWER_STATE_FILE)
                if remove_error:
                    print(f"{Y}[!]{RESET} Could not remove {FOLLOWER_STATE_FILE}: {remove_error}")
                remove_error = remove_file(PARTIAL_FOLLOWERS_FILE)
                if remove_error:
                    print(f"{Y}[!]{RESET} Could not remove {PARTIAL_FOLLOWERS_FILE}: {remove_error}")
            return followers, None
        except Exception as exc:
            last_error = exc
            if followers:
                save_error = write_followers_to_file(PARTIAL_FOLLOWERS_FILE, followers)
                if save_error:
                    print(f"{Y}[!]{RESET} Could not save {PARTIAL_FOLLOWERS_FILE}: {save_error}")
                state_error = write_follower_state(FOLLOWER_STATE_FILE, follower_iterator)
                if state_error:
                    print(f"{Y}[!]{RESET} Could not save {FOLLOWER_STATE_FILE}: {state_error}")

            if is_instagram_stop_error(exc):
                print(f"{Y}[!]{RESET} Followers temporarily restricted by Instagram: {exc}")
                return followers, last_error

            print(f"{Y}[!]{RESET} Followers list failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                seed_followers = followers
                follower_state, _ = load_follower_state(FOLLOWER_STATE_FILE)
                time.sleep(random.uniform(*retry_delay))

    return followers, last_error


def collect_recent_posts(context, username, limit):
    posts = []

    if limit <= 0:
        return posts, None

    try:
        post_iterator = iter(build_posts_iterator(context, username))
    except Exception as exc:
        return posts, exc

    while len(posts) < limit:
        try:
            posts.append(next(post_iterator))
        except StopIteration:
            return posts, None
        except Exception as exc:
            return posts, exc

    return posts, None


def fetch_like_usernames(context, post, expected_count):
    if expected_count == 0:
        return [], 0

    try:
        usernames = []
        for node in build_likes_iterator(context, post.shortcode):
            username = username_from_node(node)
            if username:
                usernames.append(username)
        return usernames, len(usernames)
    except Exception as exc:
        if is_instagram_stop_error(exc):
            return fetch_like_usernames_iphone(context, post.mediaid)
        raise


def fetch_like_usernames_iphone(context, mediaid):
    usernames = []
    max_id = None

    while True:
        params = {}
        if max_id:
            params["max_id"] = max_id

        data = context.get_iphone_json(f"api/v1/media/{mediaid}/likers/", params)

        for user in data.get("users", []):
            username = user.get("username")
            if username:
                usernames.append(username)

        if not data.get("has_more"):
            break
        max_id = data.get("next_max_id")
        if not max_id:
            break

    return usernames, len(usernames)


def fetch_comment_usernames(context, post, expected_count):
    if expected_count == 0:
        return [], 0

    try:
        return fetch_comment_usernames_graphql(context, post)
    except Exception as exc:
        if is_instagram_stop_error(exc):
            return fetch_comment_usernames_iphone(context, post.mediaid)
        raise


def fetch_comment_usernames_graphql(context, post):

    usernames = []
    seen_comment_ids = set()
    comment_count = 0

    def add_comment_node(comment_node):
        nonlocal comment_count

        comment_id = str(comment_node.get("id") or comment_node.get("pk") or "")
        if comment_id and comment_id in seen_comment_ids:
            return
        if comment_id:
            seen_comment_ids.add(comment_id)

        username = username_from_node(comment_node)
        if username:
            usernames.append(username)
        comment_count += 1

    def add_threaded_comments(parent_node):
        threaded = parent_node.get("edge_threaded_comments") or {}
        edges = threaded.get("edges") or []

        for edge in edges:
            child_node = edge.get("node") or {}
            if child_node:
                add_comment_node(child_node)

        expected_children = safe_int(threaded.get("count"), 0)
        if not parent_node.get("id") or expected_children <= len(edges):
            return

        for child_node in build_child_comments_iterator(context, post.shortcode, parent_node["id"]):
            add_comment_node(child_node)

    for parent_node in build_parent_comments_iterator(context, post.shortcode):
        add_comment_node(parent_node)
        add_threaded_comments(parent_node)

    return usernames, comment_count


def fetch_comment_usernames_iphone(context, mediaid):
    usernames = []
    min_id = None

    while True:
        params = {"can_support_threading": "true", "permalink_enabled": "false"}
        if min_id:
            params["min_id"] = min_id

        data = context.get_iphone_json(f"api/v1/media/{mediaid}/comments/", params)

        for comment in data.get("comments", []):
            user = comment.get("user") or {}
            username = user.get("username")
            if username:
                usernames.append(username)

            for child in comment.get("preview_child_comments", []):
                child_user = child.get("user") or {}
                child_username = child_user.get("username")
                if child_username:
                    usernames.append(child_username)

        if not data.get("has_more"):
            break
        min_id = data.get("next_min_id")
        if not min_id:
            break

    return usernames, len(usernames)


def load_followers_from_file(path):
    follower_path = Path(path)
    if not follower_path.exists():
        return {}, None

    followers = {}
    try:
        raw_text = follower_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, exc

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "@" in line:
            candidate = line.split("@", 1)[1].split()[0].split(",")[0]
        else:
            candidate = line.split()[0].split(",")[0]

        candidate = normalize_username(candidate.strip(";,"))
        if candidate and is_valid_username(candidate):
            followers[candidate] = candidate

    return followers, None


def write_followers_to_file(path, followers):
    try:
        with open(path, "w", encoding="utf-8") as follower_file:
            for key in sorted(followers):
                follower_file.write(f"{followers[key]}\n")
    except OSError as exc:
        return exc

    return None


def load_follower_state(path):
    state_path = Path(path)
    if not state_path.exists():
        return None, None

    try:
        with open(state_path, "rb") as state_file:
            return pickle.load(state_file), None
    except Exception as exc:
        return None, exc


def write_follower_state(path, follower_iterator):
    try:
        with open(path, "wb") as state_file:
            pickle.dump(follower_iterator.freeze(), state_file)
    except Exception as exc:
        return exc

    return None


def remove_file(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return exc

    return None


def make_scan_error_item(kind, message):
    return {
        "shortcode": kind,
        "date": "-",
        "likes_expected": "-",
        "likes_fetched": "-",
        "comments_expected": "-",
        "comments_fetched": "-",
        "errors": [message],
    }


def write_report(issues):
    with open(REPORT_FILE, "w", encoding="utf-8") as report:
        report.write("Scan incomplete. No definitive ghost follower list generated.\n")
        report.write("Details:\n")
        for item in issues:
            report.write(
                f"- {item['shortcode']} ({item['date']}): "
                f"likes {item['likes_fetched']}/{item['likes_expected']}, "
                f"comments {item['comments_fetched']}/{item['comments_expected']}"
            )
            if item["errors"]:
                report.write(f"; errors: {' | '.join(item['errors'])}")
            report.write("\n")


def write_incomplete_result_notice():
    with open(RESULT_FILE, "w", encoding="utf-8") as result:
        result.write("Scan incomplete. See scan_report.txt for details.\n")


def bool_setting(value):
    return value.strip().lower() in ("evet", "yes", "true", "1")


def load_settings(path):
    settings_path = Path(path)
    if not settings_path.exists():
        return {}

    try:
        raw_text = settings_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    settings = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper().replace(" ", "_")
        value = value.strip()
        if key and value:
            settings[key] = value

    return settings


def write_settings(path, username, cookie_header, slow_mode):
    cookie_text = " ".join(extract_cookie_text(cookie_header).splitlines()).strip()
    slow_mode_text = "yes" if slow_mode else "no"
    settings_text = "\n".join(
        [
            "# Instagram Ghost Follower Detector - Settings",
            "# Lines starting with # are comments and ignored.",
            "",
            "# Your Instagram username",
            f"USERNAME = {username}",
            "",
            "# Full Cookie header from browser DevTools Network tab (any Instagram request)",
            f"COOKIE = {cookie_text}",
            "",
            "# Slow mode: set to yes to increase delays and avoid Instagram rate limits.",
            "# Posts: 30-90s wait between each. Followers: 75-150s wait after every 12 accounts.",
            "# Total run time depends on follower count and can take several hours.",
            f"SLOW_MODE = {slow_mode_text}",
            "",
        ]
    )

    try:
        Path(path).write_text(settings_text, encoding="utf-8")
    except OSError as exc:
        return exc

    return None


def main():
    print(f"{M}{'=' * 50}{RESET}")
    print(f"{M}       INSTAGRAM GHOST FOLLOWER DETECTOR{RESET}")
    print(f"{M}{'=' * 50}{RESET}")
    print(f"\nThis tool does not produce a definitive result if data is incomplete.")
    print("It uses full Cookie headers and skips unnecessary metadata queries.\n")

    settings_path = Path(SETTINGS_FILE)
    settings = load_settings(SETTINGS_FILE)
    if settings_path.exists():
        if settings:
            print(f"{C}[*]{RESET} {SETTINGS_FILE} found, reading available values from there.")
        else:
            print(f"{Y}[!]{RESET} {SETTINGS_FILE} found, but no usable values were set.")
    else:
        print(f"{C}[*]{RESET} {SETTINGS_FILE} not found, asking for account details interactively.")

    username = settings.get("USERNAME") or settings.get("KULLANICI_ADI", "")
    cookie_raw = settings.get("COOKIE", "")
    slow_mode_raw = settings.get("SLOW_MODE") or settings.get("YAVAS_MOD", "yes")
    slow_mode = bool_setting(slow_mode_raw)
    should_save_settings = (
        not settings_path.exists()
        or not settings.get("USERNAME")
        or not settings.get("COOKIE")
        or ("SLOW_MODE" not in settings and "YAVAS_MOD" not in settings)
    )

    if not username:
        username = input("Instagram username: ").strip()
    else:
        print(f"Username: @{username}")

    if not cookie_raw:
        cookie_input = prompt_secret("Full Instagram Cookie header: ").strip()
    else:
        print("Cookie: read from settings file.")
        cookie_input = cookie_raw

    if slow_mode:
        print(f"{Y}Mode: SLOW{RESET} (delays increased to avoid Instagram rate limits)")
    else:
        print(f"{G}Mode: NORMAL{RESET}")

    if not username or not cookie_input:
        print(f"{R}[-]{RESET} Username and Cookie header cannot be empty.")
        sys.exit(1)

    cookies = parse_cookie_input(cookie_input)
    missing = missing_required_cookies(cookies)
    if missing:
        print(f"{R}[-]{RESET} Missing required cookie values: {', '.join(missing)}")
        print("    Copy the full Cookie header from your browser Network tab (an Instagram request).")
        sys.exit(1)

    try:
        loader = create_loader(username, cookies)
        print(f"\n{C}[*]{RESET} Verifying cookie session...")
        logged_in_user = get_logged_in_user(loader, username, cookies["ds_user_id"])
        logged_in_username = logged_in_user["username"]
        logged_in_user_id = logged_in_user["id"]
        print(f"{G}[+]{RESET} Session verified: @{logged_in_username}")
    except Exception as exc:
        print(f"\n{R}[-]{RESET} Session verification failed: {exc}")
        print("    Make sure you are logged into Instagram in your browser and the cookie is fresh.")
        sys.exit(1)

    if should_save_settings:
        settings_error = write_settings(SETTINGS_FILE, logged_in_username, cookie_input, slow_mode)
        if settings_error:
            print(f"{Y}[!]{RESET} Could not save {SETTINGS_FILE}: {settings_error}")
        else:
            print(f"{G}[+]{RESET} Saved account settings to {SETTINGS_FILE}.")

    expected_follower_count = get_user_follower_count(logged_in_user)
    followers_source = "Instagram"
    follower_error = None

    fallback_followers, fallback_error = load_followers_from_file(FOLLOWERS_FILE)
    if fallback_error:
        print(f"{Y}[!]{RESET} Could not read {FOLLOWERS_FILE}: {fallback_error}")

    if fallback_followers:
        if expected_follower_count is not None and len(fallback_followers) < expected_follower_count:
            issues = [
                make_scan_error_item(
                    "FOLLOWER_LIST",
                    f"{FOLLOWERS_FILE} appears incomplete: "
                    f"{len(fallback_followers)}/{expected_follower_count}",
                )
            ]
            write_report(issues)
            write_incomplete_result_notice()
            print(f"{R}[-]{RESET} {FOLLOWERS_FILE} appears incomplete; scan aborted.")
            print(f"    Details written to {REPORT_FILE}.")
            sys.exit(2)

        followers = fallback_followers
        followers_source = FOLLOWERS_FILE
        print(f"{G}[+]{RESET} Loaded {len(followers)} followers from {FOLLOWERS_FILE}.")
    else:
        print(f"\n{C}[*]{RESET} Fetching follower list...")
        followers, follower_error = collect_followers(
            loader.context,
            logged_in_user_id,
            logged_in_username,
            slow_mode,
            expected_follower_count,
        )

        if not follower_error and expected_follower_count is not None and len(followers) < expected_follower_count:
            follower_error = RuntimeError(
                f"Follower list mismatch: got {len(followers)}, expected {expected_follower_count}"
            )

        if follower_error:
            error_message = str(follower_error)
            if followers:
                error_message += f" Partial followers saved: {len(followers)} in {PARTIAL_FOLLOWERS_FILE}."
            issues = [make_scan_error_item("FOLLOWER_LIST", error_message)]
            write_report(issues)
            write_incomplete_result_notice()
            print(f"{R}[-]{RESET} Instagram follower endpoint did not return the follower list.")
            print(f"    Error: {follower_error}")
            if followers:
                print(f"    Saved {len(followers)} partial followers to {PARTIAL_FOLLOWERS_FILE}.")
            print(f"{R}[-]{RESET} Cannot proceed. Details written to {REPORT_FILE}.")
            print(f"    Safer option: create {FOLLOWERS_FILE} with one username per line and retry.")
            sys.exit(2)

    print(f"{G}[+]{RESET} Found {len(followers)} followers. Source: {followers_source}")

    print(f"\n{C}[*]{RESET} Analyzing last {POST_LIMIT} posts...")
    interacted_users = {}
    issues = []
    recent_posts, post_list_error = collect_recent_posts(loader.context, logged_in_username, POST_LIMIT)

    if post_list_error:
        print(f"{R}[-]{RESET} Could not fully retrieve post list.")
        print(f"    Error: {post_list_error}")
        print(f"    Posts retrieved: {len(recent_posts)}")
        issues.append(make_scan_error_item("POST_LIST", str(post_list_error)))

    if not recent_posts:
        write_report(issues)
        write_incomplete_result_notice()
        print(f"{R}[-]{RESET} No posts to analyze. Details written to {REPORT_FILE}.")
        sys.exit(2)

    for post_count, post in enumerate(recent_posts, 1):
        post_date = post.date_utc.strftime("%d-%m-%Y")
        likes_expected = get_post_like_count(post)
        comments_expected = get_post_comment_count(post)

        print(f"\n  {B}-> Post {post_count}/{len(recent_posts)}{RESET}: {post.shortcode} ({post_date})")

        if slow_mode:
            time.sleep(random.uniform(*SLOW_PRE_FETCH_DELAY))

        (like_usernames, likes_fetched), like_error = fetch_with_retries(
            "Likes",
            lambda current_post=post, expected=likes_expected: fetch_like_usernames(
                loader.context,
                current_post,
                expected,
            ),
        )
        if like_error:
            like_usernames = []
            likes_fetched = 0

        comment_usernames = []
        comments_fetched = 0
        comment_error = None

        if not like_error or not is_instagram_stop_error(like_error):
            (comment_usernames, comments_fetched), comment_error = fetch_with_retries(
                "Comments",
                lambda current_post=post, expected=comments_expected: fetch_comment_usernames(
                    loader.context,
                    current_post,
                    expected,
                ),
            )
            if comment_error:
                comment_usernames = []
                comments_fetched = 0

        add_usernames(interacted_users, like_usernames)
        add_usernames(interacted_users, comment_usernames)

        likes_complete = like_error is None and (likes_expected is None or likes_fetched >= likes_expected)
        comments_complete = comment_error is None and (
            comments_expected is None or comments_fetched >= comments_expected
        )

        print(
            f"     {C}Likes:{RESET} "
            f"{likes_fetched}/{expected_count_text(likes_expected)} | "
            f"{C}Comments:{RESET} "
            f"{comments_fetched}/{expected_count_text(comments_expected)}"
        )

        if not likes_complete or not comments_complete:
            errors = []
            if like_error:
                errors.append(f"likes: {like_error}")
            if comment_error:
                errors.append(f"comments: {comment_error}")

            issues.append(
                {
                    "shortcode": post.shortcode,
                    "date": post_date,
                    "likes_expected": expected_count_text(likes_expected),
                    "likes_fetched": likes_fetched,
                    "comments_expected": expected_count_text(comments_expected),
                    "comments_fetched": comments_fetched,
                    "errors": errors,
                }
            )

        if like_error and is_instagram_stop_error(like_error):
            print(f"{R}[-]{RESET} Instagram temporarily restricted the likes endpoint; scan stopped.")
            print("    This is not a code error. Instagram placed a temporary limit on your session.")
            print("    Use Instagram normally in your browser for a few hours, then retry.")
            break
        if comment_error and is_instagram_stop_error(comment_error):
            print(f"{R}[-]{RESET} Instagram temporarily restricted the comments endpoint; scan stopped.")
            print("    This is not a code error. Instagram placed a temporary limit on your session.")
            print("    Use Instagram normally in your browser for a few hours, then retry.")
            break

        if post_count < len(recent_posts):
            delay_range = SLOW_POST_DELAY if slow_mode else POST_DELAY
            time.sleep(random.uniform(*delay_range))

    print(f"\n{G}[+]{RESET} {post_count} posts processed (collected: {len(recent_posts)}).")
    print(f"{G}[+]{RESET} Total unique interactions found: {len(interacted_users)}.")

    if issues:
        print(f"\n{R}[-]{RESET} Scan incomplete; no definitive ghost follower list generated.")
        print(f"    Details written to {REPORT_FILE}.")
        write_report(issues)
        write_incomplete_result_notice()
        sys.exit(2)

    ghost_keys = sorted(set(followers) - set(interacted_users))
    ghost_followers = [followers[key] for key in ghost_keys]

    print(f"\n{M}{'=' * 50}{RESET}")
    print(f"{G}{B}      GHOST FOLLOWERS ({len(ghost_followers)} accounts){RESET}")
    print(f"{M}{'=' * 50}{RESET}")

    if not ghost_followers:
        print(f"\n{G}Everyone who follows you has interacted with at least one of your recent posts.{RESET}")
        open(RESULT_FILE, "w", encoding="utf-8").close()
        return

    with open(RESULT_FILE, "w", encoding="utf-8") as result:
        for idx, ghost in enumerate(ghost_followers, 1):
            print(f" {idx}. @{ghost}")
            result.write(f"{ghost}\n")

    print(f"\n{G}[+]{RESET} List saved to {RESULT_FILE}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Y}[!]{RESET} Cancelled by user.")
        sys.exit(130)
