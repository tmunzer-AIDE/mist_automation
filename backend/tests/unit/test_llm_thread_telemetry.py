"""Unit tests for thread context telemetry fields in GET /llm/threads/{id}."""

import pytest

from app.modules.llm.models import ConversationThread
from app.modules.llm.services.token_service import DEFAULT_CONTEXT_WINDOW


@pytest.mark.unit
class TestLlmThreadTelemetry:
    async def test_get_thread_context_metrics_without_compaction(self, client, test_user, monkeypatch):
        import app.modules.llm.services.token_service as token_service

        def _fake_count(messages, _model):
            return sum(len(m['content']) for m in messages)

        monkeypatch.setattr(token_service, 'count_message_tokens', _fake_count)

        thread = ConversationThread(user_id=test_user.id, feature='global_chat')
        thread.add_message('system', 'You are a network assistant.')
        thread.add_message('user', 'Question one')
        thread.add_message('assistant', 'Answer one')
        thread.add_message('user', 'Question two')
        thread.add_message('assistant', 'Answer two')
        await thread.insert()

        resp = await client.get(f'/api/v1/llm/threads/{thread.id}')
        assert resp.status_code == 200
        data = resp.json()

        prompt_messages = thread.get_messages_for_llm(max_turns=20)
        expected_tokens = _fake_count(prompt_messages, 'gpt-4o-mini')
        expected_percent = round((expected_tokens / DEFAULT_CONTEXT_WINDOW) * 100, 1)

        assert data['compacted'] is False
        assert data['context_window_tokens'] == DEFAULT_CONTEXT_WINDOW
        assert data['context_tokens_estimate'] == expected_tokens
        assert data['context_usage_percent'] == expected_percent
        assert data['compressed_messages'] == 0
        assert data['compression_ratio'] is None

    async def test_get_thread_context_metrics_with_compaction(self, client, test_user, monkeypatch):
        import app.modules.llm.services.token_service as token_service

        def _fake_count(messages, _model):
            return sum(len(m['content']) for m in messages)

        monkeypatch.setattr(token_service, 'count_message_tokens', _fake_count)

        thread = ConversationThread(user_id=test_user.id, feature='global_chat')
        thread.add_message('system', 'You are a network assistant.')
        thread.add_message(
            'user',
            'Walk me through every AP in our EMEA region, including model, firmware, and uplink switch port. '
            'I also need to know which RF templates are applied at each site.',
        )
        thread.add_message(
            'assistant',
            'Sure — across 5 EMEA sites you have 142 APs. Models: 87x AP43, 41x AP45, 14x AP63. '
            'Firmware mostly 0.14.x with 6 outliers on 0.12.x. Each site uses its own RF template '
            'matching the building topology; details follow per site.',
        )
        thread.add_message(
            'user',
            'Now do the same for the switches: model, port utilisation, PoE budget headroom, and any ports '
            'that have been flapping in the last 24 hours.',
        )
        thread.add_message(
            'assistant',
            'There are 38 EX4400 switches across the same sites. Average port utilisation 62%, PoE headroom '
            'ranges 18%-44%. Three ports have flapped >5 times in the last 24h: ge-0/0/12 on EMEA-PAR-01, '
            'ge-0/0/3 on EMEA-LON-02, ge-0/0/22 on EMEA-AMS-01.',
        )
        thread.add_message('user', 'Recent question')
        thread.add_message('assistant', 'Recent answer')

        thread.compaction_summary = 'User asked for EMEA AP+switch inventory; key sites and flapping ports noted.'
        thread.compacted_up_to_index = 5
        await thread.insert()

        resp = await client.get(f'/api/v1/llm/threads/{thread.id}')
        assert resp.status_code == 200
        data = resp.json()

        prompt_messages = thread.get_messages_for_llm(max_turns=20)
        expected_tokens = _fake_count(prompt_messages, 'gpt-4o-mini')
        expected_percent = round((expected_tokens / DEFAULT_CONTEXT_WINDOW) * 100, 1)

        full_history_tokens = _fake_count(
            [{'role': m.role, 'content': m.content} for m in thread.messages],
            'gpt-4o-mini',
        )

        compacted_slice = [m for m in thread.messages[: thread.compacted_up_to_index] if m.role != 'system']
        compacted_tokens = _fake_count(
            [{'role': m.role, 'content': m.content} for m in compacted_slice],
            'gpt-4o-mini',
        )
        summary_tokens = _fake_count(
            [{'role': 'system', 'content': thread.compaction_summary}],
            'gpt-4o-mini',
        )
        expected_ratio = round(compacted_tokens / summary_tokens, 2) if summary_tokens > 0 else None

        assert data['compacted'] is True
        assert data['context_window_tokens'] == DEFAULT_CONTEXT_WINDOW
        assert data['context_tokens_estimate'] == expected_tokens
        assert data['context_usage_percent'] == expected_percent
        assert data['compressed_messages'] == len(compacted_slice)
        assert data['compression_ratio'] == expected_ratio

        # Guard against regressions where telemetry counts full thread history instead of effective prompt messages.
        assert data['context_tokens_estimate'] < full_history_tokens
