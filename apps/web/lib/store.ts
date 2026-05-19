"use client";

import { create } from "zustand";
import type { Conversation, Message } from "@synq/shared-types";

type StreamingState = "idle" | "sending" | "streaming" | "error";

interface ChatState {
  conversations: Conversation[];
  currentConversationId: string | null;
  messages: Message[];
  /** Token buffer for the in-flight assistant turn; cleared when `done` arrives. */
  streamingText: string;
  /** Optimistic user message rendered before the server confirms. */
  pendingUserText: string | null;
  streamingState: StreamingState;
  errorMessage: string | null;

  setConversations: (rows: Conversation[]) => void;
  setCurrentConversation: (id: string | null) => void;
  setMessages: (rows: Message[]) => void;
  prependConversation: (c: Conversation) => void;

  beginSend: (text: string) => void;
  appendStreamToken: (text: string) => void;
  reconcileUserMessage: (m: Message) => void;
  completeAssistant: (m: Message) => void;
  failStream: (msg: string) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  streamingText: "",
  pendingUserText: null,
  streamingState: "idle",
  errorMessage: null,

  setConversations: (rows) => set({ conversations: rows }),
  setCurrentConversation: (id) =>
    set({
      currentConversationId: id,
      messages: [],
      streamingText: "",
      pendingUserText: null,
      streamingState: "idle",
      errorMessage: null,
    }),
  setMessages: (rows) => set({ messages: rows }),
  prependConversation: (c) =>
    set((s) => ({ conversations: [c, ...s.conversations] })),

  beginSend: (text) =>
    set({
      pendingUserText: text,
      streamingText: "",
      streamingState: "sending",
      errorMessage: null,
    }),

  appendStreamToken: (text) =>
    set((s) => ({
      streamingText: s.streamingText + text,
      streamingState: "streaming",
    })),

  reconcileUserMessage: (m) =>
    set((s) => ({
      messages: [...s.messages, m],
      pendingUserText: null,
    })),

  completeAssistant: (m) =>
    set((s) => ({
      messages: [...s.messages, m],
      streamingText: "",
      streamingState: "idle",
    })),

  failStream: (msg) =>
    set({
      streamingState: "error",
      errorMessage: msg,
      streamingText: "",
      pendingUserText: null,
    }),
}));
