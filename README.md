# Frappe AI

AI chat assistant for Frappe v15+ — powered by OpenCode.ai / OpenRouter.

## Installation

```bash
bench get-app https://github.com/michelemilazzo/frappe_ai
bench install-app frappe_ai
```

## Requirements

- Frappe >= 15.0.0

## Configuration

After installation go to **AI Settings** and configure:

- **Provider**: OpenRouter (recommended) or OpenCode.ai
- **API Key**: Your API key from the provider
- **Model**: e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-haiku`
- **System Prompt**: Context for the assistant

## API Usage

```python
import frappe
result = frappe.call("frappe_ai.api.chat.send_message", message="Hello!")
print(result["reply"])
```

## License

MIT
