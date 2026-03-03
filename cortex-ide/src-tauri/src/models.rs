//! Shared data models for the Cortex Desktop backend.
//!
//! This module provides serde-serializable structs used across IPC commands.
//! Core file system types (`FileEntry`, `FileMetadata`) live in `fs::types`
//! and are re-exported here for convenience.

use serde::{Deserialize, Serialize};

/// File content returned by `read_file`, including encoding metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FileContent {
    pub content: String,
    pub encoding: String,
    pub size: u64,
    pub path: String,
}

/// Project configuration stored alongside a project.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectConfig {
    pub name: String,
    pub root_path: String,
    #[serde(default)]
    pub excluded_paths: Vec<String>,
    #[serde(default)]
    pub settings: serde_json::Value,
}

/// Information about an opened or recent project.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectInfo {
    pub name: String,
    pub path: String,
    pub last_opened: u64,
}
