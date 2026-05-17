(function () {
    "use strict";

    if (window._frappAiLoaded) return;
    window._frappAiLoaded = true;

    const ICON_CHAT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>`;
    const ICON_CLOSE = "×";

    let history = [];
    let isOpen = false;

    function init() {
        if (document.getElementById("frappe-ai-btn")) return;

        // Button
        const btn = document.createElement("button");
        btn.id = "frappe-ai-btn";
        btn.title = "AI Assistant";
        btn.innerHTML = ICON_CHAT;
        btn.addEventListener("click", togglePanel);
        document.body.appendChild(btn);

        // Panel
        const panel = document.createElement("div");
        panel.id = "frappe-ai-panel";
        panel.className = "hidden";
        panel.innerHTML = `
            <div id="frappe-ai-header">
                <span>${ICON_CHAT} AI Assistant</span>
                <button id="frappe-ai-close" title="Close">${ICON_CLOSE}</button>
            </div>
            <div id="frappe-ai-messages"></div>
            <div id="frappe-ai-footer">
                <textarea id="frappe-ai-input" placeholder="Ask me anything about Frappe…" rows="1"></textarea>
                <button id="frappe-ai-send">➤</button>
            </div>
        `;
        document.body.appendChild(panel);

        document.getElementById("frappe-ai-close").addEventListener("click", togglePanel);
        document.getElementById("frappe-ai-send").addEventListener("click", sendMessage);
        document.getElementById("frappe-ai-input").addEventListener("keydown", function (e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Welcome message
        appendMessage("assistant", "Ciao! Sono l'assistente AI. Come posso aiutarti con Frappe/ERPNext?");
    }

    function togglePanel() {
        isOpen = !isOpen;
        const panel = document.getElementById("frappe-ai-panel");
        if (isOpen) {
            panel.classList.remove("hidden");
            document.getElementById("frappe-ai-input").focus();
        } else {
            panel.classList.add("hidden");
        }
    }

    function appendMessage(role, text) {
        const msgs = document.getElementById("frappe-ai-messages");
        const div = document.createElement("div");
        div.className = `ai-msg ${role}`;
        div.innerHTML = formatMessage(text);
        msgs.appendChild(div);
        msgs.scrollTop = msgs.scrollHeight;
        return div;
    }

    function formatMessage(text) {
        // Basic markdown: code blocks and line breaks
        return text
            .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
    }

    function sendMessage() {
        const input = document.getElementById("frappe-ai-input");
        const message = input.value.trim();
        if (!message) return;

        input.value = "";
        input.style.height = "38px";

        appendMessage("user", message);
        history.push({ role: "user", content: message });

        const sendBtn = document.getElementById("frappe-ai-send");
        sendBtn.disabled = true;

        const typingDiv = appendMessage("assistant", "…");
        typingDiv.classList.add("typing");

        frappe.call({
            method: "frappe_ai.api.chat.send_message",
            args: { message: message, history: history.slice(-10) },
            callback: function (r) {
                typingDiv.remove();
                sendBtn.disabled = false;
                if (r.message && r.message.reply) {
                    const reply = r.message.reply;
                    appendMessage("assistant", reply);
                    history.push({ role: "assistant", content: reply });
                    if (history.length > 20) history = history.slice(-20);
                } else {
                    appendMessage("assistant", "⚠️ Nessuna risposta dal provider AI. Controlla la configurazione in AI Settings.");
                }
            },
            error: function (err) {
                typingDiv.remove();
                sendBtn.disabled = false;
                const msg = err?.responseJSON?._server_messages
                    ? JSON.parse(err.responseJSON._server_messages)[0]?.message
                    : "Errore di connessione.";
                appendMessage("assistant", "⚠️ " + (msg || "Errore sconosciuto."));
            },
        });
    }

    // Auto-resize textarea
    document.addEventListener("input", function (e) {
        if (e.target.id === "frappe-ai-input") {
            e.target.style.height = "38px";
            e.target.style.height = Math.min(e.target.scrollHeight, 100) + "px";
        }
    });

    // Init after Frappe desk loads
    if (typeof frappe !== "undefined" && frappe.ui) {
        init();
    } else {
        document.addEventListener("DOMContentLoaded", function () {
            setTimeout(init, 1500);
        });
    }
})();
