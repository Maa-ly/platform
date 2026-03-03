/**
 * Tauri API — Typed wrappers for all Tauri IPC invoke calls
 *
 * Provides a fully typed interface to the Rust backend commands exposed via
 * Tauri's IPC bridge. Each function maps directly to a `#[tauri::command]`
 * handler in the Rust backend.
 *
 * @module lib/tauri-api
 */

import { invoke } from "@tauri-apps/api/core";

// ============================================================================
// Types
// ============================================================================

/** File entry returned by directory listing / file tree commands */
export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  is_file: boolean;
  is_symlink: boolean;
  size: number;
  modified: number;
  extension: string | null;
  children?: FileEntry[];
}

/** Options for file tree retrieval */
export interface FileTreeOptions {
  depth?: number;
  showHidden?: boolean;
  includeIgnored?: boolean;
}

/** Workspace file data from backend */
export interface WorkspaceFileData {
  folders: Array<{
    path: string;
    name?: string;
    color?: string;
    icon?: string;
  }>;
  settings: Record<string, unknown>;
}

/** Workspace state data for persistence */
export interface WorkspaceStateData {
  openEditors: string[];
  activeEditor: string | null;
  layout: Record<string, unknown> | null;
  scrollPositions: Record<string, number>;
}

/** Recent workspace entry from backend */
export interface RecentWorkspaceEntry {
  id: string;
  path: string;
  name: string;
  lastOpened: number;
  isWorkspaceFile: boolean;
  folderCount: number;
}

// ============================================================================
// File Read Operations
// ============================================================================

/** Read a file's content as a UTF-8 string */
export async function readFile(path: string): Promise<string> {
  return invoke<string>("fs_read_file", { path });
}

/** Read a file's content as base64-encoded binary */
export async function readFileBinary(path: string): Promise<string> {
  return invoke<string>("fs_read_file_binary", { path });
}

// ============================================================================
// File Write Operations
// ============================================================================

/** Write UTF-8 string content to a file (creates parent directories if needed) */
export async function writeFile(path: string, content: string): Promise<void> {
  return invoke("fs_write_file", { path, content });
}

/** Write base64-encoded binary content to a file */
export async function writeFileBinary(path: string, content: string): Promise<void> {
  return invoke("fs_write_file_binary", { path, content });
}

// ============================================================================
// File Create / Delete Operations
// ============================================================================

/** Create a new empty file (fails if file already exists) */
export async function createFile(path: string): Promise<void> {
  return invoke("fs_create_file", { path });
}

/** Delete a file */
export async function deleteFile(path: string): Promise<void> {
  return invoke("fs_delete_file", { path });
}

/** Move a file or directory to the system trash */
export async function trash(path: string): Promise<void> {
  return invoke("fs_trash", { path });
}

// ============================================================================
// File Copy / Move / Rename Operations
// ============================================================================

/** Rename a file or directory */
export async function rename(oldPath: string, newPath: string): Promise<void> {
  return invoke("fs_rename", { oldPath, newPath });
}

/** Copy a file */
export async function copyFile(source: string, destination: string): Promise<void> {
  return invoke("fs_copy_file", { source, destination });
}

/** Move a file or directory (works across filesystems) */
export async function moveFile(source: string, destination: string): Promise<void> {
  return invoke("fs_move", { source, destination });
}

// ============================================================================
// Directory Operations
// ============================================================================

/** Create a new directory (creates parent directories if needed) */
export async function createDirectory(path: string): Promise<void> {
  return invoke("fs_create_directory", { path });
}

/** Delete a directory */
export async function deleteDirectory(path: string, recursive: boolean = false): Promise<void> {
  return invoke("fs_delete_directory", { path, recursive });
}

/** Get a file tree for a directory */
export async function getFileTree(
  path: string,
  options: FileTreeOptions = {}
): Promise<FileEntry> {
  return invoke<FileEntry>("fs_get_file_tree", {
    path,
    depth: options.depth ?? 3,
    showHidden: options.showHidden ?? false,
    includeIgnored: options.includeIgnored ?? false,
  });
}

/** Get a shallow file tree (single level) for a directory */
export async function getFileTreeShallow(
  path: string,
  options: Omit<FileTreeOptions, "depth"> = {}
): Promise<FileEntry> {
  return invoke<FileEntry>("fs_get_file_tree_shallow", {
    path,
    showHidden: options.showHidden ?? false,
    includeIgnored: options.includeIgnored ?? false,
  });
}

// ============================================================================
// Shell / Explorer Operations
// ============================================================================

/** Reveal a file or directory in the system file manager */
export async function revealInExplorer(path: string): Promise<void> {
  return invoke("fs_reveal_in_explorer", { path });
}

/** Open a file with the system default application */
export async function openWithDefault(path: string): Promise<void> {
  return invoke("fs_open_with_default", { path });
}

// ============================================================================
// Workspace Commands
// ============================================================================

/** Save workspace file via backend (atomic write) */
export async function saveWorkspaceFile(
  filePath: string,
  data: WorkspaceFileData
): Promise<void> {
  return invoke("save_workspace_file", { filePath, data });
}

/** Load workspace file via backend */
export async function loadWorkspaceFile(filePath: string): Promise<WorkspaceFileData> {
  return invoke<WorkspaceFileData>("load_workspace_file", { filePath });
}

/** Import a VS Code .code-workspace file via backend */
export async function importCodeWorkspace(filePath: string): Promise<WorkspaceFileData> {
  return invoke<WorkspaceFileData>("import_code_workspace", { filePath });
}

/** Save workspace editor state to backend */
export async function saveWorkspaceState(
  workspaceId: string,
  state: WorkspaceStateData
): Promise<void> {
  return invoke("save_workspace_state", { workspaceId, state });
}

/** Restore workspace editor state from backend */
export async function restoreWorkspaceState(
  workspaceId: string
): Promise<WorkspaceStateData | null> {
  return invoke<WorkspaceStateData | null>("restore_workspace_state", { workspaceId });
}

/** Get recent workspaces from backend */
export async function getRecentWorkspaces(): Promise<RecentWorkspaceEntry[]> {
  return invoke<RecentWorkspaceEntry[]>("workspace_get_recent");
}

/** Save recent workspaces to backend */
export async function saveRecentWorkspaces(entries: RecentWorkspaceEntry[]): Promise<void> {
  return invoke("workspace_save_recent", { entries });
}

/** Copy a file/directory across workspace folders */
export async function crossFolderCopy(
  source: string,
  destination: string,
  roots: string[]
): Promise<void> {
  return invoke("workspace_cross_folder_copy", { source, destination, roots });
}

/** Move a file/directory across workspace folders */
export async function crossFolderMove(
  source: string,
  destination: string,
  roots: string[]
): Promise<void> {
  return invoke("workspace_cross_folder_move", { source, destination, roots });
}

/** Check if a workspace path is trusted */
export async function checkWorkspaceTrust(
  workspacePath: string
): Promise<{ isTrusted: boolean; path: string }> {
  return invoke<{ isTrusted: boolean; path: string }>("workspace_trust_check", {
    workspacePath,
  });
}

/** Set trust state for a workspace path */
export async function setWorkspaceTrust(
  workspacePath: string,
  trusted: boolean
): Promise<void> {
  return invoke("workspace_trust_set", { workspacePath, trusted });
}
