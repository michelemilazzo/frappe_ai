(function () {
	"use strict";

	if (window.FrappeAI?._initialized) {
		return;
	}


	// ─── STATE ───────────────────────────────────────────────────────────────────
	const MARKED_URL = "https://cdn.jsdelivr.net/npm/marked/marked.min.js";
	const TYPING_DELAY_MS = 200;
	const COPY_RESET_MS = 1500;
	const SUGGESTIONS = [
		"Show my open tasks",
		"Summarize recent orders",
		"List pending approvals",
	];

	let state = {
		isOpen: false,
		activeConversationId: null,
		conversations: [],
		isStreaming: false,
		streamInterval: null,
		hasUnread: false,
		isTyping: false,
		// ─── CHANGE 2: Voice + Attachment State ───
		isRecording: false,
		pendingAttachment: null,
		// ─── END CHANGE 2 ───
		// ─── CHANGE 3: Full-Screen Expand State ───
		isExpanded: false,
		// ─── END CHANGE 3 ───
		// ─── CHANGE 4: Search + History State ───
		isHistoryOpen: false,
		isSearchOpen: false,
		searchQuery: "",
		// ─── END CHANGE 4 ───
		// ─── CHANGE 5: Connected Header Dot State ───
		isConnected: true,
		// ─── END CHANGE 5 ───
	};

	const dom = {
		root: null,
		style: null,
		fab: null,
		fabIcon: null,
		badge: null,
		panel: null,
		// ─── CHANGE 3: Full-Screen Expand DOM Ref ───
		panelInner: null,
		expandButton: null,
		// ─── END CHANGE 3 ───
		// ─── CHANGE 4: Search + History DOM Refs ───
		titleWrap: null,
		historyButton: null,
		// ─── CHANGE 8: drawerSearchInput replaces header searchInput/searchButton/searchCloseButton ───
		drawerSearchInput: null,
		// ─── END CHANGE 8 ───
		historyDrawer: null,
		historyList: null,
		historyCloseButton: null,
		historyNewChatButton: null,
		// ─── END CHANGE 4 ───
		newChatButton: null,
		closeButton: null,
		messagesArea: null,
		// ─── CHANGE 2: Voice + Attachment DOM Refs ───
		micButton: null,
		attachButton: null,
		fileInput: null,
		attachmentPill: null,
		// ─── END CHANGE 2 ───
		textarea: null,
		sendButton: null,
		tokenCounter: null,
	};

let markedPromise = null;
let markedLoaded = false;
let typingTimeout = null;
let renderQueued = false;
// ─── CHANGE 3: Smooth Full-Screen Animation Guard ───
let panelAnimation = null;
// ─── END CHANGE 3 ───

	function _log() {
		if (window.frappe?.boot?.developer_mode === 1) {
			console.log.apply(console, arguments);
		}
	}

	function reducer(currentState, action) {
		switch (action.type) {
			case "LOAD_CONVERSATIONS": {
				return {
					...currentState,
					conversations: action.conversations,
					activeConversationId: action.activeConversationId,
				};
			}
			case "OPEN": {
				return { ...currentState, isOpen: true, hasUnread: false };
			}
			case "CLOSE": {
				// ─── CHANGE 3: Collapse Expanded State On Close ───
				return { ...currentState, isOpen: false, isExpanded: false };
				// ─── END CHANGE 3 ───
			}
			case "TOGGLE_OPEN": {
				const isOpen = !currentState.isOpen;
				return { ...currentState, isOpen, hasUnread: isOpen ? false : currentState.hasUnread };
			}
			case "NEW_CHAT": {
				return {
					...currentState,
					activeConversationId: null,
					isTyping: false,
					isStreaming: false,
					streamInterval: null,
					// ─── CHANGE 2: Clear Pending Attachment For New Chat ───
					pendingAttachment: null,
					// ─── END CHANGE 2 ───
					// ─── CHANGE 4: Close Search + History For New Chat ───
					isHistoryOpen: false,
					isSearchOpen: false,
					searchQuery: "",
					// ─── END CHANGE 4 ───
				};
			}
			// ─── CHANGE 2: Voice + Attachment Reducer Actions ───
			case "TOGGLE_RECORDING": {
				return { ...currentState, isRecording: !currentState.isRecording };
			}
			case "SET_ATTACHMENT": {
				return { ...currentState, pendingAttachment: action.attachment };
			}
			case "CLEAR_ATTACHMENT": {
				return { ...currentState, pendingAttachment: null };
			}
			// TODO: API — upload attachment before sending message
			// ─── END CHANGE 2 ───
			// ─── CHANGE 3: Full-Screen Expand Reducer Actions ───
			case "TOGGLE_EXPANDED": {
				return { ...currentState, isExpanded: !currentState.isExpanded };
			}
			case "COLLAPSE_EXPANDED": {
				return { ...currentState, isExpanded: false };
			}
			// ─── END CHANGE 3 ───
			// ─── CHANGE 4: Search + History Reducer Actions ───
			case "TOGGLE_HISTORY": {
				return {
					...currentState,
					isHistoryOpen: !currentState.isHistoryOpen,
					isSearchOpen: false,
					searchQuery: "",
				};
			}
			case "CLOSE_HISTORY": {
				return { ...currentState, isHistoryOpen: false };
			}
			case "OPEN_SEARCH": {
				return {
					...currentState,
					isSearchOpen: true,
					isHistoryOpen: false,
					searchQuery: "",
				};
			}
			case "CLOSE_SEARCH": {
				return { ...currentState, isSearchOpen: false, searchQuery: "" };
			}
			case "SET_SEARCH_QUERY": {
				return { ...currentState, searchQuery: action.searchQuery };
			}
			case "SELECT_CONVERSATION": {
				return {
					...currentState,
					activeConversationId: action.conversationId,
					isHistoryOpen: false,
					isSearchOpen: false,
					searchQuery: "",
				};
			}
			case "UPDATE_CONVERSATION_TITLE": {
				return {
					...currentState,
					conversations: currentState.conversations.map((c) =>
						c.id === action.conversationId ? { ...c, title: action.title } : c
					),
				};
			}
			case "DELETE_CONVERSATION": {
				const remaining = currentState.conversations.filter(
					(c) => c.id !== action.conversationId
				);
				const nextActive =
					currentState.activeConversationId === action.conversationId
						? (remaining[0]?.id || null)
						: currentState.activeConversationId;
				return {
					...currentState,
					conversations: remaining,
					activeConversationId: nextActive,
				};
			}
			// TODO: API — replace with server-side search in v2
			// ─── END CHANGE 4 ───
			case "LOAD_MESSAGES": {
				return {
					...currentState,
					conversations: currentState.conversations.map((c) => {
						if (c.id !== action.conversationId) return c;
						return {
							...c,
							messages: action.messages,
							title: action.title || c.title,
							last_message: action.last_message || c.last_message,
						};
					}),
				};
			}
			case "ADD_CONVERSATION": {
				return {
					...currentState,
					conversations: [action.conversation, ...currentState.conversations],
					activeConversationId: action.conversation.id,
				};
			}
			// ─── CHANGE B: Resolve pending conversation id once API responds ───
			case "RESOLVE_CONVERSATION_ID": {
				const updatedConversations = currentState.conversations.map((conversation) => {
					if (conversation.id !== action.localId) return conversation;
					return { ...conversation, id: action.realId, title: action.title, _pending: false };
				});
				return {
					...currentState,
					conversations: updatedConversations,
					activeConversationId:
						currentState.activeConversationId === action.localId
							? action.realId
							: currentState.activeConversationId,
				};
			}
			// ─── END CHANGE B ───
			case "ADD_MESSAGE": {
				return {
					...currentState,
					conversations: currentState.conversations.map((conversation) => {
						if (conversation.id !== action.conversationId) {
							return conversation;
						}

						return {
							...conversation,
							last_message: action.message.content,
							timestamp: "just now",
							messages: [...conversation.messages, action.message],
						};
					}),
				};
			}
			case "SHOW_TYPING": {
				return { ...currentState, isStreaming: true, isTyping: true };
			}
			case "START_STREAM": {
				return {
					...currentState,
					isStreaming: true,
					isTyping: false,
					streamInterval: action.streamInterval,
					conversations: currentState.conversations.map((conversation) => {
						if (conversation.id !== action.conversationId) {
							return conversation;
						}

						return {
							...conversation,
							streamingMessageId: action.message.id,
							messages: [...conversation.messages, action.message],
						};
					}),
				};
			}
			case "APPEND_STREAM_CHUNK": {
				return updateStreamingMessage(currentState, action.conversationId, (message) => ({
					...message,
					content: message.content + action.chunk,
				}));
			}
			case "FINISH_STREAM": {
				return finishStreamingMessage(currentState, action.conversationId, {
					isStreaming: false,
					streamInterval: null,
					hasUnread: currentState.isOpen ? currentState.hasUnread : true,
				});
			}
			case "STOP_STREAM": {
				return finishStreamingMessage(currentState, action.conversationId, {
					isStreaming: false,
					isTyping: false,
					streamInterval: null,
				});
			}
			default:
				return currentState;
		}
	}

	function updateStreamingMessage(currentState, conversationId, updater) {
		return {
			...currentState,
			conversations: currentState.conversations.map((conversation) => {
				if (conversation.id !== conversationId) {
					return conversation;
				}

				const messages = conversation.messages.map((message) => {
					return message.id === conversation.streamingMessageId ? updater(message) : message;
				});
				const lastMessage = messages[messages.length - 1];

				return {
					...conversation,
					last_message: lastMessage?.content || "",
					timestamp: "just now",
					messages,
				};
			}),
		};
	}

	function finishStreamingMessage(currentState, conversationId, statePatch) {
		return {
			...currentState,
			...statePatch,
			conversations: currentState.conversations.map((conversation) => {
				if (conversation.id !== conversationId) {
					return conversation;
				}

				const messages = conversation.messages.map((message) => {
					if (message.id !== conversation.streamingMessageId) {
						return message;
					}

					return { ...message, isStreaming: false };
				});
				const lastMessage = messages[messages.length - 1];

				return {
					...conversation,
					streamingMessageId: null,
					last_message: lastMessage?.content || conversation.last_message,
					timestamp: "just now",
					messages,
				};
			}),
		};
	}

	const SESSION_KEY = "frappe_ai_active_conversation";

	function setState(action, options) {
		const prev = state.activeConversationId;
		state = reducer(state, action);
		if (state.activeConversationId !== prev) {
			if (state.activeConversationId) {
				sessionStorage.setItem(SESSION_KEY, state.activeConversationId);
			} else {
				sessionStorage.removeItem(SESSION_KEY);
			}
		}
		if (options?.skipRender) {
			return;
		}
		queueRender();
	}

	function queueRender() {
		if (renderQueued) {
			return;
		}

		renderQueued = true;
		window.requestAnimationFrame(() => {
			renderQueued = false;
			render();
		});
	}

	function getActiveConversation() {
		return state.conversations.find((conversation) => {
			return conversation.id === state.activeConversationId;
		});
	}

	function getActiveConversationId() {
		return state.activeConversationId;
	}

	function createMessage(role, content, extra) {
		return {
			id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
			role,
			content,
			timestamp: "just now",
			createdAt: Date.now(),
			...(extra || {}),
		};
	}

	// ─── DOM BUILDER ─────────────────────────────────────────────────────────────
	function buildDom() {
		dom.root = document.createElement("div");
		dom.root.className = "frappe-ai-chat-root";
		dom.root.innerHTML = `
			<button
				class="frappe-ai-fab"
				type="button"
				aria-label="Open AI Assistant"
				aria-expanded="false"
				role="button"
				tabindex="0"
			>
				<span class="frappe-ai-fab-icon" aria-hidden="true">${getIcon("chat")}</span>
				<span class="frappe-ai-unread-badge" aria-hidden="true"></span>
			</button>
			<section class="frappe-ai-panel" role="dialog" aria-label="Frappe AI Chat" aria-modal="false">
				<div class="frappe-ai-panel-inner">
					<header class="frappe-ai-header">
						<div class="frappe-ai-title-wrap">
							<div class="frappe-ai-title">
								<!-- ─── CHANGE 5: Connected Header Dot ─── -->
								<span class="frappe-ai-status-dot" aria-hidden="true"></span>
								<!-- ─── END CHANGE 5 ─── -->
								<span class="frappe-ai-app-icon" aria-hidden="true">${getIcon("brain")}</span>
								<span>Frappe AI</span>
								<span class="frappe-ai-provider-badge"></span>
							</div>
							<!-- ─── CHANGE 4: Inline Chat Search Bar ─── -->
							<!-- ─── CHANGE 8: Search bar moved to history drawer; header slot kept as empty placeholder ─── -->
							<!-- ─── END CHANGE 8 ─── -->
							<!-- ─── END CHANGE 4 ─── -->
						</div>
						<div class="frappe-ai-header-actions">
							<!-- ─── CHANGE 4: Search + History Header Buttons ─── -->
							<button class="frappe-ai-icon-button fai-btn-history" type="button" data-action="history" aria-label="Chat history">
								${getIcon("history")}
							</button>
							<!-- ─── END CHANGE 4 ─── -->
							<!-- ─── CHANGE 6: New Chat button gets fai-btn-new-chat class for hide-in-expanded ─── -->
							<button class="frappe-ai-icon-button fai-btn-new-chat" type="button" data-action="new-chat" aria-label="New Chat">
								${getIcon("plus")}
							</button>
							<!-- ─── END CHANGE 6 ─── -->
							<!-- ─── CHANGE 3: Expand Header Button ─── -->
							<!-- ─── CHANGE 7: fai-btn-collapse class for highlight-in-expanded ─── -->
							<button class="frappe-ai-icon-button fai-btn-collapse" type="button" data-action="expand" aria-label="Expand Chat">
								${getIcon("expand")}
							</button>
							<!-- ─── END CHANGE 7 ─── -->
							<!-- ─── END CHANGE 3 ─── -->
							<!-- ─── CHANGE 7: fai-btn-close class for highlight-in-expanded ─── -->
							<button class="frappe-ai-icon-button fai-btn-close" type="button" data-action="close" aria-label="Close">
								${getIcon("close")}
							</button>
							<!-- ─── END CHANGE 7 ─── -->
						</div>
					</header>
					<div class="frappe-ai-messages-shell">
						<div class="frappe-ai-messages" role="log" aria-live="polite" aria-relevant="additions"></div>
						<!-- ─── CHANGE 4: History Drawer ─── -->
						<aside class="frappe-ai-history-drawer" aria-label="Conversation history">
							<div class="frappe-ai-history-header">
								<strong>Conversations</strong>
								<button class="frappe-ai-icon-button" type="button" data-action="close-history" aria-label="Close History">
									${getIcon("close")}
								</button>
							</div>
							<button class="frappe-ai-history-primary-new" type="button" data-action="history-new-chat">
								${getIcon("plus")}
								<span>New Conversation</span>
							</button>
							<input class="frappe-ai-drawer-search-input" id="frappe-ai-drawer-search" type="text" name="frappe-ai-drawer-search" placeholder="Search conversations..." aria-label="Search conversations" />
							<div class="frappe-ai-history-list"></div>
						</aside>
						<!-- ─── END CHANGE 4 ─── -->
					</div>
					<form class="frappe-ai-input-area">
						<!-- ─── CHANGE 2: Attachment Pill + Voice/Attachment Controls ─── -->
						<div class="frappe-ai-attachment-pill"></div>
						<input class="frappe-ai-file-input" type="file" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.docx" hidden />
						<!-- ─── END CHANGE 2 ─── -->
						<div class="frappe-ai-input-row">
							<!-- ─── CHANGE 2: Voice + Attachment Buttons ─── -->
							<button class="frappe-ai-input-icon-button" type="button" data-action="voice" aria-label="Record voice message">
								${getIcon("mic")}
							</button>
							<button class="frappe-ai-input-icon-button" type="button" data-action="attach" aria-label="Attach file">
								${getIcon("paperclip")}
							</button>
							<!-- ─── END CHANGE 2 ─── -->
							<div class="frappe-ai-textarea-wrap">
								<textarea
									class="frappe-ai-textarea"
									rows="1"
									placeholder="Ask anything about your data..."
									aria-label="Ask anything about your data"
								></textarea>
							</div>
							<button class="frappe-ai-send-button" type="submit" aria-label="Send Message">
								${getIcon("send")}
							</button>
						</div>
						<div class="frappe-ai-token-counter">~0 tokens</div>
					</form>
				</div>
			</section>
		`;

		document.body.appendChild(dom.root);

		dom.fab = dom.root.querySelector(".frappe-ai-fab");
		dom.fabIcon = dom.root.querySelector(".frappe-ai-fab-icon");
		dom.badge = dom.root.querySelector(".frappe-ai-unread-badge");
		dom.panel = dom.root.querySelector(".frappe-ai-panel");
		// ─── CHANGE 3: Full-Screen Expand DOM Ref Init ───
		dom.panelInner = dom.root.querySelector(".frappe-ai-panel-inner");
		dom.expandButton = dom.root.querySelector('[data-action="expand"]');
		// ─── END CHANGE 3 ───
		// ─── CHANGE 4: Search + History DOM Ref Init ───
		dom.titleWrap = dom.root.querySelector(".frappe-ai-title-wrap");
		dom.historyButton = dom.root.querySelector('[data-action="history"]');
		// ─── CHANGE 8: Search refs moved to drawer; header search elements removed ───
		dom.searchInput = null;
		dom.searchButton = null;
		dom.searchCloseButton = null;
		dom.drawerSearchInput = dom.root.querySelector(".frappe-ai-drawer-search-input");
		// ─── END CHANGE 8 ───
		dom.historyDrawer = dom.root.querySelector(".frappe-ai-history-drawer");
		dom.historyList = dom.root.querySelector(".frappe-ai-history-list");
		dom.historyCloseButton = dom.root.querySelector('[data-action="close-history"]');
		dom.historyNewChatButton = dom.root.querySelector('[data-action="history-new-chat"]');
		// ─── END CHANGE 4 ───
		dom.newChatButton = dom.root.querySelector('[data-action="new-chat"]');
		dom.closeButton = dom.root.querySelector('[data-action="close"]');
		dom.messagesArea = dom.root.querySelector(".frappe-ai-messages");
		// ─── CHANGE 2: Voice + Attachment DOM Ref Init ───
		dom.micButton = dom.root.querySelector('[data-action="voice"]');
		dom.attachButton = dom.root.querySelector('[data-action="attach"]');
		dom.fileInput = dom.root.querySelector(".frappe-ai-file-input");
		dom.attachmentPill = dom.root.querySelector(".frappe-ai-attachment-pill");
		// ─── END CHANGE 2 ───
		dom.textarea = dom.root.querySelector(".frappe-ai-textarea");
		dom.sendButton = dom.root.querySelector(".frappe-ai-send-button");
		dom.tokenCounter = dom.root.querySelector(".frappe-ai-token-counter");
	}

	function getIcon(name) {
		const icons = {
			brain: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
					<path d="M9 3.5a3 3 0 0 0-3 3v.3a3 3 0 0 0-2 2.8c0 1 .5 1.9 1.2 2.4A3.4 3.4 0 0 0 5 13.2a3.3 3.3 0 0 0 3.3 3.3H9"/>
					<path d="M15 3.5a3 3 0 0 1 3 3v.3a3 3 0 0 1 2 2.8c0 1-.5 1.9-1.2 2.4.1.4.2.8.2 1.2a3.3 3.3 0 0 1-3.3 3.3H15"/>
					<path d="M9 3.5v17"/>
					<path d="M15 3.5v17"/>
					<path d="M8.5 8H11"/>
					<path d="M13 8h2.5"/>
					<path d="M8.5 13H11"/>
					<path d="M13 13h2.5"/>
					<path d="M19.5 18.5l.5 1.2 1.2.5-1.2.5-.5 1.2-.5-1.2-1.2-.5 1.2-.5.5-1.2Z"/>
				</svg>`,
			chat: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>
					<path d="M8 9h8"/>
					<path d="M8 13h5"/>
				</svg>`,
			close: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
					<path d="M6 6l12 12"/>
					<path d="M18 6L6 18"/>
				</svg>`,
			copy: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<rect x="9" y="9" width="11" height="11" rx="2"/>
					<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
				</svg>`,
			chevron: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
					<path d="m6 9 6 6 6-6"/>
				</svg>`,
			// ─── CHANGE 3: Expand/Collapse Icons ───
			expand: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M15 3h6v6"/>
					<path d="m21 3-7 7"/>
					<path d="M9 21H3v-6"/>
					<path d="m3 21 7-7"/>
				</svg>`,
			collapse: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M9 3v6H3"/>
					<path d="m3 9 7-7"/>
					<path d="M15 21v-6h6"/>
					<path d="m21 15-7 7"/>
				</svg>`,
			// ─── END CHANGE 3 ───
			// ─── CHANGE 4: Search + History Icons ───
			search: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="11" cy="11" r="7"/>
					<path d="m20 20-3.5-3.5"/>
				</svg>`,
			history: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M3 12a9 9 0 1 0 3-6.7"/>
					<path d="M3 4v5h5"/>
					<path d="M12 7v5l3 2"/>
				</svg>`,
			// ─── END CHANGE 4 ───
			// ─── CHANGE 5: Suggestion Chip Icons ───
			checklist: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="m4 7 2 2 4-4"/>
					<path d="M12 8h8"/>
					<path d="m4 17 2 2 4-4"/>
					<path d="M12 18h8"/>
				</svg>`,
			barChart: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M4 20V10"/>
					<path d="M10 20V4"/>
					<path d="M16 20v-7"/>
					<path d="M22 20H2"/>
				</svg>`,
			inbox: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M22 12h-6l-2 3h-4l-2-3H2"/>
					<path d="m5.5 5-3.2 7v6a2 2 0 0 0 2 2h15.4a2 2 0 0 0 2-2v-6L18.5 5Z"/>
				</svg>`,
			// ─── END CHANGE 5 ───
			// ─── CHANGE 2: Voice + Attachment Icons ───
			mic: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/>
					<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
					<path d="M12 19v3"/>
				</svg>`,
			paperclip: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="m21.4 11.6-8.5 8.5a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 1 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>
				</svg>`,
			// ─── END CHANGE 2 ───
			plus: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
					<path d="M12 5v14"/>
					<path d="M5 12h14"/>
				</svg>`,
			regenerate: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M21 12a9 9 0 0 1-15 6.7"/>
					<path d="M3 12a9 9 0 0 1 15-6.7"/>
					<path d="M18 3v4h-4"/>
					<path d="M6 21v-4h4"/>
				</svg>`,
			send: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="m22 2-7 20-4-9-9-4Z"/>
					<path d="M22 2 11 13"/>
				</svg>`,
			stop: `
				<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
					<rect x="7" y="7" width="10" height="10" rx="1.5"/>
				</svg>`,
			edit: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
					<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>
				</svg>`,
			trash: `
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
					<path d="M3 6h18"/>
					<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
					<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
				</svg>`,
		};

		return icons[name] || "";
	}

	// ─── STYLES ──────────────────────────────────────────────────────────────────
	function injectStyles() {
		if (document.getElementById("frappe-ai-chat-styles")) {
			return;
		}

		dom.style = document.createElement("style");
		dom.style.id = "frappe-ai-chat-styles";
		dom.style.textContent = `
			.frappe-ai-chat-root,
			.frappe-ai-chat-root * {
				box-sizing: border-box;
			}

			.frappe-ai-chat-root {
				font-family: var(--font-stack);
				color: var(--text-color);
				/* // ─── CHANGE 5: Espresso Dark Mode Surface Tokens ─── */
				--frappe-ai-canvas: var(--bg-color);
				--frappe-ai-surface: var(--card-bg, var(--fg-color));
				--frappe-ai-raised: var(--modal-bg, var(--card-bg, var(--fg-color)));
				--frappe-ai-control: var(--control-bg, var(--bg-color));
				--frappe-ai-hover: var(--fg-hover-color, var(--control-bg, var(--bg-color)));
				--frappe-ai-subtle: var(--subtle-fg, var(--control-bg, var(--bg-color)));
				--frappe-ai-message-surface: var(--control-bg, var(--card-bg, var(--fg-color)));
				--frappe-ai-on-primary: var(--neutral, var(--fg-color));
				--frappe-ai-shadow-color: color-mix(in srgb, var(--neutral-black, var(--text-color)) 16%, transparent);
				--frappe-ai-soft-shadow-color: color-mix(in srgb, var(--neutral-black, var(--text-color)) 8%, transparent);
				/* // ─── END CHANGE 5 ─── */
			}

			.frappe-ai-fab {
				align-items: center;
				background: var(--btn-primary, var(--primary-color));
				border: 0;
				border-radius: 50%;
				bottom: 24px;
				box-shadow: var(--shadow-base), 0 8px 32px var(--frappe-ai-shadow-color);
				color: var(--frappe-ai-on-primary);
				cursor: pointer;
				display: flex;
				height: 52px;
				justify-content: center;
				/* // ─── CHANGE 1: Bottom-Right Reposition ─── */
				right: 24px;
				/* // ─── END CHANGE 1 ─── */
				padding: 0;
				position: fixed;
				transition: box-shadow 180ms ease, transform 180ms ease;
				width: 52px;
				z-index: 1040;
			}

			/* // ─── CHANGE 3: Hide FAB While Expanded (desktop only) ─── */
			@media (min-width: 769px) {
				.frappe-ai-chat-root.is-expanded .frappe-ai-fab {
					display: none;
				}
			}
			/* // ─── END CHANGE 3 ─── */

			.frappe-ai-fab:hover {
				box-shadow: var(--shadow-base), 0 12px 36px var(--frappe-ai-shadow-color);
				transform: translateY(-2px) scale(1.05);
			}

			.frappe-ai-fab:focus-visible,
			.frappe-ai-icon-button:focus-visible,
			/* // ─── CHANGE 2: Voice + Attachment Focus State ─── */
			.frappe-ai-input-icon-button:focus-visible,
			/* // ─── END CHANGE 2 ─── */
			.frappe-ai-send-button:focus-visible,
			.frappe-ai-suggestion-chip:focus-visible,
			/* // ─── CHANGE 5: Textarea Uses Wrapper Focus Ring ─── */
			.frappe-ai-copy-code:focus-visible,
			/* // ─── END CHANGE 5 ─── */
			.frappe-ai-bubble-action:focus-visible {
				outline: 2px solid var(--primary-color);
				outline-offset: 2px;
			}

			.frappe-ai-fab-icon,
			.frappe-ai-fab-icon svg {
				display: block;
				height: 24px;
				width: 24px;
			}

			.frappe-ai-unread-badge {
				background: var(--red-500, var(--primary-color));
				border: 2px solid var(--frappe-ai-raised);
				border-radius: 50%;
				height: 12px;
				position: absolute;
				right: 3px;
				top: 3px;
				transform: scale(0);
				transition: transform 160ms ease;
				width: 12px;
			}

			.frappe-ai-unread-badge.is-visible {
				transform: scale(1);
			}

			.frappe-ai-panel {
				background: var(--frappe-ai-raised);
				border: 1px solid var(--border-color);
				border-radius: 12px;
				bottom: 88px;
				box-shadow: var(--shadow-base), 0 8px 32px var(--frappe-ai-shadow-color);
				display: flex;
				flex-direction: column;
				height: 560px;
				opacity: 0;
				overflow: hidden;
				pointer-events: none;
				position: fixed;
				/* // ─── CHANGE 1: Bottom-Right Reposition ─── */
				right: 24px;
				/* // ─── END CHANGE 1 ─── */
				transform: translateY(16px);
				/* // ─── CHANGE 3: Smooth Full-Screen Animation Polish ─── */
				transform-origin: top left;
				transition: opacity 220ms ease-out, transform 220ms ease-out,
					border-radius 260ms ease-in-out, box-shadow 260ms ease-in-out;
				will-change: transform, opacity, border-radius;
				/* // ─── END CHANGE 3 ─── */
				width: 380px;
				z-index: 1039;
			}

			.frappe-ai-panel.is-open {
				opacity: 1;
				pointer-events: auto;
				transform: translateY(0);
			}

			.frappe-ai-fab.is-dragging {
				box-shadow: var(--shadow-base), 0 16px 48px var(--frappe-ai-shadow-color);
				cursor: grabbing;
				transition: box-shadow 120ms ease;
			}

			/* // ─── CHANGE 3: Full-Screen Expand Mode (desktop only — mobile uses popover) ─── */
			.frappe-ai-panel-inner {
				display: flex;
				flex: 1 1 auto;
				flex-direction: column;
				height: 100%;
				min-height: 0;
				width: 100%;
			}

			@media (min-width: 769px) {
				.frappe-ai-panel.is-expanded {
					background: var(--frappe-ai-canvas);
					border-radius: 0;
					bottom: 0;
					box-shadow: none;
					height: 100dvh;
					left: 0;
					right: 0;
					top: 0;
					width: 100dvw;
					z-index: 9999;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-panel-inner {
					background: var(--frappe-ai-raised);
					margin: 0 auto;
					max-width: 760px;
					min-width: 0;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-header,
				.frappe-ai-panel.is-expanded .frappe-ai-input-area {
					padding-left: 16px;
					padding-right: 16px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-messages {
					padding: 20px 18px;
				}
			}

			@supports not (height: 100dvh) {
				@media (min-width: 769px) {
					.frappe-ai-panel.is-expanded {
						height: 100vh;
						width: 100vw;
					}
				}
			}

			/* // ─── CHANGE 3: Desktop Full-Screen Claude-Like Layout ─── */
			@media (min-width: 769px) {
				.frappe-ai-panel.is-expanded .frappe-ai-panel-inner {
					background: var(--frappe-ai-canvas);
					display: grid;
					grid-template-columns: 268px minmax(0, 1fr);
					grid-template-rows: 52px minmax(0, 1fr) auto;
					margin: 0;
					max-width: none;
					width: 100%;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-header {
					background: var(--frappe-ai-canvas);
					border-bottom: 0;
					box-shadow: 0 1px 0 var(--border-color);
					grid-column: 2;
					grid-row: 1;
					padding: 0 22px 0 24px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-title {
					font-weight: 700;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-messages-shell {
					display: contents;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-history-drawer {
					background: var(--frappe-ai-subtle);
					border-right: 1px solid var(--border-color);
					box-shadow: 8px 0 24px var(--frappe-ai-soft-shadow-color);
					bottom: auto;
					grid-column: 1;
					grid-row: 1 / 4;
					left: auto;
					padding: 8px 8px;
					position: relative;
					top: auto;
					transform: none;
					width: auto;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-history-header {
					height: 32px;
					margin-bottom: 6px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-history-header .frappe-ai-icon-button {
					display: none;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-history-list {
					border-top: 1px solid var(--border-color);
					gap: 3px;
					padding-top: 10px;
					scrollbar-color: var(--scrollbar-thumb-color, var(--border-color)) var(--scrollbar-track-color, transparent);
					scrollbar-width: thin;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-conversation-row {
					border: 0;
					border-radius: 6px;
					padding: 4px 6px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-conversation-snippet,
				.frappe-ai-panel.is-expanded .frappe-ai-conversation-time {
					display: none;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-messages {
					background: var(--frappe-ai-canvas);
					grid-column: 2;
					grid-row: 2;
					padding: 8px 32px 28px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-message,
				.frappe-ai-panel.is-expanded .frappe-ai-search-results,
				.frappe-ai-panel.is-expanded .frappe-ai-search-empty,
				.frappe-ai-panel.is-expanded .frappe-ai-empty-state {
					margin-left: auto;
					margin-right: auto;
					max-width: 760px;
					width: min(760px, 100%);
				}

				.frappe-ai-panel.is-expanded .frappe-ai-bubble {
					max-width: min(680px, 88%);
				}

				.frappe-ai-panel.is-expanded .frappe-ai-message.is-user .frappe-ai-bubble {
					max-width: min(620px, 78%);
				}

				.frappe-ai-panel.is-expanded .frappe-ai-input-area {
					align-self: end;
					background: var(--frappe-ai-canvas);
					border-top: 0;
					grid-column: 2;
					grid-row: 3;
					padding: 12px 32px 20px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-input-row {
					background: var(--bg-color);
					border: 1px solid var(--border-color);
					border-radius: 12px;
					box-shadow: 0 1px 4px color-mix(in srgb, var(--gray-800, #000) 8%, transparent);
					margin: 0 auto;
					max-width: 760px;
					padding: 6px 8px;
					transition: border-color 140ms ease, box-shadow 140ms ease;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-input-row:focus-within {
					border-color: color-mix(in srgb, var(--primary-color) 50%, var(--border-color));
					box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 12%, transparent);
				}

				.frappe-ai-panel.is-expanded .frappe-ai-textarea {
					background: transparent;
					border: 0;
					min-height: 40px;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-textarea-wrap {
					background: transparent;
					border: 0;
					box-shadow: none;
					padding: 0;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-textarea-wrap:focus-within {
					box-shadow: none;
				}

				.frappe-ai-panel.is-expanded .frappe-ai-token-counter {
					margin: 4px auto 0;
					max-width: 760px;
					padding-right: 2px;
				}
			}
			/* // ─── END CHANGE 3 ─── */
			/* // ─── END CHANGE 3 ─── */

			/* // ─── CHANGE 6: Hide New Chat + History Buttons In Full-Screen Mode (desktop only) ─── */
			@media (min-width: 769px) {
				.fai-expanded .fai-btn-new-chat,
				.fai-expanded .fai-btn-history {
					display: none;
				}
			}
			/* // ─── END CHANGE 6 ─── */

			/* // ─── CHANGE 7: Highlight Close + Collapse Buttons In Full-Screen Mode (desktop only) ─── */
			@media (min-width: 769px) {
				.fai-expanded .fai-btn-close,
				.fai-expanded .fai-btn-collapse {
					background: var(--btn-default-bg, var(--control-bg));
					border: 1px solid var(--border-color);
					border-radius: var(--border-radius);
					color: var(--text-color);
					height: 28px;
					width: 28px;
				}

				.fai-expanded .fai-btn-close:hover,
				.fai-expanded .fai-btn-collapse:hover {
					background: var(--btn-default-hover-bg, var(--frappe-ai-hover));
					border-color: var(--gray-400, var(--border-color));
				}
			}
			/* // ─── END CHANGE 7 ─── */

			.frappe-ai-header {
				align-items: center;
				/* // ─── CHANGE 5: Frosted Header Polish ─── */
				backdrop-filter: blur(8px);
				background: color-mix(in srgb, var(--frappe-ai-raised) 85%, transparent);
				/* // ─── END CHANGE 5 ─── */
				border-bottom: 1px solid var(--border-color);
				display: flex;
				flex: 0 0 52px;
				height: 52px;
				justify-content: space-between;
				padding: 0 12px 0 14px;
			}

			/* // ─── CHANGE 4: Inline Search Header Area ─── */
			.frappe-ai-title-wrap {
				display: grid;
				flex: 1 1 auto;
				min-width: 0;
				overflow: hidden;
			}

			.frappe-ai-title,
			.frappe-ai-searchbar {
				grid-area: 1 / 1;
				transition: opacity 180ms ease, transform 180ms ease;
			}
			/* // ─── END CHANGE 4 ─── */

			.frappe-ai-title {
				align-items: center;
				color: var(--text-color);
				display: flex;
				font-size: var(--font-size-base);
				font-weight: 600;
				gap: 8px;
				min-width: 0;
			}

			.frappe-ai-provider-badge {
				background: var(--control-bg, var(--frappe-ai-subtle));
				border: 1px solid var(--border-color);
				border-radius: 4px;
				color: var(--text-muted);
				font-size: 10px;
				font-weight: 500;
				letter-spacing: 0.02em;
				line-height: 1;
				padding: 2px 6px;
				text-transform: capitalize;
			}

			.frappe-ai-provider-badge:empty {
				display: none;
			}

			/* // ─── CHANGE 5: Connected Header Dot ─── */
			.frappe-ai-status-dot {
				background: var(--text-muted);
				border-radius: 50%;
				display: inline-flex;
				flex: 0 0 6px;
				height: 6px;
				width: 6px;
			}

			.frappe-ai-status-dot.is-connected {
				background: #29a329;
			}
			/* // ─── END CHANGE 5 ─── */

			.frappe-ai-app-icon,
			.frappe-ai-app-icon svg {
				color: var(--primary-color);
				display: block;
				height: 20px;
				width: 20px;
			}

			.frappe-ai-header-actions {
				align-items: center;
				display: flex;
				gap: 4px;
			}

			/* // ─── CHANGE 4: Inline Search Bar ─── */
			/* // ─── CHANGE 8: Header searchbar CSS removed — search moved to history drawer ─── */
			/* // ─── END CHANGE 8 ─── */
			/* // ─── END CHANGE 4 ─── */

			.frappe-ai-icon-button,
			.frappe-ai-bubble-action {
				align-items: center;
				background: transparent;
				border: 0;
				border-radius: var(--border-radius);
				color: var(--text-muted);
				cursor: pointer;
				display: inline-flex;
				height: 28px;
				justify-content: center;
				padding: 0;
				transition: background 140ms ease, color 140ms ease;
				width: 28px;
			}

			.frappe-ai-icon-button:hover,
			.frappe-ai-bubble-action:hover {
				background: var(--frappe-ai-hover);
				color: var(--text-color);
			}

			.frappe-ai-icon-button svg,
			.frappe-ai-bubble-action svg {
				height: 16px;
				width: 16px;
			}

			/* // ─── CHANGE 4: Messages Shell + History Drawer ─── */
			.frappe-ai-messages-shell {
				display: flex;
				flex: 1 1 auto;
				min-height: 0;
				overflow: hidden;
				position: relative;
			}
			/* // ─── END CHANGE 4 ─── */

			.frappe-ai-messages {
				background: var(--frappe-ai-canvas);
				display: flex;
				flex: 1 1 auto;
				flex-direction: column;
				gap: 12px;
				overflow-y: auto;
				padding: 16px;
				scroll-behavior: smooth;
				scrollbar-color: var(--scrollbar-thumb-color, var(--border-color)) var(--scrollbar-track-color, transparent);
				scrollbar-width: thin;
				width: 100%;
			}

			.frappe-ai-messages::-webkit-scrollbar {
				width: 6px;
			}

			.frappe-ai-messages::-webkit-scrollbar-track {
				background: transparent;
			}

			.frappe-ai-messages::-webkit-scrollbar-thumb {
				background: var(--scrollbar-thumb-color, var(--border-color));
				border-radius: 999px;
			}

			.frappe-ai-empty-state {
				align-items: center;
				color: var(--text-muted);
				display: flex;
				flex: 1;
				flex-direction: column;
				justify-content: center;
				min-height: 100%;
				text-align: center;
			}

			.frappe-ai-empty-icon {
				align-items: center;
				background: color-mix(in srgb, var(--primary-color) 10%, var(--frappe-ai-control));
				border: 1px solid var(--border-color);
				border-radius: 50%;
				color: var(--primary-color);
				display: flex;
				height: 58px;
				justify-content: center;
				margin-bottom: 16px;
				width: 58px;
			}

			.frappe-ai-empty-icon svg {
				height: 30px;
				width: 30px;
			}

			.frappe-ai-empty-state h2 {
				color: var(--text-color);
				font-size: 18px;
				font-weight: 600;
				letter-spacing: 0;
				line-height: 1.3;
				margin: 0 0 14px;
			}

			.frappe-ai-suggestions {
				display: flex;
				flex-wrap: wrap;
				gap: 8px;
				justify-content: center;
				max-width: 300px;
			}

			.frappe-ai-suggestion-chip {
				/* // ─── CHANGE 5: Suggestion Chip Polish ─── */
				align-items: center;
				background: transparent;
				border: 1px solid var(--border-color);
				border-radius: 20px;
				color: var(--text-color);
				cursor: pointer;
				display: inline-flex;
				font-size: var(--font-size-sm);
				gap: 6px;
				line-height: 1.3;
				padding: 6px 14px;
				transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
				/* // ─── END CHANGE 5 ─── */
			}

			.frappe-ai-suggestion-chip:hover {
				/* // ─── CHANGE 5: Suggestion Chip Hover Polish ─── */
				background: var(--frappe-ai-control);
				border-color: var(--border-color);
				color: var(--text-color);
				/* // ─── END CHANGE 5 ─── */
			}

			/* // ─── CHANGE 5: Suggestion Chip Icons ─── */
			.frappe-ai-suggestion-chip svg {
				color: var(--primary-color);
				flex: 0 0 14px;
				height: 14px;
				width: 14px;
			}
			/* // ─── END CHANGE 5 ─── */

			.frappe-ai-message {
				display: flex;
				flex-direction: column;
				width: 100%;
			}

			.frappe-ai-message.is-user {
				align-items: flex-end;
			}

			.frappe-ai-message.is-assistant {
				align-items: flex-start;
			}

			.frappe-ai-bubble {
				border: 1px solid var(--border-color);
				color: var(--text-color);
				font-size: var(--font-size-base);
				line-height: 1.45;
				max-width: 85%;
				min-width: 96px;
				padding: 9px 10px 7px;
			}

			.frappe-ai-message.is-user .frappe-ai-bubble {
				/* // ─── CHANGE 5: User Bubble Surface Match ─── */
				background: var(--frappe-ai-raised);
				border-color: var(--border-color);
				border-right: 3px solid color-mix(in srgb, var(--primary-color) 30%, transparent);
				border-radius: 12px 12px 2px 12px;
				color: var(--text-color);
				/* // ─── END CHANGE 5 ─── */
				max-width: 80%;
			}

			.frappe-ai-message.is-assistant .frappe-ai-bubble {
				background: var(--frappe-ai-raised);
				border-radius: 12px 12px 12px 2px;
				/* // ─── CHANGE 5: Assistant Accent Border ─── */
				border-left: 3px solid color-mix(in srgb, var(--primary-color) 30%, transparent);
				/* // ─── END CHANGE 5 ─── */
				max-width: 85%;
			}

			.frappe-ai-bubble-meta {
				align-items: center;
				color: var(--text-muted);
				display: flex;
				font-size: var(--font-size-sm);
				gap: 6px;
				line-height: 1.2;
				margin-bottom: 5px;
			}

			.frappe-ai-bubble-meta span:first-child {
				font-weight: 600;
			}

			/* // ─── CHANGE 5: Timestamp Below Bubble ─── */
			.frappe-ai-message-time {
				color: var(--text-muted);
				font-size: var(--font-size-sm);
				line-height: 1.2;
				margin-top: 2px;
			}

			.frappe-ai-message.is-user .frappe-ai-message-time {
				text-align: right;
			}

			.frappe-ai-assistant-footer {
				align-items: center;
				display: flex;
				gap: 6px;
				justify-content: space-between;
				margin-top: 2px;
				max-width: 85%;
				width: 100%;
			}
			/* // ─── END CHANGE 5 ─── */

			.frappe-ai-bubble-content {
				overflow-wrap: anywhere;
			}

			.frappe-ai-bubble-content a {
				color: var(--primary-color);
				text-decoration: underline;
				text-underline-offset: 2px;
				word-break: break-all;
			}

			.frappe-ai-bubble-content a:hover {
				color: var(--btn-primary-hover, var(--primary-color));
				text-decoration: none;
			}

			.frappe-ai-message.is-user .frappe-ai-bubble-content a {
				color: inherit;
				opacity: 0.85;
			}

			.frappe-ai-message.is-user .frappe-ai-bubble-content a:hover {
				opacity: 1;
			}

			.frappe-ai-bubble-content > :first-child {
				margin-top: 0;
			}

			.frappe-ai-bubble-content > :last-child {
				margin-bottom: 0;
			}

			.frappe-ai-bubble-content p,
			.frappe-ai-bubble-content ul,
			.frappe-ai-bubble-content ol,
			.frappe-ai-bubble-content table,
			.frappe-ai-bubble-content pre {
				margin: 0 0 8px;
			}

			.frappe-ai-bubble-content ul,
			.frappe-ai-bubble-content ol {
				padding-left: 18px;
			}

			.frappe-ai-bubble-content table {
				border-collapse: collapse;
				display: block;
				font-size: var(--font-size-sm);
				max-width: 100%;
				overflow-x: auto;
			}

			.frappe-ai-bubble-content th,
			.frappe-ai-bubble-content td {
				border: 1px solid var(--border-color);
				padding: 5px 7px;
				text-align: left;
				vertical-align: top;
			}

			.frappe-ai-bubble-content th {
				background: var(--frappe-ai-control);
				font-weight: 600;
			}

			.frappe-ai-code-wrap {
				position: relative;
			}

			.frappe-ai-bubble-content pre {
				background: var(--frappe-ai-control);
				border: 1px solid var(--border-color);
				border-radius: var(--border-radius);
				overflow-x: auto;
				padding: 28px 10px 10px;
			}

			.frappe-ai-bubble-content code {
				font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
				font-size: var(--font-size-sm);
			}

			.frappe-ai-copy-code {
				align-items: center;
				background: var(--frappe-ai-raised);
				border: 1px solid var(--border-color);
				border-radius: var(--border-radius);
				color: var(--text-muted);
				cursor: pointer;
				display: inline-flex;
				font-size: var(--font-size-sm);
				height: 24px;
				justify-content: center;
				line-height: 1;
				padding: 0 7px;
				position: absolute;
				right: 6px;
				top: 6px;
			}

			.frappe-ai-copy-code:hover {
				color: var(--text-color);
			}

			.frappe-ai-bubble-footer {
				align-items: center;
				display: flex;
				gap: 2px;
				justify-content: flex-end;
			}

			/* // ─── CHANGE 4: Search Results + History Drawer Styles ─── */
			.frappe-ai-search-results,
			.frappe-ai-history-list {
				display: flex;
				flex-direction: column;
				gap: 8px;
				width: 100%;
			}

			.frappe-ai-search-empty {
				align-items: center;
				color: var(--text-muted);
				display: flex;
				flex: 1;
				font-size: var(--font-size-base);
				justify-content: center;
				min-height: 100%;
				text-align: center;
			}

			.frappe-ai-conversation-row {
				background: transparent;
				border: 1px solid var(--border-color);
				border-radius: var(--border-radius);
				color: var(--text-color);
				display: flex;
				align-items: stretch;
				font-family: var(--font-stack);
				position: relative;
				transition: background 140ms ease, border-color 140ms ease;
				width: 100%;
			}

			.frappe-ai-conversation-row:hover,
			.frappe-ai-conversation-row.is-active {
				background: color-mix(in srgb, var(--primary-color) 8%, var(--frappe-ai-control));
				border-color: color-mix(in srgb, var(--primary-color) 24%, var(--border-color));
			}

			.frappe-ai-conversation-body {
				background: transparent;
				border: 0;
				color: inherit;
				cursor: pointer;
				flex: 1 1 auto;
				font-family: var(--font-stack);
				min-width: 0;
				padding: 5px;
				text-align: left;
			}

			.frappe-ai-conversation-title-wrap {
				margin-bottom: 4px;
				position: relative;
			}

			.frappe-ai-conversation-title {
				display: block;
				font-size: var(--font-size-base);
				font-weight: 600;
				line-height: 1.3;
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
			}

			.frappe-ai-conversation-title-input {
				background: var(--bg-color);
				border: 1px solid var(--primary-color);
				border-radius: 4px;
				box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent);
				box-sizing: border-box;
				color: var(--text-color);
				display: none;
				font-family: var(--font-stack);
				font-size: var(--font-size-base);
				font-weight: 600;
				outline: none;
				padding: 1px 5px;
				width: 100%;
			}

			.frappe-ai-conversation-row.is-editing .frappe-ai-conversation-title {
				display: none;
			}

			.frappe-ai-conversation-row.is-editing .frappe-ai-conversation-title-input {
				display: block;
			}

			.frappe-ai-conversation-snippet {
				color: var(--text-muted);
				font-size: var(--font-size-sm);
				line-height: 1.35;
				margin-bottom: 4px;
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
			}

			.frappe-ai-conversation-time {
				color: var(--text-muted);
				font-size: var(--font-size-sm);
				line-height: 1.2;
			}

			.frappe-ai-conversation-actions {
				align-items: center;
				display: flex;
				flex: 0 0 auto;
				gap: 2px;
				opacity: 0;
				padding: 6px 0 6px 0;
				pointer-events: none;
				transition: opacity 120ms ease;
			}

			@media (min-width: 769px) {
				.fai-expanded .frappe-ai-conversation-actions {
					padding: 0;
				}
			}

			.frappe-ai-conversation-row:hover .frappe-ai-conversation-actions,
			.frappe-ai-conversation-row.is-active .frappe-ai-conversation-actions,
			.frappe-ai-conversation-row.is-editing .frappe-ai-conversation-actions {
				opacity: 1;
				pointer-events: auto;
			}

			.frappe-ai-conv-action-btn {
				align-items: center;
				background: transparent;
				border: 0;
				border-radius: 4px;
				color: var(--text-muted);
				cursor: pointer;
				display: flex;
				height: 24px;
				justify-content: center;
				padding: 0;
				transition: background 120ms ease, color 120ms ease;
				width: 24px;
			}

			.frappe-ai-conv-action-btn svg {
				height: 13px;
				width: 13px;
			}

			.frappe-ai-conv-action-btn:hover {
				background: var(--frappe-ai-hover);
				color: var(--text-color);
			}

			.frappe-ai-conv-action-btn.is-danger:hover {
				background: color-mix(in srgb, var(--red-500, #e53935) 12%, transparent);
				color: var(--red-500, #e53935);
			}

			.frappe-ai-history-drawer {
				background: var(--frappe-ai-canvas);
				border-right: 1px solid var(--border-color);
				bottom: 0;
				display: flex;
				flex-direction: column;
				left: 0;
				padding: 12px;
				position: absolute;
				top: 0;
				transform: translateX(-100%);
				transition: transform 220ms ease-out;
				width: 100%;
				z-index: 1;
			}

			.frappe-ai-history-drawer.is-open {
				transform: translateX(0);
			}

			.frappe-ai-history-header {
				align-items: center;
				display: flex;
				flex: 0 0 auto;
				justify-content: space-between;
				margin-bottom: 12px;
			}

			/* // ─── CHANGE 4: New Conversation Button + Major Element Separation ─── */
			.frappe-ai-history-primary-new {
				display: none;
			}

			@media (min-width: 769px) {
				.fai-expanded .frappe-ai-history-primary-new {
					align-items: center;
					background: var(--bg-color);
					border: 1px solid var(--border-color);
					border-radius: 6px;
					box-sizing: border-box;
					color: var(--text-color);
					cursor: pointer;
					display: inline-flex;
					flex: 0 0 auto;
					font-family: var(--font-stack);
					font-size: var(--font-size-sm);
					font-weight: 400;
					gap: 6px;
					justify-content: center;
					margin: 0 0 6px 0;
					padding: 7px 10px;
					transition: background 140ms ease, border-color 140ms ease;
					width: 100%;
				}

				.fai-expanded .frappe-ai-history-primary-new:hover {
					background: var(--frappe-ai-hover);
					border-color: var(--gray-400, var(--border-color));
				}

				.fai-expanded .frappe-ai-history-primary-new svg {
					height: 14px;
					width: 14px;
					flex-shrink: 0;
				}
			}
			/* // ─── END CHANGE 4 ─── */

			.frappe-ai-history-list {
				flex: 1 1 auto;
				overflow-y: auto;
			}

			/* // ─── CHANGE 8: Drawer Search Input + Footer Layout ─── */
			.frappe-ai-history-footer {
				display: flex;
				flex: 0 0 auto;
				flex-direction: column;
				padding-top: 10px;
			}

			.frappe-ai-drawer-search-input {
				background: var(--bg-color);
				border: 1px solid var(--border-color);
				border-radius: 6px;
				box-sizing: border-box;
				color: var(--text-color);
				flex: 0 0 auto;
				font-family: var(--font-stack);
				font-size: var(--font-size-sm);
				margin-bottom: 8px;
				outline: none;
				padding: 7px 10px;
				width: 100%;
			}

			.frappe-ai-drawer-search-input:focus {
				box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 25%, transparent);
			}

			.frappe-ai-drawer-search-empty {
				color: var(--text-muted);
				font-size: var(--font-size-sm);
				padding: 12px 0;
				text-align: center;
			}
			/* // ─── END CHANGE 8 ─── */

			/* // ─── END CHANGE 4 ─── */

			.frappe-ai-stream-thinking {
				margin-top: 8px;
			}

			.frappe-ai-typing {
				display: flex;
				flex-direction: column;
				gap: 7px;
				padding: 2px 0;
				width: 160px;
			}

			.frappe-ai-typing span {
				animation: frappe-ai-shimmer 1.4s infinite ease-in-out;
				background: linear-gradient(
					90deg,
					var(--border-color) 25%,
					color-mix(in srgb, var(--primary-color) 30%, var(--border-color)) 50%,
					var(--border-color) 75%
				);
				background-size: 200% 100%;
				border-radius: 4px;
				height: 8px;
				width: 100%;
			}

			.frappe-ai-typing span:nth-child(2) {
				animation-delay: 100ms;
				width: 75%;
			}

			.frappe-ai-typing span:nth-child(3) {
				animation-delay: 200ms;
				width: 50%;
			}

			.frappe-ai-input-area {
				background: var(--frappe-ai-raised);
				/* // ─── CHANGE 5: Input Separator Polish ─── */
				border-top: 1px solid var(--border-color);
				/* // ─── END CHANGE 5 ─── */
				flex: 0 0 auto;
				margin: 0;
				padding: 10px 12px 9px;
			}

			.frappe-ai-input-row {
				align-items: center;
				display: flex;
				/* // ─── CHANGE 2: Input Row Control Spacing ─── */
				gap: 6px;
				/* // ─── END CHANGE 2 ─── */
			}

			/* // ─── CHANGE 2: Voice + Attachment Button Styles ─── */
			.frappe-ai-input-icon-button {
				align-items: center;
				background: transparent;
				border: 0;
				border-radius: 50%;
				color: var(--text-muted);
				cursor: pointer;
				display: inline-flex;
				flex: 0 0 32px;
				height: 32px;
				justify-content: center;
				padding: 0;
				transition: background 140ms ease, color 140ms ease, transform 140ms ease;
				width: 32px;
			}

			.frappe-ai-input-icon-button:hover {
				background: var(--frappe-ai-hover);
				color: var(--text-color);
			}

			.frappe-ai-input-icon-button svg {
				height: 16px;
				width: 16px;
			}

			.frappe-ai-input-icon-button.is-recording {
				animation: recordingPulse 800ms infinite;
				background: color-mix(in srgb, #e03636 10%, transparent);
				color: #e03636;
			}

			.frappe-ai-attachment-pill {
				display: none;
				margin-bottom: 8px;
			}

			.frappe-ai-attachment-pill.has-attachment {
				display: flex;
			}

			.frappe-ai-attachment-chip {
				align-items: center;
				background: var(--frappe-ai-raised);
				border: 1px solid var(--border-color);
				border-radius: 4px;
				color: var(--text-color);
				display: inline-flex;
				font-size: var(--font-size-sm);
				gap: 6px;
				max-width: 100%;
				padding: 4px 7px;
			}

			.frappe-ai-attachment-name {
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
			}

			.frappe-ai-attachment-remove {
				background: transparent;
				border: 0;
				color: var(--text-muted);
				cursor: pointer;
				font-size: var(--font-size-base);
				line-height: 1;
				padding: 0 2px;
			}
			/* // ─── END CHANGE 2 ─── */

			/* // ─── CHANGE 5: Textarea Focus Ring Wrapper ─── */
			.frappe-ai-textarea-wrap {
				border-radius: var(--border-radius);
				display: flex;
				flex: 1 1 auto;
				min-width: 0;
				transition: box-shadow 140ms ease;
			}

			.frappe-ai-textarea-wrap:focus-within {
				box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 25%, transparent);
			}
			/* // ─── END CHANGE 5 ─── */

			.frappe-ai-textarea {
				background: var(--frappe-ai-control);
				border: 1px solid var(--border-color);
				border-radius: var(--border-radius);
				color: var(--text-color);
				flex: 1 1 auto;
				font-family: var(--font-stack);
				font-size: var(--font-size-base);
				line-height: 20px;
				max-height: 76px;
				min-height: 38px;
				outline: none;
				padding: 8px 10px;
				resize: none;
				width: 100%;
			}

			.frappe-ai-textarea::placeholder {
				color: var(--text-muted);
			}

			.frappe-ai-textarea:disabled {
				cursor: not-allowed;
				opacity: 0.7;
			}

			.frappe-ai-send-button {
				align-items: center;
				background: var(--btn-primary, var(--primary-color));
				border: 0;
				border-radius: 50%;
				color: var(--frappe-ai-on-primary);
				cursor: pointer;
				display: inline-flex;
				flex: 0 0 38px;
				height: 38px;
				justify-content: center;
				padding: 0;
				transition: opacity 140ms ease, transform 140ms ease, background 140ms ease, color 140ms ease;
				width: 38px;
			}

			.frappe-ai-send-button:hover {
				transform: translateY(-1px);
			}

			.frappe-ai-send-button:disabled {
				cursor: not-allowed;
				opacity: 0.65;
				transform: none;
			}

			.frappe-ai-send-button.is-stop {
				background: color-mix(in srgb, var(--red-500, var(--primary-color)) 12%, var(--frappe-ai-raised));
				border: 1px solid color-mix(in srgb, var(--red-500, var(--primary-color)) 30%, var(--border-color));
				color: var(--red-500, var(--primary-color));
			}

			.frappe-ai-send-button svg {
				height: 17px;
				width: 17px;
			}

			.frappe-ai-token-counter {
				color: var(--text-muted);
				font-size: 10px;
				line-height: 1;
				margin-top: 4px;
				opacity: 0.7;
				text-align: right;
			}


			@keyframes frappe-ai-shimmer {
				0% {
					background-position: 200% 0;
				}
				100% {
					background-position: -200% 0;
				}
			}

			/* // ─── CHANGE 2: Recording Pulse Animation ─── */
			@keyframes recordingPulse {
				0%,
				100% {
					transform: scale(1);
				}
				50% {
					transform: scale(1.15);
				}
			}
			/* // ─── END CHANGE 2 ─── */

			/* ─── AI Action Toast ─── */
			.frappe-ai-action-toast {
				align-items: center;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color);
				border-left: 3px solid var(--primary-color);
				border-radius: 8px;
				bottom: 88px;
				box-shadow: 0 4px 20px rgba(0,0,0,.12);
				color: var(--text-color);
				display: inline-flex;
				font-family: var(--font-stack);
				font-size: var(--font-size-sm);
				gap: 8px;
				left: 50%;
				max-width: 340px;
				opacity: 0;
				padding: 9px 14px;
				pointer-events: none;
				position: fixed;
				transform: translateX(-50%) translateY(8px);
				transition: opacity 180ms ease, transform 180ms ease;
				white-space: nowrap;
				z-index: 99999;
			}

			.frappe-ai-action-toast.is-visible {
				opacity: 1;
				transform: translateX(-50%) translateY(0);
			}

			.frappe-ai-action-toast-icon {
				color: var(--primary-color);
				display: flex;
				flex: 0 0 16px;
				height: 16px;
				width: 16px;
			}

			.frappe-ai-action-toast-icon svg {
				height: 16px;
				width: 16px;
			}

			.frappe-ai-action-toast-text {
				overflow: hidden;
				text-overflow: ellipsis;
			}
			/* ─── End AI Action Toast ─── */

			@media (max-width: 768px) {
				.frappe-ai-panel {
					bottom: 80px;
					height: 70vh;
					/* // ─── CHANGE 1: Bottom-Right Mobile Reposition ─── */
					right: 16px;
					/* // ─── END CHANGE 1 ─── */
					width: calc(100vw - 32px);
				}

				/* Mobile full-screen: fills viewport but keeps all header UI unchanged */
				.frappe-ai-panel.is-expanded {
					bottom: 0;
					border-radius: 0;
					box-shadow: none;
					height: 100dvh;
					left: 0;
					right: 0;
					top: 0;
					width: 100dvw;
					z-index: 9999;
				}

				.frappe-ai-chat-root.is-expanded .frappe-ai-fab {
					display: none;
				}
			}

			@supports not (height: 100dvh) {
				@media (max-width: 768px) {
					.frappe-ai-panel.is-expanded {
						height: 100vh;
						width: 100vw;
					}
				}
			}
		`;
		document.head.appendChild(dom.style);
	}

	// ─── EVENT HANDLERS ──────────────────────────────────────────────────────────
	function bindEvents() {
		// Toggle is handled inside _initDrag (pointerdown) to separate tap from drag
		dom.fab.addEventListener("keydown", handleFabKeydown);
		dom.closeButton.addEventListener("click", close);
		dom.newChatButton.addEventListener("click", handleNewChat);
		// ─── CHANGE 2: Voice + Attachment Event Bindings ───
		dom.micButton.addEventListener("click", handleVoiceToggle);
		dom.attachButton.addEventListener("click", handleAttachClick);
		dom.fileInput.addEventListener("change", handleFileSelected);
		dom.attachmentPill.addEventListener("click", handleAttachmentPillClick);
		// ─── END CHANGE 2 ───
		// ─── CHANGE 3: Expand Event Binding ───
		dom.expandButton.addEventListener("click", handleExpandToggle);
		// ─── END CHANGE 3 ───
		// ─── CHANGE 4: Search + History Event Bindings ───
		dom.historyButton.addEventListener("click", handleHistoryToggle);
		// ─── CHANGE 8: Drawer search replaces header search bindings ───
		dom.drawerSearchInput.addEventListener("input", handleSearchInput);
		dom.drawerSearchInput.addEventListener("keydown", handleSearchKeydown);
		// ─── END CHANGE 8 ───
		dom.historyCloseButton.addEventListener("click", handleHistoryClose);
		dom.historyNewChatButton.addEventListener("click", handleNewChat);
		dom.historyList.addEventListener("click", handleConversationListClick);
		// ─── END CHANGE 4 ───
		dom.textarea.addEventListener("input", handleTextareaInput);
		dom.textarea.addEventListener("keydown", handleTextareaKeydown);
		dom.sendButton.closest("form").addEventListener("submit", handleSubmit);
		dom.sendButton.addEventListener("click", handleSendButtonClick);
		dom.panel.addEventListener("keydown", handlePanelKeydown);
		dom.messagesArea.addEventListener("click", handleMessagesClick);
		_initDrag();
	}

	// ─── Drag-to-reposition (FAB drag moves FAB + panel together) ───
	function _initDrag() {
		let dragging = false;
		let didMove = false;
		let startX = 0, startY = 0;
		let startFabRight = 0, startFabBottom = 0;

		function _getFabPos() {
			const rect = dom.fab.getBoundingClientRect();
			return {
				right: window.innerWidth - rect.right,
				bottom: window.innerHeight - rect.bottom,
			};
		}

		function _applyPos(fabRight, fabBottom) {
			const fabW = dom.fab.offsetWidth || 52;
			const fabH = dom.fab.offsetHeight || 52;
			fabRight  = Math.max(0, Math.min(fabRight,  window.innerWidth  - fabW));
			fabBottom = Math.max(0, Math.min(fabBottom, window.innerHeight - fabH));

			dom.fab.style.right  = fabRight  + "px";
			dom.fab.style.bottom = fabBottom + "px";
			dom.fab.style.left   = "auto";
			dom.fab.style.top    = "auto";

			// Panel sits directly above the FAB, right-aligned with it
			const panelW = dom.panel.offsetWidth || 380;
			const panelRight  = fabRight - (panelW / 2) + (fabW / 2);
			const panelBottom = fabBottom + fabH + 12;

			dom.panel.style.right  = Math.max(0, panelRight)  + "px";
			dom.panel.style.bottom = Math.max(0, panelBottom) + "px";
			dom.panel.style.left   = "auto";
			dom.panel.style.top    = "auto";
		}

		function onPointerMove(e) {
			if (!dragging) return;
			const dx = startX - e.clientX;
			const dy = startY - e.clientY;
			if (!didMove && Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
			didMove = true;
			dom.fab.classList.add("is-dragging");
			_applyPos(startFabRight + dx, startFabBottom + dy);
		}

		function onPointerUp() {
			if (!dragging) return;
			dragging = false;
			dom.fab.classList.remove("is-dragging");
			document.removeEventListener("pointermove", onPointerMove);
			document.removeEventListener("pointerup", onPointerUp);

			if (didMove) {
				// Suppress the click event that follows pointerup after a drag
				dom.fab.addEventListener("click", (e) => e.stopImmediatePropagation(), { once: true, capture: true });
			} else {
				// Clean tap — toggle the panel
				handleToggle();
			}
			didMove = false;
		}

		dom.fab.addEventListener("pointerdown", (e) => {
			if (e.button !== 0) return;
			const pos = _getFabPos();
			startX = e.clientX;
			startY = e.clientY;
			startFabRight  = pos.right;
			startFabBottom = pos.bottom;
			dragging = true;
			didMove  = false;
			document.addEventListener("pointermove", onPointerMove);
			document.addEventListener("pointerup", onPointerUp);
		});
	}
	// ─── End Drag ───

	function handleToggle() {
		if (state.isOpen) {
			close();
			return;
		}

		open();
	}

	function handleFabKeydown(event) {
		if (event.key !== "Enter" && event.key !== " ") {
			return;
		}

		event.preventDefault();
		handleToggle();
	}

	function handleNewChat() {
		if (state.isStreaming) {
			stopStreaming();
		}
		setState({ type: "NEW_CHAT" });
		// ─── CHANGE 2: Reset File Input On New Chat ───
		dom.fileInput.value = "";
		// ─── END CHANGE 2 ───
		resetComposer();
		dom.textarea.focus();
	}

	// ─── CHANGE 2: Voice + Attachment Event Handlers ───
	function handleVoiceToggle() {
		setState({ type: "TOGGLE_RECORDING" });
		if (window.frappe?.show_alert) {
			frappe.show_alert("Voice input coming soon", 2);
		}
	}

	function handleAttachClick() {
		dom.fileInput.click();
	}

	function handleFileSelected() {
		const file = dom.fileInput.files?.[0];
		if (!file) {
			return;
		}

		setState({
			type: "SET_ATTACHMENT",
			attachment: {
				name: file.name,
				file,
			},
		});
	}

	function handleAttachmentPillClick(event) {
		if (!event.target.closest("[data-remove-attachment]")) {
			return;
		}

		dom.fileInput.value = "";
		setState({ type: "CLEAR_ATTACHMENT" });
	}
	// TODO: API — upload attachment before sending message
	// ─── END CHANGE 2 ───

	// ─── CHANGE 3: Expand Event Handler ───
	function handleExpandToggle() {
		animateExpandedTransition(() => {
			setState({ type: "TOGGLE_EXPANDED" });
		});
	}
	// ─── END CHANGE 3 ───

	// ─── CHANGE 4: Search + History Event Handlers ───
	// ─── CHANGE 8: handleSearchOpen removed — search is always visible in drawer ───
	function handleSearchClose() {
		setState({ type: "CLOSE_SEARCH" });
		dom.textarea.focus();
	}

	function handleSearchInput() {
		// ─── CHANGE 8: Read from drawer search input instead of header search ───
		setState({ type: "SET_SEARCH_QUERY", searchQuery: dom.drawerSearchInput.value });
		// ─── END CHANGE 8 ───
	}

	function handleSearchKeydown(event) {
		if (event.key !== "Escape") {
			return;
		}

		event.preventDefault();
		handleSearchClose();
	}

	function handleHistoryToggle() {
		setState({ type: "TOGGLE_HISTORY" });
	}

	function handleHistoryClose() {
		setState({ type: "CLOSE_HISTORY" });
	}

	function handleConversationListClick(event) {
		const actionBtn = event.target.closest("[data-action]");
		const action = actionBtn?.getAttribute("data-action");

		if (action === "edit-conversation") {
			const conversationId = actionBtn.getAttribute("data-conversation-id");
			_startEditConversationTitle(conversationId);
			return;
		}

		if (action === "delete-conversation") {
			const conversationId = actionBtn.getAttribute("data-conversation-id");
			_confirmDeleteConversation(conversationId);
			return;
		}

		// Default: select conversation
		const row = event.target.closest("[data-conversation-id]");
		if (!row) return;

		// Don't select while editing title
		if (row.closest(".frappe-ai-conversation-row.is-editing")) return;

		const conversationId = row.getAttribute("data-conversation-id");
		if (!conversationId) return;

		const alreadyLoaded = state.conversations.find(
			(c) => c.id === conversationId && c.messages.length > 0
		);

		setState({ type: "SELECT_CONVERSATION", conversationId });

		if (!alreadyLoaded) {
			loadMessages(conversationId);
		}
	}

	function _startEditConversationTitle(conversationId) {
		const row = dom.historyList.querySelector(
			`.frappe-ai-conversation-row[data-conversation-id="${conversationId}"]`
		);
		if (!row) return;
		row.classList.add("is-editing");
		const input = row.querySelector(".frappe-ai-conversation-title-input");
		if (!input) return;
		input.focus();
		input.select();

		function commit() {
			cleanup();
			const newTitle = input.value.trim();
			if (!newTitle) {
				row.classList.remove("is-editing");
				return;
			}
			frappe.call({
				method: "frappe_ai.frappe_ai.api.conversation.update_title",
				args: { conversation_id: conversationId, title: newTitle },
				callback(response) {
					if (!response.message) return;
					const saved = response.message.title;
					// Update state
					setState({
						type: "UPDATE_CONVERSATION_TITLE",
						conversationId,
						title: saved,
					});
				},
			});
		}

		function cancel() {
			cleanup();
			row.classList.remove("is-editing");
		}

		function onKeydown(e) {
			if (e.key === "Enter") { e.preventDefault(); commit(); }
			if (e.key === "Escape") { e.preventDefault(); cancel(); }
		}

		function onBlur() {
			// small delay so click on action button fires first
			setTimeout(commit, 120);
		}

		function cleanup() {
			row.classList.remove("is-editing");
			input.removeEventListener("keydown", onKeydown);
			input.removeEventListener("blur", onBlur);
		}

		input.addEventListener("keydown", onKeydown);
		input.addEventListener("blur", onBlur);
	}

	function _confirmDeleteConversation(conversationId) {
		const conv = state.conversations.find((c) => c.id === conversationId);
		const title = conv?.title || "this conversation";
		frappe.confirm(
			`Delete "<b>${frappe.utils.escape_html(title)}</b>"? This cannot be undone.`,
			() => {
				frappe.call({
					method: "frappe_ai.frappe_ai.api.conversation.delete",
					args: { conversation_id: conversationId },
					callback(response) {
						if (!response.message) return;
						setState({ type: "DELETE_CONVERSATION", conversationId });
						frappe.show_alert({ message: "Conversation deleted.", indicator: "green" }, 3);
					},
				});
			}
		);
	}
	// TODO: API — replace with server-side search in v2
	// ─── END CHANGE 4 ───

	function handleTextareaInput() {
		resizeTextarea();
		updateTokenCounter();
	}

	function handleTextareaKeydown(event) {
		if (event.key !== "Enter" || event.shiftKey) {
			return;
		}

		event.preventDefault();
		submitPrompt();
	}

	function handleSubmit(event) {
		event.preventDefault();
		submitPrompt();
	}

	function handleSendButtonClick(event) {
		if (!state.isStreaming) {
			return;
		}

		event.preventDefault();
		stopStreaming();
	}

	function handlePanelKeydown(event) {
		if (event.key === "Escape") {
			event.preventDefault();
			// ─── CHANGE 3: Escape Collapses Expanded Before Closing ───
			if (state.isExpanded) {
				animateExpandedTransition(() => {
					setState({ type: "COLLAPSE_EXPANDED" });
				});
				return;
			}
			// ─── END CHANGE 3 ───
			close();
			return;
		}

		if (event.key === "Tab") {
			trapFocus(event);
		}
	}

	function handleMessagesClick(event) {
		const codeCopyButton = event.target.closest("[data-copy-code]");
		if (codeCopyButton) {
			copyCodeBlock(codeCopyButton);
			return;
		}

		const bubbleCopyButton = event.target.closest("[data-copy-message]");
		if (bubbleCopyButton) {
			copyAssistantMessage(bubbleCopyButton);
			return;
		}

		if (event.target.closest("[data-regenerate-message]")) {
			_log("Regenerate clicked; v1 renders the control only.");
			return;
		}

		const suggestion = event.target.closest("[data-suggestion]");
		if (suggestion) {
			const prompt = suggestion.getAttribute("data-suggestion") || "";
			dom.textarea.value = prompt;
			handleTextareaInput();
			submitPrompt();
		}

		// ─── CHANGE 4: Search Result Selection ───
		const conversationResult = event.target.closest("[data-conversation-id]");
		if (conversationResult) {
			setState({
				type: "SELECT_CONVERSATION",
				conversationId: conversationResult.getAttribute("data-conversation-id"),
			});
		}
		// ─── END CHANGE 4 ───
	}

	function submitPrompt() {
		const prompt = dom.textarea.value.trim();
		if (!prompt || state.isStreaming) {
			return;
		}

		const userMessage = createMessage("user", prompt);
		resetComposer();

		// Push current page context to cache before streaming so get_page_context tool can read it
		_pushPageContext();

		const existingId = getActiveConversationId();

		if (existingId) {
			setState({ type: "ADD_MESSAGE", conversationId: existingId, message: userMessage }, { skipRender: true });
			setState({ type: "SHOW_TYPING" });
			_streamingActive = true;
			startAssistantTurn(existingId, prompt);
		} else {
			// Create conversation on server first, then stream once we have a real ID
			setState({ type: "SHOW_TYPING" });
			_streamingActive = true;
			frappe.call({
				method: "frappe_ai.frappe_ai.api.conversation.create",
				callback(response) {
					if (!response.message) {
						setState({ type: "STOP_STREAM", conversationId: null });
						return;
					}
					const { conversation_id, title } = response.message;
					const conversation = {
						id: conversation_id,
						title,
						last_message: userMessage.content,
						timestamp: "just now",
						streamingMessageId: null,
						messages: [userMessage],
					};
					setState({ type: "ADD_CONVERSATION", conversation }, { skipRender: true });
					startAssistantTurn(conversation_id, prompt);
				},
			});
		}
	}

	function _pushPageContext() {
		try {
			const ctx = _gatherPageContext();
			frappe.call({
				method: "frappe_ai.frappe_ai.api.settings.push_page_context",
				args: { context: JSON.stringify(ctx) },
				// fire-and-forget — no callback needed
			});
		} catch (e) {
			// non-fatal
		}
	}

	function _gatherPageContext() {
		const route = frappe.get_route ? frappe.get_route() : [];
		const pageType = (route[0] || "").toLowerCase();
		const ctx = {
			route: route.join("/"),
			page_type: pageType,
		};

		// ── Form context ──────────────────────────────────────────────────────
		if (window.cur_frm && cur_frm.doc) {
			const frm = cur_frm;
			ctx.doctype = frm.doctype;
			ctx.docname = frm.docname;
			ctx.is_new = Boolean(frm.is_new());
			ctx.is_dirty = Boolean(frm.is_dirty());
			ctx.docstatus = frm.doc.docstatus;

			// Field values (skip layout, password, HTML; cap at 50)
			const SKIP_FT = new Set(["password", "Section Break", "Column Break", "Tab Break", "HTML", "Heading", "Button"]);
			const fieldValues = {};
			let count = 0;
			for (const field of (frm.meta && frm.meta.fields || [])) {
				if (count >= 50) break;
				if (SKIP_FT.has(field.fieldtype)) continue;
				const val = frm.doc[field.fieldname];
				if (val !== undefined && val !== null && val !== "") {
					fieldValues[field.fieldname] = val;
					count++;
				}
			}
			ctx.field_values = fieldValues;

			// All field definitions (name + type + label) — needed for AI to know valid fieldnames
			ctx.fields = (frm.meta && frm.meta.fields || [])
				.filter(f => !SKIP_FT.has(f.fieldtype))
				.map(f => ({ fieldname: f.fieldname, label: f.label, fieldtype: f.fieldtype, options: f.options }));

			// Child tables present on this form
			const childTables = (frm.meta && frm.meta.fields || [])
				.filter(f => f.fieldtype === "Table")
				.map(f => ({
					fieldname: f.fieldname,
					label: f.label,
					row_count: (frm.doc[f.fieldname] || []).length,
				}));
			ctx.child_tables = childTables;

			// Custom / action buttons
			const customButtons = frm.custom_buttons ? Object.keys(frm.custom_buttons) : [];
			ctx.custom_buttons = customButtons;

			// Sections and tabs
			const sections = [];
			for (const f of (frm.meta && frm.meta.fields || [])) {
				if (f.fieldtype === "Section Break" || f.fieldtype === "Tab Break") {
					if (f.label) sections.push({ type: f.fieldtype, label: f.label, fieldname: f.fieldname });
				}
			}
			ctx.sections = sections;
		}

		// ── List context ──────────────────────────────────────────────────────
		if (window.cur_list) {
			ctx.list_doctype = cur_list.doctype;

			// Collect active filters from multiple sources
			const activeFilters = [];
			try {
				// 1. filter_area (the standard Frappe filter bar — most reliable)
				if (cur_list.filter_area && cur_list.filter_area.filter_list) {
					for (const f of (cur_list.filter_area.filter_list.filters || [])) {
						if (f.fieldname) {
							activeFilters.push({
								fieldname: f.fieldname,
								operator: f.operator || "=",
								value: f.get_value ? f.get_value() : f.value,
							});
						}
					}
				}
				// 2. cur_list.get_filters() — may include route/URL-injected filters
				if (!activeFilters.length && cur_list.get_filters) {
					const gf = cur_list.get_filters();
					if (Array.isArray(gf)) {
						for (const f of gf) {
							// format: [doctype, fieldname, operator, value]
							if (Array.isArray(f) && f.length >= 4) {
								activeFilters.push({ fieldname: f[1], operator: f[2], value: f[3] });
							} else if (f && typeof f === "object" && f.fieldname) {
								activeFilters.push({ fieldname: f.fieldname, operator: f.operator || "=", value: f.value });
							}
						}
					}
				}
				// 3. cur_list.filters (legacy array of [doctype, field, op, val])
				if (!activeFilters.length && Array.isArray(cur_list.filters)) {
					for (const f of cur_list.filters) {
						if (Array.isArray(f) && f.length >= 4) {
							activeFilters.push({ fieldname: f[1], operator: f[2], value: f[3] });
						}
					}
				}
				// 4. URL params — frappe_route_options / frappe.route_options may carry them
				//    Also parse from window.location.search as last resort
				if (!activeFilters.length) {
					try {
						const params = new URLSearchParams(window.location.search);
						params.forEach((val, key) => {
							if (key !== "cmd" && key !== "_") {
								activeFilters.push({ fieldname: key, operator: "=", value: val });
							}
						});
					} catch (_) {}
				}
			} catch (_) {}

			ctx.list_filters = activeFilters;
			ctx.list_has_filters = activeFilters.length > 0;
			ctx.list_total = cur_list.total_count;

			// Available columns (for filter fieldname hints)
			try {
				ctx.list_columns = (cur_list.columns || []).map(c => ({
					fieldname: c.fieldname || (c.df && c.df.fieldname),
					label: c.df && c.df.label,
				})).filter(c => c.fieldname);
			} catch (_) { ctx.list_columns = []; }
		}

		// ── Report context ────────────────────────────────────────────────────
		if (pageType === "query-report" && window.frappe && frappe.query_report) {
			ctx.report_name = frappe.query_report.report_name;
			// Report filter fields with current values
			try {
				const filters = [];
				for (const f of (frappe.query_report.filters || [])) {
					filters.push({
						fieldname: f.df && f.df.fieldname,
						label: f.df && f.df.label,
						fieldtype: f.df && f.df.fieldtype,
						value: f.get_value ? f.get_value() : null,
					});
				}
				ctx.report_filters = filters;
			} catch (_) { ctx.report_filters = []; }
		}

		// ── Open dialog ───────────────────────────────────────────────────────
		try {
			const openDialog = frappe.ui && frappe.ui.Dialog && frappe._cur_dialog;
			if (openDialog && openDialog.display) {
				ctx.open_dialog = {
					title: openDialog.title || "",
					buttons: (openDialog.get_primary_btn ? [openDialog.get_primary_btn().text()] : []),
				};
			}
		} catch (_) {}

		// ── Custom/module pages — generic input scan ──────────────────────────
		// Capture any labelled inputs visible on the main content area
		try {
			const inputs = [];
			document.querySelectorAll(".page-content input:not([type=hidden]), .page-content select, .page-content textarea").forEach(el => {
				if (!el.offsetParent) return; // hidden
				const id = el.id || el.name || "";
				const lblEl = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
				const lbl = lblEl ? lblEl.textContent.trim() : (el.placeholder || el.getAttribute("aria-label") || "");
				if (lbl || id) {
					inputs.push({ tag: el.tagName.toLowerCase(), id, label: lbl, type: el.type || "" });
				}
			});
			if (inputs.length) ctx.page_inputs = inputs.slice(0, 30);
		} catch (_) {}

		// ── Available Frappe pages (for fuzzy navigation) ─────────────────────
		try {
			if (frappe.pages) ctx.available_pages = Object.keys(frappe.pages).slice(0, 100);
		} catch (_) {}

		return ctx;
	}

	function trapFocus(event) {
		const focusableElements = getFocusableElements();
		if (!focusableElements.length) {
			return;
		}

		const firstElement = focusableElements[0];
		const lastElement = focusableElements[focusableElements.length - 1];

		if (event.shiftKey && document.activeElement === firstElement) {
			event.preventDefault();
			lastElement.focus();
			return;
		}

		if (!event.shiftKey && document.activeElement === lastElement) {
			event.preventDefault();
			firstElement.focus();
		}
	}

	function getFocusableElements() {
		return Array.from(
			dom.panel.querySelectorAll(
				'button:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
			)
		).filter((element) => {
			return element.offsetParent !== null;
		});
	}

	function resizeTextarea() {
		dom.textarea.style.height = "auto";
		dom.textarea.style.height = `${Math.min(dom.textarea.scrollHeight, 76)}px`;
	}

	function updateTokenCounter() {
		const tokenCount = Math.ceil(dom.textarea.value.length / 4);
		dom.tokenCounter.textContent = `~${tokenCount} tokens`;
	}

	function resetComposer() {
		dom.textarea.value = "";
		handleTextareaInput();
	}

	// ─── CHANGE 3: Smooth Full-Screen FLIP Animation ───
	function animateExpandedTransition(updateState) {
		if (!dom.panel || !state.isOpen) {
			updateState();
			return;
		}

		if (panelAnimation) {
			panelAnimation.cancel();
			panelAnimation = null;
		}

		const isCollapsing = state.isExpanded;
		if (isCollapsing) {
			animateCollapseToPopover(updateState);
			return;
		}

		const firstRect = dom.panel.getBoundingClientRect();
		updateState();

		window.requestAnimationFrame(() => {
			const lastRect = dom.panel.getBoundingClientRect();
			const scaleX = firstRect.width / Math.max(lastRect.width, 1);
			const scaleY = firstRect.height / Math.max(lastRect.height, 1);
			const deltaX = firstRect.left - lastRect.left;
			const deltaY = firstRect.top - lastRect.top;

			panelAnimation = dom.panel.animate(
				[
					{
						transform: `translate(${deltaX}px, ${deltaY}px) scale(${scaleX}, ${scaleY})`,
						transformOrigin: "top left",
						borderRadius: state.isExpanded ? "12px" : "0",
						boxShadow: isCollapsing
							? "none"
							: "var(--shadow-base), 0 8px 32px var(--frappe-ai-shadow-color)",
					},
					{
						transform: "translate(0, 0) scale(1, 1)",
						transformOrigin: "top left",
					borderRadius: state.isExpanded ? "0" : "12px",
						boxShadow: state.isExpanded
							? "none"
							: "var(--shadow-base), 0 8px 32px var(--frappe-ai-shadow-color)",
					},
				],
				{
					duration: 320,
					easing: "cubic-bezier(0.22, 1, 0.36, 1)",
				}
			);
			panelAnimation.onfinish = () => {
				panelAnimation = null;
			};
			panelAnimation.oncancel = () => {
				panelAnimation = null;
			};
		});
	}

	function animateCollapseToPopover(updateState) {
		const firstRect = dom.panel.getBoundingClientRect();
		const targetRect = getPopoverPanelRect();

		dom.panel.style.top = `${firstRect.top}px`;
		dom.panel.style.left = `${firstRect.left}px`;
		dom.panel.style.right = "auto";
		dom.panel.style.bottom = "auto";
		dom.panel.style.width = `${firstRect.width}px`;
		dom.panel.style.height = `${firstRect.height}px`;
		dom.panel.style.transform = "none";
		dom.panel.style.borderRadius = "0";
		dom.panel.style.boxShadow = "none";

		updateState();

		window.requestAnimationFrame(() => {
			panelAnimation = dom.panel.animate(
				[
					{
						top: `${firstRect.top}px`,
						left: `${firstRect.left}px`,
						width: `${firstRect.width}px`,
						height: `${firstRect.height}px`,
						borderRadius: "0",
						boxShadow: "none",
					},
					{
						top: `${targetRect.top}px`,
						left: `${targetRect.left}px`,
						width: `${targetRect.width}px`,
						height: `${targetRect.height}px`,
						borderRadius: "12px",
						boxShadow:
							"var(--shadow-base), 0 8px 32px var(--frappe-ai-shadow-color)",
					},
				],
				{
					duration: 300,
					easing: "cubic-bezier(0.22, 1, 0.36, 1)",
				}
			);
			panelAnimation.onfinish = cleanupPanelBoundsAnimation;
			panelAnimation.oncancel = cleanupPanelBoundsAnimation;
		});
	}

	function cleanupPanelBoundsAnimation() {
		panelAnimation = null;
		dom.panel.style.top = "";
		dom.panel.style.left = "";
		dom.panel.style.right = "";
		dom.panel.style.bottom = "";
		dom.panel.style.width = "";
		dom.panel.style.height = "";
		dom.panel.style.transform = "";
		dom.panel.style.borderRadius = "";
		dom.panel.style.boxShadow = "";
	}

	function getPopoverPanelRect() {
		const isMobile = window.matchMedia("(max-width: 768px)").matches;
		const viewportWidth = window.innerWidth;
		const viewportHeight = window.innerHeight;
		const right = isMobile ? 16 : 24;
		const bottom = isMobile ? 80 : 88;
		const width = isMobile ? viewportWidth - 32 : 380;
		const height = isMobile ? viewportHeight * 0.7 : 560;

		return {
			height,
			left: viewportWidth - right - width,
			top: viewportHeight - bottom - height,
			width,
		};
	}
	// ─── END CHANGE 3 ───

	// ─── STREAM ENGINE ───────────────────────────────────────────────────────────

	// ─── CHANGE C: fetch-based SSE streaming (replaces EventSource) ───
	let _streamAbortController = null;
	let _streamFinished = false;
	// Synchronous flag — set before the setTimeout fires so loadConversations
	// never races the timer delay in startAssistantTurn.
	let _streamingActive = false;

	function startAssistantTurn(conversationId, prompt) {
		typingTimeout = window.setTimeout(() => {
			typingTimeout = null;
			_streamFinished = false;

			const assistantMessage = createMessage("assistant", "", { isStreaming: true });
			setState({
				type: "START_STREAM",
				conversationId,
				message: assistantMessage,
				streamInterval: null,
			});

			_streamAbortController = new AbortController();

			const params = new URLSearchParams({
				conversation_id: conversationId,
				message: prompt,
				sid: frappe.boot?.sid || "",
			});

			async function runStream() {
				let response;
				try {
					response = await fetch(
						`/api/method/frappe_ai.frappe_ai.api.chat.stream_message?${params}`,
						{ signal: _streamAbortController.signal, headers: { Accept: "text/event-stream" } }
					);
				} catch (err) {
					if (err.name === "AbortError") return;
					_log("Stream fetch error:", err);
					frappe?.show_alert?.({ message: "Connection error. Please try again.", indicator: "red" }, 5);
					_finishStream(conversationId);
					return;
				}

				if (!response.ok) {
					_log("Stream HTTP error:", response.status);
					frappe?.show_alert?.({ message: `Server error (${response.status}). Please try again.`, indicator: "red" }, 5);
					_finishStream(conversationId);
					return;
				}

				const reader = response.body.getReader();
				const decoder = new TextDecoder();
				let buffer = "";

				try {
					while (true) {
						const { done, value } = await reader.read();
						if (done) break;
						buffer += decoder.decode(value, { stream: true });
						// Process all complete SSE blocks (separated by \n\n)
						const blocks = buffer.split("\n\n");
						buffer = blocks.pop(); // keep incomplete tail
						for (const block of blocks) {
							if (!block.trim()) continue;
							let eventType = "message";
							let dataLine = "";
							for (const line of block.split("\n")) {
								if (line.startsWith("event:")) eventType = line.slice(6).trim();
								else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
							}
							handleSseEvent(eventType, dataLine, conversationId);
						}
					}
					// Flush any remaining buffer
					if (buffer.trim()) {
						buffer += "\n\n";
						const blocks = buffer.split("\n\n");
						for (const block of blocks) {
							if (!block.trim()) continue;
							let eventType = "message";
							let dataLine = "";
							for (const line of block.split("\n")) {
								if (line.startsWith("event:")) eventType = line.slice(6).trim();
								else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
							}
							handleSseEvent(eventType, dataLine, conversationId);
						}
					}
				} catch (err) {
					if (err.name !== "AbortError") {
						_log("Stream read error:", err);
					}
				} finally {
					reader.releaseLock();
				}

				_finishStream(conversationId);
			}

			runStream();
		}, TYPING_DELAY_MS);
	}

	function handleSseEvent(eventType, dataLine, conversationId) {
		let data = {};
		try { data = JSON.parse(dataLine || "{}"); } catch (_) {}

		if (eventType === "token") {
			setState({ type: "APPEND_STREAM_CHUNK", conversationId, chunk: data.delta || "" });

		} else if (eventType === "done") {
			const usage = data.usage || {};
			const tokens = (usage.input || 0) + (usage.output || 0);
			if (dom.tokenCounter) dom.tokenCounter.textContent = `~${tokens} tokens`;

		} else if (eventType === "title_update") {
			if (data.title) {
				const found = state.conversations.find((c) => c.id === conversationId);
				setState({
					type: "LOAD_MESSAGES",
					conversationId,
					messages: found ? found.messages : [],
					title: data.title,
					last_message: found ? found.last_message : "",
				});
			}

		} else if (eventType === "ui_action") {
			_executeUiAction(data);

		} else if (eventType === "error") {
			frappe?.show_alert?.({ message: data.message || "An error occurred.", indicator: "red" }, 5);
		}
	}

	// ─── UI ACTION EXECUTOR (navigation + interaction) ────────────────────────
	function _executeUiAction(payload) {
		if (!payload || !payload.action) return;
		const { action } = payload;

		// Navigation actions
		if (["list", "form", "new_form", "report", "workspace"].includes(action)) {
			_executeNavAction(payload);
			return;
		}

		// Interaction actions
		_executeInteractAction(payload);
	}

	// ── Fuzzy string matching (client-side) ──────────────────────────────────
	function _fuzzyScore(query, candidate) {
		if (!query || !candidate) return 0;
		const q = query.toLowerCase().trim().replace(/[-_]/g, " ");
		const c = candidate.toLowerCase().trim().replace(/[-_]/g, " ");
		if (q === c) return 1.0;
		if (c.includes(q)) return 0.85;
		if (q.includes(c)) return 0.75;
		// Token Jaccard
		const qt = new Set(q.match(/[a-z0-9]+/g) || []);
		const ct = new Set(c.match(/[a-z0-9]+/g) || []);
		if (!qt.size || !ct.size) return 0;
		let inter = 0;
		for (const t of qt) if (ct.has(t)) inter++;
		const union = qt.size + ct.size - inter;
		const jaccard = inter / union;
		// Acronym bonus: "pms" matches "project management system"
		const acro = [...ct].map(([f]) => f).join("") || "";
		const acroBon = (acro === q.replace(/\s/g, "")) ? 0.6 : 0;
		return Math.max(jaccard, acroBon);
	}

	function _fuzzyBest(query, candidates, threshold = 0.25) {
		if (!query || !candidates || !candidates.length) return null;
		let best = null, bestScore = -1;
		for (const c of candidates) {
			const s = _fuzzyScore(query, typeof c === "string" ? c : c.label || c.fieldname || c.name || "");
			if (s > bestScore) { bestScore = s; best = c; }
		}
		return bestScore >= threshold ? best : null;
	}

	function _executeNavAction(payload) {
		const { action, doctype, name, report_name, workspace, page, filters, defaults } = payload;
		try {
			if (action === "list") {
				if (filters && Object.keys(filters).length) {
					frappe.route_options = Object.assign({}, frappe.route_options || {}, filters);
				}
				frappe.set_route("List", doctype, "List");

			} else if (action === "form") {
				frappe.set_route("Form", doctype, name);

			} else if (action === "new_form") {
				if (defaults && Object.keys(defaults).length) {
					frappe.route_options = Object.assign({}, frappe.route_options || {}, defaults);
				}
				frappe.new_doc(doctype);

			} else if (action === "report") {
				frappe.set_route("query-report", report_name, filters || {});

			} else if (action === "workspace") {
				frappe.set_route(workspace);

			} else if (action === "page") {
				// Custom Frappe page — slug already resolved server-side
				if (frappe.pages && frappe.pages[page]) {
					frappe.set_route(page);
				} else {
					// Fallback: fuzzy-search known pages in frappe.pages
					const pageKeys = Object.keys(frappe.pages || {});
					const match = _fuzzyBest(page, pageKeys);
					frappe.set_route(match || page);
				}
			}
		} catch (err) {
			console.warn("[frappe_ai] nav action error:", err);
		}
	}

	function _executeInteractAction(payload) {
		const { action } = payload;
		_showAiActionToast(_interactLabel(payload));

		try {
			// ── Form document actions ──────────────────────────────────────────
			if (action === "save_form") {
				if (cur_frm) cur_frm.save("Save");

			} else if (action === "submit_document") {
				if (cur_frm) cur_frm.savesubmit();

			} else if (action === "cancel_document") {
				if (!cur_frm) return;
				const doIt = () => cur_frm.savecancel();
				payload.confirm ? doIt() : frappe.confirm("Cancel this document?", doIt);

			} else if (action === "amend_document") {
				if (cur_frm && cur_frm.amend_doc) cur_frm.amend_doc();

			} else if (action === "delete_document") {
				_doDeleteDocument(payload.confirm);

			} else if (action === "new_document") {
				const dt = payload.doctype || (cur_frm && cur_frm.doctype);
				if (dt) frappe.new_doc(dt);

			// ── Form field actions ─────────────────────────────────────────────
			} else if (action === "set_field_value") {
				if (cur_frm && payload.fieldname) {
					const fn = _resolveFormFieldname(payload.fieldname);
					cur_frm.set_value(fn, payload.value);
				}

			} else if (action === "scroll_to_field") {
				_doScrollToField(_resolveFormFieldname(payload.fieldname));

			} else if (action === "expand_section") {
				_doExpandSection(payload.section_label);

			// ── Child table ────────────────────────────────────────────────────
			} else if (action === "add_child_row") {
				if (cur_frm && payload.table_fieldname) {
					cur_frm.add_child(payload.table_fieldname);
					cur_frm.refresh_field(payload.table_fieldname);
				}

			} else if (action === "set_child_row_value") {
				_doSetChildRowValue(payload.table_fieldname, payload.row_index, payload.fieldname, payload.value);

			} else if (action === "delete_child_row") {
				_doDeleteChildRow(payload.table_fieldname, payload.row_index);

			// ── Generic click / type ───────────────────────────────────────────
			} else if (action === "click_button") {
				_doClickButton(payload.button_label);

			} else if (action === "click_element") {
				_doClickElement(payload.selector, payload.text);

			} else if (action === "type_in_element") {
				_doTypeInElement(payload.selector, payload.label, payload.text);

			// ── List view ──────────────────────────────────────────────────────
			} else if (action === "add_list_filter") {
				_doAddListFilter(payload.fieldname, payload.operator, payload.value);

			} else if (action === "remove_list_filter") {
				_doRemoveListFilter(payload.fieldname);

			} else if (action === "clear_list_filters") {
				_doClearListFilters();

			} else if (action === "click_list_action") {
				_doClickListAction(payload.list_action);

			} else if (action === "select_list_rows") {
				_doSelectListRows(payload.select_all, payload.names);

			// ── Report ─────────────────────────────────────────────────────────
			} else if (action === "set_report_filter") {
				_doSetReportFilter(payload.filter_label, payload.value);

			} else if (action === "run_report") {
				_doRunReport();

			// ── Dialog ─────────────────────────────────────────────────────────
			} else if (action === "open_quick_entry") {
				if (frappe.ui.QuickEntryForm) new frappe.ui.QuickEntryForm(payload.doctype, null, null, true);

			} else if (action === "open_dialog_action") {
				_doDialogButtonClick(payload.button_label);

			} else if (action === "close_dialog") {
				_doCloseDialog();
			}
		} catch (err) {
			console.warn("[frappe_ai] interact error:", err);
			frappe.show_alert({ message: `Action failed: ${err.message}`, indicator: "orange" }, 4);
		}
	}

	// ── Form helpers ──────────────────────────────────────────────────────────
	function _doDeleteDocument(autoConfirm) {
		if (!cur_frm) return;
		const doctype = cur_frm.doctype, docname = cur_frm.docname;
		if (!doctype || !docname) return;
		const doDelete = () => frappe.call({
			method: "frappe.client.delete",
			args: { doctype, name: docname },
			callback() {
				frappe.show_alert({ message: `${docname} deleted.`, indicator: "green" }, 3);
				frappe.set_route("List", doctype, "List");
			},
		});
		autoConfirm ? doDelete()
			: frappe.confirm(`Delete <b>${frappe.utils.escape_html(docname)}</b>? This cannot be undone.`, doDelete);
	}

	function _doScrollToField(fieldname) {
		if (!cur_frm || !fieldname) return;
		const field = cur_frm.get_field(fieldname);
		if (field && field.wrapper) field.wrapper.scrollIntoView({ behavior: "smooth", block: "center" });
	}

	function _doExpandSection(sectionLabel) {
		if (!sectionLabel) return;
		const lc = sectionLabel.toLowerCase();

		// 1. Frappe form sections — exact then fuzzy
		if (cur_frm && cur_frm.layout) {
			const sections = cur_frm.layout.sections || [];
			const sectionLabels = sections.map(s => (s.df && s.df.label) || "").filter(Boolean);
			// Exact match first
			let target = sections.find(s => (s.df && s.df.label || "").toLowerCase() === lc);
			// Fuzzy fallback
			if (!target) {
				const bestLbl = _fuzzyBest(lc, sectionLabels);
				if (bestLbl) target = sections.find(s => (s.df && s.df.label) === bestLbl);
			}
			if (target) {
				if (target.collapsed) target.collapse(false);
				if (target.wrapper) target.wrapper.scrollIntoView({ behavior: "smooth", block: "start" });
				return;
			}
		}

		// 2. Tabs — exact then fuzzy
		if (cur_frm && cur_frm.page) {
			const tabs = Array.from(cur_frm.page.wrapper ? cur_frm.page.wrapper.querySelectorAll(".nav-link, .tab-link") : []);
			let target = tabs.find(t => (t.textContent || "").toLowerCase().trim() === lc);
			if (!target) {
				const tabLabels = tabs.map(t => (t.textContent || "").trim()).filter(Boolean);
				const best = _fuzzyBest(lc, tabLabels);
				if (best) target = tabs.find(t => (t.textContent || "").trim() === best);
			}
			if (target) { target.click(); return; }
		}

		// 3. Generic DOM heading — fuzzy text match
		const allHeadings = Array.from(document.querySelectorAll(
			".section-head, .section-heading, [data-section], .form-section .panel-heading, .accordion-toggle"
		)).filter(el => el.offsetParent);
		const headingTexts = allHeadings.map(el => (el.textContent || "").trim()).filter(Boolean);
		const bestHdg = _fuzzyBest(lc, headingTexts);
		if (bestHdg) {
			const el = allHeadings.find(e => (e.textContent || "").trim() === bestHdg);
			if (el) { el.click(); el.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
		}
	}

	function _resolveChildFieldname(tableFieldname, raw) {
		if (!cur_frm || !raw) return raw;
		// Get child doctype
		const parentMeta = cur_frm.meta;
		const tableDef = parentMeta && (parentMeta.fields || []).find(f => f.fieldname === tableFieldname && f.fieldtype === "Table");
		if (!tableDef || !tableDef.options) return raw;
		const childMeta = frappe.get_meta && frappe.get_meta(tableDef.options);
		if (!childMeta) return raw;
		const fields = childMeta.fields || [];
		const lc = raw.toLowerCase();
		const exactFn = fields.find(f => f.fieldname === raw || f.fieldname.toLowerCase() === lc);
		if (exactFn) return exactFn.fieldname;
		const labelMatch = fields.find(f => (f.label || "").toLowerCase() === lc);
		if (labelMatch) return labelMatch.fieldname;
		const bestFn = _fuzzyBest(lc, fields.map(f => f.fieldname));
		if (bestFn) return bestFn;
		const bestLbl = _fuzzyBest(lc, fields.map(f => f.label || "").filter(Boolean));
		if (bestLbl) {
			const f = fields.find(f => f.label === bestLbl);
			if (f) return f.fieldname;
		}
		return raw;
	}

	function _doSetChildRowValue(tableFieldname, rowIndex, fieldname, value) {
		if (!cur_frm || !tableFieldname || !fieldname) return;
		fieldname = _resolveChildFieldname(tableFieldname, fieldname);
		const rows = cur_frm.doc[tableFieldname] || [];
		const row = rows[rowIndex];
		if (!row) { frappe.show_alert({ message: `Row ${rowIndex} not found in ${tableFieldname}.`, indicator: "orange" }, 3); return; }
		frappe.model.set_value(row.doctype, row.name, fieldname, value);
		cur_frm.refresh_field(tableFieldname);
	}

	function _doDeleteChildRow(tableFieldname, rowIndex) {
		if (!cur_frm || !tableFieldname) return;
		const rows = cur_frm.doc[tableFieldname] || [];
		const row = rows[rowIndex];
		if (!row) { frappe.show_alert({ message: `Row ${rowIndex} not found.`, indicator: "orange" }, 3); return; }
		cur_frm.get_field(tableFieldname).grid.grid_rows[rowIndex].remove();
		cur_frm.refresh_field(tableFieldname);
	}

	// ── Generic click / type ──────────────────────────────────────────────────
	function _doClickButton(label) {
		if (!label) return;
		const lc = label.toLowerCase().trim();

		// Collect all candidate elements with their text labels
		const collectCandidates = () => {
			const out = []; // [{el, text}]
			// Form primary button
			if (cur_frm && cur_frm.page && cur_frm.page.btn_primary) {
				const pb = cur_frm.page.btn_primary;
				if (pb[0]) out.push({ el: pb[0], text: (pb.text ? pb.text() : pb[0].textContent || "").trim() });
			}
			// Form custom buttons
			if (cur_frm && cur_frm.custom_buttons) {
				for (const [bl, btn] of Object.entries(cur_frm.custom_buttons)) {
					if (btn[0]) out.push({ el: btn[0], text: bl });
				}
			}
			// Form menu dropdown items
			if (cur_frm && cur_frm.page && cur_frm.page.menu_btn_group) {
				const items = cur_frm.page.menu_btn_group[0]
					? cur_frm.page.menu_btn_group[0].querySelectorAll(".dropdown-item")
					: [];
				for (const el of items) {
					if (el.offsetParent) out.push({ el, text: (el.textContent || "").trim() });
				}
			}
			// Page-wide buttons
			document.querySelectorAll(
				".page-head button, .page-content button, .modal-footer button, .navbar button, .btn, [role=button]"
			).forEach(el => {
				if (el.offsetParent !== null && !el.disabled) {
					const txt = (el.textContent || el.getAttribute("data-label") || el.getAttribute("aria-label") || "").trim();
					if (txt) out.push({ el, text: txt });
				}
			});
			return out;
		};

		const candidates = collectCandidates();

		// 1. Exact / starts-with match
		for (const { el, text } of candidates) {
			const t = text.toLowerCase();
			if (t === lc || t.startsWith(lc)) { _triggerClick(el); return; }
		}

		// 2. Fuzzy match
		const bestItem = _fuzzyBest(lc, candidates.map(c => c.text));
		if (bestItem) {
			const found = candidates.find(c => c.text === bestItem);
			if (found) { _triggerClick(found.el); return; }
		}

		frappe.show_alert({ message: `Button "${label}" not found on this page.`, indicator: "orange" }, 4);
	}

	function _triggerClick(el) {
		// Handle both jQuery objects and native DOM elements
		if (el && el.trigger) el.trigger("click");
		else if (el) el.click();
	}

	function _doClickElement(selector, text) {
		// By CSS selector
		if (selector) {
			const el = document.querySelector(selector);
			if (el && el.offsetParent !== null) { el.click(); return; }
		}
		if (text) {
			const lc = text.toLowerCase();
			const candidates = Array.from(document.querySelectorAll(
				"a, button, [role=button], .btn, td, li, .dropdown-item, label, .frappe-control .control-label"
			)).filter(el => el.offsetParent !== null);
			// 1. Exact substring match
			const exactMatch = candidates.find(el => (el.textContent || "").toLowerCase().trim().includes(lc));
			if (exactMatch) { exactMatch.click(); return; }
			// 2. Fuzzy match
			const texts = candidates.map(el => (el.textContent || "").trim()).filter(Boolean);
			const best = _fuzzyBest(lc, texts);
			if (best) {
				const found = candidates.find(el => (el.textContent || "").trim() === best);
				if (found) { found.click(); return; }
			}
		}
		frappe.show_alert({ message: `Element not found: ${selector || text}`, indicator: "orange" }, 4);
	}

	function _doTypeInElement(selector, label, text) {
		let el = null;

		// By CSS selector
		if (selector) el = document.querySelector(selector);

		// By label text → find associated input (exact, then fuzzy)
		if (!el && label) {
			const lc = label.toLowerCase();
			const allLabels = Array.from(document.querySelectorAll(".frappe-control label, .form-group label, label"));

			// Exact / substring match
			let matchedLbl = allLabels.find(lbl => (lbl.textContent || "").toLowerCase().trim().includes(lc) && lbl.offsetParent);
			// Fuzzy fallback
			if (!matchedLbl) {
				const lblTexts = allLabels.filter(l => l.offsetParent).map(l => (l.textContent || "").trim()).filter(Boolean);
				const bestTxt = _fuzzyBest(lc, lblTexts);
				if (bestTxt) matchedLbl = allLabels.find(l => (l.textContent || "").trim() === bestTxt);
			}

			if (matchedLbl) {
				const ctrl = matchedLbl.closest(".frappe-control, .form-group");
				if (ctrl) el = ctrl.querySelector("input, select, textarea");
				if (!el && matchedLbl.htmlFor) el = document.getElementById(matchedLbl.htmlFor);
			}

			// aria-label / placeholder fallback
			if (!el) {
				el = document.querySelector(`[aria-label*="${label}"], input[placeholder*="${label}"], textarea[placeholder*="${label}"]`);
			}
		}

		if (!el || el.offsetParent === null) {
			frappe.show_alert({ message: `Input not found: ${selector || label}`, indicator: "orange" }, 4);
			return;
		}

		el.focus();
		const nativeSetter = Object.getOwnPropertyDescriptor(
			el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype, "value"
		);
		if (nativeSetter && nativeSetter.set) nativeSetter.set.call(el, text);
		else el.value = text;
		el.dispatchEvent(new Event("input", { bubbles: true }));
		el.dispatchEvent(new Event("change", { bubbles: true }));
	}

	// ── List filters ──────────────────────────────────────────────────────────
	function _resolveFormFieldname(raw) {
		if (!cur_frm || !raw) return raw;
		const meta = cur_frm.meta;
		const fields = (meta && meta.fields) || [];
		const lc = raw.toLowerCase();
		// Exact fieldname
		const exactFn = fields.find(f => f.fieldname === raw || f.fieldname.toLowerCase() === lc);
		if (exactFn) return exactFn.fieldname;
		// Label match
		const labelMatch = fields.find(f => (f.label || "").toLowerCase() === lc);
		if (labelMatch) return labelMatch.fieldname;
		// Fuzzy fieldname
		const fieldnames = fields.map(f => f.fieldname);
		const bestFn = _fuzzyBest(lc, fieldnames);
		if (bestFn) return bestFn;
		// Fuzzy label → fieldname
		const labels = fields.map(f => f.label || "").filter(Boolean);
		const bestLbl = _fuzzyBest(lc, labels);
		if (bestLbl) {
			const f = fields.find(f => f.label === bestLbl);
			if (f) return f.fieldname;
		}
		return raw;
	}

	function _resolveListFieldname(raw) {
		if (!cur_list || !raw) return raw;
		const lc = raw.toLowerCase();
		// 1. Exact fieldname match
		const meta = frappe.get_meta && frappe.get_meta(cur_list.doctype);
		const fields = (meta && meta.fields) || [];
		const exactFn = fields.find(f => f.fieldname === raw || f.fieldname.toLowerCase() === lc);
		if (exactFn) return exactFn.fieldname;
		// 2. Label match
		const labelMatch = fields.find(f => (f.label || "").toLowerCase() === lc);
		if (labelMatch) return labelMatch.fieldname;
		// 3. Fuzzy against fieldnames
		const fieldnames = fields.map(f => f.fieldname);
		const bestFn = _fuzzyBest(lc, fieldnames);
		if (bestFn) return bestFn;
		// 4. Fuzzy against labels → return fieldname
		const labels = fields.map(f => f.label || "").filter(Boolean);
		const bestLbl = _fuzzyBest(lc, labels);
		if (bestLbl) {
			const f = fields.find(f => f.label === bestLbl);
			if (f) return f.fieldname;
		}
		return raw; // fallback — let Frappe error naturally
	}

	function _doAddListFilter(fieldname, operator, value) {
		if (!cur_list || !fieldname) return;
		operator = operator || "=";
		fieldname = _resolveListFieldname(fieldname);
		try {
			// frappe.ui.FilterGroup / list.filter_area
			if (cur_list.filter_area) {
				cur_list.filter_area.add([[cur_list.doctype, fieldname, operator, value]]);
			} else if (cur_list.filters !== undefined) {
				// legacy path
				cur_list.filters = (cur_list.filters || []).filter(f => f[1] !== fieldname);
				cur_list.filters.push([cur_list.doctype, fieldname, operator, value]);
				cur_list.refresh();
			}
		} catch (e) {
			frappe.show_alert({ message: `Could not add filter: ${e.message}`, indicator: "orange" }, 4);
		}
	}

	function _doRemoveListFilter(fieldname) {
		if (!cur_list || !fieldname) return;
		fieldname = _resolveListFieldname(fieldname);
		try {
			if (cur_list.filter_area && cur_list.filter_area.filter_list) {
				cur_list.filter_area.filter_list.filters
					.filter(f => f.fieldname === fieldname)
					.forEach(f => f.remove());
			} else if (Array.isArray(cur_list.filters)) {
				cur_list.filters = cur_list.filters.filter(f => f[1] !== fieldname);
				cur_list.refresh();
			}
		} catch (e) { _log("remove_list_filter error:", e); }
	}

	function _doClearListFilters() {
		if (!cur_list) return;
		try {
			if (cur_list.filter_area) cur_list.filter_area.clear_filters();
			else { cur_list.filters = []; cur_list.refresh(); }
		} catch (e) { _log("clear_list_filters error:", e); }
	}

	// ── List toolbar ──────────────────────────────────────────────────────────
	function _doClickListAction(listAction) {
		if (!listAction) return;
		const lc = listAction.toLowerCase().trim();

		const collectListCandidates = () => {
			const out = [];
			if (cur_list && cur_list.page) {
				const tb = cur_list.page.inner_toolbar;
				if (tb && tb[0]) {
					tb[0].querySelectorAll("button, .dropdown-item, a").forEach(el => {
						if (el.offsetParent) out.push({ el, text: (el.textContent || "").trim() });
					});
				}
			}
			document.querySelectorAll(
				".list-toolbar button, .list-header button, .page-actions button, .actions-btn-group .dropdown-item"
			).forEach(el => {
				if (el.offsetParent) out.push({ el, text: (el.textContent || "").trim() });
			});
			return out;
		};

		const candidates = collectListCandidates();
		// Exact
		const exact = candidates.find(c => c.text.toLowerCase().trim() === lc);
		if (exact) { exact.el.click(); return; }
		// Fuzzy
		const best = _fuzzyBest(lc, candidates.map(c => c.text));
		if (best) {
			const found = candidates.find(c => c.text === best);
			if (found) { found.el.click(); return; }
		}

		frappe.show_alert({ message: `List action "${listAction}" not found.`, indicator: "orange" }, 4);
	}

	function _doSelectListRows(selectAll, names) {
		if (!cur_list) return;
		if (selectAll) {
			// Click the select-all checkbox
			const chk = document.querySelector(".list-check-all, .select-all-checkbox, input[data-fieldname='check_all']");
			if (chk) { chk.checked = true; chk.dispatchEvent(new Event("change", { bubbles: true })); return; }
			if (cur_list.select_all) { cur_list.select_all(); return; }
		}
		if (names && names.length) {
			names.forEach(name => {
				const row = document.querySelector(`.list-row[data-name="${CSS.escape(name)}"]`);
				if (row) {
					const chk = row.querySelector("input[type=checkbox]");
					if (chk) { chk.checked = true; chk.dispatchEvent(new Event("change", { bubbles: true })); }
				}
			});
		}
	}

	// ── Report ────────────────────────────────────────────────────────────────
	function _doSetReportFilter(filterLabel, value) {
		if (!window.frappe || !frappe.query_report) {
			frappe.show_alert({ message: "No report is open.", indicator: "orange" }, 3); return;
		}
		const lc = filterLabel.toLowerCase();
		const filters = frappe.query_report.filters || [];

		// Exact / substring match
		let target = filters.find(f => {
			const l = (f.df && f.df.label || "").toLowerCase();
			return l === lc || l.includes(lc);
		});

		// Fuzzy fallback
		if (!target) {
			const labels = filters.map(f => (f.df && f.df.label) || "").filter(Boolean);
			const best = _fuzzyBest(lc, labels);
			if (best) target = filters.find(f => (f.df && f.df.label) === best);
		}

		if (target) {
			if (target.set_value) { target.set_value(value); return; }
			if (target.df && target.df.fieldname) { frappe.query_report.set_filter_value(target.df.fieldname, value); return; }
		}

		frappe.show_alert({ message: `Report filter "${filterLabel}" not found.`, indicator: "orange" }, 4);
	}

	function _doRunReport() {
		if (window.frappe && frappe.query_report && frappe.query_report.refresh) {
			frappe.query_report.refresh(); return;
		}
		// Fallback: click the Run button
		const runBtn = document.querySelector(".run-report-btn, button[data-action=run_query], .btn-run");
		if (runBtn) runBtn.click();
	}

	// ── Dialog ────────────────────────────────────────────────────────────────
	function _doDialogButtonClick(label) {
		const lc = (label || "").toLowerCase().trim();
		const dlg = frappe._cur_dialog;

		const collectDlgCandidates = () => {
			const out = [];
			if (dlg && dlg.get_primary_btn) {
				const pb = dlg.get_primary_btn();
				if (pb && pb[0]) out.push({ el: pb[0], text: (pb.text ? pb.text() : pb[0].textContent || "").trim() });
			}
			document.querySelectorAll(".modal.show .modal-footer button, .modal-dialog button, .frappe-dialog button")
				.forEach(el => { if (el.offsetParent) out.push({ el, text: (el.textContent || "").trim() }); });
			return out;
		};

		const candidates = collectDlgCandidates();
		const exact = candidates.find(c => c.text.toLowerCase().trim() === lc);
		if (exact) { _triggerClick(exact.el); return; }
		const best = _fuzzyBest(lc, candidates.map(c => c.text));
		if (best) {
			const found = candidates.find(c => c.text === best);
			if (found) { _triggerClick(found.el); return; }
		}
		frappe.show_alert({ message: `Dialog button "${label}" not found.`, indicator: "orange" }, 4);
	}

	function _doCloseDialog() {
		const dlg = frappe._cur_dialog;
		if (dlg && dlg.hide) { dlg.hide(); return; }
		const closeBtn = document.querySelector(".modal.show .btn-modal-close, .modal.show .close, .frappe-dialog .btn-modal-close");
		if (closeBtn) closeBtn.click();
	}

	function _interactLabel(payload) {
		const { action, button_label, fieldname, value, list_action, doctype, table_fieldname, row_index, section_label, filter_label, selector, text, label } = payload;
		const map = {
			"save_form": "Saving form",
			"submit_document": "Submitting document",
			"cancel_document": "Cancelling document",
			"amend_document": "Amending document",
			"delete_document": "Deleting document",
			"clear_list_filters": "Clearing filters",
			"run_report": "Running report",
			"close_dialog": "Closing dialog",
		};
		if (map[action]) return map[action];
		if (action === "new_document") return `New ${doctype || "document"}`;
		if (action === "set_field_value") return `Set ${fieldname} → ${value}`;
		if (action === "scroll_to_field") return `Scroll to ${fieldname}`;
		if (action === "expand_section") return `Expand "${section_label}"`;
		if (action === "add_child_row") return `Add row to ${table_fieldname}`;
		if (action === "set_child_row_value") return `${table_fieldname}[${row_index}].${fieldname} → ${value}`;
		if (action === "delete_child_row") return `Delete row ${row_index} from ${table_fieldname}`;
		if (action === "click_button") return `Click "${button_label}"`;
		if (action === "click_element") return `Click ${selector || text}`;
		if (action === "type_in_element") return `Type "${payload.text}" into ${selector || label}`;
		if (action === "add_list_filter") return `Filter ${fieldname} ${payload.operator || "="} ${value}`;
		if (action === "remove_list_filter") return `Remove filter: ${fieldname}`;
		if (action === "click_list_action") return `List: ${list_action}`;
		if (action === "select_list_rows") return payload.select_all ? "Select all rows" : `Select ${(payload.names||[]).length} rows`;
		if (action === "set_report_filter") return `Report: ${filter_label} → ${value}`;
		if (action === "open_quick_entry") return `Quick entry: ${doctype}`;
		if (action === "open_dialog_action") return `Dialog: "${button_label}"`;
		return action;
	}

	// ─── AI ACTION TOAST ─────────────────────────────────────────────────────
	let _toastTimeout = null;

	function _showAiActionToast(text) {
		let toast = document.getElementById("frappe-ai-action-toast");
		if (!toast) {
			toast = document.createElement("div");
			toast.id = "frappe-ai-action-toast";
			toast.className = "frappe-ai-action-toast";
			document.body.appendChild(toast);
		}
		toast.innerHTML = `
			<span class="frappe-ai-action-toast-icon">${getIcon("brain")}</span>
			<span class="frappe-ai-action-toast-text">${escapeHtml(text)}</span>
		`;
		toast.classList.add("is-visible");
		if (_toastTimeout) clearTimeout(_toastTimeout);
		_toastTimeout = setTimeout(() => {
			toast.classList.remove("is-visible");
			_toastTimeout = null;
		}, 2800);
	}

	function _finishStream(conversationId) {
		if (_streamFinished) return; // guard against double-fire
		_streamFinished = true;
		_streamingActive = false;
		_streamAbortController = null;
		setState({ type: "FINISH_STREAM", conversationId });
		loadConversations();
	}
	// ─── END CHANGE C ───

	// ─── CHANGE D: Wire abort button to abort_stream API ───
	function stopStreaming() {
		if (typingTimeout) {
			window.clearTimeout(typingTimeout);
			typingTimeout = null;
		}

		if (_streamAbortController) {
			_streamAbortController.abort();
			_streamAbortController = null;
		}
		_streamingActive = false;

		const conversationId = getActiveConversationId();
		if (conversationId) {
			frappe.call({
				method: "frappe_ai.frappe_ai.api.chat.abort_stream",
				args: { conversation_id: conversationId },
			});
		}

		setState({ type: "STOP_STREAM", conversationId });
	}
	// ─── END CHANGE D ───

	// ─── RENDER ──────────────────────────────────────────────────────────────────
	function render() {
		if (!dom.root) {
			return;
		}

		renderShell();
		renderMessages();
		// ─── CHANGE 4: Render History Drawer ───
		renderHistoryDrawer();
		// ─── END CHANGE 4 ───
		renderComposer();
	}

	function renderShell() {
		// ─── CHANGE 3: Expanded Shell Class + Header Icon ───
		dom.root.classList.toggle("is-expanded", state.isExpanded);
		dom.panel.classList.toggle("is-expanded", state.isExpanded);
		// ─── CHANGE 6: fai-expanded on panel for new-chat/history hide ───
		dom.panel.classList.toggle("fai-expanded", state.isExpanded);
		// ─── END CHANGE 6 ───
		dom.expandButton.setAttribute("aria-label", state.isExpanded ? "Collapse Chat" : "Expand Chat");
		dom.expandButton.innerHTML = state.isExpanded ? getIcon("collapse") : getIcon("expand");
		// ─── END CHANGE 3 ───
		// ─── CHANGE 4: Search + History Shell Classes ───
		dom.historyDrawer.classList.toggle("is-open", state.isHistoryOpen);
		// ─── CHANGE 8: Sync drawer search input value (header search removed) ───
		if (dom.drawerSearchInput && dom.drawerSearchInput.value !== state.searchQuery) {
			dom.drawerSearchInput.value = state.searchQuery;
		}
		// ─── END CHANGE 8 ───
		// ─── END CHANGE 4 ───
		// ─── CHANGE 5: Connected Header Dot Render ───
		dom.root
			.querySelector(".frappe-ai-status-dot")
			?.classList.toggle("is-connected", Boolean(state.isConnected));
		// ─── END CHANGE 5 ───
		dom.panel.classList.toggle("is-open", state.isOpen);
		dom.fab.setAttribute("aria-expanded", state.isOpen ? "true" : "false");
		dom.fab.setAttribute("aria-label", state.isOpen ? "Close AI Assistant" : "Open AI Assistant");
		dom.fabIcon.innerHTML = state.isOpen ? getIcon("chevron") : getIcon("chat");
		dom.badge.classList.toggle("is-visible", Boolean(state.hasUnread && !state.isOpen));
	}

	function _isToolCallJson(content) {
		if (!content || !content.includes('"name"')) return false;
		const s = content.trim();
		// Single object: {"type":"function","name":"...",...} or {"name":"...","parameters":{}}
		if (s.startsWith("{") && s.endsWith("}")) {
			try {
				const p = JSON.parse(s);
				if (p && typeof p === "object" && (p.type === "function" || (p.name && (p.parameters !== undefined || p.arguments !== undefined)))) return true;
			} catch (_) {}
		}
		// Array of tool call objects
		if (s.startsWith("[") && s.endsWith("]")) {
			try {
				const arr = JSON.parse(s);
				if (Array.isArray(arr) && arr.length && arr.every((i) => i && (i.type === "function" || i.name))) return true;
			} catch (_) {}
		}
		return false;
	}

	function renderMessages() {
		const conversation = getActiveConversation();
		const allMessages = conversation?.messages || [];
		// Filter out raw tool-call JSON blobs that slipped through from older responses
		const messages = allMessages.filter(
			(m) => !(m.role === "assistant" && _isToolCallJson(m.content))
		);

		dom.messagesArea.innerHTML = "";

		if (!messages.length && !state.isTyping) {
			dom.messagesArea.appendChild(buildEmptyState());
			return;
		}

		messages.forEach((message) => {
			dom.messagesArea.appendChild(buildMessageElement(message));
		});

		if (state.isTyping) {
			dom.messagesArea.appendChild(buildTypingIndicator());
		}

		dom.messagesArea.scrollTop = dom.messagesArea.scrollHeight;
	}

	function renderComposer() {
		const isStreaming = state.isStreaming;

		// ─── CHANGE 2: Render Voice + Attachment Composer State ───
		dom.micButton.classList.toggle("is-recording", state.isRecording);
		renderAttachmentPill();
		// ─── END CHANGE 2 ───
		dom.textarea.disabled = isStreaming;
		dom.sendButton.disabled = false;
		dom.sendButton.classList.toggle("is-stop", isStreaming);
		dom.sendButton.setAttribute("aria-label", isStreaming ? "Stop Response" : "Send Message");
		dom.sendButton.innerHTML = isStreaming ? getIcon("stop") : getIcon("send");
	}

	// ─── CHANGE 2: Render Attachment Pill ───
	function renderAttachmentPill() {
		const attachment = state.pendingAttachment;
		dom.attachmentPill.classList.toggle("has-attachment", Boolean(attachment));

		if (!attachment) {
			dom.attachmentPill.innerHTML = "";
			return;
		}

		dom.attachmentPill.innerHTML = `
			<span class="frappe-ai-attachment-chip">
				<span class="frappe-ai-attachment-name">${escapeHtml(attachment.name)}</span>
				<button class="frappe-ai-attachment-remove" type="button" data-remove-attachment aria-label="Remove attachment">×</button>
			</span>
		`;
	}
	// TODO: API — upload attachment before sending message
	// ─── END CHANGE 2 ───

	// ─── CHANGE 4: Render History Drawer ───
	// ─── CHANGE 8: renderSearchResults removed — filtering now happens inside renderHistoryDrawer ───
	function renderHistoryDrawer() {
		// ─── CHANGE 8: Filter conversation list by drawer search query ───
		const query = state.searchQuery.trim().toLowerCase();
		const conversations = query
			? state.conversations.filter((conversation) =>
				`${conversation.title} ${conversation.last_message}`.toLowerCase().includes(query)
			)
			: state.conversations;

		dom.historyList.innerHTML = "";
		if (!conversations.length) {
			dom.historyList.innerHTML = '<div class="frappe-ai-drawer-search-empty">No results</div>';
			return;
		}
		conversations.forEach((conversation) => {
			dom.historyList.appendChild(buildConversationRow(conversation));
		});
		// ─── END CHANGE 8 ───
	}

	function buildConversationRow(conversation) {
		const row = document.createElement("div");
		row.className = "frappe-ai-conversation-row";
		row.classList.toggle("is-active", conversation.id === state.activeConversationId);
		row.setAttribute("data-conversation-id", conversation.id);
		row.innerHTML = `
			<button class="frappe-ai-conversation-body" type="button" data-action="select-conversation" data-conversation-id="${escapeHtml(conversation.id)}">
				<div class="frappe-ai-conversation-title-wrap">
					<span class="frappe-ai-conversation-title">${escapeHtml(conversation.title)}</span>
					<input class="frappe-ai-conversation-title-input" type="text" value="${escapeHtml(conversation.title)}" maxlength="120" />
				</div>
				<div class="frappe-ai-conversation-snippet">${escapeHtml(truncateText(conversation.last_message, 60))}</div>
				<div class="frappe-ai-conversation-time">${escapeHtml(conversation.timestamp || "")}</div>
			</button>
			<div class="frappe-ai-conversation-actions">
				<button class="frappe-ai-conv-action-btn" type="button" data-action="edit-conversation" data-conversation-id="${escapeHtml(conversation.id)}" aria-label="Rename conversation">${getIcon("edit")}</button>
				<button class="frappe-ai-conv-action-btn is-danger" type="button" data-action="delete-conversation" data-conversation-id="${escapeHtml(conversation.id)}" aria-label="Delete conversation">${getIcon("trash")}</button>
			</div>
		`;
		return row;
	}
	// TODO: API — replace with server-side search in v2
	// ─── END CHANGE 4 ───

	function buildEmptyState() {
		const emptyState = document.createElement("div");
		emptyState.className = "frappe-ai-empty-state";
		emptyState.innerHTML = `
			<div class="frappe-ai-empty-icon" aria-hidden="true">${getIcon("brain")}</div>
			<h2>How can I help you?</h2>
			<div class="frappe-ai-suggestions">
				${SUGGESTIONS.map((suggestion, index) => {
					// ─── CHANGE 5: Suggestion Chip Icons ───
					const icons = ["checklist", "barChart", "inbox"];
					return `<button class="frappe-ai-suggestion-chip" type="button" data-suggestion="${escapeAttribute(
						suggestion
					)}">${getIcon(icons[index])}${escapeHtml(suggestion)}</button>`;
					// ─── END CHANGE 5 ───
				}).join("")}
			</div>
		`;
		return emptyState;
	}

	function buildTypingIndicator() {
		const wrapper = document.createElement("div");
		wrapper.className = "frappe-ai-message is-assistant";
		wrapper.innerHTML = `
			<div class="frappe-ai-bubble">
				<div class="frappe-ai-bubble-meta">
					<span>Frappe AI</span>
				</div>
				<div class="frappe-ai-typing" aria-label="Frappe AI is typing">
					<span></span><span></span><span></span>
				</div>
			</div>
			<div class="frappe-ai-message-time">just now</div>
		`;
		return wrapper;
	}

	function buildMessageElement(message) {
		const wrapper = document.createElement("div");
		const isAssistant = message.role === "assistant";
		wrapper.className = `frappe-ai-message is-${message.role}`;
		wrapper.innerHTML = `
			<div class="frappe-ai-bubble">
				<div class="frappe-ai-bubble-meta">
					<span>${isAssistant ? "Frappe AI" : "You"}</span>
				</div>
				<div class="frappe-ai-bubble-content"></div>
			</div>
			${
				isAssistant
					? `<div class="frappe-ai-assistant-footer">
						<div class="frappe-ai-message-time">${escapeHtml(getRelativeTimestamp(message))}</div>
						<div class="frappe-ai-bubble-footer">
							<button class="frappe-ai-bubble-action" type="button" data-copy-message="${escapeAttribute(
								message.id
							)}" aria-label="Copy Message">${getIcon("copy")}</button>
							<button class="frappe-ai-bubble-action" type="button" data-regenerate-message="${escapeAttribute(
								message.id
							)}" aria-label="Regenerate Response">${getIcon("regenerate")}</button>
						</div>
					</div>`
					: `<div class="frappe-ai-message-time">${escapeHtml(getRelativeTimestamp(message))}</div>`
			}
		`;

		const content = wrapper.querySelector(".frappe-ai-bubble-content");
		content.innerHTML = renderMarkdown(message.content);
		if (message.isStreaming) {
			content.insertAdjacentHTML("beforeend", `
				<div class="frappe-ai-typing frappe-ai-stream-thinking">
					<span></span><span></span><span></span>
				</div>
			`);
		}
		enhanceCodeBlocks(content);

		return wrapper;
	}

	function renderMarkdown(content) {
		if (markedLoaded && window.marked?.parse) {
			return window.marked.parse(escapeMarkdownHtml(content || ""), {
				breaks: true,
				gfm: true,
			});
		}

		return `<p>${escapeHtml(content || "").replace(/\n/g, "<br>")}</p>`;
	}

	function enhanceCodeBlocks(scope) {
		scope.querySelectorAll("pre").forEach((pre) => {
			const wrapper = document.createElement("div");
			wrapper.className = "frappe-ai-code-wrap";
			pre.parentNode.insertBefore(wrapper, pre);
			wrapper.appendChild(pre);

			const copyButton = document.createElement("button");
			copyButton.className = "frappe-ai-copy-code";
			copyButton.type = "button";
			copyButton.setAttribute("data-copy-code", "true");
			copyButton.textContent = "Copy";
			wrapper.appendChild(copyButton);
		});
	}

	function getRelativeTimestamp(message) {
		if (!message.createdAt) {
			return message.timestamp || "just now";
		}

		const elapsedSeconds = Math.max(0, Math.floor((Date.now() - message.createdAt) / 1000));
		if (elapsedSeconds < 60) {
			return "just now";
		}

		const elapsedMinutes = Math.floor(elapsedSeconds / 60);
		if (elapsedMinutes < 60) {
			return `${elapsedMinutes}m ago`;
		}

		const elapsedHours = Math.floor(elapsedMinutes / 60);
		if (elapsedHours < 24) {
			return `${elapsedHours}h ago`;
		}

		return `${Math.floor(elapsedHours / 24)}d ago`;
	}

	function copyCodeBlock(button) {
		const code = button.closest(".frappe-ai-code-wrap")?.querySelector("code");
		copyText(code?.textContent || "", button);
	}

	function copyAssistantMessage(button) {
		const messageId = button.getAttribute("data-copy-message");
		const conversation = getActiveConversation();
		const message = conversation?.messages.find((item) => item.id === messageId);
		copyText(message?.content || "", button);
	}

	function copyText(text, button) {
		if (!text) {
			return;
		}

		const originalLabel = button.textContent;
		const originalHtml = button.innerHTML;
		const done = () => {
			button.textContent = "Copied!";
			window.setTimeout(() => {
				if (button.classList.contains("frappe-ai-bubble-action")) {
					button.innerHTML = originalHtml;
				} else {
					button.textContent = originalLabel || "Copy";
				}
			}, COPY_RESET_MS);
		};

		if (navigator.clipboard?.writeText) {
			navigator.clipboard.writeText(text).then(done);
			return;
		}

		const textarea = document.createElement("textarea");
		textarea.value = text;
		textarea.setAttribute("readonly", "readonly");
		textarea.style.position = "fixed";
		textarea.style.opacity = "0";
		document.body.appendChild(textarea);
		textarea.select();
		document.execCommand("copy");
		textarea.remove();
		done();
	}

	function escapeHtml(value) {
		return String(value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	}

	function escapeAttribute(value) {
		return escapeHtml(value).replace(/`/g, "&#096;");
	}

	function escapeMarkdownHtml(value) {
		return String(value).replace(/</g, "&lt;").replace(/>/g, "&gt;");
	}

	// ─── CHANGE 4: Conversation Snippet Helper ───
	function truncateText(value, length) {
		const text = String(value || "");
		if (text.length <= length) {
			return text;
		}

		return `${text.slice(0, length - 1)}…`;
	}
	// ─── END CHANGE 4 ───

	// ─── API LAYER ───────────────────────────────────────────────────────────────

	// ─── CHANGE A: Wire getConversations ───
	let _loadConversationsTimer = null;
	function loadConversations() {
		// Never fire while a stream is active — the XHR would queue behind the
		// occupied Frappe worker thread and appear stuck for minutes.
		// _streamingActive is set synchronously in submitPrompt, before the
		// setTimeout in startAssistantTurn fires, closing the timing gap.
		if (_streamingActive) return;
		// Debounce — collapse rapid successive calls into one
		if (_loadConversationsTimer) return;
		_loadConversationsTimer = window.setTimeout(() => { _loadConversationsTimer = null; }, 2000);
		setTimeout(() => {
			frappe.call({
				method: "frappe_ai.frappe_ai.api.conversation.get_list",
				args: { page: 0, limit: 50 },
				callback(response) {
					if (!response.message) return;
					const { conversations } = response.message;
					// Preserve already-loaded messages so the active chat doesn't blank out
					const existingById = {};
					for (const c of state.conversations) {
						existingById[c.id] = c;
					}
					const mapped = (conversations || []).map((conversation) => {
						const existing = existingById[conversation.name];
						return {
							id: conversation.name,
							title: conversation.title || "New Conversation",
							last_message: conversation.last_message || "",
							timestamp: conversation.modified ? _relativeDate(conversation.modified) : "",
							is_pinned: conversation.is_pinned,
							// Keep loaded messages — don't wipe them on refresh
							messages: existing ? existing.messages : [],
						};
					});
					// Restore last active conversation from session, falling back to current state
					const currentId = state.activeConversationId
						|| sessionStorage.getItem(SESSION_KEY);
					const stillExists = mapped.some((c) => c.id === currentId);
					const restoredId = stillExists ? currentId : null;
					setState({
						type: "LOAD_CONVERSATIONS",
						conversations: mapped,
						activeConversationId: restoredId,
					});
					// Load messages for restored conversation if not already loaded
					if (restoredId && !state.conversations.find((c) => c.id === restoredId)?.messages?.length) {
						loadMessages(restoredId);
					}
				},
			});
		}, 100);
	}

	function loadMessages(conversationId) {
		if (!conversationId) return;
		frappe.call({
			method: "frappe_ai.frappe_ai.api.conversation.get",
			args: { conversation_id: conversationId },
			callback(response) {
				if (!response.message?.conversation) return;
				const raw = response.message.conversation;
				const messages = (raw.messages || []).map((m) => ({
					id: m.name || `msg_${Math.random().toString(36).slice(2)}`,
					role: m.role,
					content: m.content || "",
					timestamp: m.timestamp ? _relativeDate(m.timestamp) : "just now",
					createdAt: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
					isStreaming: false,
				}));
				setState({
					type: "LOAD_MESSAGES",
					conversationId,
					messages,
					title: raw.title || "New Conversation",
					last_message: messages.length ? messages[messages.length - 1].content : "",
				});
			},
		});
	}
	// ─── END CHANGE A ───


