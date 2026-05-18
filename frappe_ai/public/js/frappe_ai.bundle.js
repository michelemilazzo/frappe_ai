(function () {
    "use strict";

    if (window._frappAiLoaded) return;
    window._frappAiLoaded = true;

    const ICON_CHAT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>`;
    const ICON_CLOSE = "×";
    const ICON_ATTACH = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
    </svg>`;

    let history = [];
    let isOpen = false;
    let attachedFiles = []; // [{name, content}]

    function init() {
        if (document.getElementById("frappe-ai-btn")) return;

        const btn = document.createElement("button");
        btn.id = "frappe-ai-btn";
        btn.title = "AI Assistant";
        btn.innerHTML = ICON_CHAT;
        btn.addEventListener("click", togglePanel);
        document.body.appendChild(btn);

        const panel = document.createElement("div");
        panel.id = "frappe-ai-panel";
        panel.className = "hidden";
        panel.innerHTML = `
            <div id="frappe-ai-header">
                <span>${ICON_CHAT} AI Assistant</span>
                <button id="frappe-ai-close" title="Close">${ICON_CLOSE}</button>
            </div>
            <div id="frappe-ai-messages"></div>
            <div id="frappe-ai-attachments"></div>
            <div id="frappe-ai-footer">
                <button id="frappe-ai-attach" title="Allega file">${ICON_ATTACH}</button>
                <input type="file" id="frappe-ai-file-input" style="display:none"
                    accept=".txt,.md,.csv,.json,.py,.js,.html,.xml,.sql,.log,.pdf,.docx,.xlsx" multiple>
                <textarea id="frappe-ai-input" placeholder="Scrivi un messaggio…" rows="1"></textarea>
                <button id="frappe-ai-send">➤</button>
            </div>
        `;
        document.body.appendChild(panel);

        document.getElementById("frappe-ai-close").addEventListener("click", togglePanel);
        document.getElementById("frappe-ai-send").addEventListener("click", sendMessage);
        document.getElementById("frappe-ai-attach").addEventListener("click", function () {
            document.getElementById("frappe-ai-file-input").click();
        });
        document.getElementById("frappe-ai-file-input").addEventListener("change", handleFileSelect);
        document.getElementById("frappe-ai-input").addEventListener("keydown", function (e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        appendMessage("assistant", "Ciao! Sono l'assistente AI. Come posso aiutarti con Frappe/ERPNext?");
    }

    function handleFileSelect(e) {
        const files = Array.from(e.target.files);
        files.forEach(function (file) {
            const reader = new FileReader();
            reader.onload = function (ev) {
                let content = ev.target.result;
                // For binary reads (PDF etc) content may be base64 or garbled — just use filename
                if (typeof content !== "string") content = "[file binary]";
                attachedFiles.push({ name: file.name, content: content.slice(0, 8000) });
                renderAttachments();
            };
            // Read as text for text-based files
            const ext = file.name.split(".").pop().toLowerCase();
            if (["pdf"].includes(ext)) {
                // PDF: attach only filename + signal
                attachedFiles.push({ name: file.name, content: "[PDF allegato — il contenuto non può essere estratto lato client]" });
                renderAttachments();
            } else {
                reader.readAsText(file, "UTF-8");
            }
        });
        // Reset input so same file can be re-selected
        e.target.value = "";
    }

    function renderAttachments() {
        const container = document.getElementById("frappe-ai-attachments");
        container.innerHTML = "";
        attachedFiles.forEach(function (f, i) {
            const chip = document.createElement("span");
            chip.className = "ai-attachment-chip";
            chip.innerHTML = `📎 ${f.name} <button data-idx="${i}">×</button>`;
            chip.querySelector("button").addEventListener("click", function () {
                attachedFiles.splice(i, 1);
                renderAttachments();
            });
            container.appendChild(chip);
        });
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
        return text
            .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
    }

    function sendMessage() {
        const input = document.getElementById("frappe-ai-input");
        let message = input.value.trim();
        if (!message && attachedFiles.length === 0) return;

        // Append file contents to message
        let fullMessage = message;
        if (attachedFiles.length > 0) {
            const fileBlock = attachedFiles.map(function (f) {
                return `\n\n--- File: ${f.name} ---\n${f.content}`;
            }).join("\n");
            fullMessage = (message ? message + "\n" : "") + fileBlock;
        }

        input.value = "";
        input.style.height = "38px";

        // Show in chat: message + attachment chips
        const displayText = message + (attachedFiles.length > 0
            ? "\n" + attachedFiles.map(f => `📎 ${f.name}`).join(", ")
            : "");
        appendMessage("user", displayText);

        history.push({ role: "user", content: fullMessage });
        attachedFiles = [];
        renderAttachments();

        const sendBtn = document.getElementById("frappe-ai-send");
        sendBtn.disabled = true;
        const typingDiv = appendMessage("assistant", "…");
        typingDiv.classList.add("typing");

        frappe.call({
            method: "frappe_ai.api.chat.send_message",
            args: { message: fullMessage, history: history.slice(-10) },
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

    document.addEventListener("input", function (e) {
        if (e.target.id === "frappe-ai-input") {
            e.target.style.height = "38px";
            e.target.style.height = Math.min(e.target.scrollHeight, 100) + "px";
        }
    });

    if (typeof frappe !== "undefined" && frappe.ui) {
        init();
    } else {
        document.addEventListener("DOMContentLoaded", function () {
            setTimeout(init, 1500);
        });
    }
})();
