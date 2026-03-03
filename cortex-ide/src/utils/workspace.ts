/**
 * Workspace utilities for consistent project path handling
 * 
 * This module provides a unified way to access the current project path
 * from localStorage, handling the multiple key names that have been used
 * historically (projectPath and cortex_current_project).
 */

import { safeGetItem, safeSetItem, safeRemoveItem } from "./safeStorage";

const PROJECT_PATH_KEY = "projectPath";
const cortex_PROJECT_KEY = "cortex_current_project";

/**
 * Get the current project path from localStorage.
 * Checks both "projectPath" and "cortex_current_project" keys for compatibility.
 * 
 * @returns The current project path, or empty string if not set
 */
export function getProjectPath(): string {
  return (
    safeGetItem(PROJECT_PATH_KEY) ||
    safeGetItem(cortex_PROJECT_KEY) ||
    ""
  );
}

/**
 * Set the current project path in localStorage.
 * Sets both keys for compatibility with existing code.
 * 
 * @param path - The project path to set
 */
export function setProjectPath(path: string): void {
  safeSetItem(PROJECT_PATH_KEY, path);
  safeSetItem(cortex_PROJECT_KEY, path);
}

/**
 * Clear the current project path from localStorage.
 * Removes both keys for full cleanup.
 */
export function clearProjectPath(): void {
  safeRemoveItem(PROJECT_PATH_KEY);
  safeRemoveItem(cortex_PROJECT_KEY);
}
