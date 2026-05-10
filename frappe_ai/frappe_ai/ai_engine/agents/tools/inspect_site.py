import frappe
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "inspect_site",
        "description": "Inspect the current Frappe site configuration: domains, languages, currencies, payment gateways, email settings, scheduler status, and site-specific configurations. Use this to understand the full site environment before making recommendations.",
        "parameters": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific sections to inspect. Options: 'general', 'domains', 'languages', 'currencies', 'payment', 'email', 'scheduler', 'limits', 'all'. Default: ['all']",
                },
                "include_settings": {
                    "type": "boolean",
                    "description": "Include all site-wide settings (default: true)",
                    "default": True,
                },
            },
            "required": [],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Inspect the Frappe site configuration."""
    sections = args.get("sections", ["all"])
    if "all" in sections:
        sections = [
            "general", "domains", "languages",
            "currencies", "payment", "email",
            "scheduler", "limits",
        ]

    result = {}

    if "general" in sections:
        result["general"] = {
            "site_name": frappe.local.site,
            "apps_installed": frappe.get_installed_apps(),
            "developer_mode": frappe.boot.get("developer_mode", 0),
            "server_timezone": frappe.defaults.get_defaults().get("time_zone"),
            "country": frappe.defaults.get_defaults().get("country"),
        }

    if "domains" in sections:
        result["domains"] = frappe.get_all(
            "Has Domain",
            filters={"parenttype": "Site"},
            fields=["domain"],
        )

    if "languages" in sections:
        result["languages"] = frappe.db.get_list(
            "Language",
            fields=["name", "language_name", "is_enabled"],
        )

    if "currencies" in sections:
        enabled = frappe.db.get_value("Accounts Settings", None, "enabled_currencies")
        result["currencies"] = {
            "enabled": enabled.split("\n") if enabled else [],
            "default": frappe.defaults.get_defaults().get("currency"),
        }

    if "payment" in sections:
        try:
            gateways = frappe.get_all(
                "Payment Gateway",
                fields=["gateway", "gateway_settings"],
            )
            result["payment_gateways"] = gateways
        except Exception:
            result["payment_gateways"] = {"error": "Payment Gateway not available"}

    if "email" in sections:
        result["email"] = {
            "email_domains": frappe.get_all("Email Domain", fields=["domain_name"]),
        }

    if "scheduler" in sections:
        try:
            result["scheduler"] = {
                "enabled": bool(frappe.utils.background_jobs.get_workers()),
            }
        except Exception:
            result["scheduler"] = {"error": "Could not inspect scheduler"}

    if "limits" in sections:
        try:
            pending = frappe.db.count("Email Queue")
            result["limits"] = {
                "pending_emails": pending,
                "space_usage": get_space_usage(),
            }
        except Exception:
            result["limits"] = {"pending_emails": 0}

    if args.get("include_settings"):
        result["site_settings"] = {}
        for setting_doctype in [
            "System Settings", "Accounts Settings",
            "Stock Settings", "Selling Settings",
            "Buying Settings", "Website Settings",
        ]:
            try:
                doc = frappe.get_single(setting_doctype)
                result["site_settings"][setting_doctype] = {
                    field.fieldname: doc.get(field.fieldname)
                    for field in doc.meta.fields
                    if field.fieldtype not in ("Section Break", "Column Break", "Tab Break")
                }
            except Exception:
                pass

    return result


def get_space_usage() -> dict:
    """Get approximate database storage usage."""
    try:
        db_size = frappe.db.sql("""
            SELECT
                ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as size_mb
            FROM information_schema.tables
            WHERE table_schema = %s
            GROUP BY table_schema
        """, frappe.conf.db_name)
        return {
            "database_mb": db_size[0][1] if db_size else 0,
        }
    except Exception:
        return {"database_mb": 0}


register_tool("inspect_site", SCHEMA, execute)