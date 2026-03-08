# Mist Automation & Backup Application - Implementation Plan

## Executive Summary

This document outlines the implementation plan for a comprehensive web application that provides:
1. **Automation Module**: Workflow automation engine responding to Mist webhooks and cron events
2. **Backup & Restore Module**: Version-controlled configuration backup with intelligent restore capabilities

**Target Stack**: Python/FastAPI backend + Angular/Material frontend + MongoDB database

**Estimated Timeline**: 16-20 weeks for MVP

---

## 1. Project Structure

### 1.1 Repository Organization

```
mist_automation/
├── backend/                      # Python/FastAPI backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application entry
│   │   ├── config.py            # Configuration management
│   │   ├── dependencies.py      # Dependency injection
│   │   ├── models/              # Database models (Pydantic/ODM)
│   │   │   ├── user.py
│   │   │   ├── workflow.py
│   │   │   ├── backup.py
│   │   │   └── config.py
│   │   ├── schemas/             # API request/response schemas
│   │   │   ├── auth.py
│   │   │   ├── workflow.py
│   │   │   └── backup.py
│   │   ├── api/                 # API route handlers
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   ├── workflows.py
│   │   │   │   ├── backups.py
│   │   │   │   ├── webhooks.py
│   │   │   │   └── admin.py
│   │   ├── services/            # Business logic layer
│   │   │   ├── auth_service.py
│   │   │   ├── workflow_service.py
│   │   │   ├── executor_service.py
│   │   │   ├── backup_service.py
│   │   │   ├── restore_service.py
│   │   │   ├── mist_service.py  # Mist API wrapper
│   │   │   ├── git_service.py
│   │   │   └── notification_service.py
│   │   ├── core/                # Core utilities
│   │   │   ├── security.py      # Auth, encryption, hashing
│   │   │   ├── database.py      # DB connection management
│   │   │   ├── cache.py         # Redis/in-memory cache
│   │   │   ├── logger.py        # Structured logging
│   │   │   ├── exceptions.py    # Custom exceptions
│   │   │   └── middleware.py    # Request/response middleware
│   │   ├── utils/               # Helper functions
│   │   │   ├── validators.py    # Input validation
│   │   │   ├── filters.py       # Filter evaluation engine
│   │   │   ├── variables.py     # Variable substitution
│   │   │   └── webhook_validator.py
│   │   └── workers/             # Background tasks
│   │       ├── __init__.py
│   │       ├── webhook_worker.py
│   │       ├── cron_worker.py
│   │       ├── backup_worker.py
│   │       └── scheduler.py
│   ├── tests/                   # Test suite
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py
│   ├── migrations/              # Database migrations (if needed)
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                    # Angular frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── core/           # Core module (singleton services)
│   │   │   │   ├── auth/
│   │   │   │   ├── guards/
│   │   │   │   ├── interceptors/
│   │   │   │   └── services/
│   │   │   ├── shared/         # Shared module (reusable components)
│   │   │   │   ├── components/
│   │   │   │   ├── directives/
│   │   │   │   ├── pipes/
│   │   │   │   └── models/
│   │   │   ├── features/       # Feature modules
│   │   │   │   ├── auth/
│   │   │   │   │   ├── login/
│   │   │   │   │   ├── onboarding/
│   │   │   │   │   └── profile/
│   │   │   │   ├── dashboard/
│   │   │   │   ├── automation/
│   │   │   │   │   ├── workflows/
│   │   │   │   │   ├── executions/
│   │   │   │   │   ├── webhook-inspector/
│   │   │   │   │   └── workflow-editor/
│   │   │   │   ├── backup/
│   │   │   │   │   ├── timeline/
│   │   │   │   │   ├── object-list/
│   │   │   │   │   ├── object-detail/
│   │   │   │   │   └── comparison/
│   │   │   │   └── admin/
│   │   │   │       ├── users/
│   │   │   │       ├── settings/
│   │   │   │       └── logs/
│   │   │   ├── store/          # NgRx state management
│   │   │   │   ├── actions/
│   │   │   │   ├── reducers/
│   │   │   │   ├── effects/
│   │   │   │   └── selectors/
│   │   │   └── app.module.ts
│   │   ├── assets/
│   │   ├── environments/
│   │   └── styles/
│   ├── Dockerfile
│   └── nginx.conf
│
├── docker-compose.yml
├── .env.example
├── README.md
└── docs/
    ├── API.md
    ├── DEPLOYMENT.md
    ├── ARCHITECTURE.md
    └── USER_GUIDE.md
```

---

## 2. Technology Stack & Dependencies

### 2.1 Backend Dependencies

**Core Framework**
```txt
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.10.0          # Updated for Python 3.14 support
pydantic-settings>=2.6.0
```

**Database & ORM**
```txt
motor>=3.6.0              # MongoDB async driver
pymongo>=4.9,<4.10        # Compatible with motor
beanie>=1.27.0            # MongoDB ODM
```

**Authentication & Security**
```txt
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.12
pyotp>=2.9.0              # For 2FA/TOTP
qrcode>=8.0               # QR code generation for 2FA
cryptography>=43.0.0      # Encryption utilities
```

