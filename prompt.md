# Tool description

A comprehensive web application for automating Juniper Mist operations and managing configuration backups with version control and restore capabilities.

# Application Overview

This application consists of two main modules:

## 1. Automation Module
A workflow automation engine that responds to Mist webhooks or scheduled (cron) events to execute conditional actions on Mist infrastructure, with optional integration to external platforms (Slack, ServiceNow, PagerDuty).

## 2. Backup & Restore Module
An intelligent configuration backup system that maintains versioned snapshots of Mist configuration objects, tracks changes via audit webhooks, and provides granular restore capabilities with automatic reference resolution.

# Requirements

## Core Functional Requirements

### 1. Authentication & Authorization System

#### Onboarding Process
- **First-time setup**: On initial deployment, the application must guide the user through creating the first administrator account
- **Bootstrap protection**: Prevent multiple admin creation if an admin already exists
- **Secure credential handling**: Hash passwords using industry-standard algorithms (bcrypt/argon2)

#### User Management
- **User CRUD operations**: Admin role can create, read, update, and delete user accounts
- **Role assignment**: Support multi-role assignment per user
- **Role definitions**:
  - `admin`: Full access to application configuration, user management, and all modules
  - `automation`: Access to view, create, edit, and manage automation workflows
  - `backup`: Access to view backup history and perform restore operations

#### User Profile & Security
- **User Profile Settings**:
  - Change password (with current password verification)
  - Update email address
  - Set timezone preference (used for cron schedule display and execution)
    - Timezone selector with common zones
    - Preview of current time in selected timezone
  - View login history
  - Manage active sessions
  
- **Two-Factor Authentication (2FA)**:
  - Enable/disable 2FA for account
  - TOTP-based (Time-based One-Time Password) using apps like Google Authenticator, Authy
  - QR code generation for easy setup
  - Backup codes generation (store securely)
  - Require 2FA code at login if enabled
  - Option to trust device for 30 days
  
- **Session Management**:
  - View all active sessions (device, browser, IP, last active time)
  - Log out from specific sessions
  - "Log out from all other devices" option
  - Current session indicator

#### Session Management
- **JWT-based authentication**: Use tokens for API authentication
- **Session timeout**: 24 hours (configurable by admin in system settings)
- **Refresh token mechanism**: Allow token renewal without re-authentication
- **Concurrent sessions**: Users can log in from multiple devices simultaneously
  - Track all active sessions per user
  - Allow users to view and terminate specific sessions
  - Session tracking: device type, browser, IP address, last activity timestamp
- **No "Remember Me"**: Standard session timeout applies to all sessions

---

### 2. Automation Module

#### 2.1 Workflow Management

**Workflow Creation & Configuration**
- Users with `automation` or `admin` role can create workflows
- Each workflow consists of:
  1. **Trigger**: Event that initiates the workflow
  2. **Filters**: One or more conditional filters applied to event data
  3. **Actions**: Sequential or parallel actions to execute if filters pass
  4. **Notifications**: Optional external notifications (Slack, ServiceNow, PagerDuty)

**Workflow States**
- `enabled`: Workflow is active and will execute on trigger
- `disabled`: Workflow is inactive and will not execute
- `draft`: Workflow is being created/edited

**Workflow Sharing**
- Workflows can be configured with sharing permissions:
  - `private`: Only the creator and admins can view/edit
  - `read-only`: All users with automation role can view but not edit
  - `read-write`: All users with automation role can view and edit

#### 2.2 Trigger Configuration

**Webhook Triggers**
- Listen for incoming Mist webhooks on dedicated endpoints
- Support all Mist webhook types:
  - Alarm webhooks (e.g., `ap_offline`, `switch_offline`, `gateway_offline`)
  - Audit webhooks (configuration changes)
  - Device events
  - Client events
  - Asset events
  
**Scheduled Triggers**
- Cron-based scheduling using standard cron syntax
- Support common presets (daily, weekly, monthly, hourly)
- Visual cron expression builder in UI
- **Timezone Handling**:
  - Cron schedules execute based on workflow creator's timezone setting
  - Display next execution time in user's current timezone
  - Store schedule in UTC internally, convert for display
  - Show timezone indicator (e.g., "Every day at 9:00 AM PST")
- **Missed Execution Policy**: 
  - Skip missed executions if server was down during scheduled time
  - Do NOT run catch-up executions
  - Wait for next scheduled time
  - Log missed execution with reason
- **Concurrent Execution Handling**:
  - Allow concurrent executions of the same cron job if previous execution still running
  - Use multiprocessing/threading to handle parallel executions
  - Track concurrent execution count per workflow
  - Option to prevent concurrent runs (configurable per workflow: "Skip if already running")

**Webhook Forwarding**
- Option to simply forward raw webhook payload to external systems without processing
- Support multiple simultaneous forwarding destinations

#### 2.3 Filter System

**Primary Filters** (Applied to webhook payload or scheduled event)
- **Field-based filtering**: Extract and compare fields from webhook payload
  - String operations: `equals`, `contains`, `starts_with`, `ends_with`, `regex`
  - Numeric operations: `equals`, `greater_than`, `less_than`, `between`
  - Boolean operations: `is_true`, `is_false`
  - List operations: `in_list`, `not_in_list`
  
- **Example filters**:
  - `event.type == "ap_offline"`
  - `device.name starts_with "XYZ"`
  - `alarm.severity in ["critical", "major"]`
  - `site_id == "abc123"`

**Secondary Filters** (Applied to data retrieved via API calls)
- Same filtering capabilities as primary filters
- Can reference both original webhook data and newly retrieved data
- Support for compound conditions (AND/OR logic)

**Filter Chaining**
- Multiple filters combined with logical operators
- Support for nested filter groups
- All filters must pass (AND logic) unless OR groups are specified

#### 2.4 Action System

**API Retrieval Actions** (Using mistapi Python package)
- Fetch device statistics
- Retrieve device events
- Get alarm history
- Query device inventory
- Fetch site information
- Get client sessions
- Any GET operation supported by mistapi

**API Modification Actions**
- Device operations:
  - Reboot device
  - Unassign device
  - Assign device to site
  - Update device configuration
  - Delete device
  - Claim devices
  
- Configuration operations:
  - Update site settings
  - Modify WLAN configuration
  - Update network templates
  - Modify RF templates
  
- Any POST/PUT/DELETE operation supported by mistapi

**Action Sequencing**
- Actions execute in defined order
- Option to stop workflow on action failure or continue
- Ability to use data from previous actions in subsequent actions
- **Variable Substitution**: Support template variables using `{{variable_name}}` syntax
  - From webhook payload: `{{event.device.name}}`, `{{alarm.severity}}`
  - From API responses: `{{device_stats.uptime}}`, `{{site.name}}`
  - From workflow context: `{{workflow.name}}`, `{{execution.timestamp}}`
  - Environment variables: `{{env.org_id}}`, `{{env.api_token}}`

**Conditional Logic**
- **If-Then-Else Actions**: Support conditional action execution
  - Define conditions using same filter syntax
  - Execute different action branches based on condition results
  - Example: "If device offline > 30 minutes, then reboot, else send alert"
  - Nested conditions supported
  - Multiple condition branches (if-else-if-else)

**External Notifications**
- **Slack Integration**:
  - Webhook URL configuration
  - Custom message templates with variable substitution
  - Support for rich formatting (blocks, attachments)
  
- **ServiceNow Integration**:
  - Instance URL configuration
  - Authentication credentials
  - Incident/ticket creation
  - Custom field mapping
  
