# Automated Bug Detection And Reporting System

This project implements a daily bug-auditing pipeline that:

1. Reads mutable prompts from YAML (hot-reload without restart).
2. Clones or refreshes a target codebase and runs detector commands.
3. Performs local dedup with a persistent SQLite file.
4. Performs external dedup against `PlatformNetwork/bounty-challenge` issues.
5. Enforces proof-of-bug requirements (native GUI artifacts, unedited capture policy, allowed formats).
6. Submits issues to 6 GitHub repositories in round-robin order until each has 25 valid issues per day.
7. Tracks invalid labels and compensates by submitting additional valid issues.
8. Enforces issue-title formatting via `submission.title_template` (default: `[Bug][alpha]{title}`).

## Files

- `/Users/odeili/Projects/algo_platform/bug_audit_system.py` - main orchestrator.
- `/Users/odeili/Projects/algo_platform/config.example.yaml` - configuration template.
- `/Users/odeili/Projects/algo_platform/.audit_state/local_dedup.sqlite3` - created at runtime.
- `/Users/odeili/Projects/algo_platform/.audit_state/daily_state.json` - created at runtime.
- `/Users/odeili/Projects/algo_platform/.audit_state/daily_summary.json` - created at runtime.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Set tokens:

```bash
export GH_TOKEN_1=...
export GH_TOKEN_2=...
export GH_TOKEN_3=...
export GH_TOKEN_4=...
export GH_TOKEN_5=...
export GH_TOKEN_6=...
# Optional:
export GH_EXTERNAL_DEDUP_TOKEN=...
# Required for real github.com/user-attachments proof uploads:
export PROOF_GH_COOKIE='user_session=...; __Host-user_session_same_site=...'
# Optional path variant:
# export PROOF_GH_COOKIE_FILE=~/.config/proof/github_cookie.txt
# Optional proof target override (owner/repo). If omitted, uploader infers from source repo git remote.
export PROOF_GH_REPO=your-user/your-proof-repo
# Optional if you want to pin repository id directly:
# export PROOF_GH_REPO_ID=123456789
# Optional gist token override (defaults to PROOF_GH_TOKEN / GH token):
# export PROOF_GIST_TOKEN=...
```

Repository config now only needs:

- `github_name` (submitter identity, e.g. GitHub username)
- `token` (env var name like `GH_TOKEN_1` or a literal token)
- Shared destination under `submission.issue_repo` (for example `PlatformNetwork/bounty-challenge`)

## Detector Contract

Each `detector_cmd` in YAML must print JSON findings to stdout.

Required fields per finding:

- `title`
- `description`
- `reproduction_steps` (list)
- `impact`
- `native_gui` (for example: `Cortex IDE`)
- `proof_artifacts` (optional during detection, required for submission; use public URLs or local file paths if `proof.upload_cmd` is configured)

Optional:

- `fingerprint` (stable detector-defined ID; otherwise computed automatically)

## Title Template

- Config key: `submission.title_template`
- Default: `[Bug][alpha]{title}`
- The `{title}` placeholder is mandatory.

## Run

Single cycle:

```bash
python bug_audit_system.py --config config.yaml --source /path/to/codebase --once
```

Continuous daily loop:

```bash
python bug_audit_system.py --config config.yaml --source https://github.com/example/target-repo.git
```

Default static detector script included:

- `/Users/odeili/Projects/algo_platform/detectors/cortex_static_triage_detector.py`
- `/Users/odeili/Projects/algo_platform/detectors/cortex_gui_capture.py` (best-effort native GUI screenshot capture on macOS/Windows/Linux)

Auto GUI proof capture:

- Configure `proof.auto_capture_cmd` (already set in `config.yaml`).
- Detector findings with no `proof_artifacts` trigger this command before submission.
- Captured files are saved under `<source_repo>/proofs/` by default.
- If `Cortex IDE` is not installed in `/Applications`, capture falls back to launching from source via `tauri:dev`.
- The fallback launch path prefers Homebrew Node LTS (`node@22`/`node@20`) to avoid esbuild crashes on bleeding-edge Node.
- Capture is strict: it refuses screenshots unless the target app process is frontmost.
- When `tauri:dev` launch is configured, macOS capture is pinned to the `cortex-gui` process (strict process check).
- Capture uses the target app front window region (not full-screen), so unrelated windows are excluded.
- Capture now runs per-finding UI navigation hooks (Docs/Quick Access flows) before screenshot.
- In WSL host mode, video capture can run per-bug mouse/click profiles from `detectors/cortex_wsl_video_actions.json` keyed by `finding_id`.
- WSL host video capture also emits `<finding>.preview.gif` (inline motion preview) and `<finding>.cursor.mp4` (cursor-visualized playback) so reports still show pointer movement when GitHub strips `<video>` tags.
- Submission rendering now selects a single inline proof per bug (screenshot for static bugs, GIF motion preview for interaction/event-routing bugs) and omits visible artifact URL/link lines.
- If the app display name differs, set `CORTEX_APP_NAME` (default: `Cortex IDE`).
- macOS requirements for `cortex_gui_capture.py`:
  - Run in an active desktop session (not headless/SSH-only shell).
  - Grant Terminal (or your runner app) `Screen Recording` permission.
  - Grant Terminal `Accessibility` permission for AppleScript keystrokes.
- Windows requirements for `cortex_gui_capture.py`:
  - Run in an interactive desktop session.
  - PowerShell (`powershell` or `pwsh`) available in `PATH`.
  - Screen capture uses .NET (`System.Drawing`) from PowerShell.
- Linux requirements for `cortex_gui_capture.py`:
  - Run in an interactive desktop session.
  - `xdotool` installed (for active window detection/activation).
  - One screenshot tool installed: `import` (ImageMagick) or `maim` or `grim`.
- In strict mode (default), capture fails fast if it cannot reach the target UI state and cannot open evidence in Cortex.
- For local troubleshooting only, set `CORTEX_ENABLE_UNVERIFIED_UI_NAV=1` to allow unverified UI navigation captures.
- Note: local captures still require `proof.upload_cmd` to publish artifacts as URLs before issue submission.
- Default proof upload backend is `github_attachment` (real `github.com/user-attachments/...` URLs).
- `github_attachment` requires `PROOF_GH_COOKIE` (or `PROOF_GH_COOKIE_FILE`).
- If `PROOF_GH_REPO_ID` is unset, uploader resolves repo id from `PROOF_GH_REPO` or the audited checkout remote.
- When `PROOF_GIST_BACKUP=1` (default in configs), uploader also creates a bracketed `[Gist backup](...)` link.

## How Dedup Works

### Local dedup (mandatory)

- Uses SQLite primary key on bug fingerprint.
- Uses reservation semantics (`reserved` -> `submitted`/`skipped`) to prevent duplicate processing when multiple agents run in parallel.

### External dedup (mandatory)

- Searches `https://github.com/PlatformNetwork/bounty-challenge/issues` through GitHub Search API.
- Checks by bug title and fingerprint prefix before any submission.

## Round-Robin And Valid/Invalid Accounting

- Issues are distributed in round-robin across `github1`..`github6`.
- Per repository, `valid = total_submitted - invalid_labeled`.
- Target is `25` valid issues per repository per day (configurable via `runtime.valid_target_per_repo`).
- If issues are labeled `invalid`, additional issues are automatically submitted until valid count reaches target.

## Proof Requirements

- Proof must reflect the real bug in the target app native GUI.
- Supported extensions are configured under `proof.allowed_image_extensions` and `proof.allowed_video_extensions`.
- Local files require `proof.upload_cmd` that returns a public URL.
- Default uploader path uses real GitHub attachments plus bracketed gist backup.
- Reference styles:
  - Screenshot format: <https://github.com/PlatformNetwork/bounty-challenge/issues/22537>
  - Video format: <https://github.com/PlatformNetwork/bounty-challenge/issues/22534>
  - Forbidden format: <https://github.com/PlatformNetwork/bounty-challenge/issues/22375#issuecomment-3983776205>

## Mutable YAML Without Restart

`bug_audit_system.py` checks config file modification time every cycle and hot-reloads automatically.
# platform
