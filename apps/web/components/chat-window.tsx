"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { ChevronDown, Paperclip } from "lucide-react";
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
import { ProviderDot } from "@/components/provider-dot";
import { providerFromModel, providerTextClass } from "@/lib/provider-identity";

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

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function totalTokens(counts: Record<string, number> | null): number | null {
  if (!counts) return null;
  const sum = Object.values(counts).reduce((a, b) => a + b, 0);
  return sum > 0 ? sum : null;
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
  const conversations = useChatStore((s) => s.conversations);
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
  const activeProvider = providerFromModel(activeModel);
  const hasPendingParse = uploads.some((u) => u.fileId && u.parseStatus === "pending");

  // Header stats — all derived from real message data, nothing fabricated.
  const convTitle = conversations.find((c) => c.id === conversationId)?.title ?? "Untitled";
  const providerCount = new Set(messages.map((m) => m.model_used).filter(Boolean)).size;
  const estCost = messages.reduce((sum, m) => sum + (m.cost_usd ? parseFloat(m.cost_usd) : 0), 0);

  return (
    <div
      className="flex h-full flex-col bg-bg"
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
    >
      {/* Topbar */}
      <header className="flex h-[54px] shrink-0 items-center gap-3 border-b border-line bg-bg px-4 md:gap-[18px] md:px-[22px]">
        <span className="truncate text-sm font-semibold text-ink">{convTitle}</span>
        <span className="hidden shrink-0 font-mono-data text-[11px] text-faint sm:inline">
          {messages.length} turns
          {providerCount > 0 && ` · ${providerCount} provider${providerCount === 1 ? "" : "s"}`}
          {estCost > 0 && ` · $${estCost.toFixed(4)} est.`}
        </span>
        <span className="flex-1" />
        <div className="relative flex items-center gap-2 rounded-[7px] border border-line-2 bg-panel px-2.5 py-1.5">
          <ProviderDot provider={activeProvider} />
          <select
            value={activeModel}
            onChange={(e) => onModelChange(e.target.value)}
            className="appearance-none bg-transparent pr-4 font-mono-data text-xs text-ink outline-none disabled:opacity-50"
            disabled={streamingState !== "idle" || models.length === 0}
            aria-label="Active model"
          >
            {models.length === 0 ? (
              <option value="">loading…</option>
            ) : (
              models.map((m) => (
                <option key={m.id} value={m.id} className="bg-panel text-ink">
                  {m.id} ({m.provider})
                </option>
              ))
            )}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-faint"
            strokeWidth={2}
          />
        </div>
      </header>

      {/* Banners */}
      {contextWarning && (
        <div className="border-b border-line bg-teal/10 px-4 py-2 font-mono-data text-xs text-teal md:px-[22px]">
          {contextWarning.message}
        </div>
      )}

      {/* Thread */}
      <div ref={scrollRef} className="relative flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[860px] flex-col px-4 py-5 md:px-8">
          {messages.map((m, i) => {
            if (m.role === "user") {
              return (
                <UserEntry key={m.id} text={extractText(m.content) + attachmentSummary(m.content)} meta={m} />
              );
            }

            const priorAssistant = messages.slice(0, i).reverse().find((x) => x.role === "assistant");
            const isHandoff = !!switchedTurnIds[m.id];
            const justHappened = lastSwitch && lastSwitch.model === m.model_used;

            return (
              <div key={m.id}>
                {isHandoff && (
                  <HandoffRow
                    from={priorAssistant?.model_used ?? null}
                    to={m.model_used}
                    reason={justHappened ? lastSwitch!.note : null}
                  />
                )}
                <AssistantEntry
                  text={extractText(m.content)}
                  meta={m}
                  conversationId={conversationId}
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
              </div>
            );
          })}

          {pendingUserText !== null && <UserEntry text={pendingUserText} pending />}

          {streamingState === "streaming" && streamingText && (
            <AssistantEntry text={streamingText} streaming />
          )}

          {errorMessage && (
            <div className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 p-3 font-mono-data text-xs text-red-300">
              {errorMessage}
            </div>
          )}
        </div>
        {isDragging && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-bg/80 backdrop-blur-sm">
            <div className="rounded-xl border border-teal/30 bg-teal/10 px-8 py-4 text-sm font-medium text-teal">
              Drop files to attach
            </div>
          </div>
        )}
      </div>

      {/* Composer */}
      <form onSubmit={handleSubmit} className="border-t border-line bg-bg2">
        <div className="mx-auto flex max-w-[860px] flex-col gap-2 px-4 py-3.5 md:px-8">
          {uploads.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {uploads.map((u) => (
                <UploadChip key={u.localId} upload={u} onRemove={() => removeUpload(u.localId)} />
              ))}
            </div>
          )}
          {hasPendingParse && (
            <div className="font-mono-data text-[11px] text-amber">
              Files still processing — send now to attach as-is, or wait for parsing to finish.
            </div>
          )}
          <div className="flex items-end overflow-hidden rounded-lg border border-line-2 bg-bg transition-colors focus-within:border-teal">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={streamingState !== "idle"}
              className="flex items-center px-3 py-3 text-faint hover:text-teal disabled:cursor-not-allowed disabled:opacity-40"
              title="Attach file"
            >
              <Paperclip className="h-4 w-4" strokeWidth={2} />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.md"
              className="hidden"
              onChange={onPickFiles}
            />
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPaste={onPaste}
              placeholder={`Message ${activeModel || "SYNQ"}…`}
              className="flex-1 bg-transparent py-3 text-sm text-ink placeholder-faint outline-none disabled:opacity-50"
              disabled={streamingState !== "idle"}
            />
            <button
              type="submit"
              disabled={
                streamingState !== "idle" ||
                (!input.trim() && uploads.filter((u) => u.fileId).length === 0)
              }
              className="self-stretch border-l border-line-2 px-4 font-mono-data text-xs font-semibold text-dim hover:bg-panel hover:text-teal disabled:cursor-not-allowed disabled:opacity-40"
            >
              SEND ↵
            </button>
          </div>
          <div className="hidden justify-end gap-3.5 font-mono-data text-[10.5px] text-faint sm:flex">
            <span>↵ send</span>
            <span>⇧↵ newline</span>
          </div>
        </div>
      </form>
    </div>
  );
}