- **PagerDuty Integration**:
  - Integration key configuration
  - Alert creation with custom severity
  - Event deduplication keys

- **Generic HTTPS POST**:
  - Custom URL endpoint
  - Custom headers
  - Custom JSON payload with variable substitution

#### 2.5 Workflow Testing & Debugging

- **Test Mode**: Allow users to test workflows before enabling them
  - **Webhook Payload Options**:
    - Manually enter custom JSON payload
    - Select from saved webhook history (see Webhook Inspector below)
    - Use saved sample payloads from production
    - Import from Smee.io channel (if configured)
  - Simulate action execution (dry run - no actual API calls)
  - Display step-by-step execution log showing:
    - Filter evaluation results (pass/fail with values)
    - Variables populated with sample data
    - Actions that would be executed (without executing)
    - Expected notifications
  - Highlight errors and validation issues
  - Save test configurations for reuse

- **Webhook Payload Library**
  - **Save from Production**: Automatically save webhook payloads received in production
    - Configurable retention (e.g., keep last 100 payloads per webhook type)
    - Option to mark specific payloads as "saved for testing"
    - Never expire saved test payloads
  - **Replay Capability**: 
    - Select any saved payload
    - Choose which workflow(s) to test with it
    - Execute in test mode or send to enabled workflows
  - **Payload Management**:
    - Browse saved payloads by type, date, source
    - Search and filter payloads
    - Export/import payloads as JSON
    - Delete old or unnecessary payloads

#### 2.6 Workflow Execution & Monitoring

**Execution Queue Management**
- **Queue Processing**: FIFO (First-In-First-Out) - workflows processed in order received
- **Max Concurrent Workflows**: 
  - Configurable limit set by admin (e.g., 5, 10, 20)
  - Default: 10 concurrent workflows
  - When limit reached, additional workflows queued
  - Queue status visible in dashboard
  
**Workflow Timeouts**
- **Per-Workflow Timeout**: 
  - Configurable during workflow creation/edit
  - Default: 2 minutes
  - Range: 30 seconds to global max
  - Workflow terminated if exceeds timeout
  - Timeout logged as execution failure
  
- **Global Maximum Timeout**: 
  - Admin-configurable system-wide limit
  - Default: 5 minutes
  - Prevents excessively long-running workflows
  - Individual workflow timeouts cannot exceed this limit

**Execution History**
- Log all workflow executions with:
  - Timestamp
  - Trigger source (webhook, cron, manual)
  - Filter results (passed/failed)
  - Actions taken
  - Success/failure status
  - Error messages if applicable
  - Execution duration
  - Timeout indicator if applicable

- **Real-time dashboard**: Display active workflows and recent executions

**Bulk Workflow Operations**
- Select multiple workflows (checkbox selection)
- Bulk actions:
  - Enable selected workflows
  - Disable selected workflows
  - Delete selected workflows (with confirmation)
  - Export selected workflows
- "Select all" and "Select none" options
- Action confirmation dialogs for destructive operations

#### 2.7 Workflow Import/Export

- **Export Workflows**: Download workflow definitions as JSON files
  - Include all configuration: triggers, filters, actions, notifications
  - Option to export with or without sensitive data (API tokens, secrets)
  - Batch export of multiple workflows
  
- **Import Workflows**: Upload previously exported workflow files
  - Validate structure and compatibility
  - Preview before import
  - Option to modify during import (rename, adjust settings)
  - Import workflows from other instances or organizations

---

### 3. Backup & Restore Module

#### 3.1 Backup Strategy

**Full Backup**
- Scheduled full backup of all Mist configuration objects
- Schedule options:
  - Once a day (specify time)
  - Once a week (specify day and time)
  - Every N days
  - Custom cron expression
  
- Backup includes all configuration objects:
  - Sites
  - WLANs
  - Templates (RF, Network, Switch, Gateway)
  - Policies
  - Webhooks
  - API tokens
  - Organization settings
  - Maps and floor plans
  - Zones
  - Asset filters
  - Any other configuration objects

**Incremental Backup via Audit Webhooks**
- Listen to Mist audit webhooks for real-time change tracking
- **On object creation**:
  - Fetch complete object data via API
  - Store object with metadata:
    - Admin name (who created it)
    - Admin email
    - Timestamp
    - Change type: `created`
    - Version number: 1
    
- **On object update**:
  - Fetch current object data via API
  - Store as new version with metadata:
    - Admin name (who modified it)
    - Admin email
    - Timestamp
    - Change type: `updated`
    - Version number: incremented
    - Diff from previous version (optional)
    
- **On object deletion**:
  - Mark object as deleted (do NOT delete backup records)
  - Store metadata:
    - Admin name (who deleted it)
    - Admin email
    - Timestamp
    - Change type: `deleted`
    - Retain all previous versions

#### 3.2 Storage Strategies

**Local Database Storage** (MongoDB or similar)
- Store configuration objects as JSON documents
- Efficient querying and versioning
- Full-text search capabilities

**Git Repository Storage** (GitHub/GitLab)
- Each object stored as separate JSON file
- Git commits for each change (automatic versioning)
- Commit messages include metadata (admin, timestamp, change type)
- Branch per organization or site
- Git history provides natural versioning
- Benefits: external backup, diff viewing, branch/merge capabilities

**Hybrid Approach**
- Store metadata and references in local database
- Store actual configuration JSON in Git repository
- Best of both worlds: fast querying + version control

**Storage Considerations**
- **No Compression**: Configuration objects stored as plain JSON (uncompressed)
  - Required for effective diff/comparison functionality
  - Enables direct viewing and editing if needed
  - Git itself provides compression for repository storage
- **Storage Quota Warnings**: Alert admins when storage thresholds are reached
  - Local database size exceeds configured threshold (e.g., 10 GB)
  - Git repository size exceeds threshold (e.g., 1 GB)
  - Number of versions approaching retention limit

#### 3.3 Restore Capabilities

**Version Restoration**
- View all versions of a specific object
- Compare versions (side-by-side diff view)
- Restore any previous version by pushing to Mist API
- **Versioning behavior**:
  - Restoring creates a new version (not a rollback of history)
  - Metadata indicates this is a restore operation

**Deleted Object Restoration**
- **UUID Regeneration**: When restoring a deleted object, Mist API assigns a new UUID
- **Reference Resolution**: The application must:
  1. Identify all objects that referenced the old UUID
  2. Fetch current state of those objects
  3. Update references to point to new UUID
  4. Push updated objects back to Mist API
  
- **Example scenario**:
  - A WLAN template (UUID: `old-123`) was deleted
  - Sites A, B, C were using this template (referenced `old-123`)
  - User restores the template → Mist assigns new UUID `new-456`
  - Application automatically updates Sites A, B, C to reference `new-456`

**Batch Restore**
- Restore multiple objects to a specific point in time
- Restore entire site configuration
- Preview changes before applying

#### 3.4 Backup UI Requirements

**Main Backup View**

**Timeline Component** (Top Section)
- Visual timeline showing all configuration changes across all objects
- Interactive timeline with zoom and pan capabilities
- Filter by:
  - Date range
  - Object type
  - Change type (create/update/delete)
  - Admin user
  - Scope (org/site)
- Click on timeline events to filter table below

