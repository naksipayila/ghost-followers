# Instagram Ghost Follower Detector

Python tool for finding followers who did not like or comment on your recent Instagram posts.

The result is only reliable when Instagram returns complete follower, like, and comment data. If Instagram rate limits the session or returns partial data, the tool stops and writes an incomplete scan notice instead of producing a misleading result.

## Features

- Reads Instagram session cookies from a local settings file.
- Checks followers against likes and comments on recent posts.
- Supports slow mode to reduce the chance of Instagram rate limits.
- Writes ghost follower results to `ghost_followers.txt`.
- Writes incomplete scan details to `scan_report.txt`.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your local settings file:

```bash
cp settings.example.txt settings.txt
```

Edit `settings.txt` and add your Instagram username and full Cookie header from browser DevTools.

## Settings

```txt
USERNAME = your.instagram.username
COOKIE = full_cookie_header_here
SLOW_MODE = yes
```

`SLOW_MODE = yes` is recommended. It increases delays between requests and reduces the chance of temporary Instagram restrictions.

Do not commit `settings.txt`. It contains private session cookies.

## Usage

```bash
python main.py
```

The tool analyzes the latest posts configured by `POST_LIMIT` in `main.py`.

## Output

- `ghost_followers.txt`: generated only when the scan completes cleanly.
- `scan_report.txt`: written when Instagram returns incomplete data or a request fails.
- `followers.txt`: optional fallback file with one username per line if the Instagram follower endpoint is restricted.

## Rate Limit Notes

Instagram may temporarily restrict follower, like, or comment endpoints. Risk increases with larger accounts, higher engagement, and repeated runs.

Recommended usage:

- Keep `SLOW_MODE = yes`.
- Avoid running scans repeatedly in a short period.
- Reduce `POST_LIMIT` if the account has high engagement.
- If restricted, use Instagram normally in the browser for a few hours before retrying.

## Security

Your Cookie header is equivalent to a logged-in session. Keep `settings.txt` private and rotate the session if it was exposed.
