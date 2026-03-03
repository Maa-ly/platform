import { Component, JSX, createSignal, Show } from "solid-js";
import { TitleBar } from "./TitleBar";
import { ActivityBar } from "./ActivityBar";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { safeGetItem, safeSetItem } from "@/utils/safeStorage";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 260;
const STORAGE_KEY_WIDTH = "ide_shell_sidebar_width";
const STORAGE_KEY_VIEW = "ide_shell_active_view";

function loadSidebarWidth(): number {
  const saved = safeGetItem(STORAGE_KEY_WIDTH);
  if (saved) {
    const parsed = parseInt(saved, 10);
    if (!isNaN(parsed)) return Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, parsed));
  }
  return SIDEBAR_DEFAULT;
}

function loadActiveView(): string | null {
  return safeGetItem(STORAGE_KEY_VIEW) || "explorer";
}

export interface IDEShellProps {
  projectName?: string;
  branch?: string | null;
  line?: number;
  column?: number;
  language?: string;
  encoding?: string;
  children?: JSX.Element;
  style?: JSX.CSSProperties;
}

export const IDEShell: Component<IDEShellProps> = (props) => {
  const [activeView, setActiveView] = createSignal<string | null>(loadActiveView());
  const [sidebarWidth, setSidebarWidth] = createSignal(loadSidebarWidth());
  const [isResizing, setIsResizing] = createSignal(false);

  const handleViewSelect = (viewId: string) => {
    if (activeView() === viewId) {
      setActiveView(null);
      safeSetItem(STORAGE_KEY_VIEW, "");
    } else {
      setActiveView(viewId);
      safeSetItem(STORAGE_KEY_VIEW, viewId);
    }
  };

  const handleResizeStart = (e: MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    const startX = e.clientX;
    const startWidth = sidebarWidth();

    const onMouseMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX;
      const newWidth = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, startWidth + delta));
      setSidebarWidth(newWidth);
    };

    const onMouseUp = () => {
      setIsResizing(false);
      safeSetItem(STORAGE_KEY_WIDTH, sidebarWidth().toString());
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  const sidebarVisible = () => activeView() !== null;

  const gridColumns = () => {
    if (sidebarVisible()) {
      return `48px ${sidebarWidth()}px 6px 1fr`;
    }
    return "48px 1fr";
  };

  return (
    <div
      style={{
        display: "grid",
        "grid-template-rows": "32px 1fr 22px",
        "grid-template-columns": gridColumns(),
        width: "100vw",
        height: "100vh",
        background: "var(--cortex-bg-primary, #141415)",
        color: "var(--cortex-text-primary, #FCFCFC)",
        "font-family": "var(--cortex-font-sans)",
        overflow: "hidden",
        ...props.style,
      }}
    >
      {/* Row 1: TitleBar spanning all columns */}
      <TitleBar
        projectName={props.projectName}
        style={{ "grid-column": "1 / -1", "grid-row": "1" }}
      />

      {/* Row 2: ActivityBar */}
      <ActivityBar
        activeView={activeView()}
        onSelect={handleViewSelect}
        style={{ "grid-column": "1", "grid-row": "2" }}
      />

      {/* Row 2: Sidebar (conditional) */}
      <Show when={sidebarVisible()}>
        <div style={{
          "grid-column": "2",
          "grid-row": "2",
          overflow: "hidden",
          transition: isResizing() ? "none" : "width 150ms ease",
        }}>
          <Sidebar activeView={activeView()} />
        </div>

        {/* Resize handle */}
        <div
          style={{
            "grid-column": "3",
            "grid-row": "2",
            width: "6px",
            cursor: "col-resize",
            background: "transparent",
            transition: "background 150ms",
          }}
          onMouseDown={handleResizeStart}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background =
              "linear-gradient(to right, transparent 2px, var(--cortex-accent-primary, #BFFF00) 2px, var(--cortex-accent-primary, #BFFF00) 4px, transparent 4px)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "transparent";
          }}
        />
      </Show>

      {/* Row 2: Main editor area */}
      <main style={{
        "grid-column": sidebarVisible() ? "4" : "2",
        "grid-row": "2",
        overflow: "hidden",
        "min-width": "0",
        "min-height": "0",
      }}>
        {props.children}
      </main>

      {/* Row 3: StatusBar spanning all columns */}
      <StatusBar
        branch={props.branch}
        line={props.line}
        column={props.column}
        language={props.language}
        encoding={props.encoding}
        style={{ "grid-column": "1 / -1", "grid-row": "3" }}
      />
    </div>
  );
};
