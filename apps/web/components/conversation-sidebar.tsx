"use client";

import { useEffect, useRef } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter, useParams } from "next/navigation";
import { useChatStore } from "@/lib/store";
import { createConversation, listConversations } from "@/lib/api";

export function ConversationSidebar() {
  const { getToken, isSignedIn } = useAuth();
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const conversations = useChatStore((s) => s.conversations);
  const setConversations = useChatStore((s) => s.setConversations);
  const prependConversation = useChatStore((s) => s.prependConversation);

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

  const onNew = async () => {
    const c = await createConversation(() => tokenRef.current());
    prependConversation(c);
    router.push(`/chat/${c.id}`);
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
            const active = params?.id === c.id;
            return (
              <button
                key={c.id}
                onClick={() => router.push(`/chat/${c.id}`)}
                className={`mb-1 block w-full truncate rounded px-3 py-2 text-left text-sm ${
                  active
                    ? "bg-gray-200 font-medium"
                    : "text-gray-700 hover:bg-gray-100"
                }`}
              >
                {c.title ?? "Untitled"}
              </button>
            );
          })
        )}
      </nav>
    </div>
  );
}
