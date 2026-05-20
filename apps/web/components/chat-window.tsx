"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import type { ContentBlock, Message } from "@synq/shared-types";
import { useChatStore } from "@/lib/store";
import {
  listModels,
  sendMessageStream,
  updateConversation,
} from "@/lib/api";

function newIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function extractText(content: ContentBlock[]): string {
  return content
    .filter((b): b is Extract<ContentBlock, { type: "text" }> => b.type === "text")
    .map((b) => b.text)
    .join("");
}

export function ChatWindow({ conversationId }: { conversationId: string }) {
  const { getToken } = useAuth();
  const messages = useChatStore((s) => s.messages);
  const streamingText = useChatStore((s) => s.streamingText);
  const pendingUserText = useChatStore((s) => s.pendingUserText);
  const streamingState = useChatStore((s) => s.streamingState);
  const errorMessage = useChatStore((s) => s.errorMessage);
  const models = useChatStore((s) => s.models);
  const defaultModel = useChatStore((s) => s.defaultModel);
  const currentModel = useChatStore((s) => s.currentModel);
  const switchedTurnIds = useChatStore((s) => s.switchedTurnIds);
  const contextWarning = useChatStore((s) => s.contextWarning);
  const lastSwitch = useChatStore((s) => s.lastSwitch);
  const setModels = useChatStore((s) => s.setModels);
  const setCurrentModel = useChatStore((s) => s.setCurrentModel);
  const beginSend = useChatStore((s) => s.beginSend);
  const appendStreamToken = useChatStore((s) => s.appendStreamToken);
  const reconcileUserMessage = useChatStore((s) => s.reconcileUserMessage);
  const applyModelSwitch = useChatStore((s) => s.applyModelSwitch);
  const applyContextWarning = useChatStore((s) => s.applyContextWarning);
  const completeAssistant = useChatStore((s) => s.completeAssistant);
  const failStream = useChatStore((s) => s.failStream);

  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Stable getToken — Clerk hands a fresh function on every render.
  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;

  // Fetch models once per session.
  useEffect(() => {
    if (models.length > 0) return;
    (async () => {
      try {
        const res = await listModels(() => tokenRef.current());
        setModels(res.models, res.default);
      } catch (e) {
        console.error(e);
      }
    })();
  }, [models.length, setModels]);

  // Abort any in-flight stream on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Auto-scroll to the bottom on new content.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, streamingText, pendingUserText]);

  const onModelChange = useCallback(
    async (next: string) => {
      // Optimistic local update so the picker feels instant; the PATCH
      // persists it server-side and kicks off the token-count backfill.
      setCurrentModel(next);
      try {
        await updateConversation(() => tokenRef.current(), conversationId, {
          current_model: next,
        });
      } catch (e) {
        console.error(e);
      }
    },
    [conversationId, setCurrentModel],
  );

  const handleSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const text = input.trim();
      if (!text || streamingState !== "idle") return;
      setInput("");

      const idempotencyKey = newIdempotencyKey();
      beginSend(text);

      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      try {
        const stream = sendMessageStream(
          () => tokenRef.current(),
          conversationId,
          {
            content: [{ type: "text", text }],
            idempotencyKey,
            model: currentModel ?? undefined,
          },
          controller.signal,
        );
        for await (const event of stream) {
          if (event.event === "user_message") {
            reconcileUserMessage(event.data);
          } else if (event.event === "token") {
            appendStreamToken(event.data.text);
          } else if (event.event === "model_switch") {
            applyModelSwitch(event.data);
          } else if (event.event === "context_warning") {
            applyContextWarning(event.data);
          } else if (event.event === "done") {
            completeAssistant(event.data);
          } else if (event.event === "error") {
            failStream(event.data.message);
            break;
          }
        }
      } catch (err) {
        if ((err as DOMException)?.name === "AbortError") return;
        failStream((err as Error).message ?? "stream failed");
      }
    },
    [
      input,
      streamingState,
      conversationId,
      currentModel,
      beginSend,
      reconcileUserMessage,
      appendStreamToken,
      applyModelSwitch,
      applyContextWarning,
      completeAssistant,
      failStream,
    ],
  );

  const activeModel = currentModel ?? defaultModel ?? "";

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div className="text-sm font-medium text-gray-700">Chat</div>
        <label className="flex items-center gap-2 text-xs text-gray-500">
          <span>Model</span>
          <select
            value={activeModel}
            onChange={(e) => onModelChange(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 focus:border-gray-900 focus:outline-none"
            disabled={streamingState !== "idle" || models.length === 0}
          >
            {models.length === 0 ? (
              <option value="">Loading…</option>
            ) : (
              models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id} ({m.provider})
                </option>
              ))
            )}
          </select>
        </label>
      </header>

      {lastSwitch && (
        <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800">
          Switched to {lastSwitch.model} ({lastSwitch.provider}) — {lastSwitch.note}
        </div>
      )}
      {contextWarning && (
        <div className="border-b border-blue-200 bg-blue-50 px-6 py-2 text-xs text-blue-800">
          {contextWarning.message}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {messages.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              text={extractText(m.content)}
              meta={m}
              switched={!!switchedTurnIds[m.id]}
            />
          ))}
          {pendingUserText !== null && (
            <Bubble role="user" text={pendingUserText} pending />
          )}
          {streamingState === "streaming" && streamingText && (
            <Bubble role="assistant" text={streamingText} streaming />
          )}
          {errorMessage && (
            <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {errorMessage}
            </div>
          )}
        </div>
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-gray-200 bg-white p-4"
      >
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`Message ${activeModel || "the assistant"}…`}
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-900"
            disabled={streamingState !== "idle"}
          />
          <button
            type="submit"
            disabled={streamingState !== "idle" || !input.trim()}
            className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

function Bubble({
  role,
  text,
  pending,
  streaming,
  meta,
  switched,
}: {
  role: "user" | "assistant" | "system";
  text: string;
  pending?: boolean;
  streaming?: boolean;
  meta?: Message;
  switched?: boolean;
}) {
  const isUser = role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      {switched && !isUser && meta?.model_used && (
        <div className="mb-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800">
          Switched to {meta.model_used}
        </div>
      )}
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-4 py-2 text-sm ${
          isUser
            ? "bg-gray-900 text-white"
            : "border border-gray-200 bg-white text-gray-900"
        } ${pending ? "opacity-60" : ""}`}
      >
        {text || (streaming ? "…" : "")}
        {meta?.model_used && !isUser ? (
          <div className="mt-1 text-[10px] uppercase tracking-wide text-gray-400">
            {meta.model_used}
          </div>
        ) : null}
      </div>
    </div>
  );
}
