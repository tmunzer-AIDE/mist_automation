"""
Central registry of all Mist configuration object types for backup.

Adding a new object type = adding one entry to ORG_OBJECTS or SITE_OBJECTS.
Both the backup service and admin API consume this registry.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from mistapi.api.v1.orgs import (
    alarmtemplates,
    aptemplates,
    assetfilters,
    assets,
    avprofiles,
    deviceprofiles,
    gatewaytemplates,
    idpprofiles,
    mxclusters,
    mxedges,
    mxtunnels,
    nacportals,
    nacrules,
    nactags,
    networks,
    networktemplates,
    orgs,
    pskportals,
    psks,
    rftemplates,
    secintelprofiles,
    secpolicies,
    servicepolicies,
    services,
    setting as org_setting,
    sitegroups,
    sites,
    sitetemplates,
    ssoroles,
    ssos,
    templates,
    usermacs,
    vars as org_vars,
    vpns,
    webhooks,
    wlans as org_wlans,
    wxrules as org_wxrules,
)
from mistapi.api.v1.sites import (
    assets as site_assets,
    beacons,
    devices,
    maps,
    networks as site_networks,
    psks as site_psks,
    rssizones,
    setting as site_setting,
    sites as site_sites,
    vbeacons,
    webhooks as site_webhooks,
    wlans as site_wlans,
    wxrules as site_wxrules,
    wxtags,
    zones,
)


@dataclass
class ObjectDef:
    """Definition of a Mist object type for backup."""

    mistapi_function: Callable
    label: str
    is_list: bool = True
    request_type: str | None = None
    name_fields: list[str] = field(default_factory=lambda: ["name"])
    get_function: Callable | None = None


# ── Org-level object types ──────────────────────────────────────────────────

ORG_OBJECTS: dict[str, ObjectDef] = {
    "data": ObjectDef(
        mistapi_function=orgs.getOrg,
        label="Organization",
        is_list=False,
    ),
    "settings": ObjectDef(
        mistapi_function=org_setting.getOrgSettings,
        label="Org Settings",
        is_list=False,
    ),
    "sites": ObjectDef(
        mistapi_function=sites.listOrgSites,
        label="Sites",
    ),
    "sitegroups": ObjectDef(
        mistapi_function=sitegroups.listOrgSiteGroups,
        label="Site Groups",
    ),
    "sitetemplates": ObjectDef(
        mistapi_function=sitetemplates.listOrgSiteTemplates,
        label="Site Templates",
    ),
    "templates": ObjectDef(
        mistapi_function=templates.listOrgTemplates,
        label="Config Templates",
    ),
    "wlans": ObjectDef(
        mistapi_function=org_wlans.listOrgWlans,
        label="Org WLANs",
        name_fields=["ssid", "name"],
    ),
    "networks": ObjectDef(
        mistapi_function=networks.listOrgNetworks,
        label="Networks",
    ),
    "networktemplates": ObjectDef(
        mistapi_function=networktemplates.listOrgNetworkTemplates,
        label="Network Templates",
    ),
    "rftemplates": ObjectDef(
        mistapi_function=rftemplates.listOrgRfTemplates,
        label="RF Templates",
    ),
    "deviceprofiles": ObjectDef(
        mistapi_function=deviceprofiles.listOrgDeviceProfiles,
        label="Device Profiles (AP)",
        request_type="ap",
    ),
    "switchprofiles": ObjectDef(
        mistapi_function=deviceprofiles.listOrgDeviceProfiles,
        label="Device Profiles (Switch)",
        request_type="switch",
    ),
    "hubprofiles": ObjectDef(
        mistapi_function=deviceprofiles.listOrgDeviceProfiles,
        label="Device Profiles (Gateway)",
        request_type="gateway",
    ),
    "aptemplates": ObjectDef(
        mistapi_function=aptemplates.listOrgAptemplates,
        label="AP Templates",
    ),
    "gatewaytemplates": ObjectDef(
        mistapi_function=gatewaytemplates.listOrgGatewayTemplates,
        label="Gateway Templates",
    ),
    "vpns": ObjectDef(
        mistapi_function=vpns.listOrgVpns,
        label="VPNs",
    ),
    "psks": ObjectDef(
        mistapi_function=psks.listOrgPsks,
        label="PSKs",
    ),
    "pskportals": ObjectDef(
        mistapi_function=pskportals.listOrgPskPortals,
        label="PSK Portals",
    ),
    "nacrules": ObjectDef(
        mistapi_function=nacrules.listOrgNacRules,
        label="NAC Rules",
    ),
    "nactags": ObjectDef(
        mistapi_function=nactags.listOrgNacTags,
        label="NAC Tags",
    ),
    "nacportals": ObjectDef(
        mistapi_function=nacportals.listOrgNacPortals,
        label="NAC Portals",
    ),
    "services": ObjectDef(
        mistapi_function=services.listOrgServices,
        label="Services",
    ),
    "servicepolicies": ObjectDef(
        mistapi_function=servicepolicies.listOrgServicePolicies,
        label="Service Policies",
    ),
    "secpolicies": ObjectDef(
        mistapi_function=secpolicies.listOrgSecPolicies,
        label="Security Policies",
    ),
    "wxrules": ObjectDef(
        mistapi_function=org_wxrules.listOrgWxRules,
        label="WxLAN Rules",
    ),
    "alarmtemplates": ObjectDef(
        mistapi_function=alarmtemplates.listOrgAlarmTemplates,
        label="Alarm Templates",
    ),
    "webhooks": ObjectDef(
        mistapi_function=webhooks.listOrgWebhooks,
        label="Webhooks",
        name_fields=["name", "url"],
    ),
    "mxtunnels": ObjectDef(
        mistapi_function=mxtunnels.listOrgMxTunnels,
        label="MxTunnels",
    ),
    "mxclusters": ObjectDef(
        mistapi_function=mxclusters.listOrgMxEdgeClusters,
        label="MxEdge Clusters",
    ),
    "mxedges": ObjectDef(
        mistapi_function=mxedges.listOrgMxEdges,
        label="MxEdges",
    ),
    "avprofiles": ObjectDef(
        mistapi_function=avprofiles.listOrgAntivirusProfiles,
        label="Antivirus Profiles",
    ),
    "idpprofiles": ObjectDef(
        mistapi_function=idpprofiles.listOrgIdpProfiles,
        label="IDP Profiles",
    ),
    "secintelprofiles": ObjectDef(
        mistapi_function=secintelprofiles.listOrgSecIntelProfiles,
        label="SecIntel Profiles",
    ),
    "ssos": ObjectDef(
        mistapi_function=ssos.listOrgSsos,
        label="SSOs",
    ),
    "ssoroles": ObjectDef(
        mistapi_function=ssoroles.listOrgSsoRoles,
        label="SSO Roles",
    ),
    "usermacs": ObjectDef(
        mistapi_function=usermacs.searchOrgUserMacs,
        label="User MACs",
        name_fields=["mac", "name"],
    ),
    "assets": ObjectDef(
        mistapi_function=assets.listOrgAssets,
        label="Assets",
    ),
    "assetfilters": ObjectDef(
        mistapi_function=assetfilters.listOrgAssetFilters,
        label="Asset Filters",
    ),
}

# ── Site-level object types ─────────────────────────────────────────────────

SITE_OBJECTS: dict[str, ObjectDef] = {
    "info": ObjectDef(
        mistapi_function=site_sites.getSiteInfo,
        label="Site Info",
        is_list=False,
    ),
    "settings": ObjectDef(
        mistapi_function=site_setting.getSiteSetting,
        label="Site Settings",
        is_list=False,
    ),
    "wlans": ObjectDef(
        mistapi_function=site_wlans.listSiteWlans,
        label="WLANs",
        name_fields=["ssid", "name"],
    ),
    "devices": ObjectDef(
        mistapi_function=devices.listSiteDevices,
        label="Devices",
        name_fields=["name", "mac"],
        request_type="all",
        get_function=devices.getSiteDevice,
    ),
    "maps": ObjectDef(
        mistapi_function=maps.listSiteMaps,
        label="Maps",
    ),
    "zones": ObjectDef(
        mistapi_function=zones.listSiteZones,
        label="Zones",
    ),
    "rssizones": ObjectDef(
        mistapi_function=rssizones.listSiteRssiZones,
        label="RSSI Zones",
    ),
    "psks": ObjectDef(
        mistapi_function=site_psks.listSitePsks,
        label="PSKs",
    ),
    "assets": ObjectDef(
        mistapi_function=site_assets.listSiteAssets,
        label="Assets",
    ),
    "beacons": ObjectDef(
        mistapi_function=beacons.listSiteBeacons,
        label="Beacons",
    ),
    "vbeacons": ObjectDef(
        mistapi_function=vbeacons.listSiteVBeacons,
        label="Virtual Beacons",
    ),
    "wxrules": ObjectDef(
        mistapi_function=site_wxrules.listSiteWxRules,
        label="WxLAN Rules",
    ),
    "wxtags": ObjectDef(
        mistapi_function=wxtags.listSiteWxTags,
        label="WxLAN Tags",
    ),
    "webhooks": ObjectDef(
        mistapi_function=site_webhooks.listSiteWebhooks,
        label="Webhooks",
        name_fields=["name", "url"],
    ),
}


# ── Helper functions ────────────────────────────────────────────────────────


def get_object_name(obj: dict[str, Any], obj_def: ObjectDef) -> str:
    """Extract display name from an object using the definition's name_fields."""
    for field_name in obj_def.name_fields:
        value = obj.get(field_name)
        if value:
            return str(value)
    return obj.get("id", "unknown")[:8]


def get_all_object_type_options() -> list[dict[str, Any]]:
    """Return all object type options for frontend dropdowns.

    Returns a list of dicts with: value, label, scope, is_list.
    """
    options: list[dict[str, Any]] = []
    for key, obj_def in ORG_OBJECTS.items():
        options.append(
            {
                "value": f"org:{key}",
                "label": obj_def.label,
                "scope": "org",
                "is_list": obj_def.is_list,
            }
        )
    for key, obj_def in SITE_OBJECTS.items():
        options.append(
            {
                "value": f"site:{key}",
                "label": obj_def.label,
                "scope": "site",
                "is_list": obj_def.is_list,
            }
        )
    return options
