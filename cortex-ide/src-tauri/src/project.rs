//! Project Management — Open, track, and persist recent projects.
//!
//! Provides Tauri commands for:
//! - `open_project` — pick a folder via the native dialog and return project info
//! - `get_recent_projects` — load persisted recent-projects list from app data dir
//! - `save_recent_project` — add/update a project in the recent-projects list

use std::path::PathBuf;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::DialogExt;
use tracing::info;

use crate::models::ProjectInfo;

const MAX_RECENT_PROJECTS: usize = 20;
const RECENT_PROJECTS_FILE: &str = "recent_projects.json";

/// Persisted list of recent projects.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct RecentProjectsList {
    entries: Vec<ProjectInfo>,
}

/// Thread-safe state for the project manager.
pub struct ProjectState {
    recent: Mutex<Option<Vec<ProjectInfo>>>,
}

impl ProjectState {
    pub fn new() -> Self {
        Self {
            recent: Mutex::new(None),
        }
    }
}

impl Default for ProjectState {
    fn default() -> Self {
        Self::new()
    }
}

fn recent_projects_path(app: &AppHandle) -> Result<PathBuf, String> {
    let app_data_dir = match app.path().app_data_dir() {
        Ok(dir) => dir,
        Err(_) => dirs::config_dir()
            .ok_or_else(|| "Could not determine config directory".to_string())?
            .join("Cortex-desktop"),
    };
    Ok(app_data_dir.join(RECENT_PROJECTS_FILE))
}

fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Open a native folder-picker dialog and return project info for the
/// selected directory. Returns `None` if the user cancels the dialog.
#[tauri::command]
pub async fn open_project(app: AppHandle) -> Result<Option<ProjectInfo>, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();

    app.dialog().file().pick_folder(move |folder_path| {
        let result = folder_path.map(|fp| {
            let path_str = fp.to_string();
            let name = PathBuf::from(&path_str)
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| path_str.clone());

            ProjectInfo {
                name,
                path: path_str,
                last_opened: now_unix_secs(),
            }
        });
        let _ = tx.send(result);
    });

    let project_info = rx
        .await
        .map_err(|_| "Dialog channel closed unexpectedly".to_string())?;

    if let Some(ref info) = project_info {
        info!("Opened project: {} at {}", info.name, info.path);

        let state = app.state::<Arc<ProjectState>>();
        let mut cached = state.recent.lock();
        if let Some(ref mut list) = *cached {
            list.retain(|p| p.path != info.path);
            list.insert(0, info.clone());
            list.truncate(MAX_RECENT_PROJECTS);
        }
    }

    Ok(project_info)
}

/// Return the list of recently opened projects, loading from disk on first access.
#[tauri::command]
pub async fn get_recent_projects(app: AppHandle) -> Result<Vec<ProjectInfo>, String> {
    let state = app.state::<Arc<ProjectState>>();

    {
        let cached = state.recent.lock();
        if let Some(ref list) = *cached {
            return Ok(list.clone());
        }
    }

    let path = recent_projects_path(&app)?;

    let entries = match tokio::fs::read_to_string(&path).await {
        Ok(content) => {
            let data: RecentProjectsList = serde_json::from_str(&content).unwrap_or_default();
            data.entries
        }
        Err(_) => Vec::new(),
    };

    let mut cached = state.recent.lock();
    *cached = Some(entries.clone());

    Ok(entries)
}

/// Add or update a project in the recent-projects list and persist to disk.
#[tauri::command]
pub async fn save_recent_project(app: AppHandle, path: String) -> Result<(), String> {
    let name = PathBuf::from(&path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.clone());

    let entry = ProjectInfo {
        name,
        path: path.clone(),
        last_opened: now_unix_secs(),
    };

    let state = app.state::<Arc<ProjectState>>();

    let entries = {
        let mut cached = state.recent.lock();
        let list = cached.get_or_insert_with(Vec::new);
        list.retain(|p| p.path != path);
        list.insert(0, entry);
        list.truncate(MAX_RECENT_PROJECTS);
        list.clone()
    };

    let file_path = recent_projects_path(&app)?;

    if let Some(parent) = file_path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("Failed to create app data dir: {}", e))?;
    }

    let data = RecentProjectsList { entries };
    let json = serde_json::to_string_pretty(&data)
        .map_err(|e| format!("Failed to serialize recent projects: {}", e))?;

    tokio::fs::write(&file_path, json)
        .await
        .map_err(|e| format!("Failed to write recent projects: {}", e))?;

    info!("Saved recent project: {}", path);
    Ok(())
}
