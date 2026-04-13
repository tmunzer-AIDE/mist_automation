"""One-shot migration scripts for the backend.

Each file in this package is a standalone, idempotent migration intended to be
run manually from `backend/` (e.g. `PYTHONPATH=. python migrations/<filename>.py`). Migrations
are not applied automatically at application startup.
"""
