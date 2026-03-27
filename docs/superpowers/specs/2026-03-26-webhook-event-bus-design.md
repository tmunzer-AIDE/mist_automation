# Webhook Event Bus Design

## Problem

The webhook gateway (`app/api/v1/webhooks.py`) hardcodes routing to each consumer module:

```python
routed_to = ["automation"]
if topic == "audits":
    routed_to.append("backup")
if webhook_type == "device-events":
    routed_to.append("impact_analysis")
```

Adding a new consumer requires:
1. Adding conditional routing logic in the gateway
2. Importing the handler function
3. Adding a `create_background_task()` call with module-specific arguments
4. Updating the `routed_to` list

This creates tight coupling between the gateway and every consumer. Each new module (telemetry, future modules) increases the complexity of `webhooks.py`.

## Design Goals

1. **Zero gateway changes** when adding a new webhook consumer
2. **Preserve existing dispatch semantics** — two dispatch phases (pre-split and per-event), sync and async modes
3. **Declarative subscriptions** — modules declare what they want in `AppModule`, not in gateway code
4. **Lightweight** — in-process event bus, no external broker needed

## Architecture

### WebhookSubscription

Added to `app/modules/__init__.py` alongside `AppModule`:

```python
@dataclass
class WebhookSubscription:
    """Declares a module's interest in webhook events."""
    handler: str                           # dotted import path to handler function
    topics: list[str] | None = None        # None = all topics
    event_types: list[str] | None = None   # None = all event types (per_event only)
    phase: str = "per_event"               # "pre_split" or "per_event"
    synchronous: bool = False              # True = awaited, result returned (pre_split only)
```

`AppModule` gets a new field:

```python
@dataclass
class AppModule:
    name: str
    router_module: str
    ...
    webhook_subscriptions: list[WebhookSubscription] = field(default_factory=list)
```

### WebhookEventContext

Standardized payload for `per_event` handlers. Defined in `app/core/event_bus.py`:

```python
@dataclass
class WebhookEventContext:
    event_id: str            # WebhookEvent document ID
    topic: str               # e.g. "device-events", "audits"
    event_type: str | None   # e.g. "AP_CONFIGURED"
    payload: dict            # enriched event payload
    site_id: str | None
    org_id: str | None
```

### EventBus

New file: `app/core/event_bus.py`

```python
class EventBus:
    """In-process webhook event dispatcher."""

    def __init__(self) -> None:
        self._pre_split: list[_ResolvedSubscription] = []
        self._per_event: list[_ResolvedSubscription] = []

    def register(self, module_name: str, sub: WebhookSubscription) -> None:
        """Register a subscription. Called at startup from module registry."""
        resolved = _ResolvedSubscription(
            module_name=module_name,
            handler_path=sub.handler,
            topics=set(sub.topics) if sub.topics else None,
            event_types=set(sub.event_types) if sub.event_types else None,
            synchronous=sub.synchronous,
            _handler=None,  # lazy-loaded
        )
        if sub.phase == "pre_split":
            self._pre_split.append(resolved)
        else:
            self._per_event.append(resolved)

    async def publish_pre_split(
        self, topic: str, payload: dict, config: SystemConfig
    ) -> dict[str, Any]:
        """Dispatch to pre-split subscribers. Returns {module_name: result}."""
        results = {}
        for sub in self._pre_split:
            if sub.topics and topic not in sub.topics:
                continue
            handler = sub.get_handler()
            if sub.synchronous:
                results[sub.module_name] = await handler(payload, config)
            else:
                create_background_task(
                    handler(payload, config),
                    name=f"webhook-{sub.module_name}-presplit",
                )
        return results

    async def publish_per_event(
        self, topic: str, ctx: WebhookEventContext
    ) -> None:
        """Dispatch to per-event subscribers as background tasks."""
        for sub in self._per_event:
            if sub.topics and topic not in sub.topics:
                continue
            if sub.event_types and ctx.event_type not in sub.event_types:
                continue
            handler = sub.get_handler()
            create_background_task(
                handler(ctx),
                name=f"webhook-{sub.module_name}-{ctx.event_id[:8]}",
            )

    def get_routed_to(self, topic: str, event_type: str | None = None) -> list[str]:
        """Return module names that would receive this topic/event_type combo.
        Used to populate WebhookEvent.routed_to before dispatch."""
        modules = set()
        for sub in self._pre_split:
            if not sub.topics or topic in sub.topics:
                modules.add(sub.module_name)
        for sub in self._per_event:
            if sub.topics and topic not in sub.topics:
                continue
            if sub.event_types and event_type and event_type not in sub.event_types:
                continue
            modules.add(sub.module_name)
        return sorted(modules)


# Module-level singleton
event_bus = EventBus()


def init_event_bus() -> None:
    """Called during app startup. Reads subscriptions from MODULES."""
    from app.modules import MODULES
    for module in MODULES:
        if not module.enabled:
            continue
        for sub in module.webhook_subscriptions:
            event_bus.register(module.name, sub)
```

