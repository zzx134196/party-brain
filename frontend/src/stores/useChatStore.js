import { create } from 'zustand'

const useChatStore = create((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  loading: false,
  streaming: false,

  setConversations: (conversations) => set({ conversations }),
  setCurrentConversation: (id) => set({ currentConversationId: id }),
  setMessages: (messages) => set({ messages }),
  setLoading: (loading) => set({ loading }),
  setStreaming: (streaming) => set({ streaming }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateLastMessage: (content) =>
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        const last = { ...messages[messages.length - 1] }
        last.content = (last.content || '') + content
        messages[messages.length - 1] = last
      }
      return { messages }
    }),

  appendThinkingContent: (text) =>
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        const last = { ...messages[messages.length - 1] }
        last.thinkingContent = (last.thinkingContent || '') + text
        messages[messages.length - 1] = last
      }
      return { messages }
    }),

  appendToolEvent: (event) =>
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        const last = { ...messages[messages.length - 1] }
        last.toolEvents = [...(last.toolEvents || []), event]
        messages[messages.length - 1] = last
      }
      return { messages }
    }),

  updateLastMessageMeta: (meta) =>
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        const last = { ...messages[messages.length - 1], ...meta }
        messages[messages.length - 1] = last
      }
      return { messages }
    }),

  clearChat: () => set({ currentConversationId: null, messages: [] }),
}))

export default useChatStore
