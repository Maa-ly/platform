import { JSX, splitProps, createSignal, createEffect, onMount, onCleanup } from "solid-js";
import { safeGetItem, safeSetItem } from "@/utils/safeStorage";

export interface SplitPaneProps {
  id?: string;
  direction?: "horizontal" | "vertical";
  ratio?: number;
  minRatio?: number;
  maxRatio?: number;
  onRatioChange?: (ratio: number) => void;
  first: () => JSX.Element;
  second: () => JSX.Element;
  storageKey?: string;
  style?: JSX.CSSProperties;
}

export function SplitPane(props: SplitPaneProps) {
  const [local] = splitProps(props, [
    "id",
    "direction",
    "ratio",
    "minRatio",
    "maxRatio",
    "onRatioChange",
    "first",
    "second",
    "storageKey",
    "style",
  ]);

  const getSavedRatio = () => {
    if (local.storageKey) {
      const saved = safeGetItem(`split_ratio_${local.storageKey}`);
      if (saved) {
        const parsed = parseFloat(saved);
        if (!isNaN(parsed)) return parsed;
      }
    }
    return local.ratio ?? 0.5;
  };

  const [ratio, setRatio] = createSignal(getSavedRatio());
  const [isDragging, setIsDragging] = createSignal(false);
  let containerRef: HTMLDivElement | undefined;

  createEffect(() => {
    if (local.storageKey) {
      safeSetItem(`split_ratio_${local.storageKey}`, ratio().toString());
    }
  });

  const isHorizontal = () => (local.direction ?? "horizontal") === "horizontal";
  const minRatio = () => local.minRatio ?? 0.15;
  const maxRatio = () => local.maxRatio ?? 0.85;

  const handleMouseDown = (e: MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    document.body.style.cursor = isHorizontal() ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging() || !containerRef) return;

    const rect = containerRef.getBoundingClientRect();
    let newRatio: number;

    if (isHorizontal()) {
      newRatio = (e.clientX - rect.left) / rect.width;
    } else {
      newRatio = (e.clientY - rect.top) / rect.height;
    }

    newRatio = Math.max(minRatio(), Math.min(maxRatio(), newRatio));
    setRatio(newRatio);
    local.onRatioChange?.(newRatio);
  };

  const handleMouseUp = () => {
    if (isDragging()) {
      setIsDragging(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
  };

  const handleDoubleClick = () => {
    setRatio(0.5);
    local.onRatioChange?.(0.5);
  };

  onMount(() => {
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  });

  onCleanup(() => {
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });

  const containerStyle = (): JSX.CSSProperties => ({
    flex: "1",
    display: "flex",
    overflow: "hidden",
    "flex-direction": isHorizontal() ? "row" : "column",
    ...local.style,
  });

  const firstPaneStyle = (): JSX.CSSProperties => ({
    display: "flex",
    overflow: "hidden",
    [isHorizontal() ? "width" : "height"]: `${ratio() * 100}%`,
    "min-width": isHorizontal() ? "100px" : undefined,
    "min-height": !isHorizontal() ? "100px" : undefined,
  });

  const dividerStyle = (): JSX.CSSProperties => ({
    "flex-shrink": "0",
    display: "flex",
    "align-items": "center",
    "justify-content": "center",
    transition: "background var(--cortex-transition-fast)",
    width: isHorizontal() ? "4px" : "100%",
    height: isHorizontal() ? "100%" : "4px",
    background: isDragging() ? "var(--jb-border-focus)" : "var(--jb-border-divider)",
    cursor: isHorizontal() ? "col-resize" : "row-resize",
  });

  const secondPaneStyle = (): JSX.CSSProperties => ({
    display: "flex",
    overflow: "hidden",
    [isHorizontal() ? "width" : "height"]: `${(1 - ratio()) * 100}%`,
    "min-width": isHorizontal() ? "100px" : undefined,
    "min-height": !isHorizontal() ? "100px" : undefined,
  });

  return (
    <div
      ref={containerRef}
      style={containerStyle()}
      data-split-id={local.id}
    >
      <div style={firstPaneStyle()}>
        {local.first()}
      </div>

      <div
        style={dividerStyle()}
        onMouseDown={handleMouseDown}
        onDblClick={handleDoubleClick}
      />

      <div style={secondPaneStyle()}>
        {local.second()}
      </div>
    </div>
  );
}
