/**
 * Global Error Handler
 *
 * Catches unhandled promise rejections and uncaught errors,
 * logs them to the Output panel "Errors" channel, and shows
 * error notifications to the user.
 *
 * Deduplicates rapid-fire identical errors within a 3-second window.
 */

const ERROR_CHANNEL = "Errors";
const DEDUP_WINDOW_MS = 3000;

interface ErrorHandlerDeps {
  notify: (options: {
    type: "error";
    message: string;
    title?: string;
    source?: string;
  }) => void;
  appendLine: (channel: string, text: string, options?: { severity?: "error" }) => void;
}

export function initGlobalErrorHandler(deps: ErrorHandlerDeps): () => void {
  const recentErrors = new Map<string, number>();

  const isDuplicate = (key: string): boolean => {
    const now = Date.now();
    const last = recentErrors.get(key);
    if (last && now - last < DEDUP_WINDOW_MS) {
      return true;
    }
    recentErrors.set(key, now);

    if (recentErrors.size > 50) {
      const cutoff = now - DEDUP_WINDOW_MS;
      for (const [k, v] of recentErrors) {
        if (v < cutoff) recentErrors.delete(k);
      }
    }
    return false;
  };

  const formatTimestamp = (): string => {
    return new Date().toISOString().slice(11, 23);
  };

  const handleError = (event: ErrorEvent): void => {
    const message = event.message || "Unknown error";
    const source = event.filename
      ? `${event.filename}:${event.lineno}:${event.colno}`
      : undefined;

    if (isDuplicate(message)) return;

    const timestamp = formatTimestamp();
    deps.appendLine(ERROR_CHANNEL, `[${timestamp}] Uncaught Error: ${message}`, { severity: "error" });
    if (source) {
      deps.appendLine(ERROR_CHANNEL, `  at ${source}`, { severity: "error" });
    }
    if (event.error?.stack) {
      deps.appendLine(ERROR_CHANNEL, `  ${event.error.stack}`, { severity: "error" });
    }

    deps.notify({
      type: "error",
      title: "Uncaught Error",
      message,
      source: source ?? "window",
    });
  };

  const handleRejection = (event: PromiseRejectionEvent): void => {
    const reason = event.reason;
    const message =
      reason instanceof Error
        ? reason.message
        : typeof reason === "string"
          ? reason
          : "Unhandled promise rejection";

    if (isDuplicate(message)) return;

    const timestamp = formatTimestamp();
    deps.appendLine(ERROR_CHANNEL, `[${timestamp}] Unhandled Rejection: ${message}`, { severity: "error" });
    if (reason instanceof Error && reason.stack) {
      deps.appendLine(ERROR_CHANNEL, `  ${reason.stack}`, { severity: "error" });
    }

    deps.notify({
      type: "error",
      title: "Unhandled Rejection",
      message,
      source: "promise",
    });
  };

  window.addEventListener("error", handleError);
  window.addEventListener("unhandledrejection", handleRejection);

  return () => {
    window.removeEventListener("error", handleError);
    window.removeEventListener("unhandledrejection", handleRejection);
    recentErrors.clear();
  };
}
