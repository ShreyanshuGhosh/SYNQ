"use client";

import { useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { ChatWindow } from "@/components/chat-window";
import { useChatStore } from "@/lib/store";
import { getConversation } from "@/lib/api";

export default function ChatThreadPage() {
  const params = useParams<{ id: string }>();
  const conversationId = params?.id;
  const { getToken, isSignedIn } = useAuth();
  const setCurrent = useChatStore((s) => s.setCurrentConversation);
  const setMessages = useChatStore((s) => s.setMessages);

  // Clerk's useAuth returns a fresh getToken function on every render. Stash
  // it in a ref so this effect doesn't re-fire (and reset the streaming
  // state) every time something unrelated re-renders the component.
  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;

  useEffect(() => {
    if (!conversationId || !isSignedIn) return;
    setCurrent(conversationId);
    let cancelled = false;
    (async () => {
      try {
        const res = await getConversation(() => tokenRef.current(), conversationId);
        // Don't clobber an in-flight stream — only seed messages if we're idle.
        if (!cancelled && useChatStore.getState().streamingState === "idle") {
          setMessages(res.messages);
        }
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
    // setCurrent / setMessages come from Zustand and are stable across renders.
    // Intentionally exclude them and getToken so the effect runs once per conv.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, isSignedIn]);

  if (!conversationId) return null;
  return <ChatWindow conversationId={conversationId} />;
}
