import { JSX, splitProps, ParentProps, createSignal, onMount } from "solid-js";

export interface ScrollAreaProps extends ParentProps {
  direction?: "vertical" | "horizontal" | "both";
  autoHide?: boolean;
  thin?: boolean;
  scrollShadow?: boolean;
  class?: string;
  style?: JSX.CSSProperties;
  onScroll?: (e: Event) => void;
  ref?: (el: HTMLDivElement) => void;
}

export function ScrollArea(props: ScrollAreaProps) {
  const [local] = splitProps(props, [
    "direction",
    "autoHide",
    "thin",
    "scrollShadow",
    "class",
    "style",
    "onScroll",
    "ref",
    "children",
  ]);

  const [scrolledTop, setScrolledTop] = createSignal(false);
  let containerRef: HTMLDivElement | undefined;

  const direction = () => local.direction ?? "vertical";

  const overflowStyle = (): Pick<JSX.CSSProperties, "overflow-x" | "overflow-y" | "overflow"> => {
    switch (direction()) {
      case "horizontal":
        return { "overflow-x": "auto", "overflow-y": "hidden" };
      case "both":
        return { overflow: "auto" };
      case "vertical":
      default:
        return { "overflow-x": "hidden", "overflow-y": "auto" };
    }
  };

  const handleScroll = (e: Event) => {
    if (local.scrollShadow && containerRef) {
      setScrolledTop(containerRef.scrollTop > 0);
    }
    local.onScroll?.(e);
  };

  const classNames = () => {
    const parts: string[] = [];
    if (local.autoHide) parts.push("scrollbar-auto-hide");
    if (local.thin) parts.push("scrollbar-thin");
    if (local.scrollShadow) {
      parts.push("scroll-shadow");
      if (scrolledTop()) parts.push("scroll-shadow-top");
    }
    if (local.class) parts.push(local.class);
    return parts.join(" ") || undefined;
  };

  const containerStyle = (): JSX.CSSProperties => ({
    position: "relative",
    flex: "1",
    "min-height": "0",
    "min-width": "0",
    ...overflowStyle(),
    ...local.style,
  });

  const setRef = (el: HTMLDivElement) => {
    containerRef = el;
    local.ref?.(el);
  };

  onMount(() => {
    if (local.scrollShadow && containerRef) {
      setScrolledTop(containerRef.scrollTop > 0);
    }
  });

  return (
    <div
      ref={setRef}
      class={classNames()}
      style={containerStyle()}
      onScroll={handleScroll}
    >
      {local.children}
    </div>
  );
}
