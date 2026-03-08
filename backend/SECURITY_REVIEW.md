# Backend Security Review Report

**Date:** March 8, 2026  
**Scope:** `/backend/app/` - Full backend codebase review  
**Reviewer:** Automated Security Analysis

---

## Executive Summary

This report documents potential security vulnerabilities identified in the Mist Automation backend codebase. Issues are categorized by severity level and include remediation recommendations.

| Severity | Count |
|----------|-------|
| 🔴 Critical | 3 |
| 🟠 High | 4 |
| 🟡 Medium | 5 |
| 🔵 Low/Info | 3 |

---

## 🔴 Critical Issues

### 1. Hardcoded Static Salt for Encryption

**Location:** `app/core/security.py` (Lines 174-175)

**Description:**  
The encryption function uses a hardcoded static salt for PBKDF2 key derivation:

```python
kdf = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,
    salt=b'mist_automation_salt',  # VULNERABILITY: Static salt
    iterations=100000,
    backend=default_backend(),
)
```

**Impact:**  
- Identical plaintexts will produce identical ciphertexts
- Rainbow table attacks become feasible
- Compromises all encrypted data if the salt is known

**Remediation:**
```python
import os

def encrypt_sensitive_data(data: str, key: Optional[str] = None) -> str:
    # Generate random salt per encryption
    salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    # ... rest of encryption
    
    # Return salt prepended to ciphertext
    return base64.b64encode(salt + encrypted).decode()
```

---

### 2. Server-Side Template Injection (SSTI) via Jinja2

**Location:** `app/utils/variables.py` (Lines 121-128)

**Description:**  
User-controlled workflow templates are rendered using Jinja2 without sandboxing:

```python
env = Environment(undefined=ChainableUndefined)  # No sandbox!
jinja_template = env.from_string(template)
result = jinja_template.render(context)
```

**Impact:**  
Attackers can execute arbitrary Python code via malicious templates:
```
{{ config.__class__.__mro__[1].__subclasses__()[40]('/etc/passwd').read() }}
```

**Remediation:**
```python
from jinja2.sandbox import SandboxedEnvironment

def substitute_variables(...) -> str:
    if strict:
        env = SandboxedEnvironment(undefined=StrictUndefined)
    else:
        env = SandboxedEnvironment(undefined=ChainableUndefined)
    # ... rest of function
```

---

### 3. Environment Variable Exposure in Templates

**Location:** `app/utils/variables.py` (Lines 66-67)

**Description:**  
All environment variables are exposed to workflow templates by default:

```python
if include_env:
    context["env"] = dict(os.environ)  # Exposes SECRET_KEY, DB passwords, etc.
```

**Impact:**  
- `SECRET_KEY` disclosure enables JWT forgery
- Database credentials enable direct DB access
- Cloud provider credentials enable infrastructure compromise

**Remediation:**
```python
# Option 1: Disable by default
include_env: bool = False

# Option 2: Whitelist safe variables
SAFE_ENV_VARS = {"TZ", "LANG", "APP_VERSION"}
if include_env:
    context["env"] = {k: v for k, v in os.environ.items() if k in SAFE_ENV_VARS}
```

---

## 🟠 High Issues

### 4. No Rate Limiting on Authentication Endpoints

**Location:** `app/api/v1/auth.py`

**Description:**  
Authentication endpoints accept unlimited requests, enabling brute-force attacks.

**Impact:**  
- Password brute-forcing
- Credential stuffing attacks
- Denial of service

**Remediation:**
```python
# requirements.txt
slowapi>=0.1.9

# app/main.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# app/api/v1/auth.py
from slowapi import limiter

@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest):
    # ...
```

---

### 5. No Account Lockout Mechanism

**Location:** `app/services/auth_service.py`

**Description:**  
Failed login attempts are logged but do not trigger account lockouts.

**Impact:**  
Unlimited password guessing attacks against user accounts.

**Remediation:**
```python
# Add to User model
failed_login_attempts: int = Field(default=0)
locked_until: datetime | None = Field(default=None)

# In authentication logic
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

if user.locked_until and user.locked_until > datetime.now(timezone.utc):
    raise AccountLockedException("Account temporarily locked")

if not verify_password(password, user.password_hash):
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + LOCKOUT_DURATION
    await user.save()
    raise InvalidCredentialsError()

# Reset on successful login
user.failed_login_attempts = 0
user.locked_until = None
```

---

### 6. Webhook Signature Validation is Optional

**Location:** `app/modules/automation/webhook_router.py` (Lines 59-68)

**Description:**  
Webhooks are processed even when signature validation fails or is not configured:

```python
signature_valid = True  # Default to valid!
if x_mist_signature:
    if config.webhook_secret:
        signature_valid = verify_mist_signature(body, x_mist_signature, config.webhook_secret)
        if not signature_valid:
            logger.warning("webhook_signature_invalid")
            # But continues processing!
```

**Impact:**  
Attackers can inject spoofed webhook events to trigger arbitrary workflows.

**Remediation:**
```python
if x_mist_signature:
    if not config.webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    
    if not verify_mist_signature(body, x_mist_signature, config.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
else:
    # Optionally require signatures in production
    if settings.environment == "production":
        raise HTTPException(status_code=401, detail="Webhook signature required")
```

---

### 7. SSRF Vulnerability via Workflow Webhook Actions

**Location:** `app/modules/automation/services/executor_service.py` (Lines 350-357)

