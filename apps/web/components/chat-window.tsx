"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import type { ContentBlock, Message } from "@synq/shared-types";
import { useChatStore } from "@/lib/store";
import { sendMessageStream } from "@/lib/api";

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
  const beginSend = useChatStore((s) => s.beginSend);
  const appendStreamToken = useChatStore((s) => s.appendStreamToken);
  const reconcileUserMessage = useChatStore((s) => s.reconcileUserMessage);
  const completeAssistant = useChatStore((s) => s.completeAssistant);
  const failStream = useChatStore((s) => s.failStream);

  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

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
          () => getToken(),
          conversationId,
          {
            content: [{ type: "text", text }],
            idempotencyKey,
          },
          controller.signal,
        );
        for await (const event of stream) {
          if (event.event === "user_message") {
            reconcileUserMessage(event.data);
          } else if (event.event === "token") {
            appendStreamToken(event.data.text);
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
      getToken,
      beginSend,
      reconcileUserMessage,
      appendStreamToken,
      completeAssistant,
      failStream,
    ],
  );

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {messages.map((m) => (
            <Bubble key={m.id} role={m.role} text={extractText(m.content)} meta={m} />
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
            placeholder="Message Gemini…"
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
}: {
  role: "user" | "assistant" | "system";
  text: string;
  pending?: boolean;
  streaming?: boolean;
  meta?: Message;
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
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
