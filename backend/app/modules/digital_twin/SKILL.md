---
name: digital-twin
description: "Use when the user wants to simulate, validate, or test Mist configuration changes before deploying them. Triggers on: 'simulate this change', 'what if I push this template', 'test before deploying', 'check for conflicts', 'validate my config', 'pre-deployment check', 'digital twin', 'dry run on the network', or any intent to verify config safety before applying."
---

# Digital Twin — Pre-deployment Configuration Simulation

You have access to the `digital_twin` MCP tool. Use it to validate proposed Mist configuration changes against the current network state **before** deploying them.

## When to Use

- User wants to push a template to one or more sites
- User wants to create/modify WLANs, networks, VLANs, or device configs
- User wants to change PSKs, RF templates, DHCP settings, or security policies
- User wants to assign templates to sites
- User wants to change an org-level template (network, gateway, site, RF) — the Twin automatically finds all affected sites and validates the impact on each
- Any configuration change that could affect the production network

## How to Use

### Step 1: Translate Intent to Writes

Convert the user's request into a list of Mist API write operations:

```json
[
  {"method": "PUT", "endpoint": "/api/v1/sites/{site_id}/setting", "body": {"vars": {"office_vlan": "100"}}},
  {"method": "POST", "endpoint": "/api/v1/sites/{site_id}/wlans", "body": {"ssid": "Guest", "vlan_id": "200"}}
]
```

Use the correct Mist API endpoints. Common ones:
- Site settings: `PUT /api/v1/sites/{site_id}/setting`
- Site info (template assignment): `PUT /api/v1/sites/{site_id}`
- WLANs: `POST/PUT /api/v1/sites/{site_id}/wlans[/{wlan_id}]`
- Networks: `POST/PUT /api/v1/orgs/{org_id}/networks[/{network_id}]`
- Devices: `PUT /api/v1/sites/{site_id}/devices/{device_id}`
- Templates: `PUT /api/v1/orgs/{org_id}/sitetemplates/{template_id}`

### Step 2: Simulate

Call the tool:

```
digital_twin(action="simulate", writes=[...])
```

The Twin runs 23 validation checks across 2 layers:
- **Layer 1 (Config)**: IP/subnet overlaps, VLAN collisions, duplicate SSIDs, unresolved template variables, DHCP misconfigs, PSK rotation impact, airtime overhead, port conflicts
- **Layer 2 (Topology)**: Connectivity loss, VLAN black holes, LAG/MCLAG integrity, VC integrity, PoE overload, port saturation, LACP misconfiguration, MTU mismatch

### Step 3: Handle Results

The tool returns a report with `overall_severity` (clean/warning/error/critical) and a list of issues.

**If issues found:**
1. Explain each issue to the user in plain language
2. Propose a fix (use the `remediation_hint` from each issue)
3. Re-simulate with corrected writes: `digital_twin(action="simulate", writes=[corrected], session_id="...")`
4. Repeat until clean

**If clean:**
1. Confirm with user: "All 23 checks passed. Ready to deploy?"
2. Call `digital_twin(action="approve", session_id="...")` to execute

### Step 4: Deploy

The `approve` action triggers a user confirmation dialog. Once confirmed, the staged writes execute against the Mist API in order.

## Important Rules

- **Always simulate before deploying.** Never call Mist API write endpoints directly when the user's intent involves config changes. Use the Twin.
- **Explain issues clearly.** Don't just list check IDs — tell the user what the problem is and what will happen if they deploy anyway.
- **Propose fixes, don't just report problems.** Use the `remediation_hint` to suggest corrections.
- **Re-simulate after fixes.** Don't assume the fix is correct — run the checks again.
- **Respect the user's decision.** If they want to proceed despite warnings, approve the deployment. Only block on errors/critical issues.

## Other Actions

- `digital_twin(action="status", session_id="...")` — check session state
- `digital_twin(action="reject", session_id="...")` — cancel a session
- `digital_twin(action="history")` — list recent sessions
