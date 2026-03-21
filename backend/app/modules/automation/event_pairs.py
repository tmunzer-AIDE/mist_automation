"""
Event pairs catalog — defines opening/closing event pairs for Mist webhook events.

Each pair describes a problem event (opening) and its resolution event (closing),
used by the aggregation engine to cancel buffered events when a device recovers.
"""

EVENT_PAIRS: list[dict] = [
    # ── AP Events ────────────────────────────────────────────────────────────
    {
        "topic": "device-events",
        "opening": "AP_DISCONNECTED",
        "closing": "AP_CONNECTED",
        "device_key": "device_mac",
        "label": "AP Disconnect / Reconnect",
    },
    {
        "topic": "device-events",
        "opening": "AP_CONFIG_FAILED",
        "closing": "AP_CONFIGURED",
        "device_key": "device_mac",
        "label": "AP Config Failed / Configured",
    },
    {
        "topic": "device-events",
        "opening": "AP_UPGRADE_FAILED",
        "closing": "AP_UPGRADED",
        "device_key": "device_mac",
        "label": "AP Upgrade Failed / Upgraded",
    },
    {
        "topic": "device-events",
        "opening": "AP_RADSEC_FAILURE",
        "closing": "AP_RADSEC_RECOVERY",
        "device_key": "device_mac",
        "label": "AP RADSEC Failure / Recovery",
    },
    {
        "topic": "device-events",
        "opening": "AP_PORT_DOWN",
        "closing": "AP_PORT_UP",
        "device_key": "device_mac",
        "label": "AP Port Down / Up",
    },
    # ── Switch Events ────────────────────────────────────────────────────────
    {
        "topic": "device-events",
        "opening": "SW_DISCONNECTED",
        "closing": "SW_CONNECTED",
        "device_key": "device_mac",
        "label": "Switch Disconnect / Reconnect",
    },
    {
        "topic": "device-events",
        "opening": "SW_CONFIG_FAILED",
        "closing": "SW_CONFIGURED",
        "device_key": "device_mac",
        "label": "Switch Config Failed / Configured",
    },
    {
        "topic": "device-events",
        "opening": "SW_UPGRADE_FAILED",
        "closing": "SW_UPGRADED",
        "device_key": "device_mac",
        "label": "Switch Upgrade Failed / Upgraded",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_FAN",
        "closing": "SW_ALARM_CHASSIS_FAN_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis Fan Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_PSU",
        "closing": "SW_ALARM_CHASSIS_PSU_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis PSU Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_HOT",
        "closing": "SW_ALARM_CHASSIS_HOT_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis Overheat Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_POE",
        "closing": "SW_ALARM_CHASSIS_POE_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis PoE Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_PEM",
        "closing": "SW_ALARM_CHASSIS_PEM_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis PEM Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_HUMIDITY",
        "closing": "SW_ALARM_CHASSIS_HUMIDITY_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis Humidity Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_VC_PORT_DOWN",
        "closing": "SW_VC_PORT_UP",
        "device_key": "device_mac",
        "label": "Switch VC Port Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "SW_EVPN_CORE_ISOLATED",
        "closing": "SW_EVPN_CORE_ISOLATION_CLEARED",
        "device_key": "device_mac",
        "label": "Switch EVPN Core Isolated",
    },
    {
        "topic": "device-events",
        "opening": "SW_OSPF_NEIGHBOR_DOWN",
        "closing": "SW_OSPF_NEIGHBOR_UP",
        "device_key": "device_mac",
        "label": "Switch OSPF Neighbor Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "SW_BGP_NEIGHBOR_DOWN",
        "closing": "SW_BGP_NEIGHBOR_UP",
        "device_key": "device_mac",
        "label": "Switch BGP Neighbor Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "SW_LACPD_TIMEOUT",
        "closing": "SW_LACPD_TIMEOUT_CLEARED",
        "device_key": "device_mac",
        "label": "Switch LACP Timeout",
    },
    {
        "topic": "device-events",
        "opening": "SW_PORT_DOWN",
        "closing": "SW_PORT_UP",
        "device_key": "device_mac",
        "label": "Switch Port Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "SW_BFD_SESSION_DISCONNECTED",
        "closing": "SW_BFD_SESSION_ESTABLISHED",
        "device_key": "device_mac",
        "label": "Switch BFD Session Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_IOT_SET",
        "closing": "SW_ALARM_IOT_CLEAR",
        "device_key": "device_mac",
        "label": "Switch IoT Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_VC_IN_TRANSITION",
        "closing": "SW_VC_STABLE",
        "device_key": "device_mac",
        "label": "Switch VC In Transition / Stable",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_PARTITION",
        "closing": "SW_ALARM_CHASSIS_PARTITION_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Chassis Partition Alarm",
    },
    {
        "topic": "device-events",
        "opening": "SW_ALARM_CHASSIS_MGMT_LINK_DOWN",
        "closing": "SW_ALARM_CHASSIS_MGMT_LINK_DOWN_CLEAR",
        "device_key": "device_mac",
        "label": "Switch Mgmt Link Down",
    },
    {
        "topic": "device-events",
        "opening": "SW_MAC_LEARNING_STOPPED",
        "closing": "SW_MAC_LEARNING_RESUMED",
        "device_key": "device_mac",
        "label": "Switch MAC Learning Stopped / Resumed",
    },
    # ── Gateway Events ───────────────────────────────────────────────────────
    {
        "topic": "device-events",
        "opening": "GW_DISCONNECTED",
        "closing": "GW_CONNECTED",
        "device_key": "device_mac",
        "label": "Gateway Disconnect / Reconnect",
    },
    {
        "topic": "device-events",
        "opening": "GW_CONFIG_FAILED",
        "closing": "GW_CONFIGURED",
        "device_key": "device_mac",
        "label": "Gateway Config Failed / Configured",
    },
    {
        "topic": "device-events",
        "opening": "GW_UPGRADE_FAILED",
        "closing": "GW_UPGRADED",
        "device_key": "device_mac",
        "label": "Gateway Upgrade Failed / Upgraded",
    },
    {
        "topic": "device-events",
        "opening": "GW_ALARM_CHASSIS_HOT",
        "closing": "GW_ALARM_CHASSIS_HOT_CLEAR",
        "device_key": "device_mac",
        "label": "Gateway Overheat Alarm",
    },
    {
        "topic": "device-events",
        "opening": "GW_ALARM_CHASSIS_WARM",
        "closing": "GW_ALARM_CHASSIS_WARM_CLEAR",
        "device_key": "device_mac",
        "label": "Gateway Warm Alarm",
    },
    {
        "topic": "device-events",
        "opening": "GW_VPN_PATH_DOWN",
        "closing": "GW_VPN_PATH_UP",
        "device_key": "device_mac",
        "label": "Gateway VPN Path Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_OSPF_NEIGHBOR_DOWN",
        "closing": "GW_OSPF_NEIGHBOR_UP",
        "device_key": "device_mac",
        "label": "Gateway OSPF Neighbor Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_BGP_NEIGHBOR_DOWN",
        "closing": "GW_BGP_NEIGHBOR_UP",
        "device_key": "device_mac",
        "label": "Gateway BGP Neighbor Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_VPN_PEER_DOWN",
        "closing": "GW_VPN_PEER_UP",
        "device_key": "device_mac",
        "label": "Gateway VPN Peer Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_TUNNEL_DOWN",
        "closing": "GW_TUNNEL_UP",
        "device_key": "device_mac",
        "label": "Gateway Tunnel Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_HA_CONTROL_LINK_DOWN",
        "closing": "GW_HA_CONTROL_LINK_UP",
        "device_key": "device_mac",
        "label": "Gateway HA Control Link Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_PORT_DOWN",
        "closing": "GW_PORT_UP",
        "device_key": "device_mac",
        "label": "Gateway Port Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_CONDUCTOR_DISCONNECTED",
        "closing": "GW_CONDUCTOR_CONNECTED",
        "device_key": "device_mac",
        "label": "Gateway Conductor Down / Up",
    },
    {
        "topic": "device-events",
        "opening": "GW_FLOW_COUNT_THRESHOLD_EXCEEDED",
        "closing": "GW_FLOW_COUNT_RETURNED_TO_NORMAL",
        "device_key": "device_mac",
        "label": "Gateway Flow Count Exceeded / Normal",
    },
    {
        "topic": "device-events",
        "opening": "GW_FIB_COUNT_THRESHOLD_EXCEEDED",
        "closing": "GW_FIB_COUNT_RETURNED_TO_NORMAL",
        "device_key": "device_mac",
        "label": "Gateway FIB Count Exceeded / Normal",
    },
    {
        "topic": "device-events",
        "opening": "GW_HA_HEALTH_WEIGHT_LOW",
        "closing": "GW_HA_HEALTH_WEIGHT_RECOVERY",
        "device_key": "device_mac",
        "label": "Gateway HA Health Low / Recovery",
    },
    {
        "topic": "device-events",
        "opening": "GW_TUNNEL_PROVISION_FAILED",
        "closing": "GW_TUNNEL_PROVISIONED",
        "device_key": "device_mac",
        "label": "Gateway Tunnel Provision Failed / OK",
    },
    # ── Mist Edge Events ─────────────────────────────────────────────────────
    {
        "topic": "mxedge-events",
        "opening": "ME_DISCONNECTED",
        "closing": "ME_CONNECTED",
        "device_key": "device_mac",
        "label": "Mist Edge Disconnect / Reconnect",
    },
    {
        "topic": "mxedge-events",
        "opening": "ME_MISCONFIGURED",
        "closing": "ME_CONFIGURED",
        "device_key": "device_mac",
        "label": "Mist Edge Misconfigured / Configured",
    },
    {
        "topic": "mxedge-events",
        "opening": "ME_PSU_UNPLUGGED",
        "closing": "ME_PSU_PLUGGED",
        "device_key": "device_mac",
        "label": "Mist Edge PSU Unplugged / Plugged",
    },
    {
        "topic": "mxedge-events",
        "opening": "ME_FAN_UNPLUGGED",
        "closing": "ME_FAN_PLUGGED",
        "device_key": "device_mac",
        "label": "Mist Edge Fan Unplugged / Plugged",
    },
    {
        "topic": "mxedge-events",
        "opening": "ME_POWERINPUT_DISCONNECTED",
        "closing": "ME_POWERINPUT_CONNECTED",
        "device_key": "device_mac",
        "label": "Mist Edge Power Disconnected / Connected",
    },
    # ── ESL Events ───────────────────────────────────────────────────────────
    {
        "topic": "device-events",
        "opening": "ESL_HUNG",
        "closing": "ESL_RECOVERED",
        "device_key": "device_mac",
        "label": "ESL Hung / Recovered",
    },
    # ── NAC Events ───────────────────────────────────────────────────────────
    {
        "topic": "nac-events",
        "opening": "NAC_CLIENT_DENY",
        "closing": "NAC_CLIENT_PERMIT",
        "device_key": "mac",
        "label": "NAC Client Denied / Permitted",
    },
]

# ── Derived lookup structures ────────────────────────────────────────────────

# Reverse lookup: closing event type → opening event type
CLOSING_EVENT_MAP: dict[str, str] = {pair["closing"]: pair["opening"] for pair in EVENT_PAIRS}


def get_event_pair(opening: str) -> dict | None:
    """Find an event pair by its opening event type.

    Args:
        opening: The opening event type string (e.g. "AP_DISCONNECTED").

    Returns:
        The matching event pair dict, or None if not found.
    """
    for pair in EVENT_PAIRS:
        if pair["opening"] == opening:
            return pair
    return None


def get_pairs_by_topic(topic: str) -> list[dict]:
    """Filter event pairs by webhook topic.

    Args:
        topic: The webhook topic (e.g. "device-events", "mxedge-events").

    Returns:
        List of event pair dicts matching the given topic.
    """
    return [pair for pair in EVENT_PAIRS if pair["topic"] == topic]
