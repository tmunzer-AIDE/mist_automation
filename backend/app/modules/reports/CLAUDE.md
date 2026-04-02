# Reports Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns.

## Backend (`app/modules/reports/`)

- **Report job model**: `ReportJob` Beanie Document stores report type, site, status, progress, and full validation results.
- **Validation service** (`services/validation_service.py`): Runs post-deployment validation as a background task. 9 steps: site info, templates & WLANs, template variables, config events, device events (24h trigger/clear correlation), APs, switches, gateways, cable tests (opt-in). Template fetching and gateway data fetching are parallelized via `asyncio.gather`.
  - **Template network filtering**: `_used_networks_from_port_config()` scans gateway port_config for actually-used networks; `_filter_template_networks()` + `_extract_used_services()` filter templates/derived sources before variable scanning to avoid false-positive undefined-variable warnings.
  - **Device event correlation**: `_fetch_device_events()` + `_correlate_device_events()` use `EVENT_TYPE_MAP` from `app/utils/event_definitions.py` (170+ event types) to track trigger/clear pairs per device. Results attached to each device via `_attach_device_events()`.
  - **Gateway config merge**: `_merge_port_configs()` does per-port deep merge (template → deviceprofile → device) so device overrides don't lose template fields like `aggregated`/`ae_idx`. Other sections (ip_configs, dhcpd_config) use shallow merge. `_fetch_device_profiles()` fetches profiles in parallel.
  - **AE/LACP detection**: Detects ae interfaces from port_stats when derived template drops range keys. Falls back to `if_stat` subinterfaces for port status. Collects LACP member details. Skips unconfigured ports.
  - **Network filtering in `_build_network_details()`**: Only includes networks actually assigned to a port (via `port_config`).
  - **Cable tests**: Opt-in via `include_cable_tests` parameter. Run sequentially per switch, parallel across switches.
- **Event definitions** (`app/utils/event_definitions.py`): `EVENT_TYPE_MAP` maps Mist event type strings to `(category, role, sub_id_field)` tuples for trigger/clear correlation. `EVENT_CATEGORY_DISPLAY` provides human-readable names. `extract_sub_id()` parses sub-identifiers from event fields or text.
- **Export service** (`services/export_service.py`): Generates PDF (via `reportlab`) and CSV (ZIP of CSVs) from completed reports. PDF includes LACP member rows for ae WAN/LAN ports. CSV includes `device_events.csv`.
- **WebSocket progress**: Broadcasts real-time progress on channel `report:{id}` using existing `ws_manager`.
- **Access control**: `require_post_deployment_role` dependency — requires `post_deployment` or `admin` role. `require_reports_role` kept as backwards-compat alias.

## Frontend (`features/reports/`)

- **Report list**: Table of past reports with create dialog (site picker dropdown, cable test checkbox).
- **Report detail**: Live progress view (WebSocket subscription) during generation, then expandable sections for template variables, APs, switches (with VC + cable test sub-tables), and gateways. Click any device row (including APs) to open detail dialog showing checks, device events (24h), and for gateways: WAN/LAN ports with LACP member sub-rows, networks. Export PDF/CSV buttons in topbar.
