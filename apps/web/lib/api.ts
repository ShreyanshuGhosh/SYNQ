import type {
  ContentBlock,
  ContextWarningEvent,
  Conversation,
  CreateConversationResponse,
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
