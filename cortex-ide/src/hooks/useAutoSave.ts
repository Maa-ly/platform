/**
 * useAutoSave - Automatic file saving based on user settings
 *
 * Implements three auto-save strategies from FilesSettings:
 * - "afterDelay": saves dirty files after a configurable delay (ms)
 * - "onFocusChange": saves dirty files when the window loses focus
 * - "onWindowChange": saves dirty files when the document becomes hidden
 *
 * Must be called inside a component wrapped by OptimizedProviders
 * (requires EditorContext and SettingsContext).
 */

import { createEffect, onCleanup } from "solid-js";
import { useEditor } from "@/context/EditorContext";
import { useFilesSettings } from "@/context/SettingsContext";

export function useAutoSave(): void {
  const editor = useEditor();
  const { settings: filesSettings } = useFilesSettings();

  let delayTimer: ReturnType<typeof setTimeout> | null = null;

  const saveAllDirty = () => {
    window.dispatchEvent(new CustomEvent("file:save-all"));
  };

  const clearDelayTimer = () => {
    if (delayTimer !== null) {
      clearTimeout(delayTimer);
      delayTimer = null;
    }
  };

  createEffect(() => {
    const mode = filesSettings().autoSave;
    const delay = filesSettings().autoSaveDelay;
    const hasDirty = editor.selectors.hasModifiedFiles();

    clearDelayTimer();

    if (mode === "afterDelay" && hasDirty) {
      delayTimer = setTimeout(saveAllDirty, Math.max(delay, 200));
    }
  });

  const handleBlur = () => {
    if (filesSettings().autoSave === "onFocusChange" && editor.selectors.hasModifiedFiles()) {
      saveAllDirty();
    }
  };

  const handleVisibilityChange = () => {
    if (
      document.visibilityState === "hidden" &&
      filesSettings().autoSave === "onWindowChange" &&
      editor.selectors.hasModifiedFiles()
    ) {
      saveAllDirty();
    }
  };

  window.addEventListener("blur", handleBlur, { passive: true });
  document.addEventListener("visibilitychange", handleVisibilityChange, { passive: true });

  onCleanup(() => {
    clearDelayTimer();
    window.removeEventListener("blur", handleBlur);
    document.removeEventListener("visibilitychange", handleVisibilityChange);
  });
}
