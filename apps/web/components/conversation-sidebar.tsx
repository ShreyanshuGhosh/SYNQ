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

  // Which row is open for editing, and the open kebab menu.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);

  // Stable token getter — see chat page comment.
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

  // Close any open kebab menu when clicking elsewhere.
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
    // Optimistic — revert on failure.
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
      // If we deleted the conversation we're viewing, move away.
      if (params?.id === id) router.push("/dashboard");
    } catch (e) {
      console.error(e);
      setConversations(snapshot); // restore
    }
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          + New chat
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-gray-400">No conversations yet.</p>
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
                  className="mb-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
                />
              );
            }
            return (
              <div key={c.id} className="group relative mb-1">
                <button
                  onClick={() => router.push(`/chat/${c.id}`)}
                  className={`block w-full truncate rounded px-3 py-2 pr-9 text-left text-sm ${
                    active
                      ? "bg-gray-200 font-medium"
                      : "text-gray-700 hover:bg-gray-100"
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
                  className={`absolute right-1 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-gray-500 hover:bg-gray-200 ${
                    menuId === c.id
                      ? "opacity-100"
                      : "opacity-0 group-hover:opacity-100"
                  }`}
                >
                  ⋯
                </button>
                {menuId === c.id && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="absolute right-1 top-full z-10 mt-1 w-32 overflow-hidden rounded-md border border-gray-200 bg-white shadow-lg"
                  >
                    <button
                      onClick={() => startRename(c.id, c.title)}
                      className="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
                    >
                      Rename
                    </button>
                    <button
                      onClick={() => onDelete(c.id)}
                      className="block w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
        <div className="mt-3 border-t border-gray-200 pt-3">
          <button
            onClick={() => router.push("/dashboard")}
            className={`block w-full rounded px-3 py-2 text-left text-sm ${
              onDashboard
                ? "bg-gray-200 font-medium"
                : "text-gray-700 hover:bg-gray-100"
            }`}
          >
            Dashboard
          </button>
        </div>
      </nav>
    </div>
  );
}
