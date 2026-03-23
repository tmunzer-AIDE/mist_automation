# Mist Automation & Backup

A self-hosted platform for automating Juniper Mist network operations and managing configuration backups. Built with FastAPI and Angular.

## Features

- **Configuration Backup & Restore** — Scheduled snapshots of your Mist org/site configs with retention policies. Optional Git versioning for full history tracking.
- **Webhook-driven Automation** — Receive Mist webhooks and trigger workflows automatically. Includes a visual graph editor for building workflows (see the [workflow guide](docs/workflows.md) for details).
- **Post-deployment Reports** — Validate AP, switch, and gateway health after changes. Checks firmware, port status, cable tests, virtual chassis consistency. Export to PDF or CSV.
- **Webhook Monitor** — Real-time view of incoming Mist webhook events with filtering and history.
- **AI Assistance** — Multi-provider LLM integration (OpenAI, Anthropic, Ollama, LM Studio, etc.) with MCP tool calling. Global chat panel, workflow AI agent nodes, and autonomous backup analysis.
- **Notifications** — Per-workflow failure alerts via Slack, Email (SMTP), PagerDuty, or ServiceNow. Integration test buttons for all channels.
- **User Management** — Role-based access (admin, automation, backup, reports), JWT auth with optional 2FA (TOTP), session management.
- **Maintenance Mode** — Admin toggle that returns 503 to non-admin users. Health endpoint stays available for monitoring.
- **Dashboard** — Overview of system activity, backup status, and recent executions.
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