// ─── CHANGE E: Wire settings.get_public on init ───
	function loadSiteSettings() {
		frappe.call({
			method: "frappe_ai.frappe_ai.api.settings.get_public",
			callback(response) {
				if (!response.message) return;
				state.siteSettings = response.message;
				_applySiteSettings(response.message);
			},
		});
	}

	function _applySiteSettings(settings) {
		if (dom.attachButton) {
			dom.attachButton.style.display = settings.file_upload_enabled ? "" : "none";
		}
		const agentIndicator = dom.root.querySelector(".frappe-ai-agent-indicator");
		if (agentIndicator) {
			agentIndicator.style.display = settings.tool_calling_enabled ? "" : "none";
		}
		const providerBadge = dom.root.querySelector(".frappe-ai-provider-badge");
		if (providerBadge && settings.provider) {
			providerBadge.textContent = settings.provider;
		}
	}
	// ─── END CHANGE E ───

	function _relativeDate(dateStr) {
		if (!dateStr) return "";
		const date = new Date(dateStr);
		const diffMs = Date.now() - date.getTime();
		const diffMins = Math.floor(diffMs / 60000);
		if (diffMins < 1) return "just now";
		if (diffMins < 60) return `${diffMins}m ago`;
		const diffHours = Math.floor(diffMins / 60);
		if (diffHours < 24) return `${diffHours}h ago`;
		return `${Math.floor(diffHours / 24)}d ago`;
	}

	// ─── INIT ───────────────────────────────────────────────────────────────────
	function init() {
		if (window.FrappeAI?._initialized) {
			return;
		}

		injectStyles();
		buildDom();
		bindEvents();

		window.FrappeAI._initialized = true;
		render();
		// ─── CHANGE A + CHANGE E: Load conversations and site settings from API ───
		loadConversations();
		loadSiteSettings();
		// ─── END CHANGE A + CHANGE E ───
		_log("Frappe AI chat initialized");
	}

	function open() {
		if (!window.FrappeAI?._initialized) {
			init();
		}

		setState({ type: "OPEN" });
		ensureMarked().then(() => {
			if (!markedLoaded && window.marked?.parse) {
				markedLoaded = true;
			}
			render();
		});
		window.setTimeout(() => {
			dom.textarea?.focus();
		}, 0);
	}

	function close() {
		setState({ type: "CLOSE" });
		dom.fab?.focus();
	}

	function ensureMarked() {
		if (markedLoaded || window.marked?.parse) {
			markedLoaded = true;
			return Promise.resolve();
		}

		if (!markedPromise) {
			markedPromise = frappe.require(MARKED_URL).then(() => {
				markedLoaded = Boolean(window.marked?.parse);
			});
		}

		return markedPromise;
	}

	window.FrappeAI = {
		init,
		open,
		close,
		_initialized: Boolean(window.FrappeAI?._initialized),
	};

	frappe.after_ajax(function () {
		// only init on desk pages, not login/setup
		if (frappe.session && frappe.session.user !== "Guest") {
			window.FrappeAI.init();
		}
	});
})();
