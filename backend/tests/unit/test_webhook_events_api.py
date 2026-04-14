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

    async def test_list_webhook_events_filters_by_event_fields(self, client):
        now = datetime.now(timezone.utc)

        target_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='alarms',
            webhook_id='target-filter-event',
            payload={'topic': 'alarms'},
            event_type='ap_offline',
            org_name='Acme Corp',
            site_name='HQ West',
            device_name='AP-CORE-01',
            device_mac='aa:bb:cc:dd:ee:ff',
            event_details='Ethernet bad cable detected on uplink',
            received_at=now - timedelta(hours=1),
            event_timestamp=now - timedelta(hours=1),
        )
        non_match_event = WebhookEvent(
            webhook_type='device-events',
            webhook_topic='audits',
            webhook_id='other-filter-event',
            payload={'topic': 'audits'},
            event_type='switch_up',
            org_name='Other Org',
            site_name='Branch 1',
            device_name='SW-01',
            device_mac='11:22:33:44:55:66',
            event_details='Port up',
            received_at=now - timedelta(hours=1),
            event_timestamp=now - timedelta(hours=1),
        )
        await target_event.insert()
        await non_match_event.insert()

        response = await client.get(
            '/api/v1/webhooks/events?limit=1000'
            '&event_type=AP_OFF'
            '&org_name=acme'
            '&site_name=west'
            '&device_name=core'
            '&device_mac=bb:cc'
            '&event_details=bad%20cable'
            '&webhook_topic=alar'
        )

        assert response.status_code == 200
        data = response.json()
        event_ids = {event['webhook_id'] for event in data['events']}
        assert event_ids == {'target-filter-event'}
        assert data['total'] == 1