function UploadChip({ upload, onRemove }: { upload: UploadState; onRemove: () => void }) {
  const isFailed = upload.parseStatus === "failed";
  const isParsing = upload.fileId && upload.parseStatus === "pending";
  const isDone = upload.parseStatus === "done";
  const isUploading = upload.progress >= 0;

  return (
    <div
      className={`flex items-center gap-2 rounded-full border px-3 py-1 font-mono-data text-xs ${
        isFailed
          ? "border-red-500/30 bg-red-500/10 text-red-300"
          : isDone
            ? "border-brand-green/30 bg-brand-green/10 text-brand-green"
            : "border-line-2 bg-panel text-dim"
      }`}
    >
      <span className="max-w-[180px] truncate font-sans font-medium">{upload.filename}</span>
      <span className="text-[10px] text-faint">{(upload.sizeBytes / 1024).toFixed(0)}KB</span>
      {isUploading && <span className="text-[10px] text-gemini">{upload.progress}%</span>}
      {isParsing && <span className="text-[10px] text-amber">parsing…</span>}
      {isDone && <span className="text-[10px] text-brand-green">ready</span>}
      {isFailed && (
        <span className="text-[10px] text-red-400" title={upload.error}>
          failed
        </span>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="ml-1 rounded-full px-1 text-faint hover:bg-panel-2 hover:text-ink"
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

/** Full-bleed routing event row — the product's hero moment. Amber owns
 * this and only this: it always means "SYNQ made a routing decision". */
function HandoffRow({ from, to, reason }: { from: string | null; to: string | null; reason?: string | null }) {
  return (
    <div className="-mx-4 my-1 grid grid-cols-[76px_1fr] gap-3 border-y border-line bg-amber/10 px-4 py-3 md:-mx-8 md:grid-cols-[118px_1fr] md:gap-[22px] md:px-8">
      <span className="pt-0.5 font-mono-data text-[11px] font-medium text-amber">synq</span>
      <div className="font-mono-data text-xs leading-relaxed text-dim">
        <b className="font-medium text-ink">{from ?? "unknown"}</b>
        <span className="text-faint"> → </span>
        <b className="font-medium text-ink">{to ?? "unknown"}</b>
        {reason && (
          <>
            <br />
            <span className="text-faint">reason</span> {reason}
          </>
        )}
      </div>
    </div>
  );
}

function UserEntry({ text, meta, pending }: { text: string; meta?: Message; pending?: boolean }) {
  return (
    <div className="flex flex-col items-end gap-1.5 border-b border-line py-4">
      <div
        className={`max-w-[85%] rounded-[10px_10px_3px_10px] border border-line-2 bg-panel-2 px-4 py-[11px] text-sm leading-relaxed text-ink md:max-w-[72%] ${
          pending ? "opacity-60" : ""
        }`}
      >
        <span className="whitespace-pre-wrap">{text}</span>
      </div>
      {meta && (
        <span className="font-mono-data text-[11px] text-faint">
          you · #{meta.turn_index} · {formatTime(meta.created_at)}
        </span>
      )}
    </div>
  );
}

function AssistantEntry({
  text,
  streaming,
  meta,
  conversationId,
  isPinned,
  onPin,
  onUnpin,
}: {
  text: string;
  streaming?: boolean;
  meta?: Message;
  conversationId?: string;
  isPinned?: boolean;
  onPin?: () => void;
  onUnpin?: () => void;
}) {
  const provider = providerFromModel(meta?.model_used);
  const canPin = !streaming && !!meta?.id && !!onPin;
  const canTrace = !streaming && !!conversationId && !!meta?.id;
  const tokens = meta ? totalTokens(meta.token_counts) : null;
  const cost = meta?.cost_usd ? parseFloat(meta.cost_usd) : null;

  return (
    <div className="group grid grid-cols-[76px_1fr] gap-3 border-b border-line py-4 md:grid-cols-[118px_1fr] md:gap-[22px] md:py-[18px]">
      <div className="flex flex-col gap-1 pt-0.5 font-mono-data text-[11px] text-faint">
        <span className={`flex items-center gap-1.5 text-[11.5px] font-medium ${providerTextClass(provider)}`}>
          <ProviderDot provider={provider} />
          {meta?.model_used ?? (streaming ? "assistant" : "—")}
        </span>
        {meta && <span className="text-faint">#{meta.turn_index} · {formatTime(meta.created_at)}</span>}
      </div>
      <div className="relative min-w-0 text-sm leading-relaxed text-ink">
        <span className="whitespace-pre-wrap">{text || (streaming ? "…" : "")}</span>
        {meta && (tokens != null || cost != null || canTrace) && (
          <div className="mt-3 flex flex-wrap items-center gap-3 font-mono-data text-[10.5px] text-faint">
            {tokens != null && <span>{tokens.toLocaleString()} tok</span>}
            {cost != null && cost > 0 && <span>${cost.toFixed(4)}</span>}
            {canTrace && (
              <a
                href={jaegerSearchUrl(conversationId!, meta?.created_at ?? null)}
                target="_blank"
                rel="noopener noreferrer"
                className="border-b border-dotted border-faint hover:border-teal hover:text-teal"
                title="Open Jaeger traces for this turn"
              >
                trace
              </a>
            )}
          </div>
        )}
        {canPin && (
          <button
            type="button"
            onClick={isPinned ? onUnpin : onPin}
            className={`absolute -right-1 -top-1 rounded-full border px-2 py-0.5 font-mono-data text-[10px] font-medium transition-opacity ${
              isPinned
                ? "opacity-100 border-amber/30 bg-amber/10 text-amber hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300"
                : "border-line-2 bg-panel text-faint opacity-0 group-hover:opacity-100 hover:border-amber/30 hover:text-amber"
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
