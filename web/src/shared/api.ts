export class ApiError extends Error {
    constructor(
        message: string,
        public status: number,
    ) {
        super(message);
    }
}
export async function api<T>(
    path: string,
    options: RequestInit = {},
): Promise<T> {
    const headers = new Headers(options.headers);
    if (options.body && !(options.body instanceof FormData))
        headers.set("Content-Type", "application/json");
    const response = await fetch("/api" + path, { ...options, headers });
    if (!response.ok) {
        let detail = "请求未完成，请稍后再试";
        try {
            const data = await response.json();
            detail =
                typeof data.detail === "string"
                    ? data.detail
                    : JSON.stringify(data.detail);
        } catch {
            /* non-JSON server failure */
        }
        throw new ApiError(detail, response.status);
    }
    return response.json();
}
export const send = (method: string, body: unknown): RequestInit => ({
    method,
    body: JSON.stringify(body),
});
export type Project = {
    id: string;
    title: string;
    description: string;
    domain: string;
    knowledge?: {
        subject?: string;
        terminology?: string;
        instructions?: string;
        language?: "zh" | "en";
    };
    updated_at: string;
};
export type Asset = {
    id: string;
    name: string;
    media_type: string;
    size: number;
};
export type Version = {
    id: string;
    artifact_id: string;
    number: number;
    content: string;
    fields: Record<string, unknown>;
    author: string;
    created_at: string;
};
export type RecordItem = {
    id: string;
    title: string;
    kind: string;
    status: string;
    revision: number;
    version: Version;
    attachments: Asset[];
    updated_at: string;
};
export type ReadingState = {
    reading_status: "unread" | "reading" | "read";
    starred: boolean;
    tags: string[];
    last_page: number;
    last_scroll?: number;
    last_version_id?: string | null;
};
export type Annotation = {
    id: string;
    source_span_id: string;
    source_version_id: string;
    start_offset: number;
    end_offset: number;
    quote: string;
    comment: string;
    page: number;
    version: number;
    rectangles: number[][];
};
export type Source = {
    content_type?: string;
    original_pdf?: {
        url: string;
        sha256: string;
        source_version_id: string;
        metadata_url: string;
        is_retracted?: boolean;
    };
    reading?: ReadingState;
    accession?: string;
    repository?: string;
    content_level?: "full_text" | "study_metadata";
    url?: string;
    id: string;
    title: string;
    authors: string;
    year: string;
    doi: string;
    version: number;
    asset_id: string;
    page_count: number;
    version_id: string;
};
export type Span = {
    extraction_error?: string;
    id: string;
    source_version_id: string;
    page: number;
    text: string;
};
export type SourceData = {
    content_type?: string;
    version: { id: string; number: number; asset_id: string };
    versions: {
        id: string;
        number: number;
        asset_id: string;
        content_type?: string;
    }[];
    pages: Span[];
};
export type Run = {
    id: string;
    project_id?: string;
    conversation_id: string;
    prompt: string;
    status: string;
    error: string;
    mode: string;
    result: {
        artifact_ids?: string[];
        answerability?: "answer" | "refuse" | "clarify";
        pipeline?: { answer: string };
    };
    created_at: string;
    finished_at: string | null;
    context?: Record<string, unknown>;
    transcript?: unknown[];
};
export type ChatMessage = { id: string; role: string; content: string };
export type Conversation = { id: string; title: string };
export type Evidence = {
    content_type?: string;
    kind: string;
    id: string;
    title: string;
    content: string;
    page?: number;
    version: number;
    asset_id?: string;
    source_id?: string;
};
export type ModelState = {
    connected: boolean;
    models: string[];
    selected: string | null;
    error?: string;
    config: {
        id?: string;
        name?: string;
        provider?: string;
        base_url: string;
        model: string;
        max_tokens: number;
        timeout: number;
    };
};
export type Overview = { counts: Record<string, number>; recent: RecordItem[] };
export type ModelProfile = {
    disable_thinking?: boolean;
    id: string;
    name: string;
    provider: "compatible" | "openai" | "codex";
    base_url: string;
    model: string;
    max_tokens: number;
    timeout: number;
    key_env: string;
    has_key?: boolean;
};
export type ProfileState = {
    profiles: ModelProfile[];
    defaults: { assistant: string; reader: string };
};
export type Skill = {
    id: string;
    name: string;
    description: string;
    instructions: string;
    category: "reading" | "thinking" | "slides" | "custom";
    source_url: string;
    enabled: boolean;
    builtin: boolean;
    origin?: string;
    output?: string;
    requires?: string;
    license?: string;
};
export type Bundle = {
    sources: Source[];
    records: RecordItem[];
    runs: Run[];
    conversations: Conversation[];
    overview: Overview;
};
export const emptyBundle: Bundle = {
    sources: [],
    records: [],
    runs: [],
    conversations: [],
    overview: { counts: {}, recent: [] },
};
