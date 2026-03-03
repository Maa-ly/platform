/**
 * WelcomePage — startup welcome component shown when no project is open.
 *
 * Features:
 * - Recent projects list with last-opened timestamps
 * - Open Folder button
 * - Clone Repository button
 * - Links to documentation
 *
 * This is a re-usable component (as opposed to the route-level pages/Welcome.tsx).
 */

import { For, Show, createSignal } from "solid-js";

export interface RecentProject {
  name: string;
  path: string;
  lastOpened: number;
}

export interface WelcomePageProps {
  recentProjects?: RecentProject[];
  onOpenFolder?: () => void;
  onCloneRepo?: () => void;
  onOpenProject?: (path: string) => void;
}

function formatTimestamp(ts: number): string {
  const now = Date.now();
  const diff = now - ts;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

function ActionButton(props: { label: string; icon: string; onClick?: () => void }) {
  const [hovered, setHovered] = createSignal(false);

  return (
    <button
      onClick={props.onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        "align-items": "center",
        gap: "10px",
        padding: "10px 16px",
        background: hovered() ? "var(--cortex-bg-hover, rgba(255,255,255,0.06))" : "var(--cortex-bg-secondary, #1e1e2e)",
        border: "1px solid var(--cortex-border-default, rgba(255,255,255,0.08))",
        "border-radius": "8px",
        color: "var(--cortex-text-primary, #e0e0e0)",
        "font-size": "13px",
        "font-weight": "500",
        cursor: "pointer",
        "font-family": "inherit",
        transition: "background 0.15s",
        width: "100%",
      }}
    >
      <span style={{
        width: "20px",
        height: "20px",
        display: "flex",
        "align-items": "center",
        "justify-content": "center",
        color: "var(--cortex-accent-primary, #BFFF00)",
        "font-size": "16px",
      }}>
        {props.icon}
      </span>
      {props.label}
    </button>
  );
}

function DocLink(props: { label: string; href: string }) {
  const [hovered, setHovered] = createSignal(false);
  return (
    <a
      href={props.href}
      target="_blank"
      rel="noopener noreferrer"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        "font-size": "12px",
        color: hovered() ? "var(--cortex-accent-primary, #BFFF00)" : "var(--cortex-text-secondary, #888)",
        "text-decoration": "none",
        padding: "4px 8px",
        "border-radius": "4px",
        transition: "color 0.15s",
      }}
    >
      {props.label} →
    </a>
  );
}

