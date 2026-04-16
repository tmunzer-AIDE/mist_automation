# Mist Automation Platform

A self-hosted platform for automating Juniper Mist network operations and managing configuration backups. Built with FastAPI and Angular.

## Features

- **Configuration Backup & Restore** — Scheduled snapshots of Mist org/site configs with retention policies and optional Git history tracking. Details: [Backup object time travel](docs/backup-object-time-travel-implementation-plan.md).
- **Webhook-driven Automation** — Receive Mist webhooks and run graph-based workflows with trigger/filter/action nodes. Details: [Workflow guide](docs/workflows.md).
- **Digital Twin (Pre-deployment Simulation)** — Simulate config changes before deployment and catch conflicts across config, topology, routing, security, and L2 checks. Details: [Digital Twin guide](docs/digital-twin.md).
- **Config Change Impact Analysis** — Automatically monitor post-change behavior, run validation checks, and generate AI-assisted impact assessments. Details: [Impact Analysis guide](docs/impact-analysis.md).
- **Telemetry & Live Device Analytics** — Always-on Mist WebSocket ingestion with InfluxDB-backed queries, live device streams, and site/client observability views. Details: [Telemetry module docs](backend/app/modules/telemetry/CLAUDE.md).
- **AI Assistance & MCP Tooling** — Multi-provider LLM support (OpenAI, Anthropic, Ollama, LM Studio, and others), conversational threads, MCP tool-calling, and persistent memory. Details: [LLM integration architecture](docs/llm-integration.md), [MCP server module](backend/app/modules/mcp_server/CLAUDE.md).
- **AP Power Scheduling** — Define off-hours windows per site to reduce AP power usage while protecting client roaming and critical APs.
- **Post-deployment Reports** — Validate AP, switch, and gateway health after changes (firmware, ports, cable tests, virtual chassis consistency) with PDF/CSV export.
- **Webhook Monitor** — Real-time view of incoming Mist webhook events with filtering and history.
- **Notifications** — Per-workflow failure alerts via Slack, Email (SMTP), PagerDuty, or ServiceNow with built-in integration tests.
- **User Management** — Role-based access (admin, automation, backup, post_deployment, impact_analysis), JWT auth with optional TOTP, passkey/WebAuthn login, and session controls.
- **Maintenance Mode** — Admin toggle that returns 503 to non-admin users while keeping health endpoints available.
- **Dashboard** — Overview of system activity, backup status, workflow executions, and impact analysis activity.
- **Dark Mode** — Because of course.

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.10+, FastAPI, Beanie (MongoDB ODM) |
| Frontend | Angular 21, Angular Material |
| Database | MongoDB |
| Cache/Queue | Redis, Celery |
| Scheduler | APScheduler |
| Mist API | `mistapi` library |

## Architecture

```
                        ┌───────────────────┐
                        │  Mist Cloud API   │
                        └─▲───▲────────┬────┘
                          │   │        │
                     REST │   │ WS     │ Webhooks
                          │   │        │
┌────────────┐ HTTP  ┌────┴───┴────────▼────────┐
│  Browser   ├──────►│     FastAPI Backend      │
│ (Angular)  │◄──────┤                          │
└────────────┘ + WS  │  ┌─────────┐ ┌─────────┐ │
                     │  │ Webhook │ │ APSch-  │ │
                     │  │ Gateway │ │ eduler  │ │
                     │  └────┬────┘ └────┬────┘ │
                     └───────┼───────────┼──────┘
                             │           │
                        ┌────▼───────────▼────┐
                        │       Redis         │
                        │     (broker)        │
                        └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
                        │   Celery Workers    │
                        │  - Webhook Worker   │
                        │  - Backup Worker    │
                        └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
                        │      MongoDB        │
                        │  configs, backups,  │
                        │  executions, users  │
                        └─────────────────────┘
```

The backend communicates with the Mist Cloud via REST API calls and WebSocket connections (device utilities like cable tests, port bounces — handled by the `mistapi` library). Mist sends webhooks back to the backend to trigger automation workflows.

Optional integrations: Slack, ServiceNow, PagerDuty (outbound notifications). Smee.io can be used in development to forward webhooks to localhost.

## Prerequisites

- Python 3.10+
- Node.js 18+ / npm
- MongoDB 4.4+
- Redis 6.0+
- A Mist API token and organization ID

## Getting Started

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `SECRET_KEY` — generate one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `MIST_API_TOKEN` — your Mist API token
- `MIST_ORG_ID` — your Mist organization ID

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -e ".[dev,test]"
python -m app.main
```

The API starts at `http://localhost:8000`.

### 3. Frontend

```bash
cd frontend
npm install
npm start
```

The UI starts at `http://localhost:4200` and proxies API requests to the backend.

### 4. First login

On first launch, you'll be redirected to an onboarding page to create the initial admin account.

## Configuration

All configuration is done through environment variables. See `.env.example` for the full list with descriptions. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key (required) | — |
| `MIST_API_TOKEN` | Mist API token (required) | — |
| `MIST_ORG_ID` | Mist organization ID (required) | — |
| `MONGODB_URL` | MongoDB connection string | `mongodb://localhost:27017` |
| `CELERY_BROKER_URL` | Redis URL for Celery | `redis://localhost:6379/1` |
| `BACKUP_FULL_SCHEDULE_CRON` | Backup schedule (cron) | `0 2 * * *` |
| `BACKUP_RETENTION_DAYS` | How long to keep backups | `90` |
| `BACKUP_GIT_ENABLED` | Enable Git versioning for backups | `false` |
| `WEBAUTHN_RP_ID` | Passkey Relying Party ID (your domain) | `localhost` |
| `WEBAUTHN_RP_NAME` | Passkey display name in browser prompts | `Mist Automation` |
| `WEBAUTHN_ORIGIN` | Expected origin for passkey verification | `http://localhost:4200` |
| `SLACK_WEBHOOK_URL` | Slack notifications (optional) | — |

## API Documentation

When the backend is running:

- **Swagger UI** — http://localhost:8000/api/v1/docs
- **ReDoc** — http://localhost:8000/api/v1/redoc
- **Health check** — http://localhost:8000/health

## Development

```bash
# Backend tests
cd backend
pytest                       # all tests
pytest -m unit               # unit only
pytest -m integration        # integration only

# Backend linting
black .
ruff check .
mypy app

# Frontend tests
cd frontend
npx ng test
```

## License

Proprietary — All rights reserved.
