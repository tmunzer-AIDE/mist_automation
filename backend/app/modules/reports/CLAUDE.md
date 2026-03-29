# Reports Module

Part of mist_automation — see root `CLAUDE.md` for global architecture and conventions, `backend/CLAUDE.md` for backend patterns.

## Backend (`app/modules/reports/`)

- **Report job model**: `ReportJob` Beanie Document stores report type, site, status, progress, and full validation results.
- **Validation service** (`services/validation_service.py`): Runs post-deployment validation as a background task. Checks template variables (Jinja2 extraction across all string values), AP health (name, firmware, eth0 speed with < 1Gbps warning, connection status), switch health (name, firmware, status, virtual chassis consistency, cable tests run sequentially per switch), and gateway health (name, firmware, WAN/LAN port status with pass/warn/fail for full/partial/no connectivity). Template fetching and gateway data fetching are parallelized via `asyncio.gather`.
- **Export service** (`services/export_service.py`): Generates PDF (via `reportlab`) and CSV (ZIP of CSVs) from completed reports.
- **WebSocket progress**: Broadcasts real-time progress on channel `report:{id}` using existing `ws_manager`.
- **Access control**: `require_post_deployment_role` dependency — requires `post_deployment` or `admin` role. `require_reports_role` kept as backwards-compat alias.

## Frontend (`features/reports/`)

- **Report list**: Table of past reports with create dialog (site picker dropdown).
- **Report detail**: Live progress view (WebSocket subscription) during generation, then expandable sections for template variables, APs, switches (with VC + cable test sub-tables), and gateways. Export PDF/CSV buttons in topbar.