### Module Registrations

```python
# In app/modules/__init__.py

MODULES = [
    ...
    AppModule(
        name="automation",
        router_module="app.modules.automation.router",
        webhook_subscriptions=[
            WebhookSubscription(
                handler="app.modules.automation.workers.webhook_worker.handle_webhook_event",
                # topics=None → all topics
            ),
        ],
        ...
    ),
    AppModule(
        name="backup",
        router_module="app.modules.backup.router",
        webhook_subscriptions=[
            WebhookSubscription(
                handler="app.modules.backup.webhook_handler.process_backup_webhook",
                topics=["audits"],
                phase="pre_split",
                synchronous=True,
            ),
        ],
        ...
    ),
    AppModule(
        name="impact_analysis",
        router_module="app.modules.impact_analysis.router",
        webhook_subscriptions=[
            WebhookSubscription(
                handler="app.modules.impact_analysis.workers.event_handler.handle_webhook_event",
                topics=["device-events"],
            ),
        ],
        ...
    ),
    ...
]
```

## Gateway Refactor

After the refactor, `webhooks.py` dispatch section becomes:

```python
from app.core.event_bus import event_bus, WebhookEventContext

# Determine routing targets (from subscriptions, not hardcoded)
routed_to = event_bus.get_routed_to(topic)

# Pre-split dispatch (backup gets full payload here)
pre_split_results = await event_bus.publish_pre_split(topic, payload, config)

# Split and process individual events
for idx, event in enumerate(events):
    enriched = enrich_event(event, topic, payload)
    fields = extract_event_fields(event, topic, payload)
    # ... create WebhookEvent document ...

    ctx = WebhookEventContext(
        event_id=str(webhook_event.id),
        topic=topic,
        event_type=fields["event_type"],
        payload=enriched,
        site_id=event.get("site_id") or payload.get("site_id"),
        org_id=event.get("org_id") or payload.get("org_id"),
    )
    await event_bus.publish_per_event(topic, ctx)

    # WebSocket broadcast (stays in gateway — infrastructure, not module concern)
    create_background_task(ws_manager.broadcast(...))
```

The gateway no longer imports any module handler. All routing is driven by `AppModule.webhook_subscriptions`.

## Handler Migration

Per-event handlers need to accept `WebhookEventContext` instead of positional args:

### Automation

```python
# Before:
async def process_webhook(webhook_id, webhook_type, payload, *, event_type=None)

# After: thin adapter
async def handle_webhook_event(ctx: WebhookEventContext) -> dict:
    return await process_webhook(ctx.event_id, ctx.topic, ctx.payload, event_type=ctx.event_type)
```

### Impact Analysis

```python
# Before:
async def handle_device_event(webhook_event_id, event_type, enriched_payload)

# After: thin adapter
async def handle_webhook_event(ctx: WebhookEventContext) -> None:
    await handle_device_event(ctx.event_id, ctx.event_type, ctx.payload)
```

### Backup

No changes needed — `process_backup_webhook(payload, config)` is called via `pre_split` phase which passes `(payload, config)` directly.

## Edge Cases

### Replay Endpoint

`POST /webhooks/events/{id}/replay` currently dispatches to automation only. Two options:
- **Option A**: Replay through the event bus (all subscribers re-process). More correct.
- **Option B**: Keep replay as automation-only (current behavior). Simpler.

Recommendation: **Option A** — replay should be consistent with normal processing. The replay endpoint builds a `WebhookEventContext` from the stored `WebhookEvent` and calls `event_bus.publish_per_event()`.

### WebSocket Monitor Broadcast

Stays in the gateway — it's infrastructure-level, not a module concern. Not routed through the event bus.

### `routed_to` Field Accuracy

Currently computed before dispatch. With the event bus, `event_bus.get_routed_to(topic, event_type)` provides the same information based on subscriptions. For pre-split subscribers, `get_routed_to` uses topic only; for per-event subscribers, it can also filter by event_type for more precise `routed_to` values.

### Startup Ordering

`init_event_bus()` must run after module registry is available but before the first webhook arrives. Add it to the FastAPI `lifespan` startup sequence, after `Database.connect_db()`.

## Future Extensions

- **Event type filtering on subscriptions**: Impact analysis could declare specific event types it cares about (PRE_CONFIG, CONFIGURED, etc.) instead of filtering internally. Optional — modules can still filter in their handlers.
- **Priority ordering**: If dispatch order matters, add a `priority: int` field to `WebhookSubscription`.
- **Telemetry module**: If telemetry needs webhook events in the future (currently uses WebSocket ingestion), it just adds a `WebhookSubscription` to its `AppModule` entry.