**Mist Integration**
```txt
mistapi>=0.60.4           # Official Mist API package
httpx>=0.28.0             # HTTP client
```

**HTTP Client**
```txt
aiohttp>=3.10.10
```

**Task Scheduling & Queue**
```txt
celery>=5.4.0
redis>=5.2.0
apscheduler>=3.10.4
```

**Git Integration**
```txt
gitpython>=3.1.43
```

**Utilities**
```txt
python-dotenv>=1.0.1
pyyaml>=6.0.2
jinja2>=3.1.4
structlog>=24.4.0         # Structured logging
python-json-logger>=2.0.7
```

**Testing**
```txt
pytest>=8.3.3
pytest-asyncio>=0.24.0
pytest-cov>=5.0.0
pytest-mock>=3.14.0
pytest-httpx>=0.30.0      # For mocking httpx requests
```

### 2.2 Frontend Dependencies

**Core Framework**
```json
{
  "@angular/core": "^20.0.0",
  "@angular/material": "^20.0.0",
  "@angular/cdk": "^20.0.0",
  "@ngrx/store": "^20.0.0",
  "@ngrx/effects": "^20.0.0",
  "rxjs": "^7.8.0"
}
```

**UI Components**
```json
{
  "ngx-monaco-editor": "^20.0.0",
  "ngx-charts": "^21.0.0",
  "date-fns": "^4.1.0",
  "diff": "^7.0.0"
}
```

**Testing & Quality**
```json
{
  "jasmine-core": "~5.4.0",
  "karma": "~6.4.0",
  "cypress": "^14.0.0",
  "@typescript-eslint/eslint-plugin": "^8.0.0",
  "prettier": "^3.4.0"
}
```

---

## 3. Development Phases

### Phase 1: Foundation Setup (Weeks 1-3)

#### Week 1: Project Initialization
- [x] Repository setup with Git
- [x] Docker Compose configuration
  - MongoDB service
  - Redis service
  - Backend service (Python/FastAPI)
  - Frontend service (Angular/Nginx)
  - Volume mounts for persistence
- [x] Environment variable documentation (.env.example)
- [x] Basic FastAPI application structure
- [x] Angular project scaffolding with Material
- [x] CI/CD pipeline configuration (optional)

#### Week 2: Database & Core Infrastructure
- [x] MongoDB schema design and indexes
- [x] Database connection management (connection pooling)
- [x] Structured logging setup
- [x] Error handling framework
- [x] API versioning structure (/api/v1/)
- [x] Standardized response format
- [x] CORS configuration
- [x] Security headers middleware

#### Week 3: Authentication System
- [x] User model with roles
- [x] Password hashing (bcrypt)
- [x] JWT token generation and validation
- [x] Session management
- [x] Login endpoint
- [x] Onboarding flow (first admin creation)
- [x] Role-based access control middleware
- [x] Angular auth service and guards
- [x] Login page UI
- [x] Token storage and HTTP interceptor

### Phase 2: User Management & Profile (Weeks 4-5)

#### Week 4: User CRUD Operations
- [x] User CRUD API endpoints
- [x] User list/create/update/delete
- [x] Role assignment
- [x] Admin panel - user management UI
- [x] User table with filtering/sorting
- [x] User creation dialog
- [x] Role management UI

#### Week 5: User Profile & 2FA
- [x] User profile API endpoints
  - Password change
  - Email update
  - Timezone settings
  - Session management
- [x] 2FA implementation
  - TOTP setup (pyotp)
  - QR code generation
  - Backup codes
  - Device trust mechanism
- [x] User profile UI
  - Profile settings page
  - 2FA setup dialog
  - Active sessions viewer
  - Login history

### Phase 3: Automation Module - Core (Weeks 6-9)

#### Week 6: Webhook Infrastructure
- [x] Webhook receiver endpoints
- [x] Webhook signature validation (HMAC-SHA256)
- [x] IP whitelisting
- [x] Webhook deduplication (Redis-based)
- [x] Webhook history storage
- [x] Webhook inspector UI
  - Real-time webhook viewer
  - Filter/search functionality
  - Payload viewer with syntax highlighting
  - Copy/save/replay actions

#### Week 7: Workflow Engine - Data Layer
- [x] Workflow model and schema
- [x] Workflow CRUD API endpoints
- [x] Workflow list/create/update/delete
- [x] Workflow status management (enabled/disabled/draft)
- [x] Sharing permissions
- [x] Bulk operations API
- [x] Workflow import/export

#### Week 8: Workflow Engine - Filter System
- [x] Filter evaluation engine
  - String operations
  - Numeric operations
  - Boolean operations
  - List operations
- [x] Filter chaining with AND/OR logic
- [x] Secondary filters (API data)
- [x] Filter testing utilities
- [x] Workflow filtering UI component

#### Week 9: Workflow Engine - Action System
- [x] Mist API service wrapper (using mistapi)
- [x] Action executor service
  - API GET actions
  - API POST/PUT/DELETE actions
  - Variable substitution
  - Conditional logic (if-then-else)
