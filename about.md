# About This Project

## Overview

**Platform** is an automated bug detection, auditing, and reporting system built to participate in the **PlatformNetwork bounty-challenge** — a decentralized bug bounty protocol where miners earn cryptocurrency rewards by discovering and reporting valid bugs in **Cortex IDE**, an AI-native desktop IDE.

The repository contains three major components working together as a pipeline:

---

## 1. Bug Audit System (Root — Python)

The core orchestrator (`bug_audit_system.py`) is a Python-based daily pipeline that automates the full lifecycle of finding, validating, deduplicating, and submitting bug reports to GitHub. It:

- **Reads mutable YAML configs** — hot-reloads prompts, detector commands, proof settings, and submission rules without restarting.
- **Clones or syncs a target codebase** — keeps a local checkout of Cortex IDE up to date via git fetch/pull before each audit cycle.
- **Runs detector scripts** — executes pluggable Python detector commands that analyze the codebase and output JSON findings (bugs) to stdout.
- **Deduplicates locally** — uses a persistent SQLite database to avoid re-submitting known bugs.
- **Deduplicates externally** — queries the GitHub Issues API on `PlatformNetwork/bounty-challenge` to check for existing reports by title and fingerprint.
- **Captures native GUI proof** — automatically takes screenshots or video recordings of Cortex IDE demonstrating each bug, using platform-specific capture (macOS AppleScript + screencapture, Windows PowerShell + .NET, Linux xdotool + screenshot tools).
- **Uploads proof artifacts** — publishes captured screenshots/videos as real GitHub user-attachment URLs with optional Gist backup.
- **Submits issues** — distributes bug reports in round-robin across 6 GitHub accounts, targeting 25 valid issues per account per day, and auto-compensates if issues are marked invalid.
- **Tracks state** — maintains daily state, summaries, and submission accounting in `.audit_state_*` directories.

### Detectors (Python scripts in `detectors/`)

Over 20 specialized detector scripts analyze different aspects of Cortex IDE:

- **Static triage detectors** — scan source code for wrong report targets, broken provider registrations, unreachable UI features, and incorrect system info.
- **GUI capture** — best-effort native screenshot/video capture across macOS, Windows, and Linux.
- **Shortcut/keybinding conflict detectors** — find conflicting keyboard shortcuts (Ctrl+K, Ctrl+T, Ctrl+Shift+R, Alt+F12, etc.).
- **UI behavior detectors** — find stuck loading states, unhandled events (Quick Chat, Quick Open, Quick Access), terminal tab nesting issues, icon mismatches (F5 debug icon), and extension panel bugs.
- **Event routing detectors** — detect events that are dispatched but never handled in the UI.
- **Proof upload utilities** — handle uploading captured proof files to GitHub attachments or other backends.

### Configuration

Multiple YAML config files at the root define different audit profiles for specific bug categories (shortcut conflicts, editor loading bugs, terminal issues, etc.). Configs specify which detectors to run, proof requirements, submission formatting, GitHub tokens, and runtime behavior.

---

## 2. Bounty Challenge (Rust/WASM — `bounty-challenge/`)

A `no_std` Rust crate compiled to WebAssembly that runs inside the PlatformNetwork validator runtime. It implements the on-chain logic for the bug bounty protocol:

- **Miner registration** — miners register their SS58 hotkey and GitHub username.
- **Issue evaluation and claiming** — validates that submitted GitHub issues are real, closed with `ide` + `valid` labels, and authored by the claiming miner.
- **Weight calculation** — computes reward weights based on valid issues, penalties for invalid submissions, and a leaderboard scoring system.
- **On-chain storage** — uses host-provided key/value storage for user balances, issue records, leaderboard data, and registration info.
- **API routes** — exposes endpoints for leaderboard, stats, registration, claiming, and issue syncing.
- **CLI tool** (`bins/bounty-cli/`) — an interactive TUI for miners to register, view leaderboard, check stats, and claim bounties.

An `AUDIT_REPORT.md` documents critical and major security issues discovered in this module (impersonation paths, missing authorization, unverified signatures, etc.).

---

## 3. Cortex IDE (Tauri v2 — `cortex-ide/`)

A local checkout of **Cortex IDE** — the target application being audited for bugs. It is an AI-powered desktop IDE built with:

- **Frontend**: SolidJS + TypeScript + Monaco Editor + xterm.js, featuring ~800 UI components across 50+ feature directories.
- **Backend**: Rust (Tauri v2) with 48 modules covering AI providers, LSP/DAP clients, Git (libgit2), terminal PTY management, extension system, agent orchestration, sandboxing, real-time collaboration, and more.
- **MCP Server**: A TypeScript/Node.js sidecar providing Model Context Protocol integration.

The IDE is in early alpha (not production-ready) and is the intentional target for the bug bounty program — miners test it and report bugs to earn rewards.

---

## How It All Fits Together

```
┌─────────────────────────────────────────────────────────┐
│  Cortex IDE (cortex-ide/)                               │
│  The target application — an AI-native IDE in alpha     │
│  Built with Tauri v2 + SolidJS + Rust                   │
└──────────────────────┬──────────────────────────────────┘
                       │ bugs found in
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Bug Audit System (root Python pipeline)                │
│  Detectors scan code → capture GUI proof → dedup →      │
│  submit issues to GitHub                                │
└──────────────────────┬──────────────────────────────────┘
                       │ issues submitted to
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Bounty Challenge (bounty-challenge/)                   │
│  On-chain WASM module validates issues, tracks miners,  │
│  calculates reward weights on PlatformNetwork           │
└─────────────────────────────────────────────────────────┘
```

1. **Cortex IDE** is the alpha software with bugs to find.
2. **Bug Audit System** automates finding those bugs, capturing evidence, and submitting them as GitHub issues.
3. **Bounty Challenge** runs on-chain to validate submitted issues and distribute rewards to miners who reported valid bugs.

---

## Tech Stack Summary

| Component           | Language        | Key Technologies                                                      |
| ------------------- | --------------- | --------------------------------------------------------------------- |
| Bug Audit System    | Python 3        | PyYAML, requests, SQLite, subprocess-based detectors                  |
| Detectors           | Python 3        | AppleScript, PowerShell, xdotool, mss, python-xlib                    |
| Bounty Challenge    | Rust (`no_std`) | WASM (wasm32-unknown-unknown), bincode, serde, platform-challenge-sdk |
| Bounty CLI          | Rust            | Interactive TUI for miners                                            |
| Cortex IDE Frontend | TypeScript      | SolidJS, Monaco Editor, xterm.js, Vite, Tailwind CSS v4               |
| Cortex IDE Backend  | Rust            | Tauri v2, Tokio, libgit2, rusqlite, reqwest                           |
| MCP Server          | TypeScript      | Node.js, @modelcontextprotocol/sdk                                    |