**Object List Table** (Main Section)
Display summary of backed up objects with columns:
- **Scope**: Organization or Site name
- **Type**: wlan, site, gateway_template, switch_template, rf_template, network_template, etc.
- **Object Name**: Display name of the object (with link to details)
- **Number of Versions**: Count of stored versions for this object
- **Created Date**: When object was first created in Mist
- **Last Update**: Timestamp of most recent change
- **Status**: Current status indicator
  - Badge: `Active` (green) - Current version in Mist
  - Badge: `Deleted` (red) - Object deleted in Mist
- **Actions**: 
  - `Details` - Navigate to object detail view
  - `Revert to Previous` - Quick action to restore previous version (only if not deleted)
  - `Restore` - Restore deleted object (only if deleted)

**Search & Filter**
- Full-text search across object names, types, and UUIDs
- Advanced filters combining multiple criteria
- Saved filter presets
- Quick filters (active objects, deleted objects, recently modified)

---

**Object Detail View** (Separate View)

Accessed by clicking on an object from the main list.

**Timeline Component** (Top Section)
- Visual timeline showing changes for THIS specific object only
- Each point represents a version (created/updated/deleted event)
- Color-coded by change type:
  - Green: Created
  - Blue: Updated
  - Orange: Restored
  - Red: Deleted
- Hover shows metadata: admin name, timestamp, change type

**Object Information Card** (Middle Section)
- Object name, type, UUID
- Current status in Mist
- Total number of versions
- First created by (admin, date)
- Last modified by (admin, date)
- If deleted: deletion info (who, when)

**Version History Table** (Bottom Section)
List all versions with columns:
- **Version Number**: v1, v2, v3, etc. (latest at top)
- **Date & Time**: When this version was created
- **Admin Name**: Who made the change
- **Change Type**: Created / Updated / Deleted / Restored
- **Actions**:
  - `View JSON` - Display raw JSON in viewer
  - `Restore This Version` - Restore this specific version to Mist
  - `Compare` - Select for comparison (enable multi-select)

**Version Comparison Features**
- **Compare to Current**: Button to compare any version with current Mist version
- **Compare Two Versions**: 
  - Checkbox selection to pick two versions
  - Side-by-side JSON diff viewer
  - Highlight additions (green), deletions (red), modifications (yellow)
  - JSON path navigation
  - Expandable/collapsible sections

**Restore Actions**
- **Dry Run Mode**: Preview button that:
  - Shows what will be changed in Mist
  - Identifies any UUID reference updates needed
  - Lists all affected objects
  - Does NOT apply changes
- **Restore Button**: Apply the restore with confirmation dialog
  - Warning if restoring deleted object (will get new UUID)
  - Show list of objects that will be updated (reference resolution)
  - Require confirmation before executing

---

### 4. Admin Configuration Panel

**User Management Section**
- List all users
- Create new users
- Edit user roles
- Deactivate/delete users
- Password reset functionality

**Backup Configuration**
- **Retention Policies**:
  - Maximum number of versions per object (e.g., keep last 50 versions)
  - Maximum age of backups (e.g., delete versions older than 1 year)
  - Automatic cleanup scheduling
  
- **Backup Schedule**:
  - Full backup frequency selector
  - Time window configuration
  - Enable/disable full backups
  
- **Storage Configuration**:
  - Storage strategy selector: `local` / `github` / `gitlab`
  - GitHub configuration:
    - Repository URL
    - Access token
    - Branch name
    - Commit author details
  - GitLab configuration:
    - Repository URL
    - Access token
    - Branch name
    - Commit author details

**Automation Configuration**
- Webhook endpoint configuration
- Webhook secret/authentication
- **Webhook Proxy Configuration** (Smee.io):
  - Enable/Disable webhook proxy toggle
  - Smee.io channel URL input
  - URL validation
  - Connection test button
  - Security warning display
  - Proxy status indicator
- **Webhook Inspector Settings**:
  - Retention period (days or count)
  - Auto-save interesting webhooks (e.g., failures, rare types)
  - Maximum saved payloads per type
- Global timeout settings
- Rate limiting configuration
- Enable/disable modules

**Mist API Configuration**
- **Organization ID**: Mist organization UUID
- **API Token**: User or service account API token (encrypted at rest)
- **Cloud Region Selection**: Dropdown to select Mist cloud host from:
  - **Global 01**: api.mist.com (default)
  - **Global 02**: api.gc1.mist.com
  - **Global 03**: api.ac2.mist.com
  - **Global 04**: api.gc2.mist.com
  - **Global 05**: api.gc4.mist.com
  - **EMEA 01**: api.eu.mist.com
  - **EMEA 02**: api.gc3.mist.com
  - **EMEA 03**: api.ac6.mist.com
  - **EMEA 04**: api.gc6.mist.com
  - **APAC 01**: api.ac5.mist.com
  - **APAC 02**: api.gc5.mist.com
  - **APAC 03**: api.gc7.mist.com
- **Connection Validation**: Immediately test connection after saving configuration
  - Validate API token
  - Verify organization access
  - Test API reachability
  - Display success/error notification to user
- **Future Enhancement**: Support for multiple organizations (currently single org only)

**Notification Integrations**
- Configure global Slack workspace
- Configure ServiceNow instance
- Configure PagerDuty account
- Test integrations

---

## Technical Requirements

### Backend Architecture (Python)