- [x] Action sequencing
- [x] Error handling and retry logic
- [x] Rate limiting for Mist API
- [x] Concurrent modification protection (distributed locking)

### Phase 4: Automation Module - Advanced (Weeks 10-12)

#### Week 10: Task Scheduling
- [x] APScheduler integration
- [x] Cron expression parsing
- [x] Timezone handling for schedules
- [x] Missed execution policy
- [x] Concurrent execution handling
- [x] Cron workflow executor
- [x] Schedule management UI
  - Visual cron builder
  - Next execution preview
  - Timezone selector

#### Week 11: Workflow Execution & Queue
- [x] Execution queue management (FIFO)
- [x] Concurrent workflow limits
- [x] Workflow timeout handling
- [x] Execution history logging
- [x] Execution status tracking
- [x] Dead letter queue for failures
- [x] Execution dashboard UI
  - Active workflows display
  - Recent executions table
  - Execution details viewer

#### Week 12: Workflow Testing & UI Polish
- [x] Workflow test mode
  - Custom payload input
  - Saved webhook replay
  - Dry run execution
  - Step-by-step log display
- [x] Workflow payload library
  - Save from production
  - Replay capability
  - Payload management
- [x] Workflow editor UI
  - Workflow creation wizard (stepper)
  - Trigger configuration
  - Filter builder
  - Action builder
  - Test mode interface
- [x] Smee.io proxy integration
  - Configuration UI
  - Proxy status indicators
  - Security warnings

### Phase 5: Backup Module - Core (Weeks 13-15)

#### Week 13: Backup Infrastructure
- [x] Backup object model
- [x] Full backup service
  - Fetch all Mist config objects
  - Store with metadata
  - Schedule configuration
- [x] Audit webhook listener
  - Create/update/delete detection
  - Incremental backup logic
- [x] Storage abstraction layer (local/Git)

#### Week 14: Git Integration
- [x] Git service implementation
  - Repository initialization
  - Commit creation with metadata
  - Push with retry logic
  - Branch management
- [x] Commit message formatting
- [x] Error handling and alerts
- [x] Git configuration UI
  - Provider selection (GitHub/GitLab)
  - Repository settings
  - Connection testing

#### Week 15: Restore Functionality
- [x] Restore service
  - Version restoration
  - Deleted object restoration
  - UUID regeneration handling
  - Reference resolution logic
  - Dry run/preview mode
- [x] Backup configuration API
  - Retention policies
  - Schedule management
  - Storage strategy selection

### Phase 6: Backup Module - UI (Weeks 16-17)

#### Week 16: Backup UI - Main Views
- [x] Backup timeline component
  - Visual timeline rendering
  - Interactive zoom/pan
  - Event filtering
  - Click-to-filter integration
- [x] Object list table
  - Column configuration
  - Search and filtering
  - Status badges
  - Quick actions
  - Pagination

#### Week 17: Backup UI - Object Details
- [x] Object detail view
  - Object timeline (specific object)
  - Object information card
  - Version history table
- [x] Version comparison
  - Two-version selector
  - Side-by-side diff viewer
  - JSON path navigation
  - Syntax highlighting
- [x] Restore dialogs
  - Dry run preview
  - Confirmation dialogs
  - Reference update preview

### Phase 7: Integrations & Admin (Weeks 18-19)

#### Week 18: External Integrations
- [x] Notification service
  - Slack integration
  - ServiceNow integration
  - PagerDuty integration
  - Generic HTTPS POST
- [x] Integration configuration UI
  - Credential management
  - Test functionality
  - Message template builder

#### Week 19: Admin Panel
- [x] Mist API configuration
  - Organization ID
  - API token (encrypted storage)
  - Cloud region selector
  - Connection validation
- [x] System settings
  - Webhook configuration
  - Execution limits
  - Timeout settings
  - Retention policies
- [x] Application audit trail
  - Audit log viewer
  - Search and filtering
  - Immutable log storage
- [x] Health check endpoint
  - Basic health status
  - Component status (future)

### Phase 8: Testing & Deployment (Week 20)

#### Week 20: Testing & Documentation
- [x] Unit test writing
  - Backend: >80% coverage
  - Frontend: Critical flows
- [x] Integration tests
  - API endpoint testing
  - Workflow execution tests
  - Backup/restore tests
- [x] Security testing
  - OWASP Top 10 verification
  - Dependency scanning
  - Input validation testing
  - XSS prevention testing
- [x] Performance testing
  - Load testing
  - Database query optimization
- [x] Documentation
  - API documentation (Swagger)
  - User guide
  - Deployment guide
  - Architecture documentation
- [x] Final deployment preparation
  - Production environment setup
  - Monitoring and alerting
  - Disaster recovery testing

---

## 4. Database Design

### 4.1 Collections/Tables

#### users
```javascript
{
  _id: ObjectId,
  email: String (unique, indexed),
  password_hash: String,
  roles: [String],  // ['admin', 'automation', 'backup']
  timezone: String,  // e.g., "America/Los_Angeles"
  totp_secret: String?,
  totp_enabled: Boolean,
  backup_codes: [String],
  created_at: DateTime,
  updated_at: DateTime,
  last_login: DateTime?,
  is_active: Boolean
}
```

