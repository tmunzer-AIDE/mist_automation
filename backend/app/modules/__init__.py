"""
Module registry for the Mist Automation backend.

To add a new module:
  1. Create a directory at app/modules/<name>/ with router.py, models.py, etc.
  2. Add one AppModule(...) entry to MODULES below — nothing else to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter


@dataclass
class AppModule:
    name: str
    router_module: str  # dotted import path, e.g. "app.api.v1.workflows"
    router_attr: str = "router"
    model_imports: list[tuple[str, str]] = field(default_factory=list)
    # Each entry: ("app.models.workflow", "Workflow")
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def get_router(self) -> APIRouter:
        import importlib

        mod = importlib.import_module(self.router_module)
        return getattr(mod, self.router_attr)

    def get_document_models(self) -> list[Any]:
        import importlib

        models = []
        for module_path, class_name in self.model_imports:
            mod = importlib.import_module(module_path)
            models.append(getattr(mod, class_name))
        return models


MODULES: list[AppModule] = [
    AppModule(
        name="auth",
        router_module="app.api.v1.auth",
        model_imports=[
            ("app.models.user", "User"),
            ("app.models.session", "UserSession"),
        ],
        tags=["Authentication"],
    ),
    AppModule(
        name="users",
        router_module="app.api.v1.users",
        model_imports=[],  # User/UserSession already owned by auth
        tags=["Users"],
    ),
    AppModule(
        name="automation",
        router_module="app.modules.automation.router",
        model_imports=[
            ("app.modules.automation.models.workflow", "Workflow"),
            ("app.modules.automation.models.execution", "WorkflowExecution"),
            ("app.modules.automation.models.webhook", "WebhookEvent"),
        ],
        tags=["Workflows"],
    ),
    AppModule(
        name="webhooks",
        router_module="app.api.v1.webhooks",
        model_imports=[],  # WebhookEvent already owned by automation
        tags=["Webhooks"],
    ),
    AppModule(
        name="backup",
        router_module="app.modules.backup.router",
        model_imports=[
            ("app.modules.backup.models", "BackupObject"),
            ("app.modules.backup.models", "BackupConfig"),
            ("app.modules.backup.models", "BackupJob"),
            ("app.modules.backup.models", "BackupLogEntry"),
        ],
        tags=["Backups"],
    ),
    AppModule(
        name="websocket",
        router_module="app.api.v1.ws",
        tags=["WebSocket"],
    ),
    AppModule(
        name="reports",
        router_module="app.modules.reports.router",
        model_imports=[
            ("app.modules.reports.models", "ReportJob"),
        ],
        tags=["Reports"],
    ),
    AppModule(
        name="dashboard",
        router_module="app.api.v1.dashboard",
        model_imports=[],
        tags=["Dashboard"],
    ),
    AppModule(
        name="admin",
        router_module="app.api.v1.admin",
        model_imports=[
            ("app.models.system", "SystemConfig"),
            ("app.models.system", "AuditLog"),
        ],
        tags=["Admin"],
    ),
    AppModule(
        name="llm",
        router_module="app.modules.llm.router",
        model_imports=[
            ("app.modules.llm.models", "LLMUsageLog"),
            ("app.modules.llm.models", "ConversationThread"),
        ],
        tags=["LLM"],
    ),
]


def get_all_document_models() -> list[Any]:
    """Return deduplicated Beanie document models from all enabled modules."""
    seen: set[Any] = set()
    models: list[Any] = []
    for module in MODULES:
        if not module.enabled:
            continue
        for model in module.get_document_models():
            if model not in seen:
                seen.add(model)
                models.append(model)
    return models
