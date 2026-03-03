//! Command Registry — Central reference for all Tauri IPC commands.
//!
//! Cortex Desktop uses a macro-chain pattern defined in `app/mod.rs` to
//! register commands with `tauri::generate_handler![]`. Each feature area
//! has its own `*_commands.rs` file under `app/` that contributes commands
//! to the chain via the `cortex_commands!` macro.
//!
//! ## Command Groups
//!
//! | Group | File | Description |
//! |-------|------|-------------|
//! | AI | `app/ai_commands.rs` | AI providers, agents, sessions, completions |
//! | Collab | `app/collab_commands.rs` | Real-time collaboration (CRDT, WebSocket) |
//! | Editor | `app/editor_commands.rs` | Folding, symbols, refactoring, snippets |
//! | Extension | `app/extension_commands.rs` | Extension lifecycle, marketplace, WASM/Node host |
//! | Git | `app/git_commands.rs` | Git operations (branch, commit, diff, merge, etc.) |
//! | I18n | `app/i18n_commands.rs` | Internationalization and locale detection |
//! | Misc | `app/misc_commands.rs` | Server, notifications, updates, MCP, window, WSL |
//! | Notebook | `app/notebook_commands.rs` | Jupyter-style notebook kernels |
//! | Remote | `app/remote_commands.rs` | SSH remote development |
//! | Settings | `app/settings_commands.rs` | User/workspace settings, profiles, sync |
//! | Terminal | `app/terminal_commands.rs` | PTY terminal management |
//! | Workspace | `app/workspace_commands.rs` | FS ops, search, testing, tasks, projects |
//!
//! ## Adding New Commands
//!
//! 1. Define `#[tauri::command]` functions in the appropriate module.
//! 2. Add the command paths to the matching `*_commands.rs` macro.
//! 3. If creating a new group, add a new `*_commands.rs` file and insert
//!    a chain step in `app/mod.rs`.
//!
//! ## Re-exports
//!
//! This module re-exports key command-bearing modules for discoverability.
