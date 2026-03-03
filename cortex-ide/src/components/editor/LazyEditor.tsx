/**
 * LazyEditor — wrapper that only mounts Monaco editor for the active tab.
 *
 * Background tabs have their Monaco model preserved but the editor DOM
 * is unmounted to reduce memory pressure and DOM node count.
 *
 * Usage in EditorGroupPanel (MultiBuffer.tsx):
 *   <LazyEditor file={file} isActive={isActive} groupId={groupId} />
 */

import { Show, createSignal, createEffect, onCleanup, lazy, Suspense } from "solid-js";
import type { OpenFile } from "@/context/EditorContext";
import { EditorSkeleton } from "./EditorSkeleton";

const CodeEditorLazy = lazy(() =>
  import("./CodeEditor").then((m) => ({ default: m.CodeEditor })),
);

export interface LazyEditorProps {
  file: OpenFile;
  isActive: boolean;
  groupId: string;
}

const mountedModels = new Set<string>();

export function LazyEditor(props: LazyEditorProps) {
  const [wasEverActive, setWasEverActive] = createSignal(props.isActive);

  createEffect(() => {
    if (props.isActive) {
      setWasEverActive(true);
      mountedModels.add(props.file.id);
    }
  });

  onCleanup(() => {
    // Model cleanup happens in CodeEditor's own onCleanup
  });

  return (
    <div
      style={{
        display: props.isActive ? "flex" : "none",
        flex: "1",
        "min-height": "0",
        "flex-direction": "column",
        overflow: "hidden",
      }}
      data-lazy-editor={props.file.id}
      data-active={props.isActive}
    >
      <Show when={wasEverActive()}>
        <Suspense fallback={<EditorSkeleton />}>
          <CodeEditorLazy file={props.file} groupId={props.groupId} />
        </Suspense>
      </Show>
    </div>
  );
}

export function hasEditorModel(fileId: string): boolean {
  return mountedModels.has(fileId);
}

export default LazyEditor;