**Description:**  
User-controlled URLs in webhook actions are not validated:

```python
url = substitute_variables(action.webhook_url, ...)
response = await client.post(url, json=body, headers=headers)
```

**Impact:**  
- Access internal services (databases, admin panels)
- Cloud metadata endpoint access (`http://169.254.169.254/...`)
- Port scanning of internal network

**Remediation:**
```python
import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
ALLOWED_SCHEMES = {"http", "https"}

def validate_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False
    
    hostname = parsed.hostname
    if hostname in BLOCKED_HOSTS:
        return False
    
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass  # Not an IP, proceed with hostname
    
    return True

# In executor
if not validate_webhook_url(url):
    raise WorkflowExecutionError(f"Blocked URL: {url}")
```

---

## 🟡 Medium Issues

### 8. Missing Content-Security-Policy Header

**Location:** `app/core/middleware.py` (Lines 108-120)

**Description:**  
Security headers are present but Content-Security-Policy is missing.

**Remediation:**
```python
response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
```

---

### 9. Weak Path Traversal Protection in Git Service

**Location:** `app/modules/backup/services/git_service.py` (Lines 430-445)

**Description:**  
Filename sanitization doesn't explicitly block `..` sequences:

```python
def _sanitize_filename(self, name: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    # Missing: ".." check
```

**Remediation:**
```python
def _sanitize_filename(self, name: str) -> str:
    # Block path traversal
    name = name.replace("..", "_")
    
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    
    # Validate final path
    final_path = self.repo_path / "test" / name
    if not str(final_path.resolve()).startswith(str(self.repo_path.resolve())):
        raise ValueError("Path traversal detected")
    
    return name or "unnamed"
```

---

### 10. TOTP Secret Stored in Plain Text

**Location:** `app/models/user.py` (Line 26)

**Description:**  
The TOTP secret is stored unencrypted despite the field comment suggesting encryption:

```python
totp_secret: str | None = Field(default=None, description="TOTP secret for 2FA (encrypted)")
```

**Remediation:**
```python
# In auth_service.py when setting up TOTP
from app.core.security import encrypt_sensitive_data, decrypt_sensitive_data

user.totp_secret = encrypt_sensitive_data(totp_secret)

# When verifying TOTP
decrypted_secret = decrypt_sensitive_data(user.totp_secret)
totp = pyotp.TOTP(decrypted_secret)
```

---

### 11. Token Refresh Doesn't Invalidate Old Session

**Location:** `app/api/v1/auth.py` (Lines 97-115)

**Description:**  
When refreshing a token, the old session remains valid, allowing tokens to be used indefinitely.

**Remediation:**
```python
@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    current_user: User = Depends(get_current_user_from_token)
):
    # Invalidate old session
    old_jti = getattr(request.state, "token_jti", None)
    if old_jti:
        old_session = await UserSession.find_one(UserSession.token_jti == old_jti)
        if old_session:
            await old_session.delete()
    
    # Create new token and session
    # ... rest of implementation
```

---

### 12. Refresh Token Type Not Validated

**Location:** `app/api/v1/auth.py`

**Description:**  
The `/auth/refresh` endpoint doesn't verify that the provided token is actually a refresh token.

**Remediation:**
```python
# Add token type validation in dependencies
async def get_current_user_from_refresh_token(...):
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise InvalidTokenException("Refresh token required")
    # ... rest of validation
```

---

## 🔵 Low / Informational Issues

### 13. Debug Mode Configuration

**Location:** `app/main.py`

**Status:** ✅ Correctly implemented

The application correctly disables documentation endpoints when not in debug mode:
```python
docs_url=f"{settings.api_v1_prefix}/docs" if settings.debug else None,
```

**Recommendation:** Ensure deployment configurations set `DEBUG=false`.

---

### 14. Sensitive Data in Logs

**Location:** Various files

**Description:**  
Some log statements include user emails and potentially sensitive metadata.

**Recommendation:**  
Review logging statements and ensure PII is appropriately masked or excluded based on your compliance requirements.

---

### 15. CORS Configuration

**Status:** ✅ Correctly implemented

```python
allow_origins=settings.cors_origins,  # Not wildcard
allow_credentials=True,
```

---

## Recommendations Summary

### Immediate Actions (Critical)
1. Replace static encryption salt with per-value random salts
2. Switch to `SandboxedEnvironment` for Jinja2 templates
3. Remove or whitelist environment variable exposure in templates

### Short-term Actions (High)
4. Implement rate limiting on authentication endpoints
5. Add account lockout after failed login attempts
6. Make webhook signature validation mandatory
7. Add URL validation for outgoing webhooks

### Medium-term Actions (Medium)
8. Add Content-Security-Policy header
9. Strengthen path traversal protection
10. Encrypt TOTP secrets at rest
11. Implement proper token rotation on refresh

---

## Additional Security Recommendations

### Consider Implementing
- [ ] Security audit logging to SIEM
- [ ] Automated dependency vulnerability scanning (e.g., `safety`, `pip-audit`)
- [ ] Penetration testing before production deployment
- [ ] Input validation schemas for all API endpoints
- [ ] Database query timeout limits
- [ ] Memory limits for request processing

### Dependencies to Review
Run periodic security audits on dependencies:
```bash
pip install pip-audit
pip-audit
```

---

*This report was generated as part of a security review. Findings should be validated and prioritized based on your specific threat model and risk tolerance.*
