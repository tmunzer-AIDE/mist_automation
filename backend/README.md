# Mist Automation & Backup - Backend

FastAPI backend for the Mist Automation & Backup application.

## Overview

This backend provides:
- **Automation Module**: Workflow automation engine for Mist webhooks and scheduled tasks
- **Backup & Restore Module**: Version-controlled configuration backup with restore capabilities
- **Authentication & Authorization**: JWT-based auth with 2FA support
- **RESTful API**: Comprehensive API for managing workflows, backups, and system configuration

## Technology Stack

- **Framework**: FastAPI (async Python web framework)
- **Database**: MongoDB with Beanie ODM
- **Cache**: Redis for session management and webhook deduplication
- **Task Queue**: Celery for background jobs
- **Scheduler**: APScheduler for cron-based workflows
- **Authentication**: JWT tokens with bcrypt password hashing

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration management
│   ├── dependencies.py      # Dependency injection utilities
│   ├── models/              # Database models (Beanie documents)
│   │   ├── user.py
│   │   ├── session.py
│   │   ├── workflow.py
│   │   ├── execution.py
│   │   ├── webhook.py
│   │   ├── backup.py
│   │   └── system.py
│   ├── schemas/             # API request/response schemas (Pydantic)
│   ├── api/                 # API route handlers
│   │   └── v1/
│   ├── services/            # Business logic layer
│   ├── core/                # Core utilities
│   │   ├── database.py      # MongoDB connection
│   │   ├── security.py      # Authentication & encryption
│   │   ├── logger.py        # Structured logging
│   │   ├── exceptions.py    # Custom exceptions
│   │   └── middleware.py    # Request/response middleware
│   ├── utils/               # Helper functions
│   └── workers/             # Background task workers
├── tests/                   # Test suite
│   ├── unit/
│   ├── integration/
│   └── conftest.py
└── requirements.txt         # Python dependencies
```

## Setup

### Prerequisites

- Python 3.14+
- MongoDB 4.4+
- Redis 6.0+

### Installation

1. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   # Or use uv for faster installation:
   uv pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp ../.env.example ../.env
   # Edit .env and set required values (SECRET_KEY, MONGODB_URL, etc.)
   ```

4. **Generate secret key:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   # Copy output to SECRET_KEY in .env
   ```

### Running the Application

**Development mode:**
```bash
python -m app.main
# Or use uvicorn directly:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Production mode:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/api/v1/docs
- **Health Check**: http://localhost:8000/health

## Database Models

### User Management
- **User**: User accounts with roles and 2FA support
- **UserSession**: Active JWT sessions with device tracking

### Automation
- **Workflow**: Workflow configurations (triggers, filters, actions)
- **WorkflowExecution**: Execution history and results
- **WebhookEvent**: Incoming webhook tracking

### Backup
- **BackupObject**: Versioned configuration backups
- **BackupConfig**: Backup settings per organization

### System
- **SystemConfig**: Global system settings
- **AuditLog**: Audit trail for all user actions

## API Structure

### Authentication
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/logout` - User logout
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/onboarding` - First-time admin setup

### Users (Admin only)
- `GET /api/v1/users` - List users
- `POST /api/v1/users` - Create user
- `GET /api/v1/users/{id}` - Get user details
- `PUT /api/v1/users/{id}` - Update user
- `DELETE /api/v1/users/{id}` - Delete user

### Workflows (Automation role)
- `GET /api/v1/workflows` - List workflows
- `POST /api/v1/workflows` - Create workflow
- `GET /api/v1/workflows/{id}` - Get workflow
- `PUT /api/v1/workflows/{id}` - Update workflow
- `DELETE /api/v1/workflows/{id}` - Delete workflow
- `POST /api/v1/workflows/{id}/execute` - Trigger manual execution

### Webhooks
- `POST /api/v1/webhooks/mist` - Receive Mist webhooks
- `GET /api/v1/webhooks/events` - List webhook events

### Backups (Backup role)
- `GET /api/v1/backups/objects` - List backed up objects
- `GET /api/v1/backups/objects/{id}` - Get object versions
- `POST /api/v1/backups/restore` - Restore configuration
- `GET /api/v1/backups/config` - Get backup configuration
- `PUT /api/v1/backups/config` - Update backup configuration

### Admin
- `GET /api/v1/admin/system` - Get system configuration
- `PUT /api/v1/admin/system` - Update system configuration
- `GET /api/v1/admin/audit-logs` - Get audit logs

## Development

### Code Style

The project uses:
- **Black** for code formatting
- **Ruff** for linting
- **MyPy** for type checking

Run code quality checks:
```bash
black .
ruff check .
mypy app
```

### Testing

Run tests:
```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific test file
pytest tests/unit/test_security.py
```

### Security

- **Authentication**: JWT tokens with configurable expiration
- **Password Hashing**: Bcrypt with customizable complexity
- **2FA**: TOTP-based with backup codes
- **Encryption**: Sensitive data encrypted with Fernet
- **Session Management**: Token revocation and device tracking
- **Input Validation**: Pydantic schemas for all API inputs
- **Security Headers**: CORS, CSP, XSS protection

## Environment Variables

Key environment variables (see `.env.example` for complete list):

- `SECRET_KEY` - JWT signing key (required)
- `MONGODB_URL` - MongoDB connection string
- `REDIS_URL` - Redis connection string
- `MIST_API_TOKEN` - Mist API token
- `MIST_ORG_ID` - Mist organization ID
- `ENVIRONMENT` - `development`, `staging`, or `production`

## Logging

Structured logging using `structlog` with JSON output in production.

Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

Configure via `LOG_LEVEL` environment variable.

## Next Steps

To continue development:

1. **Create API Schemas** (`app/schemas/`)
   - auth.py - Authentication schemas
   - workflow.py - Workflow schemas
   - backup.py - Backup schemas

2. **Implement API Endpoints** (`app/api/v1/`)
   - auth.py - Authentication endpoints
   - users.py - User management
   - workflows.py - Workflow management
   - webhooks.py - Webhook receivers
   - backups.py - Backup operations
   - admin.py - Admin functions

3. **Create Services** (`app/services/`)
   - auth_service.py - Authentication logic
   - workflow_service.py - Workflow management
   - executor_service.py - Workflow execution
   - backup_service.py - Backup operations
   - mist_service.py - Mist API integration

4. **Background Workers** (`app/workers/`)
   - webhook_worker.py - Process webhooks
   - cron_worker.py - Scheduled workflows
   - backup_worker.py - Backup operations

5. **Write Tests** (`tests/`)
   - Unit tests for all services
   - Integration tests for API endpoints
   - End-to-end workflow tests

## License

Proprietary - All rights reserved
