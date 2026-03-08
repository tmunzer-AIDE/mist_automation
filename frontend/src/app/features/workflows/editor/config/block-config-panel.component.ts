import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import {
  PipelineBlock,
  WorkflowTrigger,
  WorkflowFilter,
  SecondaryFilter,
  WorkflowAction,
  FilterOperator,
  ActionType,
} from '../../../../core/models/workflow.model';

const FILTER_OPERATORS: { value: FilterOperator; label: string }[] = [
  { value: 'equals', label: 'Equals' },
  { value: 'not_equals', label: 'Not Equals' },
  { value: 'contains', label: 'Contains' },
  { value: 'not_contains', label: 'Not Contains' },
  { value: 'starts_with', label: 'Starts With' },
  { value: 'ends_with', label: 'Ends With' },
  { value: 'greater_than', label: 'Greater Than' },
  { value: 'less_than', label: 'Less Than' },
  { value: 'greater_equal', label: 'Greater or Equal' },
  { value: 'less_equal', label: 'Less or Equal' },
  { value: 'in', label: 'In' },
  { value: 'not_in', label: 'Not In' },
  { value: 'in_list', label: 'In List' },
  { value: 'not_in_list', label: 'Not In List' },
  { value: 'between', label: 'Between' },
  { value: 'is_true', label: 'Is True' },
  { value: 'is_false', label: 'Is False' },
  { value: 'exists', label: 'Exists' },
  { value: 'regex', label: 'Regex' },
];

@Component({
  selector: 'app-block-config-panel',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatIconModule,
  ],
  templateUrl: './block-config-panel.component.html',
  styleUrl: './block-config-panel.component.scss',
})
export class BlockConfigPanelComponent implements OnChanges {
  private readonly fb = inject(FormBuilder);

  @Input() block!: PipelineBlock;
  @Output() configChanged = new EventEmitter<PipelineBlock>();

