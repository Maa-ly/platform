import { ParentProps } from "solid-js";

export default function App(props: ParentProps) {
  return (
    <div class="flex h-screen w-screen flex-col overflow-hidden bg-[var(--background)] text-[var(--foreground)]">
      {props.children}
    </div>
  );
}
