# Frappe AI

AI operations assistant for Frappe v15+ with chat + agent execution.

## Installation

```bash
bench get-app https://github.com/michelemilazzo/frappe_ai
bench install-app frappe_ai
```

## Requirements

- Frappe >= 15.0.0

## Configuration

Default mode is API-key free via local provider:

- **Provider**: `Ollama` (default) or `Claude Code (local)`
- **Model**: default `qwen2.5:7b`
- **Ollama URL**: default `http://10.10.0.4:11434`

Optional overrides (bench-wide) in `common_site_config.json`:

- `frappe_ai_provider`
- `frappe_ai_model`
- `frappe_ai_ollama_url`
- `frappe_ai_system_prompt`

## Agent Mode

Agent mode can execute real actions from the chat UI for allowed users:

- File actions: `write_file`, `read_file`, `list_files`
- Runtime actions: `run_python`, `run_shell`, `bench_cmd`
- Business actions: `create_customer`, `create_web_page`, `create_webshop_item`, `translate_doc_fields`, `generate_contract`

## API Usage

```python
import frappe
result = frappe.call("frappe_ai.api.chat.send_message", message="Hello!")
print(result["reply"])
```

## License

MIT
