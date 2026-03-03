/**
 * useWindowEvents - Tauri window lifecycle event handlers
 *
 * Handles:
 * - Close requested: prompts to save dirty files before closing
 * - beforeunload: warns about unsaved changes, triggers sync cleanup
 * - Focus/Blur: dispatches custom events for subsystems (file watchers, etc.)
 * - visibilitychange: pauses/resumes expensive operations (terminal rendering,
 *   file watchers) when the app is hidden, saves editor state snapshot
 * - Force close (Cmd+Q / Alt+F4): fires cleanup commands to backend
 *
 * Must be called inside a component wrapped by OptimizedProviders
 * (requires EditorContext and NotificationsContext).
 */

import { onMount, onCleanup } from "solid-js";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { useEditor } from "@/context/EditorContext";
import { useNotifications } from "@/context/NotificationsContext";
import { useSDK } from "@/context/SDKContext";
import { windowLifecycleService } from "@/services/windowLifecycleService";

export function useWindowEvents(): void {
  const editor = useEditor();
  const notifications = useNotifications();

  // Resolve SDK context synchronously within the component owner.
  // useSDK() is safe here because OptimizedProviders mounts SDKProvider
  // above AppContent where this hook is called.
  let sdk: ReturnType<typeof useSDK> | null = null;
  try {
    sdk = useSDK();
  } catch {
    // Not inside SDKProvider (e.g. auxiliary windows) — leave null
  }

  onMount(() => {
    const appWindow = getCurrentWebviewWindow();
    const cleanups: (() => void)[] = [];

    // ================================================================
    // Register accessors with the lifecycle service so beforeunload
    // (which runs outside the reactive system) can read state.
    // ================================================================

    windowLifecycleService.setDirtyFilesAccessor(
      () => editor.selectors.hasModifiedFiles(),
    );

    windowLifecycleService.setCleanupCallbacks({
      getActiveSessionId: () => sdk?.state.currentSession?.id ?? null,
      getDirtyFileIds: () => editor.selectors.modifiedFileIds(),
      getOpenFilePaths: () =>
        editor.state.openFiles.map((f) => f.path),
      getActiveFilePath: () =>
        editor.state.openFiles.find((f) => f.id === editor.state.activeFileId)?.path ?? null,
    });

    // ================================================================
    // Tauri close-requested handler (native close button, Cmd+W)
    // ================================================================

    appWindow.onCloseRequested(async (event) => {
      if (!editor.selectors.hasModifiedFiles()) {
        windowLifecycleService.saveEditorStateSnapshot();
        windowLifecycleService.notifyClosing();
        windowLifecycleService.performSyncCleanup();
        return;
      }

      event.preventDefault();

      const modifiedCount = editor.selectors.modifiedFileIds().length;
      const label = modifiedCount === 1 ? "1 unsaved file" : `${modifiedCount} unsaved files`;

      notifications.notify({
        type: "warning",
        title: "Unsaved Changes",
        message: `You have ${label}. Save before closing?`,
        toast: true,
        duration: 0,
        actions: [
          { id: "save-close", label: "Save All & Close", variant: "primary" },
          { id: "discard", label: "Don't Save", variant: "danger" },
          { id: "cancel", label: "Cancel" },
        ],
      });

      const handler = (e: Event) => {
        const detail = (e as CustomEvent<{ notificationId: string; actionId: string }>).detail;
        if (!detail) return;
        const { actionId } = detail;

        if (actionId === "save-close") {
          window.dispatchEvent(new CustomEvent("file:save-all"));
          windowLifecycleService.saveEditorStateSnapshot();
          windowLifecycleService.notifyClosing();
          windowLifecycleService.performSyncCleanup();
          setTimeout(() => appWindow.close(), 200);
        } else if (actionId === "discard") {
          windowLifecycleService.notifyClosing();
          windowLifecycleService.performSyncCleanup();
          appWindow.destroy();
        }
        window.removeEventListener("notification:action", handler);
      };

      window.addEventListener("notification:action", handler);
      cleanups.push(() => window.removeEventListener("notification:action", handler));
    }).then((unlisten) => {
      cleanups.push(unlisten);
    }).catch((err) => {
      console.error("[useWindowEvents] Failed to listen to close-requested:", err);
    });

    // ================================================================
    // beforeunload — last-resort warning for force close (Cmd+Q / Alt+F4)
    // ================================================================

    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      windowLifecycleService.saveEditorStateSnapshot();
      windowLifecycleService.notifyClosing();
      windowLifecycleService.performSyncCleanup();

      if (windowLifecycleService.hasDirtyFiles()) {
        e.preventDefault();
        // Returning a string is required by some browsers to show the dialog.
        // Tauri intercepts the close via onCloseRequested first, so this is
        // mainly a fallback for edge-cases.
        return "";
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    cleanups.push(() => window.removeEventListener("beforeunload", handleBeforeUnload));

    // ================================================================
    // visibilitychange — pause/resume expensive operations
    // ================================================================

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        windowLifecycleService.pauseExpensiveOperations();
        windowLifecycleService.saveEditorStateSnapshot();
      } else {
        windowLifecycleService.resumeExpensiveOperations();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange, { passive: true });
    cleanups.push(() => document.removeEventListener("visibilitychange", handleVisibilityChange));

    // ================================================================
    // Focus / Blur
    // ================================================================

    const handleFocus = () => {
      window.dispatchEvent(new CustomEvent("window:focus"));
    };
    const handleBlur = () => {
      window.dispatchEvent(new CustomEvent("window:blur"));
    };

    window.addEventListener("focus", handleFocus, { passive: true });
    window.addEventListener("blur", handleBlur, { passive: true });
    cleanups.push(() => {
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("blur", handleBlur);
    });

    onCleanup(() => {
      cleanups.forEach((fn) => fn());
    });
  });
}
