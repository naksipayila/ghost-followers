# Instagram Ghost Follower Detector

Python tool for finding followers who did not like or comment on your recent Instagram posts.

The result is only reliable when Instagram returns complete follower, like, and comment data. If Instagram rate limits the session or returns partial data, the tool stops and writes an incomplete scan notice instead of producing a misleading result.

## Features

- Reads Instagram session cookies from an optional local settings file or asks interactively.
- Checks followers against likes and comments on recent posts.
- Supports slow mode to reduce the chance of Instagram rate limits.
- Uses `followers.txt` first when available, avoiding the Instagram follower endpoint.
- Saves partial follower progress and a resume cursor if Instagram restricts the scan.
- Writes ghost follower results to `ghost_followers.txt`.
- Writes incomplete scan details to `scan_report.txt`.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the tool and enter your Instagram username and full Cookie header when prompted.

After the session is verified, the tool creates a local `settings.txt` file automatically so the next run can reuse those values. You can also create or edit `settings.txt` manually.

## Settings

```txt
USERNAME = your.instagram.username
COOKIE = full_cookie_header_here
SLOW_MODE = yes
```

`SLOW_MODE = yes` is recommended. It increases delays between requests and reduces the chance of temporary Instagram restrictions.

If `settings.txt` is missing or `SLOW_MODE` is not set, slow mode is enabled by default.

In slow mode, follower collection waits 75-150 seconds after every 12 followers and cools down for 5-10 minutes after every 120 followers. Post analysis waits 30-90 seconds between posts.

Total runtime depends heavily on follower count. Larger accounts can take several hours in slow mode.

Do not commit `settings.txt`. It contains private session cookies and is ignored by git.

## Usage

```bash
python main.py
```

The tool analyzes the latest posts configured by `POST_LIMIT` in `main.py`.

## Output

- `ghost_followers.txt`: generated only when the scan completes cleanly.
- `scan_report.txt`: written when Instagram returns incomplete data or a request fails.
- `followers.txt`: optional fallback file with one username per line if the Instagram follower endpoint is restricted.
- `followers.partial.txt`: partial follower progress saved when Instagram restricts follower collection.
- `followers.state.pkl`: local resume cursor for continuing follower collection after a restriction.

## Rate Limit Notes

Instagram may temporarily restrict follower, like, or comment endpoints. Risk increases with larger accounts, higher engagement, and repeated runs.

Recommended usage:

- Keep `SLOW_MODE = yes`.
- Prefer `followers.txt` for larger accounts so the scan does not call Instagram's follower endpoint.
- Avoid running scans repeatedly in a short period.
- Reduce `POST_LIMIT` if the account has high engagement.
- Keep follower batch delays enabled for larger accounts.
- If restricted, use Instagram normally in the browser for a few hours before retrying.

## Security

Your Cookie header is equivalent to a logged-in session. Keep `settings.txt` private and rotate the session if it was exposed.
