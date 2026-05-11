// Copyright (c) 2026, Karan Mistry and contributors
// For license information, please see license.txt

const OPENCODE_DEFAULT_MODEL = "glm-5";
let OPENCODE_MODEL_CACHE = [];
let OPENCODE_MODEL_CACHE_TS = 0;
const OPENCODE_MODEL_CACHE_TTL_MS = 30 * 1000;

function update_model_hint(frm, model, models, isSupported, hasModelInfo) {
	const availableModels = (models || []).slice(0, 6).join(", ");
	if (!hasModelInfo) {
		frm.set_df_property(
			"model",
			"description",
			"Inserisci il modello OpenCode es. glm-5, qwen3.6-plus, kimi-k2.6"
		);
		return;
	}

	if (!model) {
		frm.set_df_property(
			"model",
			"description",
			"Inserisci un modello OpenCode supportato dall'API key corrente."
		);
		return;
	}

	if (isSupported) {
		frm.set_df_property(
			"model",
			"description",
			"Modello supportato."
		);
		return;
	}

	frm.set_df_property(
		"model",
		"description",
			`Il modello corrente non risulta supportato dalla tua chiave OpenCode. Prova: ${availableModels}`
	);
}

function refresh_supported_models_hint(frm) {
	if (frm.doc.provider !== "OpenCode" || !frm.doc.model) {
		frm.set_df_property("model", "description", "");
		return;
	}

	const now = Date.now();
	if (OPENCODE_MODEL_CACHE && OPENCODE_MODEL_CACHE.length && now - OPENCODE_MODEL_CACHE_TS < OPENCODE_MODEL_CACHE_TTL_MS) {
		const normalized = (OPENCODE_MODEL_CACHE || []).map((m) => (m || "").toLowerCase());
		update_model_hint(
			frm,
			frm.doc.model,
			OPENCODE_MODEL_CACHE,
			normalized.includes((frm.doc.model || "").toLowerCase()),
			true
		);
		return;
	}

	frappe.call({
		method: "frappe_ai.frappe_ai.api.settings.get_supported_models",
		callback: function (r) {
			if (!r.message) {
				update_model_hint(frm, frm.doc.model, [], false, false);
				return;
			}
			if (r.message.status === "ok" && r.message.provider === "OpenCode") {
				OPENCODE_MODEL_CACHE = r.message.models || [];
				OPENCODE_MODEL_CACHE_TS = now;
				const normalized = (OPENCODE_MODEL_CACHE || []).map((m) => (m || "").toLowerCase());
				update_model_hint(
					frm,
					frm.doc.model,
					r.message.models || [],
					normalized.includes((frm.doc.model || "").toLowerCase()),
					true
				);
			} else {
				update_model_hint(frm, frm.doc.model, [], false, false);
			}
			},
		error: function () {
			update_model_hint(frm, frm.doc.model, [], false, false);
		},
	});
}

function show_opencode_model_selector(frm) {
	if (frm.doc.provider !== "OpenCode") {
		return;
	}

	const now = Date.now();
	if (OPENCODE_MODEL_CACHE && OPENCODE_MODEL_CACHE.length && now - OPENCODE_MODEL_CACHE_TS < OPENCODE_MODEL_CACHE_TTL_MS) {
		open_model_selector_dialog(frm, OPENCODE_MODEL_CACHE);
		return;
	}

	frappe.call({
		method: "frappe_ai.frappe_ai.api.settings.get_supported_models",
		callback: function (r) {
			if (!r.message || r.message.status !== "ok" || r.message.provider !== "OpenCode") {
				frappe.show_alert({ message: __("Impossibile recuperare i modelli supportati."), indicator: "orange" });
				return;
			}

			OPENCODE_MODEL_CACHE = r.message.models || [];
			OPENCODE_MODEL_CACHE_TS = now;
			open_model_selector_dialog(frm, OPENCODE_MODEL_CACHE);
		},
		error: function () {
			frappe.show_alert({ message: __("Impossibile recuperare i modelli supportati."), indicator: "red" });
		},
	});
}

function open_model_selector_dialog(frm, models) {
	const available = (models || []).slice().sort().map((m) => String(m));
	if (!available.length) {
		frappe.show_alert({ message: __("Nessun modello disponibile."), indicator: "orange" });
		return;
	}

	const current = String(frm.doc.model || "");
	const defaultModel = available.includes(current) ? current : available[0];

	const dialog = new frappe.ui.Dialog({
		title: __("Seleziona modello OpenCode"),
		fields: [
			{
				fieldname: "model",
				fieldtype: "Select",
				label: __("Modello supportato"),
				options: available.join("\n"),
				reqd: 1,
				default: defaultModel,
			},
		],
		primary_action_label: __("Conferma"),
		primary_action: function (values) {
			frm.set_value("model", values.model);
			update_model_hint(frm, values.model, available, true, true);
			dialog.hide();
		},
	});

	dialog.show();
}

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
			frm.remove_custom_button(__("Scegli modello OpenCode"), __("OpenCode"));
			frm.set_df_property("model", "read_only", 0);
			update_model_hint(frm, frm.doc.model, [], false, false);
			frm.toggle_display("file_upload_enabled", false);
			frm.add_custom_button(
				__("Scegli modello OpenCode"),
				() => show_opencode_model_selector(frm),
				__("OpenCode"),
			);
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
			refresh_supported_models_hint(frm);
		}
	},

	provider(frm) {
		// Reset model when provider changes
		if (frm.doc.provider === "OpenCode") {
			frm.set_value("model", OPENCODE_DEFAULT_MODEL);
		} else if (frm.doc.provider === "Gemini") {
			frm.set_value("model", "gemini-2.0-flash");
		} else {
			frm.set_df_property("model", "description", "");
		}
		refresh_supported_models_hint(frm);
		frm.refresh();
	},

	model(frm) {
		if (frm.doc.provider === "OpenCode") {
			refresh_supported_models_hint(frm);
		}
	},
});
