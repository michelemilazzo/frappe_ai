app_name = "frappe_ai"
app_title = "Frappe AI"
app_publisher = "Michele Milazzo"
app_description = "AI chat assistant for Frappe — powered by Claude, OpenRouter, OpenCode.ai"
app_icon = "octicon octicon-robot"
app_color = "#4f46e5"
app_email = "mic.milazzo@gmail.com"
app_license = "MIT"

required_apps = []

app_include_js = ["/assets/frappe_ai/js/frappe_ai.js"]
app_include_css = ["/assets/frappe_ai/css/frappe_ai.css"]

after_install = "frappe_ai.install.after_install"
