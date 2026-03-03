/**
 * Extension API — Sandboxed API surface for JavaScript/TypeScript extensions
 * running in the extension host worker.
 *
 * Mirrors the capabilities defined in the WIT interface
 * (src-tauri/src/extensions/wit/cortex.wit) for WASM extensions,
 * providing the same contract for JS/TS extensions executing in a
 * Web Worker sandbox.
 */

// ============================================================================
// Core Types
// ============================================================================

export interface Disposable {
  dispose(): void;
}

export interface Position {
  line: number;
  character: number;
}

export interface Range {
  start: Position;
  end: Position;
}

export interface TextEdit {
  range: Range;
  newText: string;
}

// ============================================================================
// Editor Types
// ============================================================================

export interface EditorInfo {
  uri: string;
  languageId: string;
  version: number;
  isDirty: boolean;
}

export interface Decoration {
  range: Range;
  hoverMessage: string;
  cssClass: string;
}

// ============================================================================
// Workspace Types
// ============================================================================

export interface FileStat {
  size: number;
  isDir: boolean;
  isFile: boolean;
  isSymlink: boolean;
  created: number;
  modified: number;
  accessed: number;
}

// ============================================================================
// UI Types
// ============================================================================

export enum MessageLevel {
  Info = 0,
  Warning = 1,
  Error = 2,
}

export interface QuickPickItem {
  label: string;
  description: string;
  detail: string;
}

export interface OutputChannel {
  readonly name: string;
  append(text: string): Promise<void>;
  dispose(): void;
}

export interface StatusBarItem {
  readonly id: string;
  update(text: string): Promise<void>;
  dispose(): void;
}

// ============================================================================
// Theme Types
// ============================================================================

export interface ThemeRegistration {
  id: string;
  label: string;
  path: string;
  uiTheme: string;
}

// ============================================================================
// Language Types
// ============================================================================

export enum DiagnosticSeverity {
  Error = 0,
  Warning = 1,
  Information = 2,
  Hint = 3,
}

export interface Diagnostic {
  range: Range;
  message: string;
  severity: DiagnosticSeverity;
  source: string;
  code: string;
}

export interface LanguageRegistration {
  id: string;
  name: string;
  extensions: string[];
  aliases?: string[];
  mimeTypes?: string[];
}

// ============================================================================
// Terminal Types
// ============================================================================

export interface TerminalHandle {
  readonly id: string;
  readonly name: string;
  sendText(text: string): Promise<void>;
  dispose(): Promise<void>;
}

// ============================================================================
// Log Level
// ============================================================================

export enum LogLevel {
  Trace = 0,
  Debug = 1,
  Info = 2,
  Warning = 3,
  Error = 4,
}

// ============================================================================
// API Sub-interfaces
// ============================================================================

export interface CommandsAPI {
  registerCommand(commandId: string, handler: (...args: unknown[]) => unknown): Disposable;
  executeCommand<T = unknown>(commandId: string, ...args: unknown[]): Promise<T>;
}

export interface EventsAPI {
  emit(eventName: string, data: unknown): void;
  on(eventName: string, handler: (data: unknown) => void): Disposable;
}

export interface WorkspaceAPI {
  readFile(path: string): Promise<string>;
  writeFile(path: string, content: string): Promise<void>;
  deleteFile(path: string): Promise<void>;
  listFiles(path: string, pattern?: string): Promise<string[]>;
  findFiles(pattern: string): Promise<string[]>;
  statFile(path: string): Promise<FileStat>;
  getConfiguration(section: string): Promise<unknown>;
  getWorkspacePath(): Promise<string | null>;
  getWorkspaceFolders(): Promise<string[]>;
  setConfiguration(section: string, value: unknown): Promise<void>;
}

