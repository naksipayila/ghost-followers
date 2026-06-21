<h1 align="center">Instagram Ghost Follower Detector</h1>

<p align="center">
  Conservative Python CLI for finding followers who did not like or comment on your recent Instagram posts.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white">
  <img alt="Instaloader" src="https://img.shields.io/badge/Instaloader-4.15.1-405DE6">
  <img alt="CLI" src="https://img.shields.io/badge/Interface-CLI-111827">
  <img alt="License" src="https://img.shields.io/badge/License-Unspecified-lightgrey">
</p>

## Overview

This tool compares your followers with the users who liked or commented on your latest posts. It only generates a ghost follower list when Instagram returns complete data. If a follower, like, or comment endpoint is restricted, the scan stops and reports what it found instead of producing unreliable results.

This is not an official Instagram API client. It relies on a logged-in browser Cookie header and Instaloader internals, so Instagram rate limits can still happen.

## Highlights

| Area | Behavior |
| --- | --- |
| Session | Verifies the Cookie session before scanning. |
| Settings | Reads local `settings.txt` or asks interactively on first run. |
| Auto-save | Creates or updates `settings.txt` only after successful verification. |
| Followers | Uses `followers.txt` first when available to avoid the follower endpoint. |
| Resume | Saves follower and post progress so interrupted scans can continue. |
| Safety | Stops on incomplete data instead of writing misleading results. |
| Output | Writes final results to `ghost_followers.txt`. |

## Quick Start

Run the scanner:

```bash
python src\main.py
```

On first run, enter your Instagram username and the full Cookie header from your browser DevTools Network tab. After the session is verified, the tool creates a local `settings.txt` file for future runs.

## Local Settings

`settings.txt` is ignored by git and should stay private.

```txt
USERNAME = your.instagram.username
COOKIE = full_cookie_header_here
```

The tool always runs with conservative delays to avoid Instagram rate limits.

| Step | Delay |
| --- | --- |
| Follower collection | `100-200` seconds after every `12` followers |
| Follower cooldown | `400-800` seconds after every `120` fetched follower records |
| Post analysis | `45-120` seconds between posts |

Runtime depends on follower count and post engagement. Larger accounts can take several hours.

## Follower Collection Strategy

The safest path for larger accounts is a local `followers.txt` file with one username per line.

```txt
username_one
username_two
username_three
```

If `followers.txt` exists, the scanner uses it and skips Instagram's follower endpoint. If it does not exist, the scanner collects followers slowly from Instagram.

Follower progress files:

| File | Purpose |
| --- | --- |
| `followers.partial.txt` | Usernames collected before a follower endpoint restriction. |
| `followers.state.pkl` | Binary cursor used to continue follower collection later. |

These files are local runtime files and are ignored by git.

## Post Analysis Resume

Completed post scans are saved to `scan_progress.json` after every fully processed post. If likes or comments fail on a later post, the next run skips already completed posts and retries the remaining posts.

Progress is reused only when the same account and recent post list match the saved state. If your recent post list changes, old progress is ignored and the scan starts fresh.

## Output Files

| File | When It Appears |
| --- | --- |
| `ghost_followers.txt` | Scan completed cleanly and definitive results were generated. |
| `followers.partial.txt` | Follower collection stopped before completion. |
| `followers.state.pkl` | Follower collection has a saved resume cursor. |
| `scan_progress.json` | Post interaction analysis has resumable progress. |

## Rate Limit Handling

The scanner treats these responses as stop conditions:

| Signal | Meaning |
| --- | --- |
| `feedback_required` | Instagram temporarily restricted the session. |
| `checkpoint_required` | Login or account verification is required. |
| `challenge_required` | Instagram requires a challenge step. |
| `Please wait a few minutes before you try again` | Temporary rate limit. |
| `401 Unauthorized` | Session or endpoint access was rejected. |
| `429` | Too many requests. |
| `too many requests` | Too many requests. |
| `rate limit` | Rate limit signal. |

If this happens, stop running the tool for a while and use Instagram normally in your browser before retrying.

## Security Notes

Your Cookie header is equivalent to a logged-in Instagram session.

| Do | Do Not |
| --- | --- |
| Keep `settings.txt` private. | Share Cookie headers. |
| Rotate your session if a Cookie was exposed. | Commit real Cookie values. |
| Keep runtime files local. | Upload generated progress files publicly. |

Local secrets and runtime outputs are excluded through `.gitignore`.

## Project Structure

```txt
.
├── src/
│   └── main.py
├── .gitignore
├── README.md
├── run.bat
```

## Important Notes

- The default post limit is `25` and is configured as `POST_LIMIT` in `main.py`.
- The tool is intentionally conservative; incomplete scans do not produce a definitive ghost follower list.
- Instagram behavior can change, so endpoint restrictions are expected sometimes.
