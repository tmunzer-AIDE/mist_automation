import { WorkflowNode } from '../../../../core/models/workflow.model';

/**
 * Check if a workflow node has all required config fields populated.
 * Returns true if the node config is valid (all required fields present).
 */
export function isNodeConfigValid(node: WorkflowNode): boolean {
  const config = node.config || {};
  const type = node.type;

  if (type === 'trigger') {
    return isTriggerValid(config);
  }

  if (type === 'subflow_input' || type === 'subflow_output') {
    return true;
  }

  const rules = NODE_REQUIRED_FIELDS[type];
  if (!rules) {
    return true; // Unknown type — don't flag
  }

  if (typeof rules === 'function') {
    return rules(config);
  }

  return rules.every((field) => !!config[field]);
}

function isTriggerValid(config: Record<string, unknown>): boolean {
  const tt = config['trigger_type'];
  if (tt === 'manual') return true;
  if (tt === 'cron') return !!config['cron_expression'];
  if (tt === 'aggregated_webhook') {
    return (
      !!config['webhook_topic'] &&
      !!config['event_type_filter'] &&
      !!config['window_seconds'] &&
      !!config['group_by']
    );
  }
  // webhook (default)
  return !!config['webhook_topic'];
}

type ValidationRule = string[] | ((config: Record<string, unknown>) => boolean);

const NODE_REQUIRED_FIELDS: Record<string, ValidationRule> = {
  mist_api_get: ['api_endpoint'],
  mist_api_post: ['api_endpoint'],
  mist_api_put: ['api_endpoint'],
  mist_api_delete: ['api_endpoint'],
  webhook: ['webhook_url'],
  slack: (c) =>
    !!c['notification_channel'] && (!!c['notification_template'] || !!c['slack_json_variable']),
  email: ['notification_channel', 'notification_template', 'email_subject'],
  pagerduty: ['notification_channel', 'notification_template'],
  servicenow: (c) => !!c['servicenow_instance_url'] && !!c['servicenow_table'],
  condition: (c) => {
    const branches = c['branches'] as { condition: string }[] | undefined;
    return !!branches && branches.length > 0 && branches.some((b) => !!b.condition);
  },
  delay: (c) => Number(c['delay_seconds']) > 0,
  set_variable: ['variable_name', 'variable_expression'],
  for_each: ['loop_over'],
  data_transform: (c) => {
    const fields = c['fields'] as unknown[] | undefined;
    return !!c['source'] && !!fields && fields.length > 0;
  },
  format_report: ['data_source', 'format'],
  invoke_subflow: ['target_workflow_id'],
  device_utils: (c) => !!c['device_type'] && !!c['function'] && !!c['site_id'] && !!c['device_id'],
  ai_agent: ['agent_task'],
  wait_for_callback: (c) => {
    const actions = c['slack_actions'] as { text: string; action_id: string }[] | undefined;
    return !!c['notification_channel'] && !!actions && actions.length > 0 && actions.every((a) => !!a.text && !!a.action_id);
  },
};