**Indexes**:
- `email`: unique index
- `is_active`: index for filtering active users

#### user_sessions
```javascript
{
  _id: ObjectId,
  user_id: ObjectId (indexed),
  token_jti: String (unique, indexed), // JWT ID for revocation
  device_info: {
    browser: String,
    os: String,
    ip_address: String
  },
  trusted_device: Boolean,
  created_at: DateTime,
  last_activity: DateTime (indexed),
  expires_at: DateTime (indexed, TTL)
}
```

**Indexes**:
- `user_id`: index
- `token_jti`: unique index
- `expires_at`: TTL index for auto-cleanup

#### workflows
```javascript
{
  _id: ObjectId,
  name: String (indexed for search),
  description: String,
  created_by: ObjectId,
  created_at: DateTime,
  updated_at: DateTime,
  status: String,  // 'enabled', 'disabled', 'draft'
  sharing: String,  // 'private', 'read-only', 'read-write'
  timeout_seconds: Number,
  trigger: {
    type: String,  // 'webhook', 'cron'
    webhook_type: String?,  // 'alarm', 'audit', 'event', etc.
    cron_expression: String?,
    timezone: String?,
    skip_if_running: Boolean?
  },
  filters: [{
    field: String,
    operator: String,
    value: Mixed,
    source: String  // 'webhook', 'api_result'
  }],
  actions: [{
    type: String,  // 'api_get', 'api_post', etc.
    endpoint: String,
    parameters: Object,
    save_as: String?,
    on_failure: String,
    condition: Object?  // For if-then-else
  }],
  notifications: [{
    type: String,  // 'slack', 'servicenow', etc.
    config: Object,
    message_template: String
  }]
}
```

**Indexes**:
- `name`: text index for search
- `created_by`: index
- `status`: index
- `(status, created_by)`: compound index

#### workflow_executions
```javascript
{
  _id: ObjectId,
  workflow_id: ObjectId (indexed),
  executed_at: DateTime (indexed, descending),
  trigger_data: Object,
  trigger_source: String,  // 'webhook', 'cron', 'manual'
  filter_results: [{
    filter_index: Number,
    passed: Boolean,
    actual_value: Mixed
  }],
  actions_taken: [{
    action_index: Number,
    status: String,  // 'success', 'failed', 'skipped'
    result: Object,
    error: String?
  }],
  status: String,  // 'success', 'failed', 'partial', 'timeout'
  error_message: String?,
  duration_ms: Number,
  timed_out: Boolean
}
```

**Indexes**:
- `workflow_id`: index
- `executed_at`: descending index
- `(workflow_id, executed_at)`: compound index

#### backup_objects
```javascript
{
  _id: ObjectId,
  org_id: String (indexed),
  site_id: String? (sparse index),
  scope: String,  // 'org', 'site'
  object_type: String (indexed),  // 'wlan', 'site', 'template', etc.
  object_uuid: String (indexed),
  object_name: String,
  version: Number,
  status: String (indexed),  // 'current', 'old_version', 'deleted'
  data: Object,  // Full configuration JSON
  metadata: {
    admin_name: String,
    admin_email: String,
    change_type: String,  // 'created', 'updated', 'deleted', 'restored'
    timestamp: DateTime
  },
  git_commit_sha: String?,
  previous_version_id: ObjectId?,
  created_at: DateTime (indexed)
}
```

**Indexes**:
- `org_id`: index
- `site_id`: sparse index
- `object_uuid`: index
- `object_type`: index
- `status`: index
- `created_at`: index
- `(org_id, object_type, status)`: compound index
- `(object_uuid, version)`: compound index

#### webhook_history
```javascript
{
  _id: ObjectId,
  received_at: DateTime (indexed, descending, TTL),
  webhook_type: String (indexed),
  source: String,  // 'mist', 'smee'
  headers: Object,
  payload: Object,
  validation_status: String,  // 'valid', 'invalid', 'skipped'
  processing_status: String,  // 'queued', 'processing', 'completed', 'failed'
  matched_workflows: [ObjectId],
  saved_for_testing: Boolean,
  error_message: String?
}
```

**Indexes**:
- `received_at`: descending index with TTL
- `webhook_type`: index
- `(webhook_type, received_at)`: compound index
- `saved_for_testing`: index for quick filtering

#### app_configuration
```javascript
{
  _id: ObjectId,
  backup_config: {
    max_versions: Number,
    max_age_days: Number,
    full_backup_schedule: String,
    storage_strategy: String,  // 'local', 'github', 'gitlab'
    git_config: {
      provider: String,
      repo_url: String,
      branch: String,
      token: String  // Encrypted
    }
  },
  mist_config: {
    org_id: String,
    api_token: String,  // Encrypted
    api_endpoint: String
  },
  notification_config: {
    slack: Object,
    servicenow: Object,
    pagerduty: Object
  },
  webhook_config: {
    webhook_secret: String,  // Encrypted
    smee_enabled: Boolean,
    smee_channel_url: String?,
    inspector_retention_days: Number,
    inspector_max_webhooks: Number,
    dedup_window_seconds: Number
  },
  execution_config: {
    max_concurrent_workflows: Number,
    global_max_timeout_seconds: Number,
    session_timeout_hours: Number
  }
}
```