export interface WindowAPI {
  showMessage(level: MessageLevel, message: string): void;
  showQuickPick(items: QuickPickItem[], placeholder?: string): Promise<string | null>;
  showInputBox(prompt: string, defaultValue?: string): Promise<string | null>;
  createOutputChannel(name: string): OutputChannel;
  setStatusBarMessage(text: string, timeoutMs?: number): void;
  registerTreeView(id: string, title: string): Promise<Disposable>;
  createWebviewPanel(viewType: string, title: string, options?: Record<string, unknown>): Promise<string>;
  registerStatusBarItem(id: string, text: string, alignment: number, priority: number): StatusBarItem;
}

export interface EditorAPI {
  getActiveEditor(): Promise<EditorInfo | null>;
  getSelection(): Promise<string | null>;
  insertText(text: string): Promise<void>;
  replaceSelection(text: string): Promise<void>;
  getDocumentText(uri: string): Promise<string>;
  openDocument(uri: string): Promise<string>;
  saveDocument(uri: string): Promise<void>;
  applyEdits(uri: string, edits: TextEdit[]): Promise<string>;
  setDecorations(uri: string, decorationType: string, rangesJson: string): Promise<void>;
}

export interface LanguagesAPI {
  registerLanguage(languageId: string, fileExtensions: string[]): void;
  registerCompletionProvider(selectorJson: string, providerId: string): Promise<Disposable>;
  registerHoverProvider(selectorJson: string, providerId: string): Promise<Disposable>;
  registerDefinitionProvider(selectorJson: string, providerId: string): Promise<Disposable>;
  registerCodeActionsProvider(selectorJson: string, providerId: string): Promise<Disposable>;
  registerDiagnostics(uri: string, diagnostics: Diagnostic[]): void;
}

export interface TerminalAPI {
  createTerminal(name: string, options?: Record<string, unknown>): Promise<TerminalHandle>;
}

export interface ScmAPI {
  registerScmProvider(id: string, label: string): Promise<Disposable>;
}

export interface DebugAPI {
  registerDebugAdapter(typeName: string): Promise<Disposable>;
}

// ============================================================================
// Main API Interface
// ============================================================================

export interface CortexExtensionAPI {
  readonly extensionId: string;
  readonly commands: CommandsAPI;
  readonly events: EventsAPI;
  readonly workspace: WorkspaceAPI;
  readonly window: WindowAPI;
  readonly editor: EditorAPI;
  readonly languages: LanguagesAPI;
  readonly terminal: TerminalAPI;
  readonly scm: ScmAPI;
  readonly debug: DebugAPI;
  log(level: LogLevel, message: string): void;
  getConfig(key: string): Promise<string | null>;
  registerCommand(commandId: string, handler: (...args: unknown[]) => unknown): Disposable;
  registerTheme(theme: ThemeRegistration): Disposable;
  registerLanguage(config: LanguageRegistration): void;
}

// ============================================================================
// Host Communication Abstraction
// ============================================================================

export type HostCallFn = (method: string, args?: unknown) => Promise<unknown>;

export type RegisterExportFn = (
  name: string,
  handler: (...args: unknown[]) => unknown,
) => void;

// ============================================================================
// Factory
// ============================================================================