  form!: FormGroup;
  filterOperators = FILTER_OPERATORS;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['block']) {
      this.buildForm();
    }
  }

  private buildForm(): void {
    switch (this.block.kind) {
      case 'trigger':
        this.buildTriggerForm();
        break;
      case 'filter':
        this.buildFilterForm();
        break;
      case 'secondary_filter':
        this.buildSecondaryFilterForm();
        break;
      case 'action':
        this.buildActionForm();
        break;
    }

    this.form.valueChanges.subscribe(() => this.emitChanges());
  }

  private buildTriggerForm(): void {
    const data = this.block.data as WorkflowTrigger;
    this.form = this.fb.group({
      type: [data.type || 'webhook'],
      webhook_type: [data.webhook_type || ''],
      webhook_topic: [data.webhook_topic || ''],
      cron_expression: [data.cron_expression || ''],
      timezone: [data.timezone || 'UTC'],
      skip_if_running: [data.skip_if_running ?? true],
    });
  }

  private buildFilterForm(): void {
    const data = this.block.data as WorkflowFilter;
    this.form = this.fb.group({
      field: [data.field || ''],
      operator: [data.operator || 'equals'],
      value: [typeof data.value === 'string' ? data.value : JSON.stringify(data.value ?? '')],
      case_sensitive: [data.case_sensitive ?? true],
      logic: [data.logic || 'and'],
    });
  }

  private buildSecondaryFilterForm(): void {
    const data = this.block.data as SecondaryFilter;
    this.form = this.fb.group({
      api_endpoint: [data.api_endpoint || ''],
      field: [data.field || ''],
      operator: [data.operator || 'equals'],
      value: [typeof data.value === 'string' ? data.value : JSON.stringify(data.value ?? '')],
      logic: [data.logic || 'and'],
    });
  }

  private buildActionForm(): void {
    const data = this.block.data as WorkflowAction;
    this.form = this.fb.group({
      name: [data.name || ''],
      type: [data.type],
      enabled: [data.enabled ?? true],
      // API fields
      api_endpoint: [data.api_endpoint || ''],
      api_body: [data.api_body ? JSON.stringify(data.api_body, null, 2) : ''],
      // Webhook fields
      webhook_url: [data.webhook_url || ''],
      webhook_headers: [
        data.webhook_headers ? JSON.stringify(data.webhook_headers, null, 2) : '',
      ],
      webhook_body: [
        data.webhook_body ? JSON.stringify(data.webhook_body, null, 2) : '',
      ],
      // Notification fields
      notification_template: [data.notification_template || ''],
      notification_channel: [data.notification_channel || ''],
      // Condition fields
      condition: [data.condition || ''],
      // Delay
      delay_seconds: [data.delay_seconds || 0],
      // Retry / error handling
      max_retries: [data.max_retries ?? 3],
      retry_delay: [data.retry_delay ?? 5],
      continue_on_error: [data.continue_on_error ?? false],
    });
  }

  private emitChanges(): void {
    const raw = this.form.getRawValue();
    let updatedData: WorkflowTrigger | WorkflowFilter | SecondaryFilter | WorkflowAction;
    let label = this.block.label;

    switch (this.block.kind) {
      case 'trigger':
        updatedData = {
          type: raw.type,
          webhook_type: raw.webhook_type || undefined,
          webhook_topic: raw.webhook_topic || undefined,
          cron_expression: raw.cron_expression || undefined,
          timezone: raw.timezone || 'UTC',
          skip_if_running: raw.skip_if_running,
        } as WorkflowTrigger;
        label =
          raw.type === 'webhook'
            ? `Webhook: ${raw.webhook_topic || raw.webhook_type || 'any'}`
            : `Cron: ${raw.cron_expression || ''}`;
        break;

      case 'filter':
        updatedData = {
          field: raw.field,
          operator: raw.operator,
          value: raw.value,
          case_sensitive: raw.case_sensitive,
          logic: raw.logic,
        } as WorkflowFilter;
        label = `${raw.field || 'field'} ${raw.operator} ${raw.value || ''}`;
        break;

      case 'secondary_filter':
        updatedData = {
          api_endpoint: raw.api_endpoint,
          field: raw.field,
          operator: raw.operator,
          value: raw.value,
          logic: raw.logic,
        } as SecondaryFilter;
        label = `${raw.api_endpoint || 'endpoint'}: ${raw.field} ${raw.operator}`;
        break;

      case 'action': {
        updatedData = {
          name: raw.name,
          type: raw.type,
          enabled: raw.enabled,
          api_endpoint: raw.api_endpoint || undefined,
          webhook_url: raw.webhook_url || undefined,
          notification_template: raw.notification_template || undefined,
          notification_channel: raw.notification_channel || undefined,
          condition: raw.condition || undefined,
          delay_seconds: raw.delay_seconds || undefined,
          max_retries: raw.max_retries,
          retry_delay: raw.retry_delay,
          continue_on_error: raw.continue_on_error,
        } as WorkflowAction;

        // Parse JSON fields
        if (raw.api_body) {
          try {
            (updatedData as WorkflowAction).api_body = JSON.parse(raw.api_body);
          } catch { /* keep as-is */ }
        }
        if (raw.webhook_headers) {
          try {
            (updatedData as WorkflowAction).webhook_headers = JSON.parse(raw.webhook_headers);
          } catch { /* keep as-is */ }
        }
        if (raw.webhook_body) {
          try {
            (updatedData as WorkflowAction).webhook_body = JSON.parse(raw.webhook_body);
          } catch { /* keep as-is */ }
        }

        label = raw.name || this.block.label;
        break;
      }
    }

    this.configChanged.emit({
      ...this.block,
      data: updatedData!,
      label,
    });
  }

  get actionType(): ActionType | null {
    if (this.block.kind !== 'action') return null;
    return (this.block.data as WorkflowAction).type;
  }

  get isApiAction(): boolean {
    const t = this.actionType;
    return t === 'mist_api_get' || t === 'mist_api_post' || t === 'mist_api_put' || t === 'mist_api_delete';
  }

  get isWebhookAction(): boolean {
    return this.actionType === 'webhook';
  }

  get isNotificationAction(): boolean {
    const t = this.actionType;
    return t === 'slack' || t === 'servicenow' || t === 'pagerduty';
  }

  get isDelayAction(): boolean {
    return this.actionType === 'delay';
  }

  get isConditionAction(): boolean {
    return this.actionType === 'condition';
  }

  get triggerType(): string {
    return this.form?.get('type')?.value || 'webhook';
  }
}
