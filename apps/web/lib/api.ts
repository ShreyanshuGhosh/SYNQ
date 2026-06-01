import type {
  ContentBlock,
  ContextWarningEvent,
  Conversation,
  CreateConversationResponse,
  FileStatusResponse,
  FileUploadResponse,
  GetConversationResponse,
  ListConversationsResponse,
  Message,
  ModelListResponse,
  ModelSwitchEvent,
  SendMessageRequest,
  UpdateConversationRequest,
} from "@synq/shared-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type GetToken = () => Promise<string | null>;

async function authHeaders(getToken: GetToken): Promise<HeadersInit> {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function listConversations(
  getToken: GetToken,
): Promise<ListConversationsResponse> {
  const res = await fetch(`${API_BASE}/conversations`, {
    headers: await authHeaders(getToken),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`listConversations: ${res.status}`);
  return res.json();
}

export async function createConversation(
  getToken: GetToken,
  title?: string,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify({ title: title ?? null }),
  });
  if (!res.ok) throw new Error(`createConversation: ${res.status}`);
  const data: CreateConversationResponse = await res.json();
  return data.conversation;
}

export async function getConversation(
  getToken: GetToken,
  id: string,
): Promise<GetConversationResponse> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    headers: await authHeaders(getToken),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`getConversation: ${res.status}`);
  return res.json();
}

/**
 * Stream a message → assistant reply via SSE.
 *
 * Yields parsed SSE events. The caller is expected to handle the AbortSignal
 * (passed via `signal`) for cleanup on unmount.
 */
export type ChatEvent =
  | { event: "user_message"; data: Message }
  | { event: "token"; data: { text: string } }
  | { event: "model_switch"; data: ModelSwitchEvent }
  | { event: "context_warning"; data: ContextWarningEvent }
  | { event: "done"; data: Message }
  | { event: "error"; data: { message: string } };

export async function listModels(
  getToken: GetToken,
): Promise<ModelListResponse> {
  const res = await fetch(`${API_BASE}/models`, {
    headers: await authHeaders(getToken),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`listModels: ${res.status}`);
  return res.json();
}

export async function updateConversation(
  getToken: GetToken,
  id: string,
  patch: UpdateConversationRequest,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: await authHeaders(getToken),
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`updateConversation: ${res.status}`);
  return res.json();
}

export async function deleteConversation(
  getToken: GetToken,
  id: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
  if (!res.ok) throw new Error(`deleteConversation: ${res.status}`);
}

export async function* sendMessageStream(
  getToken: GetToken,
  conversationId: string,
  payload: { content: ContentBlock[]; idempotencyKey: string; model?: string },
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const body: SendMessageRequest = {
    content: payload.content,
    model: payload.model ?? null,
    idempotency_key: payload.idempotencyKey,
  };
  const res = await fetch(
    `${API_BASE}/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: {
        ...(await authHeaders(getToken)),
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!res.ok || !res.body) {
    throw new Error(`sendMessageStream: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      // Normalize CRLF (sse-starlette's default) to LF so a single
      // \n\n split catches both line-ending styles. Without this, the
      // browser buffers the entire stream and only flushes when the
      // connection closes — looks like "no response until refresh".
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const rawEvent = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const parsed = parseSSEBlock(rawEvent);
        if (parsed) yield parsed;
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Phase 4 — pin one message into the conversation's pinned_context. */
export async function pinMessage(
  getToken: GetToken,
  conversationId: string,
  messageId: string,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/pin`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify({ message_id: messageId }),
  });
  if (!res.ok) throw new Error(`pinMessage: ${res.status}`);
  return res.json();
}

/** Phase 4 — remove all pinned blocks from this message. */
export async function unpinMessage(
  getToken: GetToken,
  conversationId: string,
  messageId: string,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/unpin`, {
    method: "POST",
    headers: await authHeaders(getToken),
    body: JSON.stringify({ message_id: messageId }),
  });
  if (!res.ok) throw new Error(`unpinMessage: ${res.status}`);
  return res.json();
}

export async function uploadFile(
  getToken: GetToken,
  file: File,
  opts?: { conversationId?: string; onProgress?: (pct: number) => void },
): Promise<FileUploadResponse> {
  // Use XMLHttpRequest so we get progress events; fetch + ReadableStream
  // would let us stream-read the response but doesn't expose upload progress.
  const token = await getToken();
  const form = new FormData();
  form.append("file", file);
  if (opts?.conversationId) form.append("conversation_id", opts.conversationId);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/files`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && opts?.onProgress) {
        opts.onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as FileUploadResponse);
        } catch (e) {
          reject(e);
        }
      } else {
        reject(new Error(`uploadFile: ${xhr.status} ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("uploadFile: network error"));
    xhr.send(form);
  });
}

