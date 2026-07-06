"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter, useParams, usePathname } from "next/navigation";
import { LayoutDashboard, Plus } from "lucide-react";
import { useChatStore } from "@/lib/store";
import {
  createConversation,
  deleteConversation,
  listConversations,
  updateConversation,
} from "@/lib/api";
import { ProviderDot } from "@/components/provider-dot";
import { providerFromModel } from "@/lib/provider-identity";

export function ConversationSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { getToken, isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const pathname = usePathname();
  const onDashboard = pathname === "/dashboard";
  const conversations = useChatStore((s) => s.conversations);
  const setConversations = useChatStore((s) => s.setConversations);
  const prependConversation = useChatStore((s) => s.prependConversation);
  const renameConversation = useChatStore((s) => s.renameConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);

  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;

  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await listConversations(() => tokenRef.current());
        if (!cancelled) setConversations(res.conversations);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn]);

  useEffect(() => {
    if (menuId === null) return;
    const close = () => setMenuId(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menuId]);

  const goTo = (path: string) => {
    router.push(path);
    onNavigate?.();
  };

  const onNew = async () => {
    const c = await createConversation(() => tokenRef.current());
    prependConversation(c);
    goTo(`/chat/${c.id}`);
  };

  const startRename = (id: string, current: string | null) => {
    setMenuId(null);
    setEditingId(id);
    setDraftTitle(current ?? "");
  };

  const commitRename = async (id: string) => {
    const title = draftTitle.trim();
    setEditingId(null);
    const previous = conversations.find((c) => c.id === id)?.title ?? null;
    if (title === "" || title === previous) return;
    renameConversation(id, title);
    try {
      await updateConversation(() => tokenRef.current(), id, { title });
    } catch (e) {
      console.error(e);
      renameConversation(id, previous ?? "");
    }
  };

  const onDelete = async (id: string) => {
    setMenuId(null);
    if (!window.confirm("Delete this conversation? This cannot be undone.")) {
      return;
    }
    const snapshot = conversations;
    removeConversation(id);
    try {
      await deleteConversation(() => tokenRef.current(), id);
      if (params?.id === id) router.push("/dashboard");
    } catch (e) {
      console.error(e);
      setConversations(snapshot);
    }
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <button
        onClick={onNew}
        className="mx-4 mb-2 mt-3 flex items-center justify-center gap-2 rounded-lg bg-teal px-3.5 py-2 text-[13.5px] font-semibold text-[#07211d] transition-colors hover:bg-teal/85"
      >
        <Plus className="h-4 w-4" strokeWidth={2.5} />
        New chat
      </button>

      <div className="px-[18px] pb-1.5 pt-2.5 font-mono-data text-[11px] uppercase tracking-[0.1em] text-faint">
        Conversations
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-3 py-4 font-mono-data text-xs text-faint">No conversations yet.</p>
        ) : (
          conversations.map((c) => {
            const active = !onDashboard && params?.id === c.id;
            const provider = providerFromModel(c.current_model);
            if (editingId === c.id) {
              return (
                <input
                  key={c.id}
                  autoFocus
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onBlur={() => commitRename(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename(c.id);
                    else if (e.key === "Escape") setEditingId(null);
                  }}
                  className="mb-0.5 block w-full rounded-lg border border-line-2 bg-panel px-2.5 py-2 text-sm text-ink focus:border-teal focus:outline-none"
                />
              );
            }
            return (
              <div key={c.id} className="group relative mb-0.5">
                <button
                  onClick={() => goTo(`/chat/${c.id}`)}
                  className={`flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-[9px] pr-9 text-left transition-colors ${
                    active ? "bg-panel-2" : "hover:bg-panel"
                  }`}
                >
                  <span className="truncate text-[13.5px] font-medium text-ink">
                    {c.title ?? "Untitled"}
                  </span>
                  <span className="flex items-center gap-1.5 font-mono-data text-[11px] text-faint">
                    <ProviderDot provider={provider} />
                    {provider ?? "no model yet"}
                  </span>
                </button>
                <button
                  aria-label="Conversation options"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuId(menuId === c.id ? null : c.id);
                  }}
                  className={`absolute right-1 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-faint hover:bg-panel-2 hover:text-ink ${
                    menuId === c.id ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                  }`}
                >
                  ⋯
                </button>
                {menuId === c.id && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="absolute right-1 top-full z-10 mt-1 w-32 overflow-hidden rounded-lg border border-line-2 bg-panel-2 shadow-xl"
                  >
                    <button
                      onClick={() => startRename(c.id, c.title)}
                      className="block w-full px-3 py-2 text-left text-sm text-dim hover:bg-panel hover:text-ink"
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => onDelete(c.id)}
                      className="block w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </nav>

      <div className="border-t border-line p-2">
        <button
          onClick={() => goTo("/dashboard")}
          className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-[9px] text-left text-[13.5px] font-medium transition-colors ${
            onDashboard ? "bg-panel-2 text-ink" : "text-dim hover:bg-panel hover:text-ink"
          }`}
        >
          <LayoutDashboard className="h-[15px] w-[15px]" strokeWidth={2} />
          Dashboard
        </button>
      </div>
    </div>
  );
}
