"""
Mist API endpoint catalog for workflow action autocomplete.

Static catalog of common Mist API endpoints with metadata
for autocomplete and documentation in the workflow editor.
"""

from pydantic import BaseModel


class QueryParam(BaseModel):
    """A query parameter for an API endpoint."""
    name: str
    description: str = ""
    required: bool = False
    type: str = "string"


class ApiCatalogEntry(BaseModel):
    """A single API endpoint entry in the catalog."""
    id: str
    label: str
    method: str
    endpoint: str
    path_params: list[str]
    query_params: list[QueryParam] = []
    category: str
    description: str
    has_body: bool


API_CATALOG: list[ApiCatalogEntry] = [
    # ── Sites ──────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_sites",
        label="List Sites",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/sites",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results (default 100)"),
            QueryParam(name="page", description="Page number (default 1)"),
        ],
        category="Sites",
        description="List all sites in the organization",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="get_site",
        label="Get Site",
        method="GET",
        endpoint="/api/v1/sites/{site_id}",
        path_params=["site_id"],
        category="Sites",
        description="Get details for a specific site",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="create_site",
        label="Create Site",
        method="POST",
        endpoint="/api/v1/orgs/{org_id}/sites",
        path_params=["org_id"],
        category="Sites",
        description="Create a new site in the organization",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="update_site",
        label="Update Site",
        method="PUT",
        endpoint="/api/v1/sites/{site_id}",
        path_params=["site_id"],
        category="Sites",
        description="Update site configuration",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="delete_site",
        label="Delete Site",
        method="DELETE",
        endpoint="/api/v1/sites/{site_id}",
        path_params=["site_id"],
        category="Sites",
        description="Delete a site",
        has_body=False,
    ),

    # ── Devices ────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_devices",
        label="List Org Devices",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/devices",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="type", description="Device type filter (ap, switch, gateway)"),
            QueryParam(name="name", description="Device name filter"),
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Devices",
        description="List all devices in the organization",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="list_site_devices",
        label="List Site Devices",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/devices",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="type", description="Device type filter (ap, switch, gateway)"),
            QueryParam(name="name", description="Device name filter"),
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Devices",
        description="List all devices at a site",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="get_device",
        label="Get Device",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/devices/{device_id}",
        path_params=["site_id", "device_id"],
        category="Devices",
        description="Get device details",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="update_device",
        label="Update Device",
        method="PUT",
        endpoint="/api/v1/sites/{site_id}/devices/{device_id}",
        path_params=["site_id", "device_id"],
        category="Devices",
        description="Update device configuration",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="restart_device",
        label="Restart Device",
        method="POST",
        endpoint="/api/v1/sites/{site_id}/devices/{device_id}/restart",
        path_params=["site_id", "device_id"],
        category="Devices",
        description="Restart a device",
        has_body=False,
    ),

    # ── Device Stats ───────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_site_device_stats",
        label="List Site Device Stats",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/stats/devices",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="type", description="Device type filter (ap, switch, gateway)"),
            QueryParam(name="status", description="Device status filter (connected, disconnected)"),
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Stats",
        description="Get device statistics for a site",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="get_device_stats",
        label="Get Device Stats",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/stats/devices/{device_id}",
        path_params=["site_id", "device_id"],
        category="Stats",
        description="Get statistics for a specific device",
        has_body=False,
    ),

    # ── WLANs ──────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_site_wlans",
        label="List Site WLANs",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/wlans",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="WLANs",
        description="List all WLANs at a site",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="get_wlan",
        label="Get WLAN",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/wlans/{wlan_id}",
        path_params=["site_id", "wlan_id"],
        category="WLANs",
        description="Get WLAN details",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="create_wlan",
        label="Create WLAN",
        method="POST",
        endpoint="/api/v1/sites/{site_id}/wlans",
        path_params=["site_id"],
        category="WLANs",
        description="Create a new WLAN at a site",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="update_wlan",
        label="Update WLAN",
        method="PUT",
        endpoint="/api/v1/sites/{site_id}/wlans/{wlan_id}",
        path_params=["site_id", "wlan_id"],
        category="WLANs",
        description="Update WLAN configuration",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="delete_wlan",
        label="Delete WLAN",
        method="DELETE",
        endpoint="/api/v1/sites/{site_id}/wlans/{wlan_id}",
        path_params=["site_id", "wlan_id"],
        category="WLANs",
        description="Delete a WLAN",
        has_body=False,
    ),

    # ── Templates ──────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_templates",
        label="List Templates",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/templates",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Templates",
        description="List all configuration templates",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="get_template",
        label="Get Template",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/templates/{template_id}",
        path_params=["org_id", "template_id"],
        category="Templates",
        description="Get template details",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="create_template",
        label="Create Template",
        method="POST",
        endpoint="/api/v1/orgs/{org_id}/templates",
        path_params=["org_id"],
        category="Templates",
        description="Create a new configuration template",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="update_template",
        label="Update Template",
        method="PUT",
        endpoint="/api/v1/orgs/{org_id}/templates/{template_id}",
        path_params=["org_id", "template_id"],
        category="Templates",
        description="Update a configuration template",
        has_body=True,
    ),
    ApiCatalogEntry(
        id="delete_template",
        label="Delete Template",
        method="DELETE",
        endpoint="/api/v1/orgs/{org_id}/templates/{template_id}",
        path_params=["org_id", "template_id"],
        category="Templates",
        description="Delete a template",
        has_body=False,
    ),

    # ── Clients ────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_site_clients",
        label="List Wireless Clients",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/stats/clients",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Clients",
        description="List wireless clients at a site",
        has_body=False,
    ),

    # ── Alarms ─────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_site_alarms",
        label="List Site Alarms",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/alarms",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="severity", description="Filter by severity"),
            QueryParam(name="start", description="Start time (epoch seconds)", type="integer"),
            QueryParam(name="end", description="End time (epoch seconds)", type="integer"),
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Alarms",
        description="List alarms at a site",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="ack_site_alarm",
        label="Acknowledge Alarm",
        method="POST",
        endpoint="/api/v1/sites/{site_id}/alarms/{alarm_id}/ack",
        path_params=["site_id", "alarm_id"],
        category="Alarms",
        description="Acknowledge a site alarm",
        has_body=False,
    ),

    # ── RFTemplates ────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_rftemplates",
        label="List RF Templates",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/rftemplates",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="RF Templates",
        description="List all RF templates in the organization",
        has_body=False,
    ),

    # ── Networks / VLANs ──────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_networks",
        label="List Org Networks",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/networks",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Networks",
        description="List all networks in the organization",
        has_body=False,
    ),
    ApiCatalogEntry(
        id="list_site_networks",
        label="List Site Networks",
        method="GET",
        endpoint="/api/v1/sites/{site_id}/networks",
        path_params=["site_id"],
        query_params=[
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Networks",
        description="List networks at a site",
        has_body=False,
    ),

    # ── Inventory ──────────────────────────────────────────────────
    ApiCatalogEntry(
        id="list_org_inventory",
        label="List Org Inventory",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}/inventory",
        path_params=["org_id"],
        query_params=[
            QueryParam(name="type", description="Device type filter (ap, switch, gateway)"),
            QueryParam(name="model", description="Device model filter"),
            QueryParam(name="serial", description="Serial number filter"),
            QueryParam(name="limit", description="Max number of results"),
            QueryParam(name="page", description="Page number"),
        ],
        category="Inventory",
        description="List inventory devices in the organization",
        has_body=False,
    ),

    # ── Org ────────────────────────────────────────────────────────
    ApiCatalogEntry(
        id="get_org",
        label="Get Org",
        method="GET",
        endpoint="/api/v1/orgs/{org_id}",
        path_params=["org_id"],
        category="Organization",
        description="Get organization details",
        has_body=False,
    ),
]
