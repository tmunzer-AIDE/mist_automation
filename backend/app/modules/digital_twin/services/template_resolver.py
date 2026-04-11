"""
Resolve Mist template inheritance for Digital Twin validation.

Extracts template assignments and site vars from backup data to support
L1-06 (template override crush) and L1-07 (unresolved template variables).
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Site info fields that reference org-level templates
TEMPLATE_ASSIGNMENT_FIELDS = [
    "sitetemplate_id",
    "rftemplate_id",
    "networktemplate_id",
    "gatewaytemplate_id",
    "aptemplate_id",
]

# Mapping from site info field to backup object_type
TEMPLATE_FIELD_TO_TYPE = {
    "sitetemplate_id": "sitetemplates",
    "rftemplate_id": "rftemplates",
    "networktemplate_id": "networktemplates",
    "gatewaytemplate_id": "gatewaytemplates",
    "aptemplate_id": "aptemplates",
}


async def get_site_template_context(
    org_id: str,
    site_id: str,
    virtual_state: dict[tuple, dict[str, Any]],
) -> dict[str, Any]:
    """Get template context for a site: assigned templates + site vars.

    Returns:
        {
            "site_name": str,
            "site_vars": dict,  # from site_setting.vars
            "assigned_templates": [
                {"template_type": str, "template_id": str, "template_name": str, "config": dict},
                ...
            ]
        }
    """
    from app.modules.backup.models import BackupObject

    # Get site info (may be in virtual state if being modified)
    site_info = virtual_state.get(("info", site_id, None), {})
    if not site_info:
        backup = (
            await BackupObject.find({"object_type": "info", "site_id": site_id, "is_deleted": False})
            .sort([("version", -1)])
            .first_or_none()
        )
        site_info = backup.configuration if backup else {}

    site_name = site_info.get("name", site_id)

    # Get site setting for vars
    site_setting = virtual_state.get(("settings", site_id, None), {})
    if not site_setting:
        backup = (
            await BackupObject.find(
                {"object_type": "settings", "site_id": site_id, "org_id": org_id, "is_deleted": False}
            )
            .sort([("version", -1)])
            .first_or_none()
        )
        site_setting = backup.configuration if backup else {}

    site_vars = site_setting.get("vars") or {}

    # Resolve assigned templates
    assigned_templates = []
    for field, tmpl_type in TEMPLATE_FIELD_TO_TYPE.items():
        tmpl_id = site_info.get(field)
        if not tmpl_id:
            continue

        # Check virtual state first (template might be being modified)
        tmpl_config = virtual_state.get((tmpl_type, None, tmpl_id), {})
        if not tmpl_config:
            backup = (
                await BackupObject.find({"object_type": tmpl_type, "object_id": tmpl_id, "is_deleted": False})
                .sort([("version", -1)])
                .first_or_none()
            )
            tmpl_config = backup.configuration if backup else {}

        if tmpl_config:
            assigned_templates.append(
                {
                    "template_type": tmpl_type,
                    "template_id": tmpl_id,
                    "template_name": tmpl_config.get("name", tmpl_id),
                    "config": tmpl_config,
                }
            )

    return {
        "site_name": site_name,
        "site_vars": site_vars,
        "assigned_templates": assigned_templates,
    }
