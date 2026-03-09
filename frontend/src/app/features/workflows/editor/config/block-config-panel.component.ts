import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, FormArray, FormControl } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import {
  PipelineBlock,
  WorkflowTrigger,
  WorkflowAction,
  ConditionBranch,
  ActionType,
  ApiCatalogEntry,
  VariableBinding,
} from '../../../../core/models/workflow.model';
import { WorkflowService } from '../../../../core/services/workflow.service';

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
    MatButtonModule,
    MatAutocompleteModule,
  ],
  templateUrl: './block-config-panel.component.html',
  styleUrl: './block-config-panel.component.scss',
})
export class BlockConfigPanelComponent implements OnChanges, OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly workflowService = inject(WorkflowService);

  @Input() block!: PipelineBlock;
  @Output() configChanged = new EventEmitter<PipelineBlock>();

  form!: FormGroup;
  catalogEntries: ApiCatalogEntry[] = [];
  filteredCatalog: ApiCatalogEntry[] = [];
  useCustomEndpoint = false;
  selectedCatalogEntry: ApiCatalogEntry | null = null;
  pathParamControls: FormGroup | null = null;
  queryParamControls: FormGroup | null = null;

  /** Separate form control for catalog search — not bound to api_endpoint */
  catalogSearchControl = new FormControl('');

  /** Guard to skip rebuilding form when the change came from our own emit */
  private emitting = false;

  ngOnInit(): void {
    this.workflowService.getApiCatalog().subscribe({
      next: (entries) => {
        this.catalogEntries = entries;
        this.applyMethodFilter();
        this.tryAutoSelectCatalogEntry();
      },
    });

    this.catalogSearchControl.valueChanges.subscribe(value => {
      this.filterCatalog(value || '');
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['block']) {
      if (this.emitting) {
        // Block was updated by our own emission — don't rebuild the form
        this.emitting = false;
        return;
      }
      this.buildForm();
    }
  }

  private buildForm(): void {
    switch (this.block.kind) {
      case 'trigger':
        this.buildTriggerForm();
        break;
      case 'action':
        this.buildActionForm();
        break;
    }

    this.form.valueChanges.subscribe(() => this.emitChanges());
  }

  private buildTriggerForm(): void {
    const data = this.block.data as WorkflowTrigger;
    const saveAsControls = (data.save_as || []).map(b =>
      this.fb.group({ name: [b.name || ''], expression: [b.expression || ''] })
    );
    this.form = this.fb.group({
      type: [data.type || 'webhook'],
      webhook_type: [data.webhook_type || ''],
      webhook_topic: [data.webhook_topic || ''],
      cron_expression: [data.cron_expression || ''],
      timezone: [data.timezone || 'UTC'],
      skip_if_running: [data.skip_if_running ?? true],
      condition: [data.condition || ''],
      save_as: this.fb.array(saveAsControls),
    });
  }

  private buildActionForm(): void {
    const data = this.block.data as WorkflowAction;

    // Reset catalog state
    this.selectedCatalogEntry = null;
    this.pathParamControls = null;
    this.queryParamControls = null;
    this.catalogSearchControl.setValue('', { emitEvent: false });

    // Build branches FormArray for condition actions
    const branchControls = (data.branches || []).map(b =>
      this.fb.group({ condition: [b.condition || ''] })
    );

    // Build save_as FormArray
    const saveAsControls = (data.save_as || []).map(b =>
      this.fb.group({ name: [b.name || ''], expression: [b.expression || ''] })
    );

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
      // Condition branches
      branches: this.fb.array(branchControls),
      // Delay
      delay_seconds: [data.delay_seconds || 0],
      // Variable storage — array of {name, expression} bindings
      save_as: this.fb.array(saveAsControls),
      // SET_VARIABLE fields
      variable_name: [data.variable_name || ''],
      variable_expression: [data.variable_expression || ''],
      // FOR_EACH fields
      loop_over: [data.loop_over || ''],
      loop_variable: [data.loop_variable || 'item'],
      max_iterations: [data.max_iterations ?? 100],
      // Retry / error handling
      max_retries: [data.max_retries ?? 3],
      retry_delay: [data.retry_delay ?? 5],
      continue_on_error: [data.continue_on_error ?? false],
    });

    // Determine initial mode and try to match existing endpoint to catalog
    this.applyMethodFilter();
    const matched = this.tryAutoSelectCatalogEntry();
    this.useCustomEndpoint = !!data.api_endpoint && !matched;
  }

  // ── Branches ─────────────────────────────────────────────────────

  get branchesArray(): FormArray {
    return this.form?.get('branches') as FormArray;
  }

  addBranch(): void {
    this.branchesArray.push(this.fb.group({ condition: [''] }));
  }

  removeBranch(index: number): void {
    this.branchesArray.removeAt(index);
  }

  // ── Save As (variable bindings) ──────────────────────────────────

  get saveAsArray(): FormArray {
    return this.form?.get('save_as') as FormArray;
  }

  addSaveAsBinding(): void {
    this.saveAsArray.push(this.fb.group({ name: [''], expression: [''] }));
  }

  removeSaveAsBinding(index: number): void {
    this.saveAsArray.removeAt(index);
  }

  // ── Catalog helpers ──────────────────────────────────────────────

  private getMethodForActionType(): string | null {
    switch (this.actionType) {
      case 'mist_api_get': return 'GET';
      case 'mist_api_post': return 'POST';
      case 'mist_api_put': return 'PUT';
      case 'mist_api_delete': return 'DELETE';
      default: return null;
    }
  }

  private applyMethodFilter(): void {
    const method = this.getMethodForActionType();
    this.filteredCatalog = method
      ? this.catalogEntries.filter(e => e.method === method)
      : this.catalogEntries;
  }

  filterCatalog(value: string): void {
    const search = (value || '').toLowerCase();
    const method = this.getMethodForActionType();
    this.filteredCatalog = this.catalogEntries.filter(
      e =>
        (!method || e.method === method) &&
        (e.label.toLowerCase().includes(search) ||
         e.category.toLowerCase().includes(search) ||
         e.description.toLowerCase().includes(search))
    );
  }

  selectCatalogEntry(entry: ApiCatalogEntry): void {
    this.selectedCatalogEntry = entry;
    this.catalogSearchControl.setValue('', { emitEvent: false });

    const pathGroup: Record<string, FormControl> = {};
    const currentEndpoint = this.form?.get('api_endpoint')?.value || '';
    for (const param of entry.path_params) {
      const existing = this.extractPathParamValue(param, entry.endpoint, currentEndpoint);
      pathGroup[param] = new FormControl(existing);
    }
    this.pathParamControls = this.fb.group(pathGroup);

    const queryGroup: Record<string, FormControl> = {};
    const existingParams = (this.block.data as WorkflowAction).api_params || {};
    for (const qp of entry.query_params) {
      queryGroup[qp.name] = new FormControl((existingParams as Record<string, unknown>)[qp.name] || '');
    }
    this.queryParamControls = this.fb.group(queryGroup);

    this.pathParamControls.valueChanges.subscribe(() => {
      this.rebuildEndpoint();
      this.emitChanges();
    });
    this.queryParamControls.valueChanges.subscribe(() => this.emitChanges());

    this.rebuildEndpoint();
  }

  clearCatalogSelection(): void {
    this.selectedCatalogEntry = null;
    this.pathParamControls = null;
    this.queryParamControls = null;
    this.form.patchValue({ api_endpoint: '' });
    this.catalogSearchControl.setValue('', { emitEvent: false });
    this.applyMethodFilter();
  }

  toggleCustomEndpoint(): void {
    this.useCustomEndpoint = !this.useCustomEndpoint;
    if (this.useCustomEndpoint) {
      this.selectedCatalogEntry = null;
      this.pathParamControls = null;
      this.queryParamControls = null;
    } else {
      this.form.patchValue({ api_endpoint: '' });
      this.catalogSearchControl.setValue('', { emitEvent: false });
      this.applyMethodFilter();
    }
  }

  private rebuildEndpoint(): void {
    if (!this.selectedCatalogEntry || !this.pathParamControls) return;
    let endpoint = this.selectedCatalogEntry.endpoint;
    const values = this.pathParamControls.getRawValue();
    for (const [param, value] of Object.entries(values)) {
      if (value) {
        endpoint = endpoint.replace(`{${param}}`, value as string);
      }
    }
    this.form.patchValue({ api_endpoint: endpoint }, { emitEvent: false });
  }

  private extractPathParamValue(param: string, template: string, currentEndpoint: string): string {
    if (!currentEndpoint) return '';
    const templateParts = template.split('/');
    const endpointParts = currentEndpoint.split('/');
    const paramPlaceholder = `{${param}}`;
    for (let i = 0; i < templateParts.length; i++) {
      if (templateParts[i] === paramPlaceholder && i < endpointParts.length) {
        const val = endpointParts[i];
        if (val && (!val.startsWith('{') || val.startsWith('{{'))) return val;
      }
    }
    return '';
  }

  private findCatalogEntryForEndpoint(endpoint: string | undefined): ApiCatalogEntry | null {
    if (!endpoint) return null;
    const method = this.getMethodForActionType();
    for (const entry of this.catalogEntries) {
      if (method && entry.method !== method) continue;
      const regex = new RegExp(
        '^' + entry.endpoint.replace(/\{[^}]+\}/g, '[^/]+') + '$'
      );
      if (regex.test(endpoint)) return entry;
    }
    return null;
  }

  private tryAutoSelectCatalogEntry(): boolean {
    if (!this.isApiAction) return false;
    const data = this.block.data as WorkflowAction;
    if (!data.api_endpoint) return false;
    const entry = this.findCatalogEntryForEndpoint(data.api_endpoint);
    if (entry) {
      this.selectCatalogEntry(entry);
      return true;
    }
    return false;
  }

  // ── Emit ─────────────────────────────────────────────────────────

  private emitChanges(): void {
    const raw = this.form.getRawValue();
    let updatedData: WorkflowTrigger | WorkflowAction;
    let label = this.block.label;

    switch (this.block.kind) {
      case 'trigger': {
        const triggerSaveAs: VariableBinding[] = raw.save_as || [];
        updatedData = {
          type: raw.type,
          webhook_type: raw.webhook_type || undefined,
          webhook_topic: raw.webhook_topic || undefined,
          cron_expression: raw.cron_expression || undefined,
          timezone: raw.timezone || 'UTC',
          skip_if_running: raw.skip_if_running,
          condition: raw.condition || undefined,
          save_as: triggerSaveAs.length > 0 ? triggerSaveAs : undefined,
        } as WorkflowTrigger;
        label =
          raw.type === 'webhook'
            ? `Webhook: ${raw.webhook_type || 'any'}`
            : `Cron: ${raw.cron_expression || ''}`;
        break;
      }

      case 'action': {
        const existingData = this.block.data as WorkflowAction;
        const formBranches: { condition: string }[] = raw.branches || [];
        const mergedBranches: ConditionBranch[] | undefined =
          formBranches.length > 0
            ? formBranches.map((fb: { condition: string }, i: number) => ({
                condition: fb.condition,
                actions: existingData.branches?.[i]?.actions || [],
              }))
            : undefined;

        // Collect query params from dynamic controls
        let apiParams: Record<string, unknown> | undefined;
        if (this.queryParamControls) {
          const qpValues = this.queryParamControls.getRawValue();
          const params: Record<string, string> = {};
          for (const [key, val] of Object.entries(qpValues)) {
            if (val) params[key] = val as string;
          }
          if (Object.keys(params).length > 0) {
            apiParams = params;
          }
        }

        // Collect save_as bindings
        const saveAsBindings: VariableBinding[] = raw.save_as || [];
        const saveAs = saveAsBindings.length > 0 ? saveAsBindings : undefined;

        updatedData = {
          name: raw.name,
          type: raw.type,
          enabled: raw.enabled,
          api_endpoint: raw.api_endpoint || undefined,
          api_params: apiParams,
          webhook_url: raw.webhook_url || undefined,
          notification_template: raw.notification_template || undefined,
          notification_channel: raw.notification_channel || undefined,
          branches: mergedBranches,
          else_actions: existingData.else_actions,
          delay_seconds: raw.delay_seconds || undefined,
          save_as: saveAs,
          variable_name: raw.variable_name || undefined,
          variable_expression: raw.variable_expression || undefined,
          loop_over: raw.loop_over || undefined,
          loop_variable: raw.loop_variable || undefined,
          loop_actions: existingData.loop_actions,
          max_iterations: raw.max_iterations || 100,
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

    this.emitting = true;
    this.configChanged.emit({
      ...this.block,
      data: updatedData!,
      label,
    });
  }

  // ── Getters ──────────────────────────────────────────────────────

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

  get isSetVariableAction(): boolean {
    return this.actionType === 'set_variable';
  }

  get isForEachAction(): boolean {
    return this.actionType === 'for_each';
  }

  /** Actions that produce output and can have save_as bindings */
  get hasOutput(): boolean {
    return this.isApiAction || this.isWebhookAction;
  }

  /** Actions that support retry/error handling */
  get hasErrorHandling(): boolean {
    return !this.isSetVariableAction && !this.isForEachAction && !this.isConditionAction && !this.isDelayAction;
  }

  get triggerType(): string {
    return this.form?.get('type')?.value || 'webhook';
  }
}