export async function getFileStatus(
  getToken: GetToken,
  fileId: string,
): Promise<FileStatusResponse> {
  const res = await fetch(`${API_BASE}/files/${fileId}`, {
    headers: await authHeaders(getToken),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`getFileStatus: ${res.status}`);
  return res.json();
}

// ── Phase 5 — Dashboard ─────────────────────────────────────────────────

export type RouterChainEntry = { model: string; provider: string };
export type RouterChainResponse = {
  chain: RouterChainEntry[];
  cost_aware_routing: boolean;
  cost_aware_prompt_threshold: number;
};

export type ProviderHealth = {
  provider: string;
  status: "healthy" | "degraded" | "half_open" | "unhealthy" | "unknown";
  latency_ms: number | null;
  checked_at: number | null;
  model_used: string | null;
  error?: string;
  // Phase 6 — last 5 probe outcomes, newest first.
  history?: Array<{
    status: string | null;
    latency_ms: number | null;
    checked_at: number | null;
  }>;
};

// ── Phase 6 — Feature flags ─────────────────────────────────────────────
export type FlagRow = {
  name: string;
  value: boolean;
  default: boolean;
  description: string;
  env_var: string;
};
export type FlagsResponse = { flags: FlagRow[] };

export type LimitsResponse = {
  daily_soft_limit_usd: number;
  hard_daily_limit_usd: number | null;
  today_usd_estimate: number;
  hard_limit_blocked: boolean;
  soft_warning_active: boolean;
  price_table_models: string[];
};

export type StatsToday = {
  today_cost_usd: number;
  turns_today: number;
  fallbacks_today: number;
  manual_switches_today: number;
  daily_soft_limit_usd: number;
};

export type DailyCostRow = { day: string | null; cost_usd: number; total_tokens: number };
export type DailyCostResponse = { days: DailyCostRow[]; daily_soft_limit_usd: number };

export type ProviderShareRow = { provider: string; cost_usd: number; pct: number; turns: number };
export type ProviderShareResponse = { providers: ProviderShareRow[] };

export type FallbackRow = {
  ts: string | null;
  fallback_from: string | null;
  fallback_to: string | null;
  fallback_reason: string | null;
  conversation_id: string | null;
  latency_ms: number | null;
};
export type FallbackResponse = { fallbacks: FallbackRow[] };

export type HourlyTokenRow = { hour: string | null; prompt: number; completion: number };
export type HourlyTokenResponse = { hours: HourlyTokenRow[] };

async function getJson<T>(getToken: GetToken, path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await authHeaders(getToken),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export const dash = {
  routerChain: (t: GetToken) => getJson<RouterChainResponse>(t, "/api/router/chain"),
  health: (t: GetToken) => getJson<{ providers: ProviderHealth[] }>(t, "/api/health/providers"),
  limits: (t: GetToken) => getJson<LimitsResponse>(t, "/api/config/limits"),
  statsToday: (t: GetToken) => getJson<StatsToday>(t, "/api/usage/stats/today"),
  daily: (t: GetToken, days = 30) => getJson<DailyCostResponse>(t, `/api/usage/daily?days=${days}`),
  providersMonth: (t: GetToken) => getJson<ProviderShareResponse>(t, "/api/usage/providers/month"),
  fallbacks: (t: GetToken, limit = 20) => getJson<FallbackResponse>(t, `/api/usage/fallbacks?limit=${limit}`),
  tokens: (t: GetToken, hours = 168) => getJson<HourlyTokenResponse>(t, `/api/usage/tokens?hours=${hours}`),
  flags: (t: GetToken) => getJson<FlagsResponse>(t, "/api/flags"),
};

function parseSSEBlock(block: string): ChatEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    // SSE per spec: comments start with ":" — used as heartbeats by
    // sse-starlette. Skip them silently.
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  try {
    const data = JSON.parse(dataStr);
    return { event, data } as ChatEvent;
  } catch {
    return null;
  }
}
