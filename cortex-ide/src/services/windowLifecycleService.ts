/**
 * Window Lifecycle Service
 *
 * Centralized service for managing window lifecycle events including:
 * - Dirty file tracking (accessible outside SolidJS reactive system)
 * - Cleanup orchestration before window close
 * - Pause/resume of expensive operations on visibility change
 * - WebSocket teardown coordination
 * - Editor state snapshot persistence
 *
 * This service exists as a plain module (not a SolidJS context) so that
 * `beforeunload` and `visibilitychange` handlers can access it synchronously
 * without depending on the reactive system being alive.
 */

import { invoke } from "@tauri-apps/api/core";

interface CleanupCallbacks {
  getActiveSessionId: () => string | null;
  getDirtyFileIds: () => string[];
  getOpenFilePaths: () => string[];
  getActiveFilePath: () => string | null;
}

let dirtyFilesAccessor: (() => boolean) | null = null;
let cleanupCallbacks: CleanupCallbacks | null = null;
let isPaused = false;
let isCleaningUp = false;

export const windowLifecycleService = {
  setDirtyFilesAccessor(accessor: () => boolean): void {
    dirtyFilesAccessor = accessor;
  },

  setCleanupCallbacks(callbacks: CleanupCallbacks): void {
    cleanupCallbacks = callbacks;
  },

  hasDirtyFiles(): boolean {
    try {
      return dirtyFilesAccessor ? dirtyFilesAccessor() : false;
    } catch {
      return false;
    }
  },

  performSyncCleanup(): void {
    if (isCleaningUp) return;
    isCleaningUp = true;

    try {
      const sessionId = cleanupCallbacks?.getActiveSessionId();
      if (sessionId) {
        invoke("cortex_cancel", { sessionId }).catch(() => {});
      }
      invoke("agent_cleanup").catch(() => {});
    } catch {
      // Best-effort
    } finally {
      isCleaningUp = false;
    }
  },

  notifyClosing(): void {
    window.dispatchEvent(new CustomEvent("window:closing"));
  },

  pauseExpensiveOperations(): void {
    if (isPaused) return;
    isPaused = true;
    window.dispatchEvent(new CustomEvent("window:visibility-pause"));
  },

  resumeExpensiveOperations(): void {
    if (!isPaused) return;
    isPaused = false;
    window.dispatchEvent(new CustomEvent("window:visibility-resume"));
  },

  get paused(): boolean {
    return isPaused;
  },

  saveEditorStateSnapshot(): void {
    if (!cleanupCallbacks) return;

    try {
      const snapshot = {
        openFiles: cleanupCallbacks.getOpenFilePaths(),
        activeFile: cleanupCallbacks.getActiveFilePath(),
        dirtyFiles: cleanupCallbacks.getDirtyFileIds(),
        timestamp: Date.now(),
      };
      localStorage.setItem("cortex_editor_state_snapshot", JSON.stringify(snapshot));
    } catch {
      // Storage quota exceeded or other error
    }
  },
};
