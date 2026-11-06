import type { RecordItem } from "./api";
export type EditorState = {
    kind: string;
    record?: RecordItem;
    content?: string;
    title?: string;
    fields?: Record<string, unknown>;
};
