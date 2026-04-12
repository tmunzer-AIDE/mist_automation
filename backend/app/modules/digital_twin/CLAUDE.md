# Digital Twin Module

Part of mist_automation. See root CLAUDE.md for global architecture.

## Purpose

Pre-deployment simulation for Mist write operations. Twin stages writes, predicts impact on a virtual site state, and gates execution on check results.

## Entry Points

- LLM: MCP tool `digital_twin` (simulate, remediate, approve, reject).
- Workflow: `twin_session_var` in `MistService._api_call()` intercepts POST/PUT/DELETE when `workflow.twin_validation=True`.
- Restore path: backup restore flows can use the same staging/validation model.

## Core Flow (Non-Obvious Invariants)

1. Stage writes via `endpoint_parser` into `StagedWrite`.
2. Build predicted virtual state via `state_resolver`.
3. Compile both paths:
	 - predicted: `compile_virtual_state(...)`
	 - baseline: `compile_base_state(...)`
4. Build site snapshots for baseline and predicted.
5. Run checks and build `PredictionReport`.
6. Approve only when policy gates pass.

Critical invariant: baseline must go through compile too. If baseline uses raw backup while predicted uses compiled config, diff-based checks can miss real regressions (notably inherited `port_config` deltas).

## State/Backup Shape Rules You Need To Remember

- Canonical singleton object mapping:
	- `/sites/{id}/setting` and `/orgs/{id}/setting` -> `settings`
	- `/sites/{id}` -> `info`
	- `/orgs/{id}` -> `data`
- Legacy aliases are still accepted (`setting`, `site_setting`, `site`).
- Singleton staged writes use `object_id=None`.
- Site identity can come from three backup forms and must be checked in this order when available:
	- site-scoped `info`
	- site-scoped `site` (legacy)
	- org-scoped `sites` record keyed by `object_id=<site_id>`

## Site Network Assembly (Main Source Of False Positives/Negatives)

- Include only networks actually referenced by the site's assigned templates plus inline `site_setting.networks`.
- If template assignment cannot be resolved, fallback to all org networks (partial-backup safety).
- Template-only networks must be seeded from template inline `networks` when no standalone `networks` backup object exists.
- Final network dict is sorted by key for deterministic details across baseline vs predicted passes.

Why this matters: without scoped filtering and seeding, VLAN/routing/config checks can silently downgrade to "not applicable" or generate cross-template false overlaps.

## Preflight, Approval, and Session Safety

- Unresolved path placeholders (`{x}`, `<x>`, `:x`) are parse errors.
- Preflight blocks simulation checks when targets are invalid:
	- unknown site scope
	- non-singleton PUT/DELETE target missing from backup
- Blocking preflight issues (`SYS-*`, layer 0, error/critical) mark session `failed`.
- `approve_and_execute()` rejects when:
	- `execution_safe` is false, or
	- blocking preflight issues exist.
- Re-simulate on existing session enforces server-side ownership and org match.

## Diff Gating Semantics

- Analyzer runs each check twice:
	- baseline vs baseline (existing debt)
	- baseline vs predicted (proposed change)
- Predicted failures are `pre_existing=True` only when predicted details are a subset of baseline details.
- `execution_safe` ignores pre-existing failures but blocks on new/worsened error/critical findings.
- `overall_severity` still reflects the true worst state (including pre-existing).

## Live Telemetry Rules (Easy To Misread From Code)

- `fetch_live_data()` merges two sources in parallel:
	- `listOrgDevicesStats` (AP/client-heavy, partial LLDP)
	- `searchSiteSwOrGwPorts` (authoritative switch/gateway LLDP + port state)
- Per-source failure logs do not abort full live fetch.
- MACs are normalized on ingest and during snapshot build (`:`/`-` removed, lowercase).
- OSPF/BGP peers are extracted from stats payload variants and normalized into `peer_ip` entries.

## Check Semantics That Matter Operationally

- Port impact (`PORT-DISC`, `PORT-CLIENT`) is `skipped` (not `pass`) when infra exists but LLDP is missing.
- Port-impact check IDs are split by risk class:
	- `PORT-DISC`: physical disconnect (removed/disabled LLDP-linked port)
	- `PORT-VLAN`: VLAN isolation on LLDP-linked ports (baseline VLANs no longer carried)
	- `PORT-L2`: mixed case containing both physical disconnect and VLAN isolation in one simulation.
- `ROUTE-GW` validates only routed networks (L3 indicators present), not pure L2 VLAN entries.
- `ROUTE-OSPF`/`ROUTE-BGP` are device-scoped (peer checked against that same device's interfaces).
- If protocol config exists but peer telemetry is absent, routing peer checks return `skipped` (not `pass`).
- `CONN-VLAN-PATH` uses per-VLAN subgraphs and flags baseline-reachable -> predicted-unreachable regressions; AP impact escalates severity.

### Change-Aware Check Profiles

- `analyze_site_with_context()` supports change-type aware execution.
- For `devices`-only changes (e.g. `site_devices` switch updates), the analyzer runs topology/L3 checks only:
	- connectivity (`CONN-PHYS`, `CONN-VLAN`, `CONN-VLAN-PATH`)
	- config conflicts except Wi-Fi SSID (`CFG-SUBNET`, `CFG-VLAN`, `CFG-DHCP-*`; excludes `CFG-SSID`)
	- port impact (`PORT-*`)
	- routing (`ROUTE-*`)
	- STP (`STP-*`)
- Wi-Fi-centric categories are skipped in this profile (`CFG-SSID`, `SEC-GUEST`, `TMPL-VAR`, etc.).
- Any change set touching non-device object types falls back to the full check suite.

## Topology Normalization Contract

Shared helpers in `topology_utils.py` are the single source for:

- port-id normalization (`ge-0/0/9.0`, `xe-0/0/0:0` -> base port),
- tolerant port lookup candidates (`p`, `p.0`, `p:0`),
- merged infra-neighbor maps (`port_devices` seeded, LLDP overlay).
- interface materialization (profile attributes flattened per port + explicit `resolved_vlan_ids`).

`build_site_snapshot()` persists this materialized view as `DeviceSnapshot.resolved_port_config`; graph/check logic should prefer that field and only fallback to on-the-fly materialization when tests construct snapshots manually.

`site_graph` and `port_impact` must stay aligned to these helpers to avoid diverging reachability vs impact conclusions.

## Workflow Interception Contract

When twin validation is enabled in workflow execution:

1. Create a `TwinSession` before graph execution.
2. Set `twin_session_var` so Mist writes are staged, not executed.
3. Always reset `twin_session_var` in `finally` to avoid cross-request leakage.

## Config Compiler Details Worth Keeping In Mind

- Switch chain: template -> site setting -> device profile -> device config (with switch rule first-match behavior).
- Gateway chain: gateway template -> device profile -> device config.
- AP configs are pass-through.
- Switch top-level template `port_config` is intentionally ignored by allowlist; effective switch ports come from matching rules and device overrides.
- Port ranges/comma lists are expanded before merge so point overrides and ranged defaults collide on identical keys.
- Template/profile loads follow: staged state -> preload cache -> backup query.
- Device profile impact discovery is device-based (scan devices, then derive impacted sites), not template-assignment based.

## Twin-to-IA Bridge

Post-approval deployment can spawn IA monitoring sessions per impacted device and compare predicted vs actual outcomes (`correct`, `over_predicted`, `under_predicted`, `unknown`) for calibration.

## Core Dependencies

- `netaddr`: subnet math in config/routing checks.
- `networkx`: graph-based connectivity and VLAN path checks.
