/**
 * SplashScreen — branded loading screen shown during app initialization.
 *
 * Displays the Cortex IDE logo with a pulse animation, an animated
 * loading bar, and rotating status messages that update as the
 * app progresses through its startup phases.
 */

import { createSignal, onMount, onCleanup } from "solid-js";

const STATUS_MESSAGES = [
  "Initializing workspace…",
  "Loading extensions…",
  "Starting language server…",
  "Preparing editor…",
  "Almost ready…",
];

const MESSAGE_INTERVAL = 1800;

export interface SplashScreenProps {
  statusText?: string;
}

export function SplashScreen(props: SplashScreenProps) {
  const [messageIndex, setMessageIndex] = createSignal(0);
  const [fadeIn, setFadeIn] = createSignal(false);

  let interval: ReturnType<typeof setInterval> | undefined;

  onMount(() => {
    requestAnimationFrame(() => setFadeIn(true));
    interval = setInterval(() => {
      setMessageIndex((i) => (i + 1) % STATUS_MESSAGES.length);
    }, MESSAGE_INTERVAL);
  });

  onCleanup(() => {
    if (interval) clearInterval(interval);
  });

  const currentMessage = () => props.statusText || STATUS_MESSAGES[messageIndex()];

  return (
    <div
      style={{
        position: "fixed",
        inset: "0",
        display: "flex",
        "flex-direction": "column",
        "align-items": "center",
        "justify-content": "center",
        background: "#131217",
        "z-index": "99999",
        "font-family": "'DM Sans', system-ui, -apple-system, sans-serif",
        opacity: fadeIn() ? "1" : "0",
        transition: "opacity 0.3s ease-in",
      }}
    >
      {/* Logo / Brand Mark */}
      <div
        style={{
          width: "64px",
          height: "64px",
          "border-radius": "16px",
          background: "linear-gradient(135deg, #BFFF00 0%, #8BC34A 100%)",
          display: "flex",
          "align-items": "center",
          "justify-content": "center",
          "margin-bottom": "24px",
          animation: "splashPulse 2s ease-in-out infinite",
          "box-shadow": "0 0 40px rgba(191, 255, 0, 0.15)",
        }}
      >
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <path
            d="M16 4L28 10V22L16 28L4 22V10L16 4Z"
            stroke="#131217"
            stroke-width="2.5"
            stroke-linejoin="round"
          />
          <path
            d="M16 4V16M16 16L28 10M16 16L4 10M16 16V28"
            stroke="#131217"
            stroke-width="2"
            stroke-linecap="round"
          />
        </svg>
      </div>

      {/* App Name */}
      <h1
        style={{
          "font-size": "20px",
          "font-weight": "600",
          color: "#ffffff",
          margin: "0 0 8px 0",
          "letter-spacing": "-0.01em",
        }}
      >
        Cortex IDE
      </h1>

      {/* Loading bar */}
      <div
        style={{
          width: "200px",
          height: "2px",
          background: "rgba(255,255,255,0.08)",
          "border-radius": "1px",
          overflow: "hidden",
          "margin-bottom": "16px",
        }}
      >
        <div
          style={{
            width: "40%",
            height: "100%",
            background: "linear-gradient(90deg, #BFFF00, #8BC34A)",
            "border-radius": "1px",
            animation: "splashBar 1.8s ease-in-out infinite",
          }}
        />
      </div>

      {/* Status Message */}
      <div
        style={{
          "font-size": "12px",
          color: "rgba(255,255,255,0.45)",
          "min-height": "18px",
          transition: "opacity 0.2s",
        }}
      >
        {currentMessage()}
      </div>

      {/* Animations */}
      <style>{`
        @keyframes splashPulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.05); opacity: 0.9; }
        }
        @keyframes splashBar {
          0% { transform: translateX(-100%); }
          50% { transform: translateX(150%); }
          100% { transform: translateX(350%); }
        }
      `}</style>
    </div>
  );
}

export default SplashScreen;
