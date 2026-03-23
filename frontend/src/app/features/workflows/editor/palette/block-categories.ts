import { ACTION_META } from '../../../../core/models/workflow-meta';
import { ActionType } from '../../../../core/models/workflow.model';

export interface BlockOption {
  kind: 'action';
  actionType?: string;
  label: string;
  icon: string;
  color: string;
  description: string;
}

export interface BlockCategory {
  name: string;
  options: BlockOption[];
}

function blockOption(actionType: ActionType, description: string): BlockOption {
  const meta = ACTION_META[actionType];
  return {
    kind: 'action',
    actionType,
    label: meta.label,
    icon: meta.icon,
    color: meta.color,
    description,
  };
}

export const BLOCK_CATEGORIES: BlockCategory[] = [
  {
    name: 'API Actions',
    options: [
      blockOption('mist_api_get', 'Fetch data from Mist API'),
      blockOption('mist_api_post', 'Create resource via Mist API'),
      blockOption('mist_api_put', 'Update resource via Mist API'),
      blockOption('mist_api_delete', 'Delete resource via Mist API'),
      blockOption('device_utils', 'Run device diagnostic (ping, traceroute, ARP, etc.)'),
    ],
  },
  {
    name: 'Flow Control',
    options: [
      blockOption('delay', 'Wait for a specified duration'),
      blockOption('wait_for_callback', 'Send Slack message and pause until button clicked'),
      blockOption('condition', 'Branch based on a condition'),
      blockOption('set_variable', 'Compute and store a variable'),
      blockOption('for_each', 'Iterate over a list with nested actions'),
    ],
  },
  {
    name: 'Sub-Flows',
    options: [blockOption('invoke_subflow', 'Call a reusable sub-flow workflow')],
  },
  {
    name: 'Data Processing',
    options: [
      blockOption('data_transform', 'Extract and filter fields from data'),
      blockOption('format_report', 'Format data as table report'),
    ],
  },
  {
    name: 'Notification',
    options: [
      blockOption('webhook', 'Send HTTP request to external URL'),
      blockOption('slack', 'Send Slack notification'),
      blockOption('servicenow', 'Create or update ServiceNow record'),
      blockOption('pagerduty', 'Trigger PagerDuty incident'),
      blockOption('email', 'Send email notification'),
      blockOption('syslog', 'Send message to Syslog server (RFC 5424 / CEF)'),
    ],
  },
  {
    name: 'App Actions',
    options: [
      blockOption('trigger_backup', 'Trigger a configuration backup'),
      blockOption('restore_backup', 'Restore a configuration from backup'),
      blockOption('compare_backups', 'Compare two backup snapshots'),
    ],
  },
  {
    name: 'AI',
    options: [blockOption('ai_agent', 'Autonomous AI agent with MCP tool access')],
  },
];

/** Sub-flow-only block: shown in palette only when editing a subflow workflow. */
export const SUBFLOW_OUTPUT_BLOCK: BlockOption = blockOption(
  'subflow_output',
  'Set outputs and end sub-flow execution'
);