export function WelcomePage(props: WelcomePageProps) {
  return (
    <div
      style={{
        display: "flex",
        "flex-direction": "column",
        "align-items": "center",
        "justify-content": "center",
        width: "100%",
        height: "100%",
        "min-height": "300px",
        padding: "32px 24px",
        background: "var(--cortex-bg-primary, #131217)",
        "font-family": "'DM Sans', system-ui, -apple-system, sans-serif",
        color: "var(--cortex-text-primary, #e0e0e0)",
        "box-sizing": "border-box",
      }}
    >
      <div style={{
        display: "flex",
        "flex-direction": "column",
        gap: "24px",
        "max-width": "440px",
        width: "100%",
      }}>
        {/* Branding */}
        <div style={{
          display: "flex",
          "flex-direction": "column",
          "align-items": "center",
          gap: "8px",
        }}>
          <div style={{
            width: "48px",
            height: "48px",
            "border-radius": "12px",
            background: "linear-gradient(135deg, #BFFF00 0%, #8BC34A 100%)",
            display: "flex",
            "align-items": "center",
            "justify-content": "center",
            "margin-bottom": "8px",
          }}>
            <svg width="24" height="24" viewBox="0 0 32 32" fill="none">
              <path d="M16 4L28 10V22L16 28L4 22V10L16 4Z" stroke="#131217" stroke-width="2.5" stroke-linejoin="round"/>
              <path d="M16 4V16M16 16L28 10M16 16L4 10M16 16V28" stroke="#131217" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </div>
          <h2 style={{
            "font-size": "18px",
            "font-weight": "600",
            margin: "0",
            color: "var(--cortex-text-primary, #fff)",
          }}>
            Welcome to Cortex
          </h2>
          <p style={{
            "font-size": "13px",
            color: "var(--cortex-text-secondary, #888)",
            margin: "0",
            "text-align": "center",
          }}>
            Open a folder or clone a repository to get started.
          </p>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", "flex-direction": "column", gap: "8px" }}>
          <ActionButton label="Open Folder…" icon="📂" onClick={props.onOpenFolder} />
          <ActionButton label="Clone Repository…" icon="⎇" onClick={props.onCloneRepo} />
        </div>

        {/* Recent Projects */}
        <Show when={props.recentProjects && props.recentProjects.length > 0}>
          <div style={{ display: "flex", "flex-direction": "column", gap: "6px" }}>
            <div style={{
              "font-size": "11px",
              "font-weight": "500",
              color: "var(--cortex-text-secondary, #888)",
              "text-transform": "uppercase",
              "letter-spacing": "0.05em",
              padding: "0 4px",
            }}>
              Recent Projects
            </div>
            <div style={{
              display: "flex",
              "flex-direction": "column",
              background: "var(--cortex-bg-secondary, #1e1e2e)",
              "border-radius": "8px",
              border: "1px solid var(--cortex-border-default, rgba(255,255,255,0.08))",
              overflow: "hidden",
            }}>
              <For each={props.recentProjects!.slice(0, 8)}>
                {(project) => {
                  const [hovered, setHovered] = createSignal(false);
                  return (
                    <button
                      onClick={() => props.onOpenProject?.(project.path)}
                      onMouseEnter={() => setHovered(true)}
                      onMouseLeave={() => setHovered(false)}
                      title={project.path}
                      style={{
                        display: "flex",
                        "align-items": "center",
                        "justify-content": "space-between",
                        padding: "8px 12px",
                        background: hovered() ? "var(--cortex-bg-hover, rgba(255,255,255,0.04))" : "transparent",
                        border: "none",
                        "border-bottom": "1px solid var(--cortex-border-default, rgba(255,255,255,0.04))",
                        color: "var(--cortex-text-primary, #e0e0e0)",
                        cursor: "pointer",
                        "font-family": "inherit",
                        "font-size": "13px",
                        "text-align": "left",
                        width: "100%",
                        transition: "background 0.1s",
                      }}
                    >
                      <div style={{
                        display: "flex",
                        "flex-direction": "column",
                        gap: "2px",
                        "min-width": "0",
                        flex: "1",
                      }}>
                        <span style={{
                          "font-weight": "500",
                          overflow: "hidden",
                          "text-overflow": "ellipsis",
                          "white-space": "nowrap",
                        }}>
                          {project.name}
                        </span>
                        <span style={{
                          "font-size": "11px",
                          color: "var(--cortex-text-tertiary, #666)",
                          overflow: "hidden",
                          "text-overflow": "ellipsis",
                          "white-space": "nowrap",
                        }}>
                          {project.path}
                        </span>
                      </div>
                      <span style={{
                        "font-size": "11px",
                        color: "var(--cortex-text-tertiary, #555)",
                        "white-space": "nowrap",
                        "margin-left": "12px",
                        "flex-shrink": "0",
                      }}>
                        {formatTimestamp(project.lastOpened)}
                      </span>
                    </button>
                  );
                }}
              </For>
            </div>
          </div>
        </Show>

        {/* Documentation Links */}
        <div style={{
          display: "flex",
          gap: "8px",
          "flex-wrap": "wrap",
          "justify-content": "center",
        }}>
          <DocLink label="Documentation" href="https://docs.cortex.dev" />
          <DocLink label="Getting Started" href="https://docs.cortex.dev/getting-started" />
          <DocLink label="Shortcuts" href="https://docs.cortex.dev/shortcuts" />
        </div>
      </div>
    </div>
  );
}

export default WelcomePage;
