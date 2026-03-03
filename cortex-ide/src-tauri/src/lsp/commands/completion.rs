//! Completion commands
//!
//! Commands for code completion.

use tauri::State;

use crate::lsp::types::{CompletionItem, CompletionParams, CompletionResult};

use super::state::LspState;

/// Request completions
#[tauri::command]
pub async fn lsp_completion(
    server_id: String,
    params: CompletionParams,
    state: State<'_, LspState>,
) -> Result<CompletionResult, String> {
    let client = {
        let clients = state.clients.lock();
        clients
            .get(&server_id)
            .cloned()
            .ok_or_else(|| format!("Server not found: {}", server_id))?
    };

    client
        .completion(params)
        .await
        .map_err(|e| format!("Completion request failed: {}", e))
}

/// Resolve a completion item (get additional details like documentation)
#[tauri::command]
pub async fn lsp_completion_resolve(
    server_id: String,
    item: CompletionItem,
    state: State<'_, LspState>,
) -> Result<CompletionItem, String> {
    let client = {
        let clients = state.clients.lock();
        clients
            .get(&server_id)
            .cloned()
            .ok_or_else(|| format!("Server not found: {}", server_id))?
    };

    client
        .completion_resolve(item)
        .await
        .map_err(|e| format!("Completion resolve failed: {}", e))
}