export function createExtensionAPI(
  extensionId: string,
  hostCall: HostCallFn,
  registerExport: RegisterExportFn,
): CortexExtensionAPI {
  const eventHandlers = new Map<string, Set<(data: unknown) => void>>();

  const commands: CommandsAPI = {
    registerCommand(commandId, handler) {
      registerExport(commandId, handler);
      hostCall("registerCommand", { commandId }).catch(() => {});
      const disposable: Disposable = {
        dispose() {
          registerExport(commandId, () => undefined);
        },
      };
      return disposable;
    },
    async executeCommand<T = unknown>(commandId: string, ...args: unknown[]) {
      return hostCall("executeCommand", { commandId, args }) as Promise<T>;
    },
  };

  const events: EventsAPI = {
    emit(eventName, data) {
      hostCall("emitEvent", { eventName, data }).catch(() => {});
    },
    on(eventName, handler) {
      let handlers = eventHandlers.get(eventName);
      if (!handlers) {
        handlers = new Set();
        eventHandlers.set(eventName, handlers);
      }
      handlers.add(handler);
      registerExport(`on${eventName}`, (data: unknown) => {
        const fns = eventHandlers.get(eventName);
        if (fns) {
          for (const fn of fns) fn(data);
        }
      });
      return {
        dispose() {
          const fns = eventHandlers.get(eventName);
          if (fns) {
            fns.delete(handler);
            if (fns.size === 0) eventHandlers.delete(eventName);
          }
        },
      };
    },
  };

  const workspace: WorkspaceAPI = {
    async readFile(path) {
      return hostCall("readFile", { path }) as Promise<string>;
    },
    async writeFile(path, content) {
      await hostCall("writeFile", { path, content });
    },
    async deleteFile(path) {
      await hostCall("deleteFile", { path });
    },
    async listFiles(path, pattern) {
      const result = await hostCall("listFiles", { path, pattern });
      return (result as string[] | undefined) ?? [];
    },
    async findFiles(pattern) {
      const result = await hostCall("findFiles", { pattern });
      return (result as string[] | undefined) ?? [];
    },
    async statFile(path) {
      return hostCall("statFile", { path }) as Promise<FileStat>;
    },
    async getConfiguration(section) {
      return hostCall("getConfiguration", { section });
    },
    async getWorkspacePath() {
      return hostCall("getWorkspacePath", {}) as Promise<string | null>;
    },
    async getWorkspaceFolders() {
      const result = await hostCall("getWorkspaceFolders", {});
      return (result as string[] | undefined) ?? [];
    },
    async setConfiguration(section, value) {
      await hostCall("setConfiguration", { section, value: JSON.stringify(value) });
    },
  };

  const windowAPI: WindowAPI = {
    showMessage(level, message) {
      hostCall("showMessage", { level, message }).catch(() => {});
    },
    async showQuickPick(items, placeholder) {
      return hostCall("showQuickPick", {
        itemsJson: JSON.stringify(items),
        placeholder,
      }) as Promise<string | null>;
    },
    async showInputBox(prompt, defaultValue) {
      return hostCall("showInputBox", { prompt, defaultValue }) as Promise<string | null>;
    },
    createOutputChannel(name) {
      const channelHandle = `${extensionId}:${name}`;
      hostCall("createOutputChannel", { name }).catch(() => {});
      return {
        name,
        async append(text: string) {
          await hostCall("outputChannelAppend", { channelHandle, text });
        },
        dispose() {
          /* channel disposal handled by host on extension deactivation */
        },
      };
    },
    setStatusBarMessage(text, timeoutMs) {
      hostCall("setStatusBarMessage", { text, timeoutMs }).catch(() => {});
    },
    async registerTreeView(id, title) {
      await hostCall("registerTreeView", { id, title });
      return {
        dispose() {
          hostCall("disposeTreeView", { id }).catch(() => {});
        },
      };
    },
    async createWebviewPanel(viewType, title, options) {
      return hostCall("createWebviewPanel", {
        viewType,
        title,
        optionsJson: JSON.stringify(options ?? {}),
      }) as Promise<string>;
    },
    registerStatusBarItem(id, text, alignment, priority) {
      hostCall("registerStatusBarItem", { id, text, alignment, priority }).catch(() => {});
      return {
        id,
        async update(newText: string) {
          await hostCall("updateStatusBarItem", { id, text: newText });
        },
        dispose() {
          hostCall("disposeStatusBarItem", { id }).catch(() => {});
        },
      };
    },
  };

  const editorAPI: EditorAPI = {
    async getActiveEditor() {
      return hostCall("getActiveEditor", {}) as Promise<EditorInfo | null>;
    },
    async getSelection() {
      return hostCall("getSelection", {}) as Promise<string | null>;
    },
    async insertText(text) {
      await hostCall("insertText", { text });
    },
    async replaceSelection(text) {
      await hostCall("replaceSelection", { text });
    },
    async getDocumentText(uri) {
      return hostCall("getText", { uri }) as Promise<string>;
    },
    async openDocument(uri) {
      return hostCall("openDocument", { uri }) as Promise<string>;
    },
    async saveDocument(uri) {
      await hostCall("saveDocument", { uri });
    },
    async applyEdits(uri, edits) {
      return hostCall("applyEdits", {
        uri,
        editsJson: JSON.stringify(edits),
      }) as Promise<string>;
    },
    async setDecorations(uri, decorationType, rangesJson) {
      await hostCall("setDecorations", {
        uri,
        decorationTypeHandle: decorationType,
        rangesJson,
      });
    },
  };

  const languagesAPI: LanguagesAPI = {
    registerLanguage(languageId, fileExtensions) {
      hostCall("registerLanguage", {
        languageId,
        extensionsList: JSON.stringify(fileExtensions),
      }).catch(() => {});
    },
    async registerCompletionProvider(selectorJson, providerId) {
      await hostCall("registerCompletionProvider", { selectorJson, providerId });
      return {
        dispose() {
          hostCall("disposeProvider", { providerId }).catch(() => {});
        },
      };
    },
    async registerHoverProvider(selectorJson, providerId) {
      await hostCall("registerHoverProvider", { selectorJson, providerId });
      return {
        dispose() {
          hostCall("disposeProvider", { providerId }).catch(() => {});
        },
      };
    },
    async registerDefinitionProvider(selectorJson, providerId) {
      await hostCall("registerDefinitionProvider", { selectorJson, providerId });
      return {
        dispose() {
          hostCall("disposeProvider", { providerId }).catch(() => {});
        },
      };
    },
    async registerCodeActionsProvider(selectorJson, providerId) {
      await hostCall("registerCodeActionsProvider", { selectorJson, providerId });
      return {
        dispose() {
          hostCall("disposeProvider", { providerId }).catch(() => {});
        },
      };
    },
    registerDiagnostics(uri, diagnostics) {
      hostCall("registerDiagnostic", {
        uri,
        diagnostics: JSON.stringify(diagnostics),
      }).catch(() => {});
    },
  };

  const terminalAPI: TerminalAPI = {
    async createTerminal(name, options) {
      const handleId = (await hostCall("createTerminal", {
        name,
        optionsJson: JSON.stringify(options ?? {}),
      })) as string;
      return {
        id: handleId,
        name,
        async sendText(text: string) {
          await hostCall("terminalSendText", { terminalHandle: handleId, text });
        },
        async dispose() {
          await hostCall("terminalDispose", { terminalHandle: handleId });
        },
      };
    },
  };

  const scmAPI: ScmAPI = {
    async registerScmProvider(id, label) {
      await hostCall("registerScmProvider", { id, label });
      return {
        dispose() {
          hostCall("disposeScmProvider", { id }).catch(() => {});
        },
      };
    },
  };

  const debugAPI: DebugAPI = {
    async registerDebugAdapter(typeName) {
      await hostCall("registerDebugAdapter", { typeName });
      return {
        dispose() {
          hostCall("disposeDebugAdapter", { typeName }).catch(() => {});
        },
      };
    },
  };

  return {
    extensionId,
    commands,
    events,
    workspace,
    window: windowAPI,
    editor: editorAPI,
    languages: languagesAPI,
    terminal: terminalAPI,
    scm: scmAPI,
    debug: debugAPI,

    log(level, message) {
      hostCall("log", { level, message }).catch(() => {});
    },

    async getConfig(key) {
      return hostCall("getConfig", { key }) as Promise<string | null>;
    },

    registerCommand(commandId, handler) {
      return commands.registerCommand(commandId, handler);
    },

    registerTheme(theme) {
      hostCall("registerTheme", theme).catch(() => {});
      return {
        dispose() {
          hostCall("unregisterTheme", { id: theme.id }).catch(() => {});
        },
      };
    },

    registerLanguage(config) {
      languagesAPI.registerLanguage(config.id, config.extensions);
    },
  };
}