#### audit_logs
```javascript
{
  _id: ObjectId,
  timestamp: DateTime (indexed, descending),
  user_id: ObjectId?,
  user_email: String,
  action: String,  // 'user.create', 'workflow.update', 'restore.execute', etc.
  resource_type: String,  // 'user', 'workflow', 'backup', etc.
  resource_id: String?,
  details: Object,
  ip_address: String,
  user_agent: String
}
```

**Indexes**:
- `timestamp`: descending index
- `user_id`: index
- `action`: index
- `resource_type`: index

### 4.2 Database Indexing Strategy

**Performance Optimization**:
1. All foreign keys indexed
2. Frequently queried fields indexed
3. Compound indexes for common query patterns
4. Text indexes for search functionality
5. TTL indexes for auto-cleanup (sessions, webhook history)
6. Sparse indexes for optional fields

---

## 5. API Design

### 5.1 API Versioning & Standards

**Base URL**: `/api/v1`

**Response Format**:
```javascript
// Success
{
  "success": true,
  "data": { ... },
  "message": "Optional message"
}

// Error
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": { ... }
  }
}

// Paginated
{
  "success": true,
  "data": [...],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 150
  }
}
```

### 5.2 API Endpoints

#### Authentication
```
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
POST   /api/v1/auth/refresh
POST   /api/v1/auth/onboard              # First admin creation
POST   /api/v1/auth/verify-2fa
POST   /api/v1/auth/setup-2fa
POST   /api/v1/auth/disable-2fa
GET    /api/v1/auth/me
```

#### Users
```
GET    /api/v1/users                     # List users
POST   /api/v1/users                     # Create user
GET    /api/v1/users/:id
PUT    /api/v1/users/:id
DELETE /api/v1/users/:id
GET    /api/v1/users/:id/sessions        # List user sessions
DELETE /api/v1/users/:id/sessions/:sid   # Delete specific session
```

#### User Profile
```
GET    /api/v1/profile
PUT    /api/v1/profile
PUT    /api/v1/profile/password
PUT    /api/v1/profile/timezone
GET    /api/v1/profile/sessions
DELETE /api/v1/profile/sessions/:id
```

#### Workflows
```
GET    /api/v1/workflows                 # List workflows
POST   /api/v1/workflows                 # Create workflow
GET    /api/v1/workflows/:id
PUT    /api/v1/workflows/:id
DELETE /api/v1/workflows/:id
PATCH  /api/v1/workflows/:id/status      # Enable/disable
POST   /api/v1/workflows/:id/test        # Test workflow
POST   /api/v1/workflows/:id/execute     # Manual execution
POST   /api/v1/workflows/bulk-enable     # Bulk enable
POST   /api/v1/workflows/bulk-disable    # Bulk disable
POST   /api/v1/workflows/bulk-delete     # Bulk delete
POST   /api/v1/workflows/import
GET    /api/v1/workflows/:id/export
```

#### Workflow Executions
```
GET    /api/v1/executions                # List all executions
GET    /api/v1/workflows/:id/executions  # List workflow executions
GET    /api/v1/executions/:id            # Execution details
```

#### Webhooks
```
POST   /api/v1/webhooks/mist             # Webhook receiver
GET    /api/v1/webhooks/history          # Webhook history
GET    /api/v1/webhooks/history/:id
POST   /api/v1/webhooks/history/:id/replay
POST   /api/v1/webhooks/history/:id/save
DELETE /api/v1/webhooks/history/:id
```

#### Backups
```
GET    /api/v1/backups                   # List backup objects
GET    /api/v1/backups/:object_uuid      # Object versions
GET    /api/v1/backups/:object_uuid/versions/:version
POST   /api/v1/backups/full              # Trigger full backup
GET    /api/v1/backups/timeline          # Get timeline data
POST   /api/v1/backups/restore           # Restore object
POST   /api/v1/backups/restore/preview   # Dry run
GET    /api/v1/backups/compare           # Compare versions
```

#### Admin - Configuration
```
GET    /api/v1/admin/config
PUT    /api/v1/admin/config/mist
PUT    /api/v1/admin/config/backup
PUT    /api/v1/admin/config/notifications
PUT    /api/v1/admin/config/webhooks
PUT    /api/v1/admin/config/execution
POST   /api/v1/admin/config/mist/test    # Test Mist connection
```

#### Admin - System
```
GET    /api/v1/admin/audit-logs
GET    /api/v1/admin/system-health
GET    /api/v1/admin/metrics
```

#### Health
```
GET    /api/v1/health                    # Basic health check
```

---

## 6. Security Implementation

### 6.1 OWASP Top 10 Protection Checklist

#### 1. Broken Access Control
- [x] Implement role-based middleware
- [x] Verify user ID from JWT matches resource owner
- [x] Check permissions on every API endpoint
- [x] Default deny approach
- [x] Angular route guards for frontend protection