**Framework**: FastAPI or Flask
- RESTful API design
- **API Versioning**: All endpoints prefixed with `/api/v1/`
- **Standardized Response Format**:
  ```json
  // Success response
  {
    "success": true,
    "data": { ... },
    "message": "Optional success message"
  }
  
  // Error response
  {
    "success": false,
    "error": {
      "code": "ERROR_CODE",
      "message": "Human-readable error message",
      "details": { ... }
    }
  }
  
  // Paginated list response
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
- **HTTP Status Codes**: Consistent usage
  - 200: Success (GET, PUT)
  - 201: Created (POST)
  - 204: No Content (DELETE)
  - 400: Bad Request (validation errors)
  - 401: Unauthorized (authentication required)
  - 403: Forbidden (insufficient permissions)
  - 404: Not Found
  - 429: Too Many Requests (rate limiting)
  - 500: Internal Server Error
- **Pagination**: Limit/offset based for list endpoints
  - Query parameters: `?limit=20&offset=0`
  - Default limit: 20, max limit: 100
- OpenAPI/Swagger documentation
- **CORS Configuration**:
  - Allowed origins: Same domain only (no cross-origin)
  - Credentials: Allow cookies for authentication
  - No wildcard origins in production

**Health Check Endpoint**
- **Basic Health**: `GET /api/v1/health`
  - Returns 200 OK if application is running
  - Response: `{"status": "healthy", "timestamp": "ISO8601"}`
  - Used by load balancers and monitoring tools
- **Future Enhancement**: Detailed health check showing DB, Redis, Mist API status

**Mist Integration**
- Use `mistapi` Python package for all Mist API interactions
- **Rate Limiting**: Prevent overwhelming Mist API
  - Mist API global limit: 5000 API calls per hour per organization
  - Implement application-level rate limiting:
    - Track API calls per workflow
    - Warn when approaching limits (e.g., at 80% - 4000 calls/hour)
    - Configurable per-workflow rate limits
    - Queue requests when limit reached
    - Exponential backoff on rate limit errors (429 responses)
- **Concurrent Modification Protection**:
  - Implement distributed locking for object modifications
  - When workflow attempts to modify an object:
    - Acquire lock for object UUID
    - If locked by another workflow, queue or retry after delay
    - Release lock after operation completes
  - Lock timeout to prevent deadlocks
  - Display "object currently locked" message to users if conflict
- Implement connection pooling
- Handle Mist API pagination automatically
- Error handling and retry logic for API failures

**Webhook Server**
- Dedicated endpoints for Mist webhooks
- **Webhook Signature Validation**:
  - Validate `X-Mist-Signature-v2` header
  - Algorithm: HMAC_SHA256(secret, body)
  - Reject webhooks with invalid or missing signatures
  - Reference: https://github.com/tmunzer/mwtt/blob/master/src/mwtt.py#L130
- **IP Whitelisting**: Only accept webhooks from known Mist cloud IP ranges:
  - Global 01: 54.193.71.17, 54.215.237.20
  - Global 02: 34.94.226.48/28 (34.94.226.48 - 34.94.226.63)
  - Global 03: 34.231.34.177, 54.235.187.11, 18.233.33.230
  - Global 04: 34.152.4.85, 35.203.21.42, 34.152.7.156
  - Global 05: 35.192.224.0/29 (35.192.224.0 - 35.192.224.7)
  - EMEA 01: 3.122.172.223, 3.121.19.146, 3.120.167.1
  - EMEA 02: 35.234.156.66
  - EMEA 03: 51.112.15.151, 51.112.76.109, 51.112.86.222
  - EMEA 04: 34.166.152.112/29 (34.166.152.112 - 34.166.152.119)
  - APAC 01: 54.206.226.168, 13.238.77.6, 54.79.134.226
  - APAC 02: 34.47.180.168/29 (34.47.180.168 - 34.47.180.175)
  - APAC 03: 34.104.128.8/29 (34.104.128.8 - 34.104.128.15)
- Asynchronous processing queue for webhook handling
- **Webhook Deduplication**:
  - Track webhook unique identifier or content hash
  - Deduplication window: 1 minute
  - If same webhook ID/hash received within 1 minute, ignore as duplicate
  - **MVP Implementation**: In-memory store (dictionary/cache) for recent webhook IDs
  - **Production Enhancement**: Use Redis for distributed deduplication across multiple instances
  - Log duplicate webhooks (for monitoring)
  - Store: `{webhook_id or hash: timestamp}` for dedup checking
- Global webhook secret configuration (stored encrypted)

**Webhook Proxy for Development/Testing (Smee.io Integration)**
- **Purpose**: Enable webhook testing during development and in environments without public endpoints
- **Configuration Methods**:
  1. **Environment Variable** (Development Mode):
     - Set `SMEE_CHANNEL_URL` environment variable
     - Automatically proxy webhooks when variable is set
     - Ideal for local development
  2. **Admin Panel Configuration**:
     - "Enable Webhook Proxy" toggle in admin settings
     - Input field for Smee.io channel URL (e.g., `https://smee.io/abc123`)
     - Validate URL format (must be smee.io domain)
     - **Security Warning Banner**: Display prominent warning
       - "⚠️ TESTING MODE: Webhook proxy is enabled. DO NOT USE IN PRODUCTION."
       - Show current proxy URL
       - Easy disable button
- **Functionality**:
  - When enabled, application subscribes to Smee.io channel
  - Receives webhooks forwarded from Smee.io
  - Processes webhooks normally through workflow engine
  - All webhook validation still applies (signature, IP whitelisting disabled when proxy enabled)
- **Status Indicators**:
  - Dashboard shows "Webhook Proxy: Active" badge when enabled
  - Display proxy URL and connection status
  - Warning banner on every page when proxy is active
- **Limitations**:
  - Only Smee.io supported (no other proxy services initially)
  - Automatic fallback to direct webhooks if Smee.io unavailable

**Task Scheduler**
- Background job scheduler (APScheduler, Celery, or similar)
- Support for cron-based scheduling
- Persistent task queue

**Database Layer**
- MongoDB (preferred) or PostgreSQL
- ORM/ODM for database interactions
- **Database Indexes** (for performance):
  - **Users collection**:
    - `email` (unique index)
  - **Workflows collection**:
    - `name` (text index for search)
    - `created_by`
    - `status`
    - `trigger.type`
    - Compound: `(status, created_by)`
  - **WorkflowExecution collection**:
    - `workflow_id`
    - `executed_at` (descending, for recent queries)
    - Compound: `(workflow_id, executed_at)`
  - **BackupObject collection**:
    - `org_id`
    - `site_id` (sparse index, as it can be null)
    - `object_uuid`
    - `object_type`
    - `status`
    - `created_at`
    - Compound: `(org_id, object_type, status)`
    - Compound: `(object_uuid, version)` for version queries
  - **WebhookHistory collection**:
    - `received_at` (descending, with TTL for auto-cleanup)
    - `webhook_type`
    - Compound: `(webhook_type, received_at)`
- Connection pooling
- No automated database migrations (manual schema updates as needed)

**Authentication**
- JWT token generation and validation
- Password hashing (bcrypt or argon2)
- Role-based access control middleware
- Session management with configurable timeout
- **Two-Factor Authentication (2FA)**:
  - TOTP implementation (pyotp library)
  - QR code generation for authenticator apps
  - Backup codes generation and validation
  - 2FA verification at login
  - Device trust mechanism (optional 30-day trust)

**Git Integration** (if selected as storage strategy)
- GitPython library for Git operations
- **Branch Strategy**:
  - Single branch (configurable by admin, default: `main`)
  - All backups committed to this branch
  - No branch-per-org or branch-per-site complexity for MVP
- **Commit Message Format**: Automated commits with structured messages
  - Format: `[{change_type}] {object_type}/{object_name} (by {admin_name})`
  - Examples:
    - `[CREATED] wlan/Corporate-WiFi (by john.doe@example.com)`
    - `[UPDATED] site/Building-A (by jane.smith@example.com)`
    - `[DELETED] gateway_template/Branch-Template (by admin@example.com)`
    - `[FULL_BACKUP] Organization backup completed`
  - Commit body includes timestamp and metadata
- **Push Failure Handling**:
  - Retry up to 3 times with exponential backoff (1s, 2s, 4s)
  - If all retries fail:
    - Log error with full details
    - Send alert to administrators (Slack/in-app)
    - Queue for manual resolution
    - Continue normal operation (local DB has data)
  - Display warning in admin panel if Git sync is failing
- **Repository Size Monitoring** (Future Enhancement):
  - Display Git repository size in admin panel
  - Configurable alert threshold (e.g., warn at 500MB, critical at 1GB)
  - Alert administrators when threshold exceeded
  - Suggest archiving old branches or repository cleanup

**Logging & Monitoring**
- **Structured Logging**: JSON format for all logs
  ```json
  {
    "timestamp": "2026-03-07T10:30:45.123Z",
    "level": "INFO",
    "logger": "workflow.executor",
    "message": "Workflow executed successfully",
    "context": {
      "workflow_id": "abc123",
      "duration_ms": 1234,
      "user_id": "user456"
    }
  }
  ```
- **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
  - Development: DEBUG level
  - Production: INFO level
- **Log Rotation**: Daily rotation
- **Log Retention**: Keep last 7 days (MVP)
  - Future: Configurable retention period
- **Sensitive Data Masking**: 
  - Automatically redact passwords, API tokens, secrets in logs
  - Replace with `***REDACTED***` or show last 4 characters only
  - Never log full authentication credentials
  - Mask PII (personal identifiable information)
- Request/response logging (exclude sensitive headers)
- Performance monitoring (execution times, API latency)

### Frontend Architecture (Angular + Angular Material)

**Angular Version**: Latest LTS version

