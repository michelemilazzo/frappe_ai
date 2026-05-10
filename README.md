# Frappe AI — AI DevOps Assistant per Frappe/ERPNext

![Version](https://img.shields.io/badge/version-1.1.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Frappe](https://img.shields.io/badge/Frappe-v16-red)

Assistente AI potenziato per **Frappe v16 / ERPNext** con supporto multi-provider (OpenCode.ai, Gemini, Groq, Grok, Nvidia) e **18 tool integrati** per gestire app, DocType, bug, e automazione — tutto con permessi utente rispettati.

---

## 🚀 Installazione Rapida

```bash
# 1. Clona l'app
cd /home/frappe/frappe-bench/apps
bench get-app https://github.com/michelemilazzo/frappe_ai.git --branch develop

# 2. Installa sul sito
bench --site press.onekeyco.com install-app frappe_ai

# 3. Riavvia
sudo bench restart
```

## 🎯 Provider AI Supportati

| Provider | Modelli gratuiti | Attivazione |
|---|---|---|
| **OpenCode** ⭐ (default) | glm-4.7-free, kimi-k2, qwen3-coder, grok-code-fast-1, minimax-m2.1-free | [opencode.ai](https://opencode.ai) |
| **Gemini** | gemini-3-flash, gemini-3-flash-8b | [aistudio.google.com](https://aistudio.google.com) |
| **Groq** | llama-3.1-70b, mixtral-8x7b | [console.groq.com](https://console.groq.com) |
| **Grok** | grok-code-fast-1 | [x.ai](https://x.ai) |
| **Nvidia** | mistral, llama | [build.nvidia.com](https://build.nvidia.com) |

## 🤖 18 Tool Integrati

### 📊 Dati & Ricerca (5 tool)
| Tool | Descrizione |
|---|---|
| `search_documents` | Cerca record in qualsiasi DocType con filtri |
| `get_document` | Carica un documento specifico per nome |
| `count_documents` | Conta record con filtri |
| `get_doctype_meta` | Schema completo campi di un DocType |
| `list_doctypes` | Elenca tutti i DocType disponibili |

### ✍️ Scrittura Dati (3 tool)
| Tool | Descrizione |
|---|---|
| `create_document` | Crea nuovo documento (con permessi) |
| `update_document` | Aggiorna campi di un documento esistente |
| `delete_document` | Elimina documento (solo bozze, con conferma) |

### 🖥️ Navigazione UI (2 tool)
| Tool | Descrizione |
|---|---|
| `navigate_ui` | Apri liste, form, report, workspace, pagine |
| `interact_ui` | Click, type, save, submit, filter sul form attivo |

### 🔍 AI DevOps (6 tool)
| Tool | Descrizione |
|---|---|
| `discover_apps` | Scopri tutte le app installate con DocType e moduli |
| `inspect_site` | Configurazione completa del sito (domini, valute, scheduler) |
| `learn_app` | Impara come funziona un'app/DocType in profondità |
| `analyze_code` | Analisi sicurezza, performance, bug, best practices |
| `monitor_bugs` | Monitora errori, analizza pattern, suggerisci fix |
| `suggest_improvements` | Suggerimenti per performance, sicurezza, UX, automazione |
| `manage_app` | Controlla stato app installate |
| `generate_app` | Genera scaffolding per nuove app Frappe |

## 📋 Uso dalla Chat

```
"Mostra le app installate"
→ discover_apps

"Come funziona il DocType Sales Invoice?"
→ learn_app(doctype="Sales Invoice")

"Controlla se ci sono errori nelle ultime 24h"
→ monitor_bugs(action="get_errors")

"Analizza il codice del DocType Customer"
→ analyze_code(doctype="Customer")

"Creare un nuovo documento Cliente"
→ create_document(doctype="Customer", values={...})

"Cerca le fatture aperte di questo mese"
→ search_documents(doctype="Sales Invoice", filters={"status":"Unpaid"})

"Come posso migliorare le performance del sito?"
→ suggest_improvements(category="performance")

"Genera un'app per gestione progetti"
→ generate_app(app_name="project_manager", doctypes=[...])

"Vai alla lista dei Clienti"
→ navigate_ui(action="list", doctype="Customer")
```

## ⚙️ Configurazione

1. Vai su **Desk → AI Assistant Settings**
2. Seleziona **Provider**: OpenCode (o altro)
3. Inserisci la **API Key** da [opencode.ai](https://opencode.ai)
4. Scegli il **Modello** (default: `glm-4.7-free` — gratuito)
5. Clicca **"Test Connection"** per verificare

## 🔒 Sicurezza

- **Permessi utente**: ogni tool opera nel contesto dell'utente loggato
- **Permission query**: conversationi accessibili solo dal proprietario
- **Rate limiting**: configurabile per utente (default: 60/h)
- **Budget mensile**: controllo spesa configurabile
- **Audit log**: ogni chiamata e uso è tracciato
- **No SQL raw**: accesso ai dati solo tramite Frappe ORM

## 📁 Struttura del Progetto

```
frappe_ai/
├── frappe_ai/
│   ├── __init__.py
│   ├── hooks.py
│   ├── setup.py
│   ├── config/
│   │   └── desktop.py
│   ├── api/
│   │   ├── chat.py          # API chat + streaming SSE
│   │   ├── conversation.py  # Gestione conversazioni
│   │   └── settings.py      # Configurazione pubblica + test
│   ├── ai_engine/
│   │   ├── base_provider.py  # Classe base per provider AI
│   │   ├── router.py         # Routing verso il provider giusto
│   │   ├── context_manager.py # Costruzione contesto conversazione
│   │   ├── rate_limiter.py   # Rate limiting per utente
│   │   ├── system_prompt.md  # System prompt intelligente
│   │   ├── agents/
│   │   │   ├── agent_runner.py  # Esecuzione agenti multi-step
│   │   │   ├── tool_registry.py # Registry dei tool
│   │   │   └── tools/           # 18 tool implementati
│   │   └── providers/
│   │       ├── opencode_provider.py  # ⭐ Nuovo: OpenCode.ai
│   │       ├── gemini_provider.py    # Google Gemini
│   │       ├── groq_provider.py      # Groq
│   │       ├── grok_provider.py      # xAI Grok
│   │       └── nvidia_provider.py    # Nvidia
│   ├── doctype/
│   │   ├── ai_assistant_settings/   # Configurazione AI
│   │   ├── ai_conversation/         # Conversazioni
│   │   ├── ai_message/              # Messaggi
│   │   ├── ai_rate_limit/           # Rate limiting
│   │   ├── ai_usage_log/            # Log uso token
│   │   └── ai_tool_call_log/        # Log chiamate tool
│   ├── public/
│   │   └── js/
│   │       └── frappe_ai_chat.js    # UI chat nativa Frappe
│   └── page/
│       └── ai/                       # Pagina chat AI
├── patches/                          # Migrazioni database
├── templates/                        # Template HTML
├── requirements.txt                  # Dipendenze Python
└── README.md                         # Questo file
```

## 🌐 OpenCode.ai Integration (Default)

OpenCode Zen supporta 75+ provider e 200+ modelli tramite un'unica API. Il routing automatico seleziona l'endpoint corretto in base al nome del modello:

| Prefisso Modello | API Type | Endpoint |
|---|---|---|
| `gpt-*`, `o1-*`, `o3-*` | Responses API | `/zen/v1/responses` |
| `claude-*` | Messages API | `/zen/v1/messages` |
| `gemini-*` | Google GenAI | `/zen/v1/models/{model}` |
| `glm-*`, `kimi-*`, `grok-*`, `qwen-*` | Chat Completions | `/zen/v1/chat/completions` |

### Modelli gratuiti consigliati

```text
1. glm-4.7-free       → Veloce, ottimo per uso quotidiano
2. kimi-k2            → Buon bilanciamento qualità/velocità
3. qwen3-coder         → Eccellente per codice e analisi tecnica
4. minimax-m2.1-free   → Economico e capace
5. grok-code-fast-1    → Buon rapporto qualità/costo
```

## 🔄 Distribuzione Multi-Sito

```bash
# Installa su tutti i siti del bench
for site in $(bench --site list); do
    bench --site "$site" install-app frappe_ai 2>/dev/null
done
sudo bench restart
```

## 🛠️ Configurazione OpenCode CLI

Crea `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "provider": {
    "anthropic": {
      "models": {},
      "options": {
        "apiKey": "{env:ANTHROPIC_API_KEY}"
      }
    },
    "openrouter": {
      "models": {},
      "options": {
        "apiKey": "{env:OPENROUTER_API_KEY}"
      }
    }
  },
  "instructions": ["./custom-instructions.md"]
}
```

## 📜 Licenza

MIT — vedi [license.txt](license.txt)

## 🙏 Crediti

Basato su [karanmistry007/frappe_ai](https://github.com/karanmistry007/frappe_ai) con l'aggiunta del provider OpenCode.ai e tool AI DevOps.