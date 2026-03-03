/**
 * useFileSystem — Combines workspace store with Tauri IPC for filesystem CRUD
 *
 * Provides reactive filesystem operations with optimistic updates. Each action
 * immediately updates the Zustand store for instant UI feedback, then calls the
 * Tauri backend. On failure, the store is reverted to its previous state.
 *
 * @module hooks/useFileSystem
 *
 * @example
 * ```tsx
 * function FileEditor() {
 *   const fs = useFileSystem();
 *
 *   const handleSave = async () => {
 *     const activeId = fs.activeFileId();
 *     if (!activeId) return;
 *     const file = fs.getOpenFile(activeId);
 *     if (file) {
 *       await fs.saveFile(file.path, file.content);
 *     }
 *   };
 *
 *   return <button onClick={handleSave}>Save</button>;
 * }
 * ```
 */

import { useWorkspaceStore } from "@/store/workspace";
import type { FileState, WorkspaceState, WorkspaceActions } from "@/store/workspace";
import * as tauriApi from "@/lib/tauri-api";
import { getLanguageFromFilename } from "@/lib/file-icons";

// ============================================================================
// Types
// ============================================================================

/** Result of a filesystem operation */
export interface FileSystemResult<T = void> {
  success: boolean;
  data?: T;
  error?: string;
}

/** Return type of useFileSystem hook */
export interface UseFileSystemReturn {
  /** Accessor for the currently active file ID */
  activeFileId: () => string | null;
  /** Get an open file by its ID */
  getOpenFile: (fileId: string) => FileState | undefined;
  /** Get all open files */
  getOpenFiles: () => Record<string, FileState>;

  /** Open a file from disk into the editor (reads content via IPC) */
  openFile: (path: string) => Promise<FileSystemResult<FileState>>;
  /** Save a file's content to disk */
  saveFile: (path: string, content: string) => Promise<FileSystemResult>;
  /** Create a new file on disk and optionally open it */
  createFile: (path: string, openAfter?: boolean) => Promise<FileSystemResult>;
  /** Delete a file from disk (moves to trash) */
  deleteFile: (path: string) => Promise<FileSystemResult>;
  /** Rename a file on disk */
  renameFile: (oldPath: string, newPath: string) => Promise<FileSystemResult>;
  /** Create a new directory */
  createDirectory: (path: string) => Promise<FileSystemResult>;
}

// ============================================================================
// Helpers
// ============================================================================

function extractFileName(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/");
  return parts[parts.length - 1] || "untitled";
}

function generateFileId(path: string): string {
  return path.replace(/\\/g, "/");
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for filesystem operations with optimistic updates.
 *
 * Combines the workspace Zustand store with Tauri IPC calls. All mutations
 * follow an optimistic update pattern:
 * 1. Update the store immediately for instant UI feedback
 * 2. Perform the IPC call to the Rust backend
 * 3. Revert the store on failure
 */
export function useFileSystem(): UseFileSystemReturn {
  const activeFileId = useWorkspaceStore((s: WorkspaceState & WorkspaceActions) => s.activeFileId);
  const openFiles = useWorkspaceStore((s: WorkspaceState & WorkspaceActions) => s.openFiles);

  const getOpenFile = (fileId: string): FileState | undefined => {
    return useWorkspaceStore.getState().openFiles[fileId];
  };

  const getOpenFiles = (): Record<string, FileState> => {
    return openFiles();
  };

  const openFile = async (path: string): Promise<FileSystemResult<FileState>> => {
    const fileId = generateFileId(path);
    const existing = useWorkspaceStore.getState().openFiles[fileId];
    if (existing) {
      useWorkspaceStore.getState().setActiveFile(fileId);
      return { success: true, data: existing };
    }

    try {
      const content = await tauriApi.readFile(path);
      const fileName = extractFileName(path);
      const language = getLanguageFromFilename(fileName);

      const fileState: FileState = {
        id: fileId,
        path,
        name: fileName,
        content,
        language,
        modified: false,
      };

      useWorkspaceStore.getState().openFile(fileState);
      return { success: true, data: fileState };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to open file: ${message}` };
    }
  };

  const saveFile = async (path: string, content: string): Promise<FileSystemResult> => {
    const fileId = generateFileId(path);
    const store = useWorkspaceStore.getState();
    const file = store.openFiles[fileId];

    if (file) {
      store.setFileModified(fileId, false);
    }

    try {
      await tauriApi.writeFile(path, content);
      return { success: true };
    } catch (err) {
      if (file) {
        useWorkspaceStore.getState().setFileModified(fileId, true);
      }
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to save file: ${message}` };
    }
  };

  const createFileAction = async (
    path: string,
    openAfter: boolean = true
  ): Promise<FileSystemResult> => {
    try {
      await tauriApi.createFile(path);

      if (openAfter) {
        const fileName = extractFileName(path);
        const language = getLanguageFromFilename(fileName);
        const fileId = generateFileId(path);

        const fileState: FileState = {
          id: fileId,
          path,
          name: fileName,
          content: "",
          language,
          modified: false,
        };

        useWorkspaceStore.getState().openFile(fileState);
      }

      return { success: true };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to create file: ${message}` };
    }
  };

  const deleteFileAction = async (path: string): Promise<FileSystemResult> => {
    const fileId = generateFileId(path);
    const store = useWorkspaceStore.getState();
    const file = store.openFiles[fileId];

    if (file) {
      store.closeFile(fileId);
    }

    try {
      await tauriApi.trash(path);
      return { success: true };
    } catch (err) {
      if (file) {
        useWorkspaceStore.getState().openFile(file);
      }
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to delete file: ${message}` };
    }
  };

  const renameFileAction = async (
    oldPath: string,
    newPath: string
  ): Promise<FileSystemResult> => {
    const oldFileId = generateFileId(oldPath);
    const store = useWorkspaceStore.getState();
    const oldFile = store.openFiles[oldFileId];

    if (oldFile) {
      store.closeFile(oldFileId);

      const newFileName = extractFileName(newPath);
      const newLanguage = getLanguageFromFilename(newFileName);
      const newFileId = generateFileId(newPath);

      const newFileState: FileState = {
        ...oldFile,
        id: newFileId,
        path: newPath,
        name: newFileName,
        language: newLanguage,
      };

      store.openFile(newFileState);
    }

    try {
      await tauriApi.rename(oldPath, newPath);
      return { success: true };
    } catch (err) {
      if (oldFile) {
        const currentStore = useWorkspaceStore.getState();
        const newFileId = generateFileId(newPath);
        currentStore.closeFile(newFileId);
        currentStore.openFile(oldFile);
      }
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to rename file: ${message}` };
    }
  };

  const createDirectoryAction = async (path: string): Promise<FileSystemResult> => {
    try {
      await tauriApi.createDirectory(path);
      return { success: true };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return { success: false, error: `Failed to create directory: ${message}` };
    }
  };

  return {
    activeFileId,
    getOpenFile,
    getOpenFiles,
    openFile,
    saveFile,
    createFile: createFileAction,
    deleteFile: deleteFileAction,
    renameFile: renameFileAction,
    createDirectory: createDirectoryAction,
  };
}
