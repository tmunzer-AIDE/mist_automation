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
    ],
  },
  {
    name: 'Flow Control',
    options: [
      blockOption('delay', 'Wait for a specified duration'),
      blockOption('condition', 'Branch based on a condition'),
      blockOption('set_variable', 'Compute and store a variable'),
      blockOption('for_each', 'Iterate over a list with nested actions'),
    ],
  },
  {
    name: 'Notification',
    options: [
      blockOption('webhook', 'Send HTTP request to external URL'),
      blockOption('slack', 'Send Slack notification'),
      blockOption('servicenow', 'Create or update ServiceNow record'),
      blockOption('pagerduty', 'Trigger PagerDuty incident'),
    ],
  },
];
