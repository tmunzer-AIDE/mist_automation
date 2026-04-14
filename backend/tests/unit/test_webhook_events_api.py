"""Unit tests for webhook events listing API."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.automation.models.webhook import WebhookEvent


@pytest.mark.unit
class TestWebhookEventsApi:
    async def test_list_webhook_events_filters_by_hours(self, client):
        now = datetime.now(timezone.utc)

        old_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='device-events',
            webhook_id='old-event',
            payload={'topic': 'device-events'},
            received_at=now - timedelta(hours=30),
            event_timestamp=now - timedelta(hours=30),
        )
        recent_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='device-events',
            webhook_id='recent-event',
            payload={'topic': 'device-events'},
            received_at=now - timedelta(hours=2),
            event_timestamp=now - timedelta(hours=2),
        )
        await old_event.insert()
        await recent_event.insert()

        response = await client.get('/api/v1/webhooks/events?hours=24&limit=1000')

        assert response.status_code == 200
        data = response.json()
        event_ids = {event['webhook_id'] for event in data['events']}
        assert 'recent-event' in event_ids
        assert 'old-event' not in event_ids
        assert data['total'] == 1

    async def test_list_webhook_events_without_hours_returns_all(self, client):
        now = datetime.now(timezone.utc)

        old_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='device-events',
            webhook_id='old-event-all',
            payload={'topic': 'device-events'},
            received_at=now - timedelta(hours=30),
            event_timestamp=now - timedelta(hours=30),
        )
        recent_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='device-events',
            webhook_id='recent-event-all',
            payload={'topic': 'device-events'},
            received_at=now - timedelta(hours=2),
            event_timestamp=now - timedelta(hours=2),
        )
        await old_event.insert()
        await recent_event.insert()

        response = await client.get('/api/v1/webhooks/events?limit=1000')

        assert response.status_code == 200
        data = response.json()
        event_ids = {event['webhook_id'] for event in data['events']}
        assert 'recent-event-all' in event_ids
        assert 'old-event-all' in event_ids
        assert data['total'] == 2
