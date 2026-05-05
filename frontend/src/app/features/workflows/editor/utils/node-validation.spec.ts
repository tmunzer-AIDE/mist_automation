import { isNodeConfigValid } from './node-validation';
import { WorkflowNode } from '../../../../core/models/workflow.model';

function makeSlackNode(config: Record<string, unknown>): WorkflowNode {
  return {
    id: 'slack-1',
    type: 'slack',
    name: 'Send to Slack',
    position: { x: 0, y: 0 },
    config,
    output_ports: [{ id: 'default', label: '', type: 'default' }],
    enabled: true,
    continue_on_error: false,
    max_retries: 0,
    retry_delay: 0,
    save_as: [],
  };
}

describe('isNodeConfigValid — Slack node', () => {
  it('is valid with channel + notification_template', () => {
    const node = makeSlackNode({
      notification_channel: 'https://hooks.slack.com/...',
      notification_template: 'Alert!',
    });
    expect(isNodeConfigValid(node)).toBe(true);
  });

  it('is valid with channel + slack_json_variable (the AI Alert recipe shape)', () => {
    const node = makeSlackNode({
      notification_channel: 'https://hooks.slack.com/...',
      slack_json_variable: '{{ nodes.AI_Agent.result }}',
    });
    expect(isNodeConfigValid(node)).toBe(true);
  });

  it('is invalid without channel', () => {
    const node = makeSlackNode({
      notification_template: 'Alert!',
    });
    expect(isNodeConfigValid(node)).toBe(false);
  });

  it('is invalid without either notification_template or slack_json_variable', () => {
    const node = makeSlackNode({
      notification_channel: 'https://hooks.slack.com/...',
    });
    expect(isNodeConfigValid(node)).toBe(false);
  });
});
