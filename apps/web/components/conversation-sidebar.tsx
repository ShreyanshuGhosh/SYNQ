"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter, useParams, usePathname } from "next/navigation";
import { useChatStore } from "@/lib/store";
import {
  createConversation,
  deleteConversation,
  listConversations,
  updateConversation,
} from "@/lib/api";

export function ConversationSidebar() {
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

  const onNew = async () => {
    const c = await createConversation(() => tokenRef.current());
    prependConversation(c);
    router.push(`/chat/${c.id}`);
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
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
        >
          + New chat
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-slate-500">No conversations yet.</p>
        ) : (
          conversations.map((c) => {
            const active = !onDashboard && params?.id === c.id;
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
                  className="mb-1 block w-full rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2 text-sm text-white focus:border-blue-500/50 focus:outline-none"
                />
              );
            }
            return (
              <div key={c.id} className="group relative mb-0.5">
                <button
                  onClick={() => router.push(`/chat/${c.id}`)}
                  className={`block w-full truncate rounded-lg px-3 py-2 pr-9 text-left text-sm transition-colors ${
                    active
                      ? "bg-white/[0.08] font-medium text-white"
                      : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
                  }`}
                >
                  {c.title ?? "Untitled"}
                </button>
                <button
                  aria-label="Conversation options"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuId(menuId === c.id ? null : c.id);
                  }}
                  className={`absolute right-1 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-slate-500 hover:bg-white/[0.08] hover:text-white ${
                    menuId === c.id ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                  }`}
                >
                  ⋯
                </button>
                {menuId === c.id && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="absolute right-1 top-full z-10 mt-1 w-32 overflow-hidden rounded-lg border border-white/[0.08] bg-[#111b30] shadow-xl"
                  >
                    <button
                      onClick={() => startRename(c.id, c.title)}
                      className="block w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-white/[0.06] hover:text-white"
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
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <button
            onClick={() => router.push("/dashboard")}
            className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
              onDashboard
                ? "bg-white/[0.08] font-medium text-white"
                : "text-slate-400 hover:bg-white/[0.05] hover:text-white"
            }`}
          >
            Dashboard
          </button>
        </div>
      </nav>
    </div>
  );
}
