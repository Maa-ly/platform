import { Component, JSX, Show } from "solid-js";

export interface StatusBarProps {
  branch?: string | null;
  line?: number;
  column?: number;
  language?: string;
  encoding?: string;
  style?: JSX.CSSProperties;
}

export const StatusBar: Component<StatusBarProps> = (props) => {
  const textStyle: JSX.CSSProperties = {
    "font-family": "var(--cortex-font-sans)",
    "font-size": "12px",
    "font-weight": "400",
    color: "var(--cortex-text-secondary, #8C8D8F)",
    "white-space": "nowrap",
  };

  return (
    <footer
      style={{
        display: "flex",
        "align-items": "center",
        "justify-content": "space-between",
        height: "22px",
        "min-height": "22px",
        padding: "0 12px",
        background: "var(--cortex-bg-secondary, #1C1C1D)",
        "border-top": "1px solid var(--cortex-border-default, #2E2F31)",
        "grid-column": "1 / -1",
        "user-select": "none",
        ...props.style,
      }}
    >
      {/* Left section */}
      <div style={{ display: "flex", "align-items": "center", gap: "12px" }}>
        <Show when={props.branch}>
          <div style={{ display: "flex", "align-items": "center", gap: "4px" }}>
            {/* Git branch icon */}
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" style={{ color: "var(--cortex-text-secondary, #8C8D8F)" }}>
              <path d="M11.75 5a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5ZM4.25 5a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5ZM4.25 13.5a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5ZM4.25 5v6M11.75 5v1.5c0 1.1-.9 2-2 2h-3.5" />
            </svg>
            <span style={textStyle}>{props.branch}</span>
          </div>
        </Show>
        <span style={textStyle}>{props.encoding ?? "UTF-8"}</span>
      </div>

      {/* Right section */}
      <div style={{ display: "flex", "align-items": "center", gap: "12px" }}>
        <span style={textStyle}>
          Ln {props.line ?? 1}, Col {props.column ?? 1}
        </span>
        <span style={textStyle}>
          {props.language ?? "Plain Text"}
        </span>
        {/* Notification bell */}
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" style={{ color: "var(--cortex-text-secondary, #8C8D8F)", cursor: "pointer" }}>
          <path d="M8 14c.7 0 1.37-.2 1.93-.56A2 2 0 0 1 8 12a2 2 0 0 1-1.93 1.44c.56.36 1.23.56 1.93.56Z" fill="currentColor" />
          <path d="M12 7c0-2.2-1.8-4-4-4S4 4.8 4 7v3l-1 2h10l-1-2V7Z" />
        </svg>
      </div>
    </footer>
  );
};
