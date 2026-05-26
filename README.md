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

## Global Routing And Fallback

Default behavior is global and works across installations:

- Primary provider: `Claude Code (local)` (no external API key)
- Simple tasks: route to free model provider (`OpenRouter` free model)
- Fallback: local `Ollama` model (`qwen2.5:7b`) if primary/free route fails

Optional site/bench keys in `site_config.json` or `common_site_config.json`:

- `frappe_ai_provider`
- `frappe_ai_model`
- `frappe_ai_simple_task_provider`
- `frappe_ai_simple_task_model`
- `frappe_ai_fallback_provider`
- `frappe_ai_fallback_model`

## Website Guest Access

Public website chat calls are whitelisted for guests:

- `frappe_ai.api.chat.send_message`
- `frappe_ai.api.chat.get_memory`
- `frappe_ai.api.chat.save_memory`

Guest memory is isolated by session id (not shared globally across visitors).

## API Usage

```python
import frappe
result = frappe.call("frappe_ai.api.chat.send_message", message="Hello!")
print(result["reply"])
```

## License

MIT
