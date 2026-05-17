app_name = "frappe_ai"
app_title = "Frappe AI"
app_publisher = "Michele Milazzo"
app_description = "AI chat assistant for Frappe — powered by OpenCode.ai (OpenRouter fallback)"
app_icon = "octicon octicon-robot"
app_color = "#3498db"
app_email = "mic.milazzo@gmail.com"
app_license = "MIT"

required_apps = []

app_include_js = ["frappe_ai.bundle.js"]

after_install = "frappe_ai.install.after_install"