**UI Components** (Angular Material)
- Data tables with sorting, filtering, pagination
- Forms with validation
- Date/time pickers
- Dialogs and modals
- Snackbars for notifications
- Cards and expansion panels
- Tabs
- Stepper for workflow creation
- Chips for tags/filters
- Tree view for hierarchical data

**Pages/Views Required**

1. **Login/Onboarding Page**
   - Login form
   - First-time admin creation wizard

2. **Dashboard**
   - **Overview Statistics**:
     - Total number of workflows (enabled/disabled/draft)
     - Workflow execution success rate (last 24h, 7d, 30d)
     - Total workflow executions today
     - Number of backed up objects
     - Time since last successful full backup
     - Storage usage (database size, git repo size if applicable)
   - **Performance Metrics**:
     - Mist API response times (average, 95th percentile)
     - API calls made today / remaining in rate limit
     - Webhook processing latency
   - **Recent Activity**:
     - Recent workflow executions (with status indicators)
     - Recent backup operations
     - Recent configuration changes detected
   - **System Health**:
     - Mist API connection status
     - Webhook endpoint status
     - Database connection status
     - Background job queue status
     - Alerts/warnings if any

3. **Automation Module**
   - Workflow list (data table)
   - Workflow creation wizard (stepper)
   - Workflow editor
   - Execution history
   - Test/debug interface
   - Webhook inspector (see below)

4. **Backup Module**
   - Timeline view (visual timeline component)
   - Table view (data table with advanced filtering)
   - Object detail viewer (JSON viewer with syntax highlighting)
   - Version comparison (side-by-side diff viewer)
   - Restore confirmation dialogs

5. **Admin Panel**
   - User management
   - Backup configuration
   - Integration configuration
   - Webhook proxy configuration (Smee.io)
   - System settings
   - Logs viewer

6. **Webhook Inspector**
   - **Real-time Webhook Viewer**: Built-in interface to monitor incoming webhooks
   - **Features**:
     - Live feed of received webhooks (auto-refresh or WebSocket)
     - Filter by webhook type, source, date range
     - Display for each webhook:
       - Timestamp (received at)
       - Webhook type (alarm, audit, event, etc.)
       - Source (direct from Mist or via Smee.io proxy)
       - HTTP headers (X-Mist-Signature-v2, content-type, etc.)
       - Full JSON payload with syntax highlighting
       - Validation status (signature valid/invalid, IP check result)
       - Processing status (queued, processing, completed, failed)
       - Matched workflows (which workflows were triggered)
     - **Actions per webhook**:
       - View details (expand to see full payload)
       - Copy payload (copy JSON to clipboard)
       - Save for testing (add to webhook payload library)
       - Replay (send through workflow engine again)
       - Download as JSON file
     - **Search & Filter**:
       - Full-text search across payloads
       - Filter by type, date, validation status, processing status
       - Quick filters: "Failed only", "Last hour", "Saved for testing"
   - **Retention**: Configurable in admin panel (default: last 1000 webhooks or 7 days)
   - **Access Control**: Requires `automation` or `admin` role
   - **Performance**: Paginated display with virtual scrolling for large datasets

**State Management**
- NgRx or Akita for application state
- Reactive forms with form validation
- HTTP interceptors for auth headers

**Real-time Updates** (Future Enhancement)
- WebSocket connections for live updates (post-MVP)
- Server-sent events for backup progress (post-MVP)
- Toast notifications for important events (using polling for MVP)

**Responsive Design**
- **Desktop-first design**: Optimized for desktop browsers
- **Tablet support**: Responsive layouts work well on tablets
- **Mobile support**: Future enhancement (not MVP)

**Browser Support**
- **Primary browsers**: Chrome and Firefox (latest versions)
- **Secondary browsers**: Safari and Edge (should work, but not primary testing targets)
- **Minimum versions**: 
  - Chrome: Last 2 major versions
  - Firefox: Last 2 major versions
  - Safari: Last 2 major versions
  - Edge: Chromium-based versions only

**Accessibility**
- WCAG 2.1 Level AA compliance
- Semantic HTML
- ARIA labels
- Keyboard navigation

**Code Editor Integration**
- For cron expressions: visual editor + text mode
- For JSON viewing: Monaco Editor or similar
- For filters: expression builder UI

---

## Data Models

### User
```json
{
  "_id": "ObjectId",
  "email": "string",
  "password_hash": "string",
  "roles": ["admin", "automation", "backup"],
  "timezone": "string",
  "totp_secret": "string|null",
  "totp_enabled": "boolean",
  "backup_codes": ["string"],
  "created_at": "datetime",
  "last_login": "datetime",
  "is_active": "boolean"
}
```

### UserSession
```json
{
  "_id": "ObjectId",
  "user_id": "ObjectId",
  "token": "string",
  "device_info": {
    "browser": "string",
    "os": "string",
    "ip_address": "string"
  },
  "created_at": "datetime",
  "last_activity": "datetime",
  "expires_at": "datetime"
}
```

### Workflow
```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string",
  "created_by": "user_id",
  "created_at": "datetime",
  "updated_at": "datetime",
  "status": "enabled|disabled|draft",
  "sharing": "private|read-only|read-write",
  "timeout_seconds": "number",
  "trigger": {
    "type": "webhook|cron",
    "webhook_type": "alarm|audit|event|...",
    "cron_expression": "string",
    "timezone": "string",
    "skip_if_running": "boolean"
  },
  "filters": [
    {
      "field": "string",
      "operator": "equals|contains|starts_with|...",
      "value": "any",
      "source": "webhook|api_result"
    }
  ],
  "actions": [
    {
      "type": "api_get|api_post|api_put|api_delete|notify",
      "endpoint": "string",
      "parameters": {},
      "save_as": "variable_name",
      "on_failure": "stop|continue"
    }
  ],
  "notifications": [
    {
      "type": "slack|servicenow|pagerduty|webhook",
      "config": {},
      "message_template": "string"
    }
  ]
}
```

### WorkflowExecution
```json
{
  "_id": "ObjectId",
  "workflow_id": "ObjectId",
  "executed_at": "datetime",
  "trigger_data": {},
  "filter_results": [],
  "actions_taken": [],
  "status": "success|failed|partial|timeout",
  "error_message": "string",
  "duration_ms": "number"
}
```

### BackupObject
```json
{
  "_id": "ObjectId",
  "org_id": "string",
  "site_id": "string|null",
  "scope": "org|site",
  "object_type": "wlan|site|template|...",
  "object_uuid": "string",
  "object_name": "string",
  "version": "number",
  "status": "current|old_version|deleted",
  "data": {},
  "metadata": {
    "admin_name": "string",
    "admin_email": "string",
    "change_type": "created|updated|deleted|restored",
    "timestamp": "datetime"
  },
  "git_commit_sha": "string|null",
  "previous_version_id": "ObjectId|null"
}
```

### AppConfiguration
```json
{
  "_id": "ObjectId",
  "backup_config": {
    "max_versions": "number",
    "max_age_days": "number",
    "full_backup_schedule": "string",
    "storage_strategy": "local|github|gitlab",
    "git_config": {
      "provider": "github|gitlab",
      "repo_url": "string",
      "branch": "string",
      "token": "string (encrypted)"
    }
  },
  "mist_config": {
    "org_id": "string",
    "api_token": "string (encrypted)",
    "api_endpoint": "string"
  },
  "notification_config": {
    "slack": {},
    "servicenow": {},
    "pagerduty": {}
  },
  "webhook_config": {
    "smee_enabled": "boolean",
    "smee_channel_url": "string|null",
    "inspector_retention_days": "number",
    "inspector_max_webhooks": "number",
    "dedup_window_seconds": "number"
  },
  "execution_config": {
    "max_concurrent_workflows": "number",
    "global_max_timeout_seconds": "number",
    "session_timeout_hours": "number"
  }
}
```