#### 2. Cryptographic Failures
- [x] Encrypt API tokens in database (AES-256)
- [x] Hash passwords with bcrypt (cost factor 12)
- [x] Store encryption keys in environment variables
- [x] HTTPS/TLS only (enforce in production)
- [x] Secure cookie flags (HttpOnly, Secure, SameSite)

#### 3. Injection
- [x] Use Pydantic for input validation
- [x] Use pymongo with parameterized queries
- [x] Never use eval() or exec()
- [x] Sanitize all user inputs
- [x] Validate webhook signatures

#### 4. Insecure Design
- [x] Threat modeling documented
- [x] Principle of least privilege
- [x] Rate limiting on sensitive endpoints
- [x] Session timeout enforcement

#### 5. Security Misconfiguration
- [x] No default credentials
- [x] Minimal error messages in production
- [x] Security headers configured
- [x] Disable debug mode in production
- [x] Remove unused dependencies

#### 6. Vulnerable Components
- [x] Regular pip-audit and npm audit
- [x] Dependency review process
- [x] Keep dependencies updated
- [x] Automated security scanning in CI

#### 7. Authentication Failures
- [x] Strong password requirements
- [x] 2FA support (TOTP)
- [x] Rate limiting on login (5 attempts/15 min)
- [x] Secure session management
- [x] Token expiration and refresh

#### 8. Software and Data Integrity
- [x] Webhook signature validation
- [x] Audit logging for all changes
- [x] Git commits for backup integrity
- [x] Verify Mist API responses

#### 9. Logging and Monitoring
- [x] Log all auth events
- [x] Log authorization failures
- [x] Alert on suspicious patterns
- [x] No sensitive data in logs
- [x] Structured logging (JSON)

#### 10. SSRF
- [x] Validate all external URLs
- [x] Allowlist for external APIs
- [x] No user-controlled URL fetching

### 6.2 Security Headers

```python
# FastAPI middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; ..."
    return response
```

### 6.3 Input Validation

**Pydantic Schemas for All Requests**:
```python
from pydantic import BaseModel, EmailStr, Field, validator

class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    roles: list[str] = Field(default_factory=list)
    
    @validator('roles')
    def validate_roles(cls, v):
        allowed_roles = {'admin', 'automation', 'backup'}
        if not all(role in allowed_roles for role in v):
            raise ValueError('Invalid role')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain digit')
        return v
```

### 6.4 XSS Prevention (Angular)

```typescript
// Use Angular templates (auto-escaping)
// Avoid innerHTML unless absolutely necessary
// Use DomSanitizer when needed

import { DomSanitizer } from '@angular/platform-browser';

constructor(private sanitizer: DomSanitizer) {}

safeHtml(html: string) {
  return this.sanitizer.sanitize(SecurityContext.HTML, html);
}
```

---

## 7. Testing Strategy

### 7.1 Backend Testing

#### Unit Tests (pytest)
```python
# tests/unit/test_filters.py
def test_string_equals_filter():
    filter_config = {"field": "name", "operator": "equals", "value": "test"}
    data = {"name": "test"}
    result = evaluate_filter(filter_config, data)
    assert result is True

# tests/unit/test_auth.py
def test_password_hashing():
    password = "TestPassword123!"
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)
```

#### Integration Tests
```python
# tests/integration/test_workflows.py
@pytest.mark.asyncio
async def test_create_workflow(async_client, auth_headers):
    workflow_data = {
        "name": "Test Workflow",
        "trigger": {"type": "webhook", "webhook_type": "alarm"},
        "filters": [],
        "actions": []
    }
    response = await async_client.post(
        "/api/v1/workflows",
        json=workflow_data,
        headers=auth_headers
    )
    assert response.status_code == 201
    assert response.json()["success"] is True
```

**Target Coverage**: 80%+

### 7.2 Frontend Testing

#### Unit Tests (Jasmine/Karma)
```typescript
describe('WorkflowService', () => {
  it('should fetch workflows', () => {
    service.getWorkflows().subscribe(workflows => {
      expect(workflows.length).toBeGreaterThan(0);
    });
  });
});
```

#### E2E Tests (Cypress)
```javascript
describe('Workflow Creation', () => {
  it('should create a new workflow', () => {
    cy.login('admin@test.com', 'password');
    cy.visit('/workflows/new');
    cy.get('input[name="name"]').type('Test Workflow');
    cy.get('button[type="submit"]').click();
    cy.url().should('include', '/workflows');
  });
});
```

### 7.3 Security Testing

1. **Dependency Scanning**:
   ```bash
   pip-audit
   npm audit
   ```

2. **Input Validation Testing**:
   - SQL/NoSQL injection attempts
   - XSS payload testing
   - Command injection attempts

3. **Authentication Testing**:
   - Brute force attempts
   - Token expiration validation
   - 2FA bypass attempts

4. **OWASP Top 10 Verification**:
   - Manual checklist review
   - Automated scanning tools (Bandit, Safety)

---

## 8. Deployment Strategy

### 8.1 Docker Compose Configuration

