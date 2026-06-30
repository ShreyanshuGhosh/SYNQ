"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import type {
  ContentBlock,
  FileStatusResponse,
  Message,
} from "@synq/shared-types";
import { useChatStore } from "@/lib/store";
import {
  getFileStatus,
  listModels,
  pinMessage,
  unpinMessage,
  sendMessageStream,
  updateConversation,
  uploadFile,
} from "@/lib/api";

const IMAGE_MIMES = new Set(["image/png", "image/jpeg", "image/webp"]);

type UploadState = {
  localId: string;
  filename: string;
  mime: string;
  sizeBytes: number;
  progress: number;
  fileId?: string;
  parseStatus?: "pending" | "done" | "failed";
  error?: string;
};

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

function attachmentSummary(content: ContentBlock[]): string {
  const n = content.filter(
    (b) => b.type === "image" || b.type === "file_ref",
  ).length;
  if (n === 0) return "";
  return ` · ${n} attachment${n === 1 ? "" : "s"}`;
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
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;

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

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, streamingText, pendingUserText]);

  useEffect(() => {
    const pendingIds = uploads
      .filter((u) => u.fileId && u.parseStatus === "pending")
      .map((u) => u.fileId!) as string[];
    if (pendingIds.length === 0) return;
    const interval = setInterval(async () => {
      const results = await Promise.allSettled(
        pendingIds.map((id) => getFileStatus(() => tokenRef.current(), id)),
      );
      setUploads((prev) =>
        prev.map((u) => {
          if (!u.fileId) return u;
          const r = results.find(
            (x): x is PromiseFulfilledResult<FileStatusResponse> =>
              x.status === "fulfilled" && x.value.file_id === u.fileId,
          );
          if (!r) return u;
          return {
            ...u,
            parseStatus: r.value.parse_status,
            error:
              r.value.parse_status === "failed"
                ? ((r.value.error as { message?: string } | null)?.message ?? "parse_failed")
                : u.error,
          };
        }),
      );
    }, 1000);
    return () => clearInterval(interval);
  }, [uploads]);

  const onModelChange = useCallback(
    async (next: string) => {
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

  const acceptFiles = useCallback(
    async (files: File[]) => {
      const next: UploadState[] = files.map((f) => ({
        localId: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        filename: f.name,
        mime: f.type,
        sizeBytes: f.size,
        progress: 0,
      }));
      setUploads((u) => [...u, ...next]);

      await Promise.all(
        files.map(async (f, i) => {
          const localId = next[i].localId;
          try {
            const res = await uploadFile(() => tokenRef.current(), f, {
              conversationId,
              onProgress: (pct) =>
                setUploads((u) =>
                  u.map((x) => (x.localId === localId ? { ...x, progress: pct } : x)),
                ),
            });
            setUploads((u) =>
              u.map((x) =>
                x.localId === localId
                  ? { ...x, progress: -1, fileId: res.file_id, parseStatus: res.parse_status }
                  : x,
              ),
            );
          } catch (e) {
            setUploads((u) =>
              u.map((x) =>
                x.localId === localId
                  ? { ...x, parseStatus: "failed", error: (e as Error).message }
                  : x,
              ),
            );
          }
        }),
      );
    },
    [conversationId],
  );

  const onPickFiles = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length) void acceptFiles(files);
      e.target.value = "";
    },
    [acceptFiles],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length) void acceptFiles(files);
    },
    [acceptFiles],
  );

  const onPaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData.items);
      const files = items
        .filter((it) => it.kind === "file")
        .map((it) => it.getAsFile())
        .filter((x): x is File => x !== null);
      if (files.length) void acceptFiles(files);
    },
    [acceptFiles],
  );

  const removeUpload = useCallback((localId: string) => {
    setUploads((u) => u.filter((x) => x.localId !== localId));
  }, []);

  const handleSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const text = input.trim();
      const readyAttachments = uploads.filter(
        (u) => u.fileId && u.parseStatus !== "failed",
      );
      if (streamingState !== "idle") return;
      if (!text && readyAttachments.length === 0) return;
      setInput("");
      setUploads([]);

      const content: ContentBlock[] = [];
      if (text) content.push({ type: "text", text });
      for (const u of readyAttachments) {
        if (!u.fileId) continue;
        if (IMAGE_MIMES.has(u.mime)) {
          content.push({ type: "image", file_id: u.fileId });
        } else {
          content.push({ type: "file_ref", file_id: u.fileId });
        }
      }

      const idempotencyKey = newIdempotencyKey();
      beginSend(text + attachmentSummary(content));

      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;

      try {
        const stream = sendMessageStream(
          () => tokenRef.current(),
          conversationId,
          { content, idempotencyKey, model: currentModel ?? undefined },
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
      uploads,
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
  const hasPendingParse = uploads.some((u) => u.fileId && u.parseStatus === "pending");

  return (
    <div
      className="flex h-full flex-col bg-[#090d1a]"
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
    >
      {/* Header */}
      <header className="flex items-center justify-between border-b border-white/[0.07] bg-[#0a0e1c] px-6 py-3">
        <div className="text-sm font-medium text-white">Chat</div>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <span>Model</span>
          <select
            value={activeModel}
            onChange={(e) => onModelChange(e.target.value)}
            className="rounded-lg border border-white/10 bg-[#111b30] px-2 py-1 text-xs text-white focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
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

      {/* Banners */}
      {lastSwitch && (
        <div className="border-b border-amber-500/20 bg-amber-500/10 px-6 py-2 text-xs text-amber-300">
          Switched to {lastSwitch.model} ({lastSwitch.provider}) — {lastSwitch.note}
        </div>
      )}
      {contextWarning && (
        <div className="border-b border-blue-500/20 bg-blue-500/10 px-6 py-2 text-xs text-blue-300">
          {contextWarning.message}
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="relative flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {messages.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              text={extractText(m.content) + attachmentSummary(m.content)}
              meta={m}
              conversationId={conversationId}
              switched={!!switchedTurnIds[m.id]}
              isPinned={pinnedIds.has(m.id)}
              onPin={async () => {
                try {
                  await pinMessage(() => tokenRef.current(), conversationId, m.id);
                  setPinnedIds((prev) => new Set(prev).add(m.id));
                } catch (e) {
                  console.error("pin failed", e);
                }
              }}
              onUnpin={async () => {
                try {
                  await unpinMessage(() => tokenRef.current(), conversationId, m.id);
                  setPinnedIds((prev) => {
                    const next = new Set(prev);
                    next.delete(m.id);
                    return next;
                  });
                } catch (e) {
                  console.error("unpin failed", e);
                }
              }}
            />
          ))}
          {pendingUserText !== null && (
            <Bubble role="user" text={pendingUserText} pending />
          )}
          {streamingState === "streaming" && streamingText && (
            <Bubble role="assistant" text={streamingText} streaming />
          )}
          {errorMessage && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">
              {errorMessage}
            </div>
          )}
        </div>
        {isDragging && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-[#090d1a]/70 backdrop-blur-sm">
            <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-8 py-4 text-sm font-medium text-blue-300">
              Drop files to attach
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-white/[0.07] bg-[#0a0e1c] p-4"
      >
        <div className="mx-auto flex max-w-2xl flex-col gap-2">
          {uploads.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {uploads.map((u) => (
                <UploadChip
                  key={u.localId}
                  upload={u}
                  onRemove={() => removeUpload(u.localId)}
                />
              ))}
            </div>
          )}
          {hasPendingParse && (
            <div className="text-[11px] text-amber-400">
              Files still processing — send now to attach as-is, or wait for parsing to finish.
            </div>
          )}
          <div className="flex gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.md"
              className="hidden"
              onChange={onPickFiles}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={streamingState !== "idle"}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-40"
              title="Attach file"
            >
              +
            </button>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPaste={onPaste}
              placeholder={`Message ${activeModel || "the assistant"}…`}
              className="flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-slate-500 outline-none transition-colors focus:border-blue-500/50 disabled:opacity-50"
              disabled={streamingState !== "idle"}
            />
            <button
              type="submit"
              disabled={
                streamingState !== "idle" ||
                (!input.trim() && uploads.filter((u) => u.fileId).length === 0)
              }
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function UploadChip({
  upload,
  onRemove,
}: {
  upload: UploadState;
  onRemove: () => void;
}) {
  const isFailed = upload.parseStatus === "failed";
  const isParsing = upload.fileId && upload.parseStatus === "pending";
  const isDone = upload.parseStatus === "done";
  const isUploading = upload.progress >= 0;

  return (
    <div
      className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
        isFailed
          ? "border-red-500/30 bg-red-500/10 text-red-300"
          : isDone
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            : "border-white/10 bg-white/[0.04] text-slate-300"
      }`}
    >
      <span className="max-w-[180px] truncate font-medium">{upload.filename}</span>
      <span className="text-[10px] text-slate-500">
        {(upload.sizeBytes / 1024).toFixed(0)}KB
      </span>
      {isUploading && (
        <span className="text-[10px] text-blue-400">{upload.progress}%</span>
      )}
      {isParsing && <span className="text-[10px] text-amber-400">parsing…</span>}
      {isDone && <span className="text-[10px] text-emerald-400">ready</span>}
      {isFailed && (
        <span className="text-[10px] text-red-400" title={upload.error}>
          failed
        </span>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="ml-1 rounded-full px-1 text-slate-500 hover:bg-white/[0.08] hover:text-white"
        aria-label="Remove attachment"
      >
        ×
      </button>
    </div>
  );
}

const JAEGER_BASE = process.env.NEXT_PUBLIC_JAEGER_URL ?? "http://localhost:16686";

function jaegerSearchUrl(conversationId: string, createdAt: string | null | undefined): string {
  const tags = JSON.stringify({ conversation_id: conversationId });
  const params = new URLSearchParams({ service: "context-switcher-api", tags });
  if (createdAt) {
    const t = Date.parse(createdAt);
    if (!Number.isNaN(t)) {
      params.set("start", String((t - 30_000) * 1000));
      params.set("end", String((t + 30_000) * 1000));
    }
  }
  return `${JAEGER_BASE}/search?${params.toString()}`;
}

function Bubble({
  role,
  text,
  pending,
  streaming,
  meta,
  conversationId,
  switched,
  isPinned,
  onPin,
  onUnpin,
}: {
  role: "user" | "assistant" | "system";
  text: string;
  pending?: boolean;
  streaming?: boolean;
  meta?: Message;
  conversationId?: string;
  switched?: boolean;
  isPinned?: boolean;
  onPin?: () => void;
  onUnpin?: () => void;
}) {
  const isUser = role === "user";
  const canPin = !pending && !streaming && !!meta?.id && !!onPin;
  const canTrace =
    !pending && !streaming && !isUser && !!conversationId && !!meta?.id;

  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      {switched && !isUser && meta?.model_used && (
        <div className="mb-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300">
          Switched to {meta.model_used}
        </div>
      )}
      <div className="relative max-w-[85%]">
        <div
          className={`whitespace-pre-wrap rounded-xl px-4 py-3 text-sm ${
            isUser
              ? "bg-blue-600 text-white"
              : "border border-white/[0.07] bg-[#0d1526] text-slate-100"
          } ${pending ? "opacity-60" : ""}`}
        >
          {text || (streaming ? "…" : "")}
          {meta?.model_used && !isUser ? (
            <div className="mt-1.5 flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-500">
              <span>{meta.model_used}</span>
              {canTrace && (
                <a
                  href={jaegerSearchUrl(conversationId!, meta?.created_at ?? null)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 inline-flex items-center rounded border border-white/[0.08] px-1 py-0 text-[10px] font-normal normal-case text-slate-500 transition-colors hover:border-blue-500/30 hover:text-blue-400"
                  title="Open Jaeger traces for this turn"
                >
                  trace
                </a>
              )}
            </div>
          ) : null}
        </div>
        {canPin && (
          <button
            type="button"
            onClick={isPinned ? onUnpin : onPin}
            className={`absolute -top-2 ${
              isUser ? "-left-2" : "-right-2"
            } rounded-full border px-2 py-0.5 text-[10px] font-medium shadow-sm transition-all ${
              isPinned
                ? "opacity-100 border-amber-500/30 bg-amber-500/10 text-amber-300 hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300"
                : "border-white/[0.08] bg-[#111b30] text-slate-500 opacity-0 group-hover:opacity-100 hover:border-amber-500/30 hover:text-amber-300"
            }`}
            title={isPinned ? "Click to unpin" : "Pin to context — survives compression"}
          >
            {isPinned ? "Pinned" : "Pin"}
          </button>
        )}
      </div>
    </div>
  );
}