### WebhookHistory
```json
{
  "_id": "ObjectId",
  "received_at": "datetime",
  "webhook_type": "alarm|audit|event|...",
  "source": "mist|smee",
  "headers": {},
  "payload": {},
  "validation_status": "valid|invalid|skipped",
  "processing_status": "queued|processing|completed|failed",
  "matched_workflows": ["workflow_id"],
  "saved_for_testing": "boolean",
  "error_message": "string|null"
}
```

---

## Monitoring & Alerting

**System Monitoring**
- Health check endpoints for service availability
- Database connection monitoring
- Mist API connectivity monitoring
- Background job queue monitoring
- Storage capacity monitoring

**Failure Notifications**

The application should send alerts to administrators when:

1. **Workflow Failures**
   - Workflow fails to execute
   - Workflow fails repeatedly (e.g., 3 failures in 1 hour)
   - Workflow timeout
   
2. **Backup Failures**
   - Full backup fails to complete
   - Incremental backup fails
   - Backup storage unavailable
   - Git push failures (if using Git storage)
   
3. **API Issues**
   - Mist API becomes unreachable
   - API rate limit exceeded
   - Authentication failures with Mist API
   
4. **System Issues**
   - Database connection failures
   - Storage capacity warnings
   - Critical errors in application logs

**Notification Channels**
- **In-App Notifications**: Real-time alerts displayed in UI (bell icon with badge)
- **Slack**: Send messages to configured Slack channels
- **Email**: Optional email notifications (future enhancement)

**Alert Management**
- Admins can view all alerts in dedicated alerts panel
- Mark alerts as acknowledged/resolved
- Alert history and tracking
- Configurable alert thresholds

**Future Enhancement**
- Health check endpoints for external monitoring (Prometheus, Datadog)
- Metrics export in Prometheus format
- Custom alert rules

---

## Disaster Recovery

**Backup Strategy for Application Data**

To protect against application database loss, implement a hybrid disaster recovery strategy:

1. **Critical Data Export to Git**
   - Daily automated export of critical application data as encrypted JSON files:
     - User accounts and roles
     - Workflow definitions
     - Application configuration
     - Backup object metadata (if not already in Git)
   - Files committed to Git repository (same or separate repo from config backups)
   - Encrypted using application encryption key
   
2. **Database Backup**
   - Daily automated MongoDB dumps to external storage (optional but recommended)
   - Retention policy: keep last 30 daily backups
   - Backup verification (periodic restore tests)
   
3. **Recovery Process**
   - On database loss:
     1. Deploy fresh application instance
     2. Import critical data from Git repository (decrypt JSON files)
     3. Rebuild application state from exported data
     4. Resume operations with minimal data loss
   - Configuration backups safe in Git (if using Git storage strategy)
   - Workflow definitions and user accounts restored from daily exports
   
4. **Recovery Time Objective (RTO)**
   - Target: < 4 hours to restore full functionality
   - Automated recovery scripts for faster restoration
   
5. **Recovery Point Objective (RPO)**
   - Maximum data loss: 24 hours (daily export frequency)
   - Consider increasing export frequency for critical deployments

**Disaster Recovery Testing**
- Periodic DR drills (quarterly recommended)
- Document recovery procedures
- Test restore process in staging environment

---

## Security Requirements

**CRITICAL: The application MUST implement comprehensive security measures following industry best practices.**

### OWASP Top 10 Protection

The application must be protected against all OWASP Top 10 vulnerabilities:

1. **Broken Access Control**
   - Enforce role-based access control on all endpoints
   - Verify user permissions server-side (never trust client)
   - Deny access by default
   - Prevent horizontal privilege escalation (users accessing other users' data)
   - Prevent vertical privilege escalation (users accessing admin functions)

2. **Cryptographic Failures**
   - All sensitive data encrypted at rest (API tokens, passwords, secrets)
   - Strong encryption algorithms (AES-256)
   - Secure key management (keys not in codebase)
   - All communications over HTTPS/TLS only
   - No hardcoded secrets or credentials

3. **Injection Attacks**
   - **SQL/NoSQL Injection Prevention**:
     - Use parameterized queries/prepared statements exclusively
     - Use ORM/ODM with proper escaping (pymongo, SQLAlchemy)
     - Never concatenate user input into database queries
     - Validate and sanitize all input
   - **Command Injection Prevention**:
     - Avoid shell commands with user input
     - If unavoidable, use strict allowlists and escaping
     - Never use `eval()` or `exec()` with user data
   - **LDAP, XPath, OS Command Injection**: Same strict input validation

4. **Insecure Design**
   - Threat modeling during design phase
   - Security requirements integrated from start
   - Principle of least privilege throughout
   - Defense in depth strategy

5. **Security Misconfiguration**
   - No default credentials
   - Minimal error messages to users (no stack traces in production)
   - Disable directory listing
   - Remove unnecessary features/dependencies
   - Security headers properly configured (see below)

6. **Vulnerable and Outdated Components**
   - Keep all dependencies up to date
   - Regular security audits of dependencies (`npm audit`, `pip-audit`)
   - Review libraries for known vulnerabilities before use
   - Automated dependency scanning in CI/CD

7. **Identification and Authentication Failures**
   - Strong password requirements (min 12 chars, complexity)
   - Password hashing with bcrypt/argon2 (high cost factor)
   - 2FA support (TOTP)
   - Session management: secure tokens, proper timeout, invalidation
   - Prevent brute force: rate limiting on login
   - No credential stuffing vulnerabilities

8. **Software and Data Integrity Failures**
   - Verify webhook signatures (HMAC validation)
   - Code signing for deployments
   - Audit logging of all critical changes
   - Integrity checks for backups

9. **Security Logging and Monitoring Failures**
   - Log all authentication events (success/failure)
   - Log authorization failures
   - Log input validation failures
   - Alerts for suspicious patterns
   - Tamper-proof audit logs
   - No sensitive data in logs (passwords, tokens)

10. **Server-Side Request Forgery (SSRF)**
    - Validate and sanitize all URLs
    - Allowlist for external API calls
    - No user-controlled URLs without validation
    - Network segmentation where possible

### Cross-Site Scripting (XSS) Protection

- **Output Encoding**: Encode all user-generated content before rendering
- **Content Security Policy (CSP)**: Strict CSP headers
  ```
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';
  ```
- **Angular Security**: Leverage Angular's built-in XSS protection
  - Use Angular templates (auto-escaping)
  - Avoid `bypassSecurityTrust` methods unless absolutely necessary
  - Sanitize any dynamic HTML with DomSanitizer
- **HTTP Headers**:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Frontend Validation**: Validate on client AND server (never trust client alone)

### Additional Security Measures

### Additional Security Measures

1. **Authentication & Authorization**
   - All API endpoints require authentication except login/onboarding
   - Role-based access control enforced on all protected routes
   - Token expiration and refresh mechanism
   - Logout invalidates tokens server-side

2. **Secret Management**
   - All API tokens, passwords, and secrets encrypted at rest
   - Use environment variables for sensitive configuration
   - No secrets in logs or error messages
   - No secrets committed to version control

3. **Input Validation**
   - **Server-Side Validation**: Always validate on backend (never trust client)
   - Validate data types, formats, ranges, lengths
   - Reject unexpected input (fail closed, not open)
   - Sanitize all user inputs before processing
   - Use schema validation libraries (Pydantic for Python)
   - Prevent injection attacks (SQL, NoSQL, command injection)
   - Email validation, URL validation
   - File upload validation (if applicable): type, size, content

4. **Webhook Security**
   - Validate webhook signatures from Mist (HMAC-SHA256)
   - HTTPS-only communication
   - IP whitelisting for webhook sources
   - Replay attack prevention (timestamp validation, nonce tracking)

5. **Audit Logging**
   - **Application Audit Trail**: Comprehensive audit log for all administrative actions within the app
     - User creation, modification, deletion
     - Role assignment changes
     - Workflow create, update, delete, enable, disable
     - Backup configuration changes
     - Restore operations (with details of what was restored)
     - System configuration changes
     - Failed authentication attempts
   - **Audit Log Storage**: Separate collection/table from operational data
   - **Audit Log Viewer**: Admin UI to search and filter audit logs
   - **Immutable Logs**: Audit records cannot be modified or deleted
   - Log all restore operations with full context
   - Log authentication events (login, logout, failed attempts)

6. **Data Encryption**
   - **Encryption at Rest**: 
     - All sensitive data encrypted in database (API tokens, passwords, secrets)
     - Use strong encryption (AES-256)
     - Encryption keys managed securely (not in codebase)
   - **Encryption in Transit**:
     - All HTTP communication over HTTPS/TLS
     - TLS 1.2 minimum, TLS 1.3 preferred
     - Strong cipher suites only
   - **Secret Management**:
     - Environment variables for encryption keys
     - Separate secrets for different environments (dev, staging, prod)

7. **Security Testing**
   - Regular security testing during development
   - Automated vulnerability scanning
   - Code security reviews
   - Penetration testing before production deployment

---

## Performance Requirements

1. **Scalability**
   - Support multiple organizations
   - Handle high webhook volumes (100+ webhooks/minute)
   - Efficient database queries with indexing

2. **Backup Performance**
   - Full backup should complete within reasonable time (< 30 minutes for large orgs)
   - Incremental backups processed in near real-time
   - Background processing doesn't block UI

3. **UI Performance**
   - Page load time < 2 seconds
   - Table rendering with virtual scrolling for large datasets
   - Lazy loading for heavy components

---

## Error Handling & Resilience

1. **Workflow Execution**
   - Retry logic for transient API failures
   - Dead letter queue for failed workflows
   - Alert admins on repeated failures

2. **Backup Operations**
   - Retry failed backup operations
   - Partial success handling (some objects failed)
   - Backup verification (compare with Mist)

3. **Graceful Degradation**
   - UI remains functional if some services are unavailable
   - Clear error messages to users
   - Fallback mechanisms

---

## Testing Requirements

1. **Backend Testing**
   - Unit tests for business logic (pytest)
   - Integration tests for API endpoints
   - Mock Mist API for testing
   - Test coverage > 80%

2. **Frontend Testing**
   - Unit tests for components (Jasmine/Karma)
   - E2E tests for critical flows (Protractor/Cypress)
   - Accessibility testing

3. **Security Testing**
   - Dependency vulnerability scanning (pip-audit, npm audit)
   - Input validation testing
   - Authentication/authorization testing
   - XSS prevention testing
   - SQL/NoSQL injection testing
   - OWASP Top 10 checklist verification
   - Security headers validation

---

# Constraints

## Technical Constraints

- **Backend**: Must use Python with `mistapi` package for Mist API communication
- **Frontend**: Must use Angular with Angular Material for UI components
- **Database**: MongoDB preferred, but PostgreSQL acceptable
- **Deployment**: Should be containerized (Docker) for easy deployment

## Code Quality & Maintainability

**CRITICAL: Code must adhere to industry best practices for quality and maintainability.**

### DRY (Don't Repeat Yourself)
- **No code duplication**: Extract common logic into reusable functions/classes
- **Shared utilities**: Create utility modules for repeated operations
- **Configuration over code**: Use configuration files instead of hardcoding values
- **Inheritance and composition**: Use OOP principles to avoid duplication
- **Template reuse**: Frontend components should be reusable

### KISS (Keep It Simple, Stupid)
- **Simplicity first**: Choose simple solutions over complex ones when both work
- **Avoid over-engineering**: Don't add features or abstractions not needed for MVP
- **Clear logic flow**: Avoid convoluted conditional logic
- **Minimal dependencies**: Only use external libraries when they provide clear value
- **Straightforward architecture**: Avoid unnecessary layers of abstraction

### Human Readable
- **Clear naming**: 
  - Variables: descriptive names (e.g., `workflow_execution_count` not `wec`)
  - Functions: verb-based names describing action (e.g., `validate_webhook_signature()`)
  - Classes: noun-based names (e.g., `WorkflowExecutor`, `BackupManager`)
- **Self-documenting code**: Code should be understandable without excessive comments
- **Comments when needed**: 
  - Explain "why" not "what" (code shows what, comments explain why)
  - Document complex algorithms or business logic
  - Add docstrings to all functions, classes, modules
- **Consistent formatting**: Use auto-formatters (Black for Python, Prettier for TypeScript)
- **Proper indentation**: Follow language-specific style guides

### Human Maintainable
- **Modular design**: 
  - Single Responsibility Principle: Each module/class does one thing well
  - Loose coupling: Modules should be independent
  - High cohesion: Related functionality grouped together
- **Separation of concerns**: 
  - Business logic separate from presentation
  - API routes separate from business logic
  - Database access layer separate from business logic
- **Error handling**: 
  - Explicit error handling (no silent failures)
  - Meaningful error messages
  - Proper exception hierarchies
- **Testing**: 
  - Unit tests for business logic
  - Integration tests for API endpoints
  - Test coverage >80%
  - Tests serve as documentation
- **Documentation**:
  - README with setup instructions
  - API documentation (OpenAPI/Swagger)
  - Architecture documentation
  - Code comments for complex logic
- **Version control**: 
  - Meaningful commit messages
  - Small, focused commits
  - Feature branches
  - Code review before merge

## Security Constraints

- **Reversibility**: All configuration changes must be reversible
- **Scalability**: Architecture must support horizontal scaling
- **Security**: 
  - **MANDATORY**: Protect against OWASP Top 10 vulnerabilities
  - **MANDATORY**: Prevent SQL/NoSQL injection attacks
  - **MANDATORY**: Prevent Cross-Site Scripting (XSS) attacks
  - No hardcoded secrets or credentials
  - All sensitive data encrypted at rest
  - Use X-FROM headers in HTTP requests
  - Validate and sanitize all inputs server-side
  - Implement proper authentication and authorization
  - Security headers properly configured
- **Code Quality**:
  - **MANDATORY**: Follow DRY (Don't Repeat Yourself) principles
  - **MANDATORY**: Follow KISS (Keep It Simple, Stupid) principles
  - **MANDATORY**: Code must be human readable with clear naming and structure
  - **MANDATORY**: Code must be human maintainable with modular design
  - Include unit tests for critical functionality
  - Test coverage >80%
  - Meaningful logs (no PII in logs, mask sensitive data)
  - Follow PEP 8 for Python
  - Follow Angular style guide for frontend
  - Use code formatters (Black, Prettier)
  - Comprehensive documentation
- **Dependencies**:
  - Review new libraries for security vulnerabilities and license compatibility
  - Keep dependencies up to date
  - Regular security audits of dependencies

---

# Technologies

## Backend Stack
- **Language**: Python 3.9+
- **Framework**: FastAPI (recommended) or Flask
- **Mist Integration**: `mistapi` package
- **Database**: MongoDB (pymongo/motor) or PostgreSQL (SQLAlchemy)
- **Task Queue**: Celery + Redis or APScheduler
- **Authentication**: PyJWT, passlib/bcrypt or argon2-cffi
- **2FA**: pyotp (TOTP implementation)
- **Git Integration**: GitPython (if using Git storage)
- **HTTP Client**: httpx or aiohttp
- **Schema Validation**: Pydantic (prevents injection, validates input)
- **Testing**: pytest, pytest-asyncio, pytest-cov
- **Code Quality**:
  - black (code formatter)
  - flake8 or pylint (linting)
  - mypy (type checking)
  - bandit (security linting)
- **Logging**: structlog or python-json-logger
- **Security**: 
  - python-dotenv (environment variables)
  - cryptography (encryption)
  - pip-audit (dependency vulnerability scanning)

## Frontend Stack
- **Framework**: Angular (latest LTS)
- **UI Library**: Angular Material
- **State Management**: NgRx or Akita
- **HTTP Client**: Angular HttpClient
- **Forms**: Reactive Forms with validation
- **Code Editor**: Monaco Editor or ngx-codemirror
- **Date/Time**: date-fns or moment.js
- **Charts**: ngx-charts or Chart.js
- **JSON Diff**: ngx-json-viewer or similar
- **Testing**: Jasmine, Karma, Cypress
- **Code Quality**:
  - Prettier (code formatter)
  - ESLint (linting)
  - TSLint or typescript-eslint
- **Security**:
  - Angular's built-in XSS protection (use Angular templates)
  - DomSanitizer for any dynamic HTML
  - npm audit for dependency scanning

## DevOps & Deployment
- **Containerization**: Docker, Docker Compose
- **Docker Compose Setup**: 
  - Complete docker-compose.yml including:
    - Backend service (Python/FastAPI)
    - Frontend service (Angular/Nginx)
    - MongoDB database
    - Redis (for webhook deduplication in production)
    - Volume mounts for persistence
    - Network configuration
  - Local development instructions
  - Production deployment guidance
- **Environment Variables**:
  - Comprehensive documentation of all variables
  - Required vs optional variables clearly marked
  - Default values specified
  - Example `.env.example` file
  - Variables for:
    - Database connection
    - JWT secrets
    - Encryption keys
    - Mist API configuration
    - Smee.io proxy (optional)
    - Session timeout
    - Concurrent workflow limits
    - Feature flags
- **Reverse Proxy**: Nginx configuration for frontend and API routing
- **Process Manager**: Gunicorn/Uvicorn (backend)
- **Database Management**: MongoDB without automated migrations (manual schema updates if needed)

## External Integrations
- **Mist API**: Via mistapi package
- **Git**: GitHub API / GitLab API
- **Notifications**: Slack API, ServiceNow API, PagerDuty API

---

# Development Phases

## Phase 1: Foundation
- Project setup (backend + frontend)
- Docker Compose configuration with all services
- Environment variable documentation
- Database schema design
- Authentication system with 2FA
- User profile management (timezone, password change, sessions)
- Basic user management
- Onboarding flow

## Phase 2: Automation Module
- Webhook receiver with deduplication
- Smee.io proxy integration
- Webhook inspector UI
- Webhook payload library and replay
- Workflow CRUD operations with bulk actions
- Cron scheduling with timezone support
- Execution queue management and concurrency control
- Filter engine
- Action executor (API calls)
- Basic UI for workflow management

## Phase 3: Backup Module
- Full backup implementation with Git integration
- Git commit message formatting and retry logic
- Audit webhook listener
- Incremental backup logic
- Storage abstraction (local/Git)
- Basic restore functionality
- Dry run/preview mode for restores

## Phase 4: Advanced Features
- UUID reference resolution for restores
- Workflow execution history
- Workflow testing/debugging mode
- Workflow import/export
- Variables and conditional logic in workflows
- Advanced filtering and search
- Timeline visualization
- Comparison/diff viewer

## Phase 5: Integrations
- Slack integration
- ServiceNow integration
- PagerDuty integration
- Generic webhook forwarding

## Phase 6: Admin & Polish
- Admin configuration panel
- Retention policies
- Monitoring and alerting system
- Application audit trail
- Disaster recovery automation
- Documentation
- Error handling improvements

## Phase 7: Testing & Deployment
- Comprehensive testing
- Performance optimization
- Security audit
- Deployment documentation
- User guide

---

# Future Enhancements (Post-MVP)

The following features are considered valuable but not critical for the initial release:

1. **Workflow Versioning**: Track changes to workflow definitions with rollback capability
2. **Resource Limits**: Memory/CPU limits per workflow execution
3. **Workflow Organization**: Tags, labels, categories for workflow management
4. **Advanced Search**: Full-text search across workflows by name, description, tags
5. **User Notification Preferences**: Per-user alert configuration and channel selection
6. **Email Notifications**: In addition to Slack notifications
7. **Mobile Support**: Optimize UI for smartphone usage
8. **Additional Webhook Proxies**: Support for webhook.site, requestbin, etc.
9. **Advanced Metrics**: Detailed performance analytics and custom dashboards
10. **Multi-Organization Support**: Manage multiple Mist organizations from single instance
11. **Real-time Updates**: WebSocket/SSE for live status updates across UI
12. **Detailed Health Endpoint**: Extended health check with component status
13. **API Rate Limiting**: Per-user and IP-based rate limiting for app API
14. **File Upload Size Limits**: Configurable limits for workflow imports and exports
15. **Git Repository Management**: Automated archiving and cleanup tools
16. **Internationalization (i18n)**: Multi-language support (MVP: English only)
17. **Extended Log Retention**: Configurable log retention beyond 7 days

---

# Success Criteria

1. ✅ Users can create and manage automation workflows via intuitive UI
2. ✅ Workflows execute reliably on webhook triggers and cron schedules
3. ✅ Filters correctly evaluate webhook data and API responses
4. ✅ Actions successfully interact with Mist API using mistapi package
5. ✅ External notifications (Slack, etc.) are delivered correctly
6. ✅ Full backups complete successfully on schedule
7. ✅ Incremental backups trigger on audit webhooks in real-time
8. ✅ All configuration object versions are stored with complete metadata
9. ✅ Restore functionality works for current and deleted objects with dry run preview
10. ✅ UUID references are automatically updated when restoring deleted objects
11. ✅ Workflow testing mode allows debugging before deployment
12. ✅ Smee.io integration enables local development and testing
13. ✅ Webhook inspector provides visibility into all received webhooks
14. ✅ Webhook replay functionality enables testing with production data
15. ✅ Workflows support variables and conditional logic
16. ✅ Version comparison provides clear diff visualization
17. ✅ Role-based access control prevents unauthorized access
18. ✅ Application is secure (webhooks validated, IP whitelisted, data encrypted)
19. ✅ Monitoring and alerting notifies admins of failures
20. ✅ Disaster recovery process can restore from Git exports
21. ✅ UI is responsive and accessible
22. ✅ System is scalable and performant with rate limiting
23. ✅ Code is well-tested (>80% coverage) and documented