```yaml
version: '3.8'

services:
  mongodb:
    image: mongo:8.0
    container_name: mist_automation_db
    environment:
      MONGO_INITDB_ROOT_USERNAME: ${MONGO_USER}
      MONGO_INITDB_ROOT_PASSWORD: ${MONGO_PASSWORD}
    volumes:
      - mongodb_data:/data/db
    ports:
      - "27017:27017"
    networks:
      - mist_network

  redis:
    image: redis:7-alpine
    container_name: mist_automation_redis
    volumes:
      - redis_data:/data
    networks:
      - mist_network

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: mist_automation_backend
    environment:
      - MONGODB_URL=mongodb://${MONGO_USER}:${MONGO_PASSWORD}@mongodb:27017
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
    depends_on:
      - mongodb
      - redis
    volumes:
      - ./backend:/app
      - backup_data:/backups
    ports:
      - "8000:8000"
    networks:
      - mist_network

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: mist_automation_frontend
    depends_on:
      - backend
    ports:
      - "80:80"
    networks:
      - mist_network

volumes:
  mongodb_data:
  redis_data:
  backup_data:

networks:
  mist_network:
    driver: bridge
```

### 8.2 Environment Variables

Create `.env` file:
```bash
# Database
MONGO_USER=mistadmin
MONGO_PASSWORD=<strong-password>
MONGODB_URL=mongodb://mistadmin:<strong-password>@mongodb:27017
REDIS_URL=redis://redis:6379

# Security
JWT_SECRET_KEY=<random-256-bit-key>
ENCRYPTION_KEY=<random-256-bit-key>
SESSION_TIMEOUT_HOURS=24

# Mist Configuration
MIST_ORG_ID=
MIST_API_TOKEN=
MIST_API_ENDPOINT=https://api.mist.com

# Webhook Configuration
WEBHOOK_SECRET=<strong-secret>
SMEE_CHANNEL_URL=  # Optional for development

# Execution Configuration
MAX_CONCURRENT_WORKFLOWS=10
GLOBAL_MAX_TIMEOUT_SECONDS=300

# Git Configuration (optional)
GIT_PROVIDER=  # github or gitlab
GIT_REPO_URL=
GIT_TOKEN=
GIT_BRANCH=main

# Logging
LOG_LEVEL=INFO

# Frontend
API_BASE_URL=http://backend:8000/api/v1
```

### 8.3 Backend Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Run with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.4 Frontend Dockerfile

```dockerfile
# Build stage
FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build --prod

# Production stage
FROM nginx:alpine

COPY --from=build /app/dist/mist-automation /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 8.5 Nginx Configuration

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # Frontend routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Increase upload size for workflow imports
    client_max_body_size 10M;
}
```

---

## 9. Code Quality Standards

### 9.1 Python Code Style

**Use Black for formatting**:
```bash
black backend/app --line-length 100
```

**Use Flake8 for linting**:
```bash
flake8 backend/app --max-line-length=100
```

**Use MyPy for type checking**:
```bash
mypy backend/app --strict
```

**Example Code Structure**:
```python
"""Workflow service module.

This module provides business logic for workflow management.
"""
from typing import Optional, List
from datetime import datetime

from app.models.workflow import Workflow
from app.core.exceptions import WorkflowNotFoundError


class WorkflowService:
    """Service for managing workflows."""
    
    def __init__(self, db_client):
        """Initialize workflow service.
        
        Args:
            db_client: Database client instance
        """
        self.db = db_client
    
    async def create_workflow(
        self,
        name: str,
        created_by: str,
        **kwargs
    ) -> Workflow:
        """Create a new workflow.
        
        Args:
            name: Workflow name
            created_by: User ID of creator
            **kwargs: Additional workflow configuration
            
        Returns:
            Created workflow object
            
        Raises:
            ValueError: If name is invalid
        """
        # Validate input
        if not name or len(name) < 3:
            raise ValueError("Workflow name must be at least 3 characters")
        
        # Create workflow
        workflow_data = {
            "name": name,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
            **kwargs
        }
        
        # Store in database
        result = await self.db.workflows.insert_one(workflow_data)
        workflow_data["_id"] = result.inserted_id
        
        return Workflow(**workflow_data)
```

### 9.2 TypeScript Code Style

**Use Prettier for formatting**:
```json
{
  "printWidth": 100,
  "tabWidth": 2,
  "singleQuote": true,
  "trailingComma": "es5",
  "arrowParens": "avoid"
}
```

**Use ESLint**:
```json
{
  "extends": [
    "eslint:recommended",
    "@angular-eslint/recommended"
  ],
  "rules": {
    "@typescript-eslint/naming-convention": ["error"]
  }
}
```

