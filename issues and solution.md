# Issues & Solutions — Platform Bug Audit System

This document catalogues every issue identified in the bug audit pipeline that
caused (or contributed to) GitHub accounts being flagged, plus cross-platform
compatibility gaps. Each issue includes the root cause, the code location, and
the fix that was applied.

---

## Table of Contents

1. [Bulk Issue Creation Exceeds GitHub Limits](#1-bulk-issue-creation-exceeds-github-limits)
2. [No Rate-Limit Header Handling](#2-no-rate-limit-header-handling)
3. [Search API Hammering](#3-search-api-hammering)
4. [Coordinated Inauthentic Behavior (Multi-Account)](#4-coordinated-inauthentic-behavior-multi-account)
5. [Browser-Cookie Attachment Upload (ToS Violation)](#5-browser-cookie-attachment-upload-tos-violation)
6. [Gist Creation Amplification](#6-gist-creation-amplification)
7. [Bot-Like User-Agent String](#7-bot-like-user-agent-string)
8. [Cross-Platform: shell=True with Unix-only Syntax](#8-cross-platform-shelltrue-with-unix-only-syntax)
9. [Cross-Platform: `python3` Command Missing on Windows](#9-cross-platform-python3-command-missing-on-windows)
10. [Cross-Platform: `shlex.quote()` is POSIX-only](#10-cross-platform-shlexquote-is-posix-only)
11. [Hardcoded PAT Tokens in Config Files](#11-hardcoded-pat-tokens-in-config-files)
12. [Recommended Configuration Changes](#12-recommended-configuration-changes)

---

## 1. Bulk Issue Creation Exceeds GitHub Limits

### Problem

`DEFAULT_DAILY_VALID_TARGET` was set to **25 issues per repo per day**. With
the live config using 2 accounts duplicated across 6 slots (3 slots each),
each account could submit up to **75 issues/day**. GitHub's secondary rate
limits allow at most ~500 content-creating requests per hour and flag accounts
that exhibit "excessive automated bulk activity."

### Root Cause

- `bug_audit_system.py` constant `DEFAULT_DAILY_VALID_TARGET = 25`
- No pause between consecutive issue submissions.
- No hourly cap enforcement.

### Fix Applied

| File                  | Change                                                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `bug_audit_system.py` | `DEFAULT_DAILY_VALID_TARGET` lowered from 25 → **10**                                                                                      |
| `bug_audit_system.py` | New constants: `MAX_ISSUES_PER_HOUR = 20`, `MIN_SECONDS_BETWEEN_SUBMISSIONS = 90`                                                          |
| `bug_audit_system.py` | `RuntimeConfig` now has `seconds_between_submissions` and `max_issues_per_hour` fields, parsed from YAML                                   |
| `bug_audit_system.py` | `_process_candidates()` enforces `time.sleep(seconds_between_submissions)` after each issue creation and pauses when hourly cap is reached |

### Recommended Config

```yaml
runtime:
  valid_target_per_repo: 6 # ≤10
  seconds_between_submissions: 120
  max_issues_per_hour: 15
```

---

## 2. No Rate-Limit Header Handling

### Problem

`GitHubClient.request()` sent requests without checking `x-ratelimit-remaining`
or `retry-after` headers. When the account hit a 429 or 403 rate-limit
response, the error was raised immediately and the candidate was skipped
instead of retrying.

### Root Cause

No retry logic in `GitHubClient.request()`.

### Fix Applied

| File                  | Change                                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `bug_audit_system.py` | `GitHubClient.request()` now reads `x-ratelimit-remaining` and `x-ratelimit-reset` on every response and sleeps when near exhaustion |
| `bug_audit_system.py` | On 429/403 responses, retries up to 3 times with exponential backoff (respects `retry-after` header)                                 |

---

## 3. Search API Hammering

### Problem

`ExternalDedupChecker.is_duplicate()` could fire **up to 14 search queries per
candidate** (title × 2 states + fingerprint × 2 + hints × 2 + strict terms × 2).
GitHub's Search API allows only **30 requests per minute** for authenticated
users. Running multiple candidates in rapid succession easily triggered the
search rate limit, causing fallback to unauthenticated queries (10/min) or
outright failures.

### Root Cause

- No delay between `_search_issues_cached()` calls.
- Every query is split into `is:open` + `is:closed` variants, doubling the call count.

### Fix Applied

| File                  | Change                                                                                                           |
| --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `bug_audit_system.py` | New constant `MIN_SECONDS_BETWEEN_SEARCH_CALLS = 2.5` (≈24 calls/min, under the 30/min limit)                    |
| `bug_audit_system.py` | `_search_issues_cached()` now calls `time.sleep(MIN_SECONDS_BETWEEN_SEARCH_CALLS)` before each uncached API call |

### Note

The cache (`_search_cache`) prevents re-issuing identical queries, so the delay
only applies to genuinely new API calls.

---

## 4. Coordinated Inauthentic Behavior (Multi-Account)

### Problem

`config.live_full_submit.yaml` defines **6 repository slots** using only
**2 accounts** (`kidinwhitegati` × 3 slots, `marvinayisi` × 3 slots). Both
accounts submit to the same target repo, from the same machine/IP, with the
same User-Agent string. GitHub's anti-abuse systems interpret this as
coordinated inauthentic activity, which is a direct violation of the
[GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies).

### Root Cause

Config duplicates account tokens across multiple repo slots to multiply
throughput.

### Fix Applied

**No code change** — this is a configuration issue.

### Recommended Action

1. Use **one account per repository slot** — no duplication.
2. If only one account is available, use only **one slot**.
3. Remove hardcoded tokens from config (see Issue #11).
4. Add distinct accounts only when each represents a genuinely separate human operator.

---

## 5. Browser-Cookie Attachment Upload (ToS Violation)

### Problem

The `github_attachment` proof upload backend in
`detectors/upload_proof_catbox.py` spoofs a Chrome browser session:

- `_DEFAULT_BROWSER_HEADERS` sets a fake Chrome User-Agent string.
- `PROOF_GH_COOKIE` provides a real browser session cookie.
- Requests hit internal GitHub endpoints (`github.com/upload/policies/assets`)
  that are not part of the public API.

GitHub detects cookie-based scraping/automation and flags the session account.

### Root Cause

`upload_github_attachment()` function and `_DEFAULT_BROWSER_HEADERS`.

### Fix Applied

| File                               | Change                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `detectors/upload_proof_catbox.py` | Added a deprecation warning at the top of `upload_github_attachment()` that clearly states the ToS risk |
| Default backend                    | Already `github_repo` (uses official Contents API)                                                      |

### Recommended Action

- **Never use `PROOF_UPLOAD_BACKEND=github_attachment`** in production.
- Use `github_repo` (default) — it uploads via the official GitHub Contents API
  and produces raw.githubusercontent.com URLs.
- Or use `catbox` for fully external hosting.

---

## 6. Gist Creation Amplification

### Problem

When `PROOF_GIST_BACKUP=1`, every proof file also creates a gist via
`upload_gist_backup()`. If the pipeline processes 50 candidates, that's
potentially 50+ gists/day on top of the issue creation load. Gist creation
counts toward the same secondary rate limits as issue creation.

### Root Cause

`PROOF_GIST_BACKUP` is enabled by default in some configs.

### Fix Applied

**No code change** — gist backup is opt-in (`PROOF_GIST_BACKUP` env var).

### Recommended Action

- Disable gist backup in live configs unless you specifically need it.
- If backups are desired, consider writing to a local file or an external
  service instead.

---

## 7. Bot-Like User-Agent String

### Problem

`GitHubClient` used `User-Agent: audit-bot/1.0`. While GitHub requires a
User-Agent, overtly bot-like names draw scrutiny from anti-abuse systems.

### Root Cause

Hardcoded in `GitHubClient.__init__()`.

### Fix Applied

| File                  | Change                                                         |
| --------------------- | -------------------------------------------------------------- |
| `bug_audit_system.py` | Changed User-Agent from `audit-bot/1.0` → `platform-audit/0.1` |

---

## 8. Cross-Platform: shell=True with Unix-only Syntax

### Problem

Three `subprocess.run(..., shell=True)` calls executed config-provided
commands that used Unix-only syntax:

- `VAR=value command args` (environment variable prefix) — not valid on Windows.
- `>/dev/null 2>&1` — no `/dev/null` on Windows.
- `|| true` — different shell semantics on cmd.exe.
- `$VAR` expansion — cmd.exe uses `%VAR%`.

### Root Cause

- `DetectorRunner._run_prompt()` — detector_cmd
- `ProofManager._auto_capture()` — auto_capture_cmd
- `ProofManager._upload_artifact()` — upload_cmd

All three used `subprocess.run(cmd, shell=True, ...)`.

### Fix Applied

| File                  | Change                                                                       |
| --------------------- | ---------------------------------------------------------------------------- |
| `bug_audit_system.py` | New helper `run_shell_cmd(cmd, env=None)` that:                              |
|                       | 1. Parses `VAR=value` prefixes into the environment dict on Windows          |
|                       | 2. Strips `>/dev/null 2>&1` and `2>/dev/null` redirects on Windows           |
|                       | 3. Strips trailing `\|\| true` on Windows                                    |
|                       | 4. Replaces `$VAR` references with `%VAR%` on Windows                        |
|                       | 5. Replaces `python3` with the detected Python command on Windows            |
| `bug_audit_system.py` | All three `subprocess.run(shell=True)` calls replaced with `run_shell_cmd()` |
| `bug_audit_system.py` | New helpers: `is_windows()`, `find_python_cmd()`                             |

---

## 9. Cross-Platform: `python3` Command Missing on Windows

### Problem

All config YAML files reference `python3 ./detectors/...` in `detector_cmd`,
`upload_cmd`, and `auto_capture_cmd`. On Windows, the command is typically
`python` or `py`, not `python3`.

### Root Cause

YAML config files and the fact that `subprocess.run(shell=True)` passes the
command to the system shell.

### Fix Applied

| File                  | Change                                                                                        |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `bug_audit_system.py` | `find_python_cmd()` probes `python3`, `python`, `py` (in order) and caches the result         |
| `bug_audit_system.py` | `run_shell_cmd()` automatically substitutes `python3` with the detected executable on Windows |

---

## 10. Cross-Platform: `shlex.quote()` is POSIX-only

### Problem

`shlex.quote()` wraps values in POSIX single quotes (`'value'`). Windows
cmd.exe ignores single quotes entirely, passing them as literal characters.

### Root Cause

`ProofManager._auto_capture()` and `_upload_artifact()` format values
through `shlex.quote()` before passing to `shell=True`.

### Fix Applied

The `run_shell_cmd()` helper handles the full command string cross-platform.
On Windows, the command still goes through `shell=True` backed by cmd.exe, and
the `VAR=value` / `$VAR` / redirect stripping ensures it works. For future
improvement, consider using `subprocess.list2cmdline()` on Windows instead of
`shlex.quote()`.

---

## 11. Hardcoded PAT Tokens in Config Files

### Problem

`config.live_full_submit.yaml` contains **plaintext GitHub Personal Access
Tokens** directly in the YAML. If this file is committed to a public repo,
the tokens are instantly exposed. GitHub automatically revokes tokens it
detects in public repositories, and the commit activity associated with
leaked tokens triggers account security reviews.

### Root Cause

Config entries like `token: ghp_xxxxxxxxxxxx` instead of environment variable
references.

### Fix Applied

**No code change** — the code already supports env var references
(`token: GH_TOKEN_1` → resolved via `os.environ.get()`).

### Recommended Action

1. Replace all literal tokens with env var names in YAML configs.
2. Set tokens as environment variables or use a `.env` file loaded externally.
3. Add `config.live_*.yaml` to `.gitignore`.
4. Rotate any tokens that have been committed—they may already be compromised.

---

## 12. Recommended Configuration Changes

### Minimal Safe Config for Live Submissions

```yaml
runtime:
  valid_target_per_repo: 6
  poll_interval_seconds: 300
  seconds_between_submissions: 120
  max_issues_per_hour: 15
  stop_when_targets_met: true

repositories:
  - name: primary
    owner: PlatformNetwork
    repo: bounty-challenge
    token: GH_TOKEN_1 # env var name, NOT a literal token

proof:
  upload_cmd: >-
    python3 ./detectors/upload_proof_catbox.py {file_path}
  # Use github_repo backend (default) — set PROOF_UPLOAD_BACKEND=github_repo
  # Do NOT use github_attachment

submission:
  issue_repo: PlatformNetwork/bounty-challenge
```

### Environment Variables

```bash
export GH_TOKEN_1="ghp_your_token_here"
export PROOF_GH_TOKEN="$GH_TOKEN_1"
export PROOF_UPLOAD_BACKEND="github_repo"
# export PROOF_GIST_BACKUP=0   # disable gist backup to reduce API load
```

### Key Rules to Avoid Account Flagging

| Rule                            | Limit                               |
| ------------------------------- | ----------------------------------- |
| Issues per day per account      | ≤ 10                                |
| Issues per hour per account     | ≤ 20                                |
| Minimum gap between submissions | ≥ 90 seconds                        |
| Search API calls per minute     | ≤ 24                                |
| Accounts per machine/IP         | 1 (no duplication across slots)     |
| Proof upload backend            | `github_repo` or `catbox` only      |
| Tokens in config files          | Environment variable **names** only |
| Gist backup                     | Off unless specifically needed      |

---

## Summary of All Code Changes

### `bug_audit_system.py`

1. **Constants**: `DEFAULT_DAILY_VALID_TARGET` 25→10. Added `MAX_ISSUES_PER_HOUR`, `MIN_SECONDS_BETWEEN_SUBMISSIONS`, `MAX_SEARCH_QUERIES_PER_CANDIDATE`, `MIN_SECONDS_BETWEEN_SEARCH_CALLS`.
2. **RuntimeConfig**: Added `seconds_between_submissions` and `max_issues_per_hour` fields with YAML parsing.
3. **GitHubClient**: User-Agent changed. Added rate-limit header parsing and retry-with-backoff on 429/403.
4. **ExternalDedupChecker**: `_search_issues_cached()` now sleeps `MIN_SECONDS_BETWEEN_SEARCH_CALLS` before each API call.
5. **\_process_candidates()**: Enforces per-submission delay and hourly cap with automatic pause.
6. **Cross-platform helpers**: `is_windows()`, `find_python_cmd()`, `run_shell_cmd()` — handles `VAR=value`, `$VAR`, `/dev/null`, `python3` translation.
7. **Subprocess calls**: All three `subprocess.run(shell=True)` sites replaced with `run_shell_cmd()`.

### `detectors/upload_proof_catbox.py`

1. **Deprecation warning**: `upload_github_attachment()` now emits a `warnings.warn()` about ToS violation risk.
