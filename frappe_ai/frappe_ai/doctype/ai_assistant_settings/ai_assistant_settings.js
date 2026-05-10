// Copyright (c) 2026, Karan Mistry and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Assistant Settings", {
	refresh(frm) {
		// Mostra/nascondi campi in base al provider selezionato
		const provider = frm.doc.provider;
		const isOpenCode = provider === "OpenCode";

		// API key è sempre richiesta per OpenCode
		frm.toggle_display("api_key", true);

		// Base URL custom (utile per proxy/self-hosted)
		frm.toggle_display("api_base_url", isOpenCode);

		// Modello: permetti qualsiasi valore per OpenCode (user typed)
		if (isOpenCode) {
			frm.set_df_property("model", "read_only", 0);
			frm.set_df_property("model", "description",
				"Inserisci il modello OpenCode es. glm-4.7-free, gpt-5.2, claude-sonnet-4-5, gemini-3-flash, kimi-k2");
			frm.toggle_display("file_upload_enabled", false);
		} else {
			frm.set_df_property("model", "description", "");
			frm.toggle_display("file_upload_enabled", true);
		}

		// Test connection button
		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "frappe_ai.frappe_ai.api.settings.test_connection",
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({
							message: __("Connessione riuscita! Provider: {0}, Modello: {1}",
								[r.message.provider, r.message.model]),
							indicator: "green",
						});
					} else {
						frappe.throw(r.message?.message || "Errore di connessione");
					}
				},
			});
		});

		// Suggest quick models for OpenCode
		if (isOpenCode) {
			frm.set_query("model", () => ({
				filters: { custom: 1 }, // user-entered
			}));
		}
	},

	provider(frm) {
		// Reset model when provider changes
		if (frm.doc.provider === "OpenCode") {
			frm.set_value("model", "glm-4.7-free");
		} else if (frm.doc.provider === "Gemini") {
			frm.set_value("model", "gemini-2.0-flash");
		}
		frm.refresh();
	},
});