**Example Component**:
```typescript
import { Component, OnInit } from '@angular/core';
import { WorkflowService } from '@app/core/services/workflow.service';
import { Workflow } from '@app/shared/models/workflow.model';

/**
 * Workflow list component.
 * Displays all workflows with filtering and sorting.
 */
@Component({
  selector: 'app-workflow-list',
  templateUrl: './workflow-list.component.html',
  styleUrls: ['./workflow-list.component.scss']
})
export class WorkflowListComponent implements OnInit {
  workflows: Workflow[] = [];
  loading = false;
  
  constructor(private workflowService: WorkflowService) {}
  
  ngOnInit(): void {
    this.loadWorkflows();
  }
  
  /**
   * Load workflows from API.
   */
  loadWorkflows(): void {
    this.loading = true;
    this.workflowService.getWorkflows().subscribe({
      next: workflows => {
        this.workflows = workflows;
        this.loading = false;
      },
      error: err => {
        console.error('Failed to load workflows', err);
        this.loading = false;
      }
    });
  }
}
```

---

## 10. Monitoring & Operations

### 10.1 Logging Strategy

**Structured Logging with structlog**:
```python
import structlog

logger = structlog.get_logger()

# Log with context
logger.info(
    "workflow_executed",
    workflow_id=workflow.id,
    execution_time_ms=duration,
    status="success"
)

# Log errors with full context
logger.error(
    "mist_api_error",
    endpoint="/api/v1/orgs",
    status_code=429,
    error="Rate limit exceeded",
    exc_info=True
)
```

**Log Levels**:
- DEBUG: Detailed information for debugging
- INFO: General informational messages
- WARNING: Warning messages (non-critical issues)
- ERROR: Error messages (failures that don't crash)
- CRITICAL: Critical errors (system failures)

### 10.2 Alerting

**Alert on**:
1. Workflow execution failures (3+ in 1 hour)
2. Backup failures
3. Mist API connectivity issues
4. Git push failures
5. Database connection issues
6. Storage capacity warnings

**Notification Channels**:
- In-app notifications (toast messages)
- Slack alerts to admin channel
- Email (future enhancement)

---

## 11. Risk Assessment & Mitigation

### 11.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Mist API rate limiting | High | Medium | Implement rate limiting, queuing, and backoff |
| Git repository size growth | Medium | High | Configure retention policies, monitor size |
| MongoDB performance degradation | High | Medium | Proper indexing, query optimization |
| Webhook deduplication failures | Medium | Low | Use Redis for distributed dedup |
| Concurrent workflow conflicts | Medium | Medium | Distributed locking for object modifications |

### 11.2 Security Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQL/NoSQL injection | Critical | Pydantic validation, parameterized queries |
| XSS attacks | High | Angular's built-in protection, CSP headers |
| Broken authentication | Critical | JWT with expiration, 2FA, rate limiting |
| Data breach (API tokens) | Critical | Encryption at rest, secure key management |
| SSRF attacks | Medium | URL validation, allowlisting |

---

## 12. Success Metrics

### 12.1 Performance Metrics

- API response time < 200ms (p95)
- Workflow execution < 30s average
- Full backup completion < 30 minutes
- UI page load < 2 seconds

### 12.2 Reliability Metrics

- Uptime: 99.5%+
- Webhook processing success rate: 99%+
- Backup success rate: 99%+
- Zero critical security vulnerabilities

### 12.3 Code Quality Metrics

- Test coverage: >80%
- Zero critical linting errors
- All dependencies up-to-date
- Documentation coverage: 100% of public APIs

---

## 13. Next Steps

### Immediate Actions (Week 1)

1. **Repository Setup**
   - [ ] Initialize Git repository
   - [ ] Set up branch protection rules
   - [ ] Configure .gitignore

2. **Development Environment**
   - [ ] Install Docker and Docker Compose
   - [ ] Set up Python virtual environment
   - [ ] Install Node.js and Angular CLI
   - [ ] Create .env.example file

3. **Project Structure**
   - [ ] Create directory structure
   - [ ] Set up FastAPI application skeleton
   - [ ] Set up Angular application
   - [ ] Configure Docker Compose

4. **Documentation**
   - [ ] Create README.md
   - [ ] Document setup instructions
   - [ ] Create CONTRIBUTING.md

### Phase Progression

- Follow the week-by-week plan outlined in Section 3
- Weekly code reviews and testing
- Security audit at end of each phase
- User acceptance testing before production

---

## 14. Appendix

### 14.1 Useful Commands

**Backend**:
```bash
# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest tests/ -v --cov=app --cov-report=html

# Format code
black app/

# Lint code
flake8 app/

# Security scan
bandit -r app/ -ll

# Dependency audit
pip-audit
```

**Frontend**:
```bash
# Run development server
ng serve

# Build for production
ng build --configuration production

# Run tests
ng test

# Run E2E tests
ng e2e

# Lint
ng lint

# Format
npx prettier --write "src/**/*.{ts,html,scss}"
```

**Docker**:
```bash
# Build and start all services
docker-compose up --build

# Stop all services
docker-compose down

# View logs
docker-compose logs -f backend

# Execute command in container
docker-compose exec backend bash
```

### 14.2 References

- [mistapi Documentation](https://pypi.org/project/mistapi/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Angular Material Documentation](https://material.angular.io/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Mist API Documentation](https://api.mist.com/api/v1/docs/)

---

**Document Version**: 1.0  
**Last Updated**: March 7, 2026  
**Author**: Development Team
