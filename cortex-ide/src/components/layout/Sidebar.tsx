import { Component, JSX, Show, Switch, Match } from "solid-js";

export interface SidebarProps {
  activeView: string | null;
  style?: JSX.CSSProperties;
}

const VIEW_LABELS: Record<string, string> = {
  explorer: "Explorer",
  search: "Search",
  scm: "Source Control",
  extensions: "Extensions",
  chat: "AI Chat",
};

const VIEW_ICONS: Record<string, () => JSX.Element> = {
  explorer: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
    </svg>
  ),
  search: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="6" />
      <path d="M16 16l5 5" />
    </svg>
  ),
  scm: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="5" r="2.5" />
      <circle cx="12" cy="19" r="2.5" />
      <path d="M12 7.5v9" />
    </svg>
  ),
  extensions: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <rect x="4" y="4" width="7" height="7" rx="1" />
      <rect x="13" y="4" width="7" height="7" rx="1" />
      <rect x="4" y="13" width="7" height="7" rx="1" />
      <rect x="13" y="13" width="7" height="7" rx="1" />
    </svg>
  ),
  chat: () => (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 4h16a2 2 0 012 2v9a2 2 0 01-2 2H9l-5 4v-4a2 2 0 01-2-2V6a2 2 0 012-2z" />
    </svg>
  ),
};

export const Sidebar: Component<SidebarProps> = (props) => {
  return (
    <Show when={props.activeView}>
      <div
        style={{
          display: "flex",
          "flex-direction": "column",
          height: "100%",
          background: "var(--cortex-sidebar-bg, #1C1C1D)",
          overflow: "hidden",
          ...props.style,
        }}
      >
        {/* Header */}
        <div style={{
          display: "flex",
          "align-items": "center",
          height: "34px",
          "min-height": "34px",
          padding: "0 12px",
          "border-bottom": "1px solid var(--cortex-border-default, #2E2F31)",
          "font-family": "var(--cortex-font-sans)",
          "font-size": "11px",
          "font-weight": "600",
          "text-transform": "uppercase",
          "letter-spacing": "0.5px",
          color: "var(--cortex-text-secondary, #8C8D8F)",
          "user-select": "none",
        }}>
          {VIEW_LABELS[props.activeView!] ?? props.activeView}
        </div>

        {/* Content */}
        <div style={{
          flex: "1",
          display: "flex",
          "flex-direction": "column",
          "align-items": "center",
          "justify-content": "center",
          padding: "24px",
          gap: "12px",
          color: "var(--cortex-text-muted, #666)",
          overflow: "auto",
        }}>
          <Switch fallback={
            <span style={{
              "font-family": "var(--cortex-font-sans)",
              "font-size": "13px",
            }}>
              {VIEW_LABELS[props.activeView!] ?? props.activeView}
            </span>
          }>
            <Match when={props.activeView === "explorer"}>
              {VIEW_ICONS.explorer()}
              <span style={{ "font-family": "var(--cortex-font-sans)", "font-size": "13px" }}>
                No folder opened
              </span>
            </Match>
            <Match when={props.activeView === "search"}>
              {VIEW_ICONS.search()}
              <span style={{ "font-family": "var(--cortex-font-sans)", "font-size": "13px" }}>
                Search across files
              </span>
            </Match>
            <Match when={props.activeView === "scm"}>
              {VIEW_ICONS.scm()}
              <span style={{ "font-family": "var(--cortex-font-sans)", "font-size": "13px" }}>
                No repository detected
              </span>
            </Match>
            <Match when={props.activeView === "extensions"}>
              {VIEW_ICONS.extensions()}
              <span style={{ "font-family": "var(--cortex-font-sans)", "font-size": "13px" }}>
                Browse extensions
              </span>
            </Match>
            <Match when={props.activeView === "chat"}>
              {VIEW_ICONS.chat()}
              <span style={{ "font-family": "var(--cortex-font-sans)", "font-size": "13px" }}>
                Start a conversation
              </span>
            </Match>
          </Switch>
        </div>
      </div>
    </Show>
  );
};
