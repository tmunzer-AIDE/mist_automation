import {
  Component,
  computed,
  DestroyRef,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ReactiveFormsModule,
  FormBuilder,
  FormGroup,
  FormArray,
  FormControl,
} from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subject, takeUntil } from 'rxjs';
import {
  WorkflowNode,
  ActionType,
  ApiCatalogEntry,
  DeviceUtilEntry,
  EventPair,
  VariableBinding,
  VariableTree,
  WorkflowType,
  SubflowParameter,
  WorkflowResponse,
  SubflowSchemaResponse,
} from '../../../../core/models/workflow.model';
import { LlmService } from '../../../../core/services/llm.service';
import { LlmConfigAvailable, McpConfigAvailable } from '../../../../core/models/llm.model';
import { WorkflowService } from '../../../../core/services/workflow.service';
import { VariablePickerComponent } from './variable-picker.component';
import { JsonSectionToggleComponent } from './json-section-toggle.component';
import { TemplateValidationDirective } from '../../../../shared/directives/template-validation.directive';
import { MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';

@Component({
  selector: 'app-node-config-panel',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatChipsModule,
    MatIconModule,
    MatButtonModule,
    MatAutocompleteModule,
    MatMenuModule,
    MatSlideToggleModule,
    MatExpansionModule,
    MatTooltipModule,
    VariablePickerComponent,
    JsonSectionToggleComponent,
    TemplateValidationDirective,
  ],
  template: `
    @if (node && form) {
      <div class="config-panel">
        <div class="panel-header">
          <h3 class="panel-title">{{ node.type === 'trigger' ? 'Trigger' : node.type === 'subflow_input' ? 'Sub-Flow Input' : node.type === 'subflow_output' ? 'Sub-Flow Output' : node.type === 'invoke_subflow' ? 'Sub-Flow Call' : 'Node' }} Config</h3>
        </div>

        <form [formGroup]="form" class="config-form">
          <!-- ── Trigger config ─────────────────────────────────────── -->
          @if (node.type === 'trigger') {
            <mat-form-field appearance="outline">
              <mat-label>Name</mat-label>
              <input matInput formControlName="name" />
            </mat-form-field>

            <mat-form-field appearance="outline">
              <mat-label>Trigger Type</mat-label>
              <input matInput [matAutocomplete]="triggerTypeAuto"
                     [value]="triggerTypeDisplayValue()"
                     (input)="triggerTypeSearch.set($any($event.target).value)">
              <mat-autocomplete #triggerTypeAuto (optionSelected)="form.get('trigger_type')!.setValue($event.option.value)">
                @for (opt of filteredTriggerTypes(); track opt.value) {
                  <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                }
              </mat-autocomplete>
            </mat-form-field>

            @if (form.get('trigger_type')?.value === 'webhook') {
              <mat-form-field appearance="outline">
                <mat-label>Webhook Topic</mat-label>
                <input matInput [matAutocomplete]="whTopicAuto"
                       [value]="webhookTopicDisplayValue()"
                       (input)="webhookTopicSearch.set($any($event.target).value)">
                <mat-autocomplete #whTopicAuto (optionSelected)="form.get('webhook_topic')!.setValue($event.option.value)">
                  @for (opt of filteredWebhookTopics(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Event Type Filter (optional)</mat-label>
                <input matInput formControlName="event_type_filter" />
              </mat-form-field>
            }

            @if (form.get('trigger_type')?.value === 'aggregated_webhook') {
              <mat-form-field appearance="outline">
                <mat-label>Event Pair</mat-label>
                <input matInput [matAutocomplete]="eventPairAuto"
                       (input)="eventPairSearch.set($any($event.target).value)">
                <mat-autocomplete #eventPairAuto (optionSelected)="onEventPairSelected($event.option.value)">
                  <mat-option value="">Custom</mat-option>
                  @for (pair of filteredEventPairs(); track pair.opening) {
                    <mat-option [value]="pair.opening">{{ pair.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Webhook Topic</mat-label>
                <input matInput [matAutocomplete]="aggWhTopicAuto"
                       [value]="aggWebhookTopicDisplayValue()"
                       (input)="aggWebhookTopicSearch.set($any($event.target).value)">
                <mat-autocomplete #aggWhTopicAuto (optionSelected)="form.get('webhook_topic')!.setValue($event.option.value)">
                  @for (opt of filteredAggWebhookTopics(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Opening Event Type</mat-label>
                <input matInput formControlName="event_type_filter" placeholder="e.g. AP_DISCONNECTED" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Closing Event Type (optional)</mat-label>
                <input matInput formControlName="closing_event_type" placeholder="e.g. AP_CONNECTED" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Device Key</mat-label>
                <input matInput formControlName="device_key" placeholder="device_mac" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Window Duration (seconds)</mat-label>
                <input matInput type="number" formControlName="window_seconds" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Group By</mat-label>
                <input matInput [matAutocomplete]="groupByAuto"
                       [value]="groupByDisplayValue()"
                       (input)="groupBySearch.set($any($event.target).value)">
                <mat-autocomplete #groupByAuto (optionSelected)="form.get('group_by')!.setValue($event.option.value)">
                  @for (opt of filteredGroupByOptions(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Min Events</mat-label>
                <input matInput type="number" formControlName="min_events" />
              </mat-form-field>
            }

            @if (form.get('trigger_type')?.value === 'cron') {
              <mat-form-field appearance="outline">
                <mat-label>Cron Expression</mat-label>
                <input matInput formControlName="cron_expression" placeholder="0 */6 * * *" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Timezone</mat-label>
                <input matInput formControlName="timezone" />
              </mat-form-field>
            }

            <mat-expansion-panel class="advanced-panel">
              <mat-expansion-panel-header>
                <mat-panel-title>Advanced</mat-panel-title>
              </mat-expansion-panel-header>
              <mat-form-field appearance="outline">
                <mat-label>Condition (optional)</mat-label>
                <textarea matInput formControlName="condition" rows="2"
                  placeholder="{{ '{{' }} type == 'ap_offline' {{ '}}' }}"></textarea>
              </mat-form-field>
              <mat-checkbox formControlName="skip_if_running">Skip if already running</mat-checkbox>
            </mat-expansion-panel>
          }

          <!-- ── Action config ──────────────────────────────────────── -->
          @if (node.type !== 'trigger') {
            <mat-form-field appearance="outline">
              <mat-label>Name</mat-label>
              <input matInput formControlName="name" />
            </mat-form-field>

            <!-- API action fields -->
            @if (isApiAction) {
              @if (!useCustomEndpoint && !selectedCatalogEntry) {
                <mat-form-field appearance="outline">
                  <mat-label>Search API endpoint...</mat-label>
                  <input matInput [formControl]="catalogSearchControl"
                    [matAutocomplete]="catalogAuto" />
                  <mat-autocomplete #catalogAuto="matAutocomplete">
                    @for (entry of filteredCatalog; track entry.id) {
                      <mat-option (onSelectionChange)="selectCatalogEntry(entry)">
                        <span class="catalog-label">{{ entry.label }}</span>
                        <span class="catalog-desc">{{ entry.description }}</span>
                      </mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
                <button mat-button (click)="toggleCustomEndpoint()">Use custom endpoint</button>
              }

              @if (selectedCatalogEntry) {
                <div class="selected-entry">
                  <span class="entry-method">{{ selectedCatalogEntry.method }}</span>
                  <span class="entry-label">{{ selectedCatalogEntry.label }}</span>
                  <button mat-icon-button (click)="clearCatalogSelection()">
                    <mat-icon>close</mat-icon>
                  </button>
                </div>

                @if (pathParamControls) {
                  <div class="params-section" [formGroup]="pathParamControls">
                    @for (param of selectedCatalogEntry.path_params; track param) {
                      <mat-form-field appearance="outline">
                        <mat-label>{{ param }}</mat-label>
                        <input matInput [formControlName]="param" />
                        <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                          <mat-icon>data_object</mat-icon>
                        </button>
                        <mat-menu #varMenu="matMenu">
                          <app-variable-picker
                            [variableTree]="variableTree"
                            (variableSelected)="insertIntoControl(pathParamControls!.get(param)!, $event)"
                          />
                        </mat-menu>
                      </mat-form-field>
                    }
                  </div>
                }

                @if (queryParamControls && selectedCatalogEntry.query_params.length > 0) {
                  <div class="params-section" [formGroup]="queryParamControls">
                    @for (qp of selectedCatalogEntry.query_params; track qp.name) {
                      <mat-form-field appearance="outline">
                        <mat-label>{{ qp.name }}</mat-label>
                        <input matInput [formControlName]="qp.name" />
                        <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                          <mat-icon>data_object</mat-icon>
                        </button>
                        <mat-menu #varMenu="matMenu">
                          <app-variable-picker
                            [variableTree]="variableTree"
                            (variableSelected)="insertIntoControl(queryParamControls!.get(qp.name)!, $event)"
                          />
                        </mat-menu>
                      </mat-form-field>
                    }
                  </div>
                }
              }

              @if (useCustomEndpoint) {
                <mat-form-field appearance="outline">
                  <mat-label>API Endpoint</mat-label>
                  <input matInput formControlName="api_endpoint" [appTemplateValidation]="variableTree" />
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #varMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="insertIntoControl(form.get('api_endpoint')!, $event)"
                    />
                  </mat-menu>
                </mat-form-field>
                <button mat-button (click)="toggleCustomEndpoint()">Use API catalog</button>
              }

              @if (node.type === 'mist_api_post' || node.type === 'mist_api_put') {
                <mat-form-field appearance="outline">
                  <mat-label>Request Body (JSON)</mat-label>
                  <textarea matInput formControlName="api_body" rows="4"></textarea>
                </mat-form-field>
              }
            }

            <!-- Webhook fields -->
            @if (node.type === 'webhook') {
              <mat-form-field appearance="outline">
                <mat-label>Webhook URL</mat-label>
                <input matInput formControlName="webhook_url" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="webhookUrlVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #webhookUrlVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('webhook_url')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Authentication</mat-label>
                <input matInput [matAutocomplete]="whAuthAuto"
                       [value]="webhookAuthDisplayValue()"
                       (input)="webhookAuthSearch.set($any($event.target).value)">
                <mat-autocomplete #whAuthAuto (optionSelected)="form.get('webhook_auth_type')!.setValue($event.option.value)">
                  @for (opt of filteredWebhookAuthTypes(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              @if (form.get('webhook_auth_type')?.value === 'oauth2_password') {
                <div class="section-title">OAuth 2.0 Credentials</div>
                <mat-form-field appearance="outline">
                  <mat-label>Token URL</mat-label>
                  <input
                    matInput
                    formControlName="oauth2_token_url"
                    placeholder="https://instance.service-now.com/oauth_token.do"
                  />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Client ID</mat-label>
                  <input matInput formControlName="oauth2_client_id" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Client Secret</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="oauth2_client_secret"
                    [placeholder]="
                      node.config['oauth2_client_secret_set']
                        ? 'Leave empty to keep current'
                        : ''
                    "
                  />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Username</mat-label>
                  <input matInput formControlName="oauth2_username" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Password</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="oauth2_password"
                    [placeholder]="
                      node.config['oauth2_password_set'] ? 'Leave empty to keep current' : ''
                    "
                  />
                </mat-form-field>
              }

              <mat-form-field appearance="outline">
                <mat-label>Headers (JSON)</mat-label>
                <textarea matInput formControlName="webhook_headers" rows="2" [appTemplateValidation]="variableTree"></textarea>
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Body (JSON)</mat-label>
                <textarea matInput formControlName="webhook_body" rows="3" [appTemplateValidation]="variableTree"></textarea>
              </mat-form-field>
            }

            <!-- ServiceNow fields -->
            @if (node.type === 'servicenow') {
              <mat-form-field appearance="outline">
                <mat-label>HTTP Method</mat-label>
                <input matInput [matAutocomplete]="snowMethodAuto"
                       [value]="snowMethodDisplayValue()"
                       (input)="snowMethodSearch.set($any($event.target).value)">
                <mat-autocomplete #snowMethodAuto (optionSelected)="form.get('servicenow_method')!.setValue($event.option.value)">
                  @for (opt of filteredSnowMethods(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Instance URL</mat-label>
                <input
                  matInput
                  formControlName="servicenow_instance_url"
                  placeholder="https://instance.service-now.com"
                />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Table</mat-label>
                <input matInput formControlName="servicenow_table" placeholder="incident" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Authentication</mat-label>
                <input matInput [matAutocomplete]="snowAuthAuto"
                       [value]="snowAuthDisplayValue()"
                       (input)="snowAuthSearch.set($any($event.target).value)">
                <mat-autocomplete #snowAuthAuto (optionSelected)="form.get('servicenow_auth_type')!.setValue($event.option.value)">
                  @for (opt of filteredSnowAuthTypes(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              @if (form.get('servicenow_auth_type')?.value === 'basic') {
                <mat-form-field appearance="outline">
                  <mat-label>Username</mat-label>
                  <input matInput formControlName="servicenow_username" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Password</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="servicenow_password"
                    [placeholder]="
                      node.config['servicenow_password_set']
                        ? 'Leave empty to keep current'
                        : ''
                    "
                  />
                </mat-form-field>
              }

              @if (form.get('servicenow_auth_type')?.value === 'oauth2_password') {
                <div class="section-title">OAuth 2.0 Credentials</div>
                <mat-form-field appearance="outline">
                  <mat-label>Token URL</mat-label>
                  <input
                    matInput
                    formControlName="oauth2_token_url"
                    placeholder="https://instance.service-now.com/oauth_token.do"
                  />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Client ID</mat-label>
                  <input matInput formControlName="oauth2_client_id" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Client Secret</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="oauth2_client_secret"
                    [placeholder]="
                      node.config['oauth2_client_secret_set']
                        ? 'Leave empty to keep current'
                        : ''
                    "
                  />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Username</mat-label>
                  <input matInput formControlName="oauth2_username" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Password</mat-label>
                  <input
                    matInput
                    type="password"
                    formControlName="oauth2_password"
                    [placeholder]="
                      node.config['oauth2_password_set']
                        ? 'Leave empty to keep current'
                        : ''
                    "
                  />
                </mat-form-field>
              }

              @if (
                form.get('servicenow_method')?.value === 'POST' ||
                form.get('servicenow_method')?.value === 'PUT'
              ) {
                <mat-form-field appearance="outline">
                  <mat-label>Body (JSON)</mat-label>
                  <textarea matInput formControlName="servicenow_body" rows="3" [appTemplateValidation]="variableTree"></textarea>
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="snowBodyVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #snowBodyVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="
                        insertIntoControl(form.get('servicenow_body')!, $event)
                      "
                    />
                  </mat-menu>
                </mat-form-field>
              }

              @if (form.get('servicenow_method')?.value === 'GET') {
                <mat-form-field appearance="outline">
                  <mat-label>Query Params (JSON)</mat-label>
                  <textarea
                    matInput
                    formControlName="servicenow_query_params"
                    rows="2"
                    placeholder='{"sysparm_query": "active=true", "sysparm_limit": "10"}'
                    [appTemplateValidation]="variableTree"
                  ></textarea>
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="snowQueryVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #snowQueryVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="
                        insertIntoControl(form.get('servicenow_query_params')!, $event)
                      "
                    />
                  </mat-menu>
                </mat-form-field>
              }
            }

            <!-- Notification fields -->
            @if (isNotificationAction) {
              <mat-form-field appearance="outline">
                <mat-label>{{ node.type === 'slack' ? 'Slack Webhook URL' : 'Channel' }}</mat-label>
                <input matInput formControlName="notification_channel" />
              </mat-form-field>

              @if (node.type === 'slack') {
                <mat-form-field appearance="outline">
                  <mat-label>Header (optional)</mat-label>
                  <input matInput formControlName="slack_header" [appTemplateValidation]="variableTree" />
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="slackHeaderVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #slackHeaderVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="insertIntoControl(form.get('slack_header')!, $event)"
                    />
                  </mat-menu>
                </mat-form-field>
              }

              <mat-form-field appearance="outline">
                <mat-label>Message Template</mat-label>
                <textarea matInput formControlName="notification_template" rows="3" [appTemplateValidation]="variableTree"></textarea>
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('notification_template')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              @if (node.type === 'slack') {
                <app-json-section-toggle
                  sectionLabel="Key-Value Fields (optional)"
                  [sectionData]="slackFieldsArray.getRawValue()"
                  (dataChanged)="applySlackFieldsJson($event)"
                >
                  @for (field of slackFieldsArray.controls; track $index; let i = $index) {
                    <div class="branch-row" [formGroup]="$any(field)">
                      <mat-form-field appearance="outline" class="save-as-name">
                        <mat-label>Label</mat-label>
                        <input matInput formControlName="label" />
                      </mat-form-field>
                      <mat-form-field appearance="outline" class="save-as-name">
                        <mat-label>Value</mat-label>
                        <input matInput formControlName="value" />
                      </mat-form-field>
                      <button mat-icon-button (click)="removeSlackField(i)">
                        <mat-icon>close</mat-icon>
                      </button>
                    </div>
                  }
                  <button mat-button (click)="addSlackField()">
                    <mat-icon>add</mat-icon> Add Field
                  </button>
                </app-json-section-toggle>

                <mat-form-field appearance="outline">
                  <mat-label>Footer (optional)</mat-label>
                  <input matInput formControlName="slack_footer" [appTemplateValidation]="variableTree" />
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="slackFooterVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #slackFooterVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="insertIntoControl(form.get('slack_footer')!, $event)"
                    />
                  </mat-menu>
                </mat-form-field>

                <mat-form-field appearance="outline">
                  <mat-label>JSON Payload (optional)</mat-label>
                  <input matInput formControlName="slack_json_variable" placeholder="trigger" [appTemplateValidation]="variableTree" />
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="jsonVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #jsonVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="insertJsonVariablePath($event)"
                    />
                  </mat-menu>
                  <mat-hint
                    >Renders the variable as Slack content: plain text → mrkdwn sections
                    (auto-chunked at 3,000 chars), structured data → formatted JSON code block,
                    Slack-ready Block Kit → used directly</mat-hint
                  >
                </mat-form-field>

                <div class="slack-guidance">
                  <mat-icon>info_outline</mat-icon>
                  <div class="slack-guidance-text">
                    <p>Use <strong>Message Template</strong> for simple alerts. If a previous node produced Slack-ready blocks, they are included automatically. If you want to send AI text directly, use the AI result variable or start from the recipe.</p>
                    <details class="slack-guidance-more">
                      <summary>Show more</summary>
                      <p>Common Markdown emphasis (bold, strikethrough) and simple Markdown links in text sent to Slack through the normal text path (especially AI-generated output) are automatically converted to Slack mrkdwn. Code blocks and inline code spans are preserved verbatim; unsupported constructs are left as-is. The conversion handles double-asterisk bold (<code>**bold**</code> &rarr; <code>*bold*</code>) and double-underscore bold (<code>__bold__</code> &rarr; <code>*bold*</code>), strikethrough (<code>~~strike~~</code> &rarr; <code>~strike~</code>), and links (<code>[text](url)</code> &rarr; <code>&lt;url|text&gt;</code>). Markdown lists and blockquotes render natively in Slack mrkdwn; no conversion is performed or needed. Single-asterisk italic is <strong>not</strong> auto-converted in v1.</p>
                      <p><strong>Note:</strong> If you need to use hand-authored Slack mrkdwn (e.g., <code>*bold*</code> for emphasis), disable <strong>Auto-convert Markdown to Slack mrkdwn</strong> in the Slack node settings. When disabled, the text is sent to Slack unchanged.</p>
                    </details>
                  </div>
                </div>

                <mat-checkbox formControlName="auto_convert_markdown">
                  Auto-convert Markdown to Slack mrkdwn
                  <mat-icon
                    matTooltip="Converts common AI-generated Markdown (**bold**, __bold__, ~~strike~~, and simple links) before sending to Slack. Disable this if you hand-write Slack mrkdwn and want it sent unchanged."
                    matTooltipPosition="above"
                    aria-label="More information about Markdown auto-conversion"
                    tabindex="0"
                    (click)="$event.stopPropagation()"
                    (keydown)="$event.stopPropagation()"
                    >info</mat-icon
                  >
                </mat-checkbox>

                <div class="config-hint">
                  <mat-icon>info_outline</mat-icon>
                  If an upstream Format Report uses Slack format, its table is automatically
                  included below the message.
                </div>
              }
            }

            <!-- Wait for Callback -->
            @if (node.type === 'wait_for_callback') {
              <mat-form-field appearance="outline">
                <mat-label>Slack Webhook URL</mat-label>
                <input matInput formControlName="notification_channel" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Header (optional)</mat-label>
                <input matInput formControlName="slack_header" [appTemplateValidation]="variableTree" />
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Message Template</mat-label>
                <textarea matInput formControlName="notification_template" rows="3" [appTemplateValidation]="variableTree"></textarea>
                <button mat-icon-button matSuffix [matMenuTriggerFor]="waitVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #waitVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('notification_template')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <div class="section-label">Action Buttons</div>
              @for (action of waitActionsArray.controls; track action; let i = $index) {
                <div class="inline-row">
                  <mat-form-field appearance="outline" class="flex-1">
                    <mat-label>Button Text</mat-label>
                    <input matInput [formControl]="$any(action).controls.text" />
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="flex-1">
                    <mat-label>Action ID</mat-label>
                    <input matInput [formControl]="$any(action).controls.action_id" />
                  </mat-form-field>
                  <mat-form-field appearance="outline" style="width: 120px">
                    <mat-label>Style</mat-label>
                    <input matInput [matAutocomplete]="waitStyleAuto"
                           [value]="waitStyleDisplay($any(action).controls.style.value)"
                           readonly>
                    <mat-autocomplete #waitStyleAuto (optionSelected)="$any(action).controls.style.setValue($event.option.value)">
                      @for (opt of waitStyleOptions; track opt.value) {
                        <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                      }
                    </mat-autocomplete>
                  </mat-form-field>
                  <button mat-icon-button color="warn" (click)="removeWaitAction(i)">
                    <mat-icon>delete</mat-icon>
                  </button>
                </div>
              }
              <button mat-stroked-button (click)="addWaitAction()">
                <mat-icon>add</mat-icon> Add Button
              </button>

              <mat-form-field appearance="outline" style="margin-top: 16px">
                <mat-label>Timeout (seconds, optional)</mat-label>
                <input matInput type="number" formControlName="timeout_seconds" />
                <mat-hint>Auto-fail if no response within this time (0 = no timeout)</mat-hint>
              </mat-form-field>
            }

            <!-- Delay -->
            @if (node.type === 'delay') {
              <mat-form-field appearance="outline">
                <mat-label>Delay (seconds)</mat-label>
                <input matInput type="number" formControlName="delay_seconds" />
              </mat-form-field>
            }

            <!-- Set Variable -->
            @if (node.type === 'set_variable') {
              @for (ctrl of variablesArray.controls; track $index; let i = $index) {
                <div class="variable-row">
                  <mat-form-field appearance="outline" class="var-name">
                    <mat-label>Name</mat-label>
                    <input matInput [formControl]="$any(ctrl).controls.name" placeholder="my_variable" />
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="var-expr">
                    <mat-label>Value</mat-label>
                    <input matInput [formControl]="$any(ctrl).controls.expression" [appTemplateValidation]="variableTree" />
                  </mat-form-field>
                  @if (variablesArray.length > 1) {
                    <button mat-icon-button (click)="removeVariable(i)" class="var-remove">
                      <mat-icon>close</mat-icon>
                    </button>
                  }
                </div>
              }
              <button mat-button (click)="addVariable()" class="add-variable-btn">
                <mat-icon>add</mat-icon> Add Variable
              </button>
            }

            <!-- For Each -->
            @if (node.type === 'for_each') {
              <mat-form-field appearance="outline">
                <mat-label>Loop Over (dot path)</mat-label>
                <input matInput formControlName="loop_over" placeholder="nodes.MyApiCall.body.results" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('loop_over')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Loop Variable Name</mat-label>
                <input matInput formControlName="loop_variable" />
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Max Iterations</mat-label>
                <input matInput type="number" formControlName="max_iterations" />
              </mat-form-field>
              <mat-slide-toggle formControlName="parallel">Run iterations in parallel</mat-slide-toggle>
              @if (form.get('parallel')?.value) {
                <mat-form-field appearance="outline">
                  <mat-label>Max Concurrent</mat-label>
                  <input matInput type="number" formControlName="max_concurrent" />
                </mat-form-field>
              }
            }

            <!-- Data Transform -->
            @if (node.type === 'data_transform') {
              <mat-form-field appearance="outline">
                <mat-label>Source (dot path to array)</mat-label>
                <input matInput formControlName="dt_source" placeholder="nodes.Get_Devices.body" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('dt_source')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <app-json-section-toggle
                sectionLabel="Fields to Extract"
                [sectionData]="dtFieldsArray.getRawValue()"
                (dataChanged)="applyDtFieldsJson($event)"
              >
                @for (field of dtFieldsArray.controls; track $index; let i = $index) {
                  <div class="branch-row" [formGroup]="$any(field)">
                    <mat-form-field appearance="outline" class="save-as-name">
                      <mat-label>Path</mat-label>
                      <input matInput formControlName="path" placeholder="port_stat.eth0.up" />
                      <button mat-icon-button matSuffix [matMenuTriggerFor]="dtPathVarMenu">
                        <mat-icon>data_object</mat-icon>
                      </button>
                      <mat-menu #dtPathVarMenu="matMenu">
                        <app-variable-picker
                          [variableTree]="variableTree"
                          (variableSelected)="insertDtFieldPath(i, $event)"
                        />
                      </mat-menu>
                    </mat-form-field>
                    <mat-form-field appearance="outline" class="save-as-name">
                      <mat-label>Label</mat-label>
                      <input matInput formControlName="label" placeholder="Eth0 Up" />
                    </mat-form-field>
                    @if (dtFieldsArray.length > 1) {
                      <button mat-icon-button (click)="removeDtField(i)">
                        <mat-icon>close</mat-icon>
                      </button>
                    }
                  </div>
                }
                <button mat-button (click)="addDtField()">
                  <mat-icon>add</mat-icon> Add Field
                </button>
              </app-json-section-toggle>

              <mat-form-field appearance="outline">
                <mat-label>Filter Condition (optional)</mat-label>
                <input matInput formControlName="dt_filter" [appTemplateValidation]="variableTree"
                  placeholder="{{ '{{' }} item.type == 'switch' {{ '}}' }}" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="filterVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #filterVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('dt_filter')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
            }

            <!-- Format Report -->
            @if (node.type === 'format_report') {
              <mat-form-field appearance="outline">
                <mat-label>Data Source (dot path to rows)</mat-label>
                <input matInput formControlName="fr_data_source" [appTemplateValidation]="variableTree"
                  placeholder="nodes.Transform_Data.rows" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('fr_data_source')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Columns Source (optional, dot path)</mat-label>
                <input matInput formControlName="fr_columns_source"
                  placeholder="nodes.Transform_Data.columns" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="colVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #colVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('fr_columns_source')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Format</mat-label>
                <input matInput [matAutocomplete]="frFormatAuto"
                       [value]="frFormatDisplayValue()"
                       (input)="frFormatSearch.set($any($event.target).value)">
                <mat-autocomplete #frFormatAuto (optionSelected)="form.get('fr_format')!.setValue($event.option.value)">
                  @for (opt of filteredFrFormats(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Title (optional)</mat-label>
                <input matInput formControlName="fr_title" [appTemplateValidation]="variableTree"
                  placeholder="Deployment Report - {{ '{{' }} trigger.site_name {{ '}}' }}" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="titleVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #titleVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('fr_title')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Footer (optional)</mat-label>
                <input matInput formControlName="fr_footer_template" [appTemplateValidation]="variableTree"
                  placeholder="Generated at {{ '{{' }} now_iso {{ '}}' }}" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="footerVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #footerVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('fr_footer_template')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
            }

            <!-- Email extra fields -->
            @if (node.type === 'email') {
              <mat-form-field appearance="outline">
                <mat-label>Subject</mat-label>
                <input matInput formControlName="email_subject" [appTemplateValidation]="variableTree"
                  placeholder="Deployment Report - {{ '{{' }} trigger.site_name {{ '}}' }}" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="subjVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #subjVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('email_subject')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
              <mat-checkbox formControlName="email_html">Send as HTML</mat-checkbox>
            }

            <!-- Syslog -->
            @if (node.type === 'syslog') {
              <div class="syslog-row">
                <mat-form-field appearance="outline" class="syslog-host">
                  <mat-label>Syslog Host</mat-label>
                  <input matInput formControlName="syslog_host" placeholder="syslog.example.com" [appTemplateValidation]="variableTree" />
                </mat-form-field>
                <mat-form-field appearance="outline" class="syslog-port">
                  <mat-label>Port</mat-label>
                  <input matInput type="number" formControlName="syslog_port" />
                </mat-form-field>
              </div>

              <div class="syslog-row">
                <mat-form-field appearance="outline">
                  <mat-label>Protocol</mat-label>
                  <input matInput [matAutocomplete]="sysProtocolAuto"
                         [value]="syslogProtocolDisplayValue()"
                         (input)="syslogProtocolSearch.set($any($event.target).value)">
                  <mat-autocomplete #sysProtocolAuto (optionSelected)="form.get('syslog_protocol')!.setValue($event.option.value)">
                    @for (opt of filteredSyslogProtocols(); track opt.value) {
                      <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Format</mat-label>
                  <input matInput [matAutocomplete]="sysFormatAuto"
                         [value]="syslogFormatDisplayValue()"
                         (input)="syslogFormatSearch.set($any($event.target).value)">
                  <mat-autocomplete #sysFormatAuto (optionSelected)="form.get('syslog_format')!.setValue($event.option.value)">
                    @for (opt of filteredSyslogFormats(); track opt.value) {
                      <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
              </div>

              <div class="syslog-row">
                <mat-form-field appearance="outline">
                  <mat-label>Facility</mat-label>
                  <input matInput [matAutocomplete]="sysFacilityAuto"
                         [value]="syslogFacilityDisplayValue()"
                         (input)="syslogFacilitySearch.set($any($event.target).value)">
                  <mat-autocomplete #sysFacilityAuto (optionSelected)="form.get('syslog_facility')!.setValue($event.option.value)">
                    @for (opt of filteredSyslogFacilities(); track opt.value) {
                      <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>Severity</mat-label>
                  <input matInput [matAutocomplete]="sysSeverityAuto"
                         [value]="syslogSeverityDisplayValue()"
                         (input)="syslogSeveritySearch.set($any($event.target).value)">
                  <mat-autocomplete #sysSeverityAuto (optionSelected)="form.get('syslog_severity')!.setValue($event.option.value)">
                    @for (opt of filteredSyslogSeverities(); track opt.value) {
                      <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
              </div>

              <mat-form-field appearance="outline">
                <mat-label>Message Template</mat-label>
                <textarea matInput formControlName="notification_template" rows="3" [appTemplateValidation]="variableTree"></textarea>
                <button mat-icon-button matSuffix [matMenuTriggerFor]="syslogVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #syslogVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('notification_template')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              @if (form.value.syslog_format === 'cef') {
                <mat-form-field appearance="outline">
                  <mat-label>CEF Device Vendor</mat-label>
                  <input matInput formControlName="cef_device_vendor" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>CEF Device Product</mat-label>
                  <input matInput formControlName="cef_device_product" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>CEF Event Class ID</mat-label>
                  <input matInput formControlName="cef_event_class_id" [appTemplateValidation]="variableTree" />
                </mat-form-field>
                <mat-form-field appearance="outline">
                  <mat-label>CEF Name</mat-label>
                  <input matInput formControlName="cef_name" [appTemplateValidation]="variableTree" />
                </mat-form-field>
              }
            }

            <!-- Script (JavaScript) -->
            @if (node.type === 'script') {
              <p class="field-help">
                Write JavaScript code. Access upstream data via <code>inputs</code> object
                (<code>inputs.trigger</code>, <code>inputs.nodes.NodeName</code>).
                Return a value with <code>return</code>.
              </p>
              <mat-form-field appearance="outline">
                <mat-label>JavaScript Code</mat-label>
                <textarea
                  matInput
                  formControlName="script_code"
                  rows="12"
                  class="code-editor"
                  spellcheck="false"
                  placeholder="// Example: cross-reference two datasets
var apList = inputs.nodes.Get_AP_Stats;
var neighbors = inputs.nodes.Get_RRM_Neighbors.results;

// Find APs safe to disable
var activeMacs = new Set(
  apList.filter(ap => ap.num_clients > 0).map(ap => ap.mac)
);

var protectedMacs = new Set();
neighbors.forEach(entry => {
  if (activeMacs.has(entry.mac)) {
    entry.neighbors.forEach(n => protectedMacs.add(n.mac));
  }
});

return apList.filter(ap =>
  ap.num_clients === 0 &&
  !protectedMacs.has(ap.mac)
).map(ap => ({ id: ap.id, mac: ap.mac, name: ap.name }));"
                ></textarea>
              </mat-form-field>
            }

            <!-- Device Utils -->
            @if (isDeviceUtilAction) {
              <mat-form-field appearance="outline">
                <mat-label>Device Type</mat-label>
                <input matInput [matAutocomplete]="duDeviceTypeAuto"
                       [value]="duDeviceTypeDisplayValue()"
                       (input)="duDeviceTypeSearch.set($any($event.target).value)">
                <mat-autocomplete #duDeviceTypeAuto (optionSelected)="form.get('du_device_type')!.setValue($event.option.value)">
                  @for (opt of filteredDuDeviceTypes(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              @if (form.get('du_device_type')?.value) {
                <mat-form-field appearance="outline">
                  <mat-label>Utility Function</mat-label>
                  <input matInput [matAutocomplete]="duFunctionAuto"
                         [value]="duFunctionDisplayValue()"
                         (input)="duFunctionSearch.set($any($event.target).value)">
                  <mat-autocomplete #duFunctionAuto (optionSelected)="form.get('du_function')!.setValue($event.option.value)">
                    @for (entry of searchFilteredDeviceFunctions(); track entry.id) {
                      <mat-option [value]="entry.function">{{ entry.label }}</mat-option>
                    }
                  </mat-autocomplete>
                </mat-form-field>
              }

              <mat-form-field appearance="outline">
                <mat-label>Site ID</mat-label>
                <input matInput formControlName="du_site_id" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="duSiteVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #duSiteVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('du_site_id')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Device ID</mat-label>
                <input matInput formControlName="du_device_id" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="duDeviceVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #duDeviceVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('du_device_id')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              @if (selectedDeviceEntry && deviceParamControls) {
                <div class="section-title">Parameters</div>
                <div class="params-section" [formGroup]="deviceParamControls">
                  @for (param of selectedDeviceEntry.params; track param.name) {
                    <mat-form-field appearance="outline">
                      <mat-label>{{ param.name }}{{ param.required ? ' *' : '' }}</mat-label>
                      <input matInput [formControlName]="param.name" />
                      <button mat-icon-button matSuffix [matMenuTriggerFor]="duParamVarMenu">
                        <mat-icon>data_object</mat-icon>
                      </button>
                      <mat-menu #duParamVarMenu="matMenu">
                        <app-variable-picker
                          [variableTree]="variableTree"
                          (variableSelected)="insertIntoControl(deviceParamControls!.get(param.name)!, $event)"
                        />
                      </mat-menu>
                      @if (param.description) {
                        <mat-hint>{{ param.description }}</mat-hint>
                      }
                    </mat-form-field>
                  }
                </div>
              }
            }

            <!-- AI Agent -->
            @if (isAiAgentAction) {
              <mat-form-field appearance="outline">
                <mat-label>LLM Configuration</mat-label>
                <input matInput [matAutocomplete]="llmConfigAuto"
                       [value]="llmConfigDisplayValue()"
                       (input)="llmConfigSearch.set($any($event.target).value)">
                <mat-autocomplete #llmConfigAuto (optionSelected)="form.get('llm_config_id')!.setValue($event.option.value)">
                  <mat-option value="">Default</mat-option>
                  @for (cfg of filteredLlmConfigs(); track cfg.id) {
                    <mat-option [value]="cfg.id">
                      {{ cfg.name }} ({{ cfg.provider }})
                      @if (cfg.is_default) { — Default }
                    </mat-option>
                  }
                </mat-autocomplete>
                <mat-hint>Select which LLM to use for this agent</mat-hint>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Task</mat-label>
                <textarea matInput formControlName="agent_task" rows="3"
                  placeholder="Describe what the agent should accomplish..." [appTemplateValidation]="variableTree"></textarea>
                <mat-hint>Supports Jinja2 variables</mat-hint>
                <button mat-icon-button matSuffix [matMenuTriggerFor]="agentTaskVarMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #agentTaskVarMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('agent_task')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>System Prompt (optional)</mat-label>
                <textarea matInput formControlName="agent_system_prompt" rows="2"
                  placeholder="Custom instructions for the agent..." [appTemplateValidation]="variableTree"></textarea>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Max Iterations</mat-label>
                <input matInput type="number" formControlName="agent_max_iterations" />
                <mat-hint>1 - 50</mat-hint>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>MCP Servers</mat-label>
                <mat-chip-grid #mcpChipGrid>
                  @for (id of selectedMcpIds(); track id) {
                    <mat-chip-row (removed)="removeMcpConfig(id)">{{ mcpDisplayName(id) }}
                      <button matChipRemove><mat-icon>cancel</mat-icon></button>
                    </mat-chip-row>
                  }
                </mat-chip-grid>
                <input [matChipInputFor]="mcpChipGrid" [matAutocomplete]="mcpAuto"
                       (input)="mcpConfigSearch.set($any($event.target).value)">
                <mat-autocomplete #mcpAuto (optionSelected)="addMcpConfig($event)">
                  @for (cfg of filteredMcpConfigs(); track cfg.id) {
                    <mat-option [value]="cfg.id">{{ cfg.name }}</mat-option>
                  }
                </mat-autocomplete>
                <mat-hint>Select MCP servers for tool access (configure in Admin > MCP Servers)</mat-hint>
              </mat-form-field>

              <mat-expansion-panel class="advanced-panel">
                <mat-expansion-panel-header>
                  <mat-panel-title>Structured Output</mat-panel-title>
                </mat-expansion-panel-header>
                <div class="output-fields-editor">
                  <p class="field-hint">Define output fields to extract structured data from the agent's analysis. Use in downstream conditions via <code>{{ '{' }}{{ '{' }} nodes.NodeName.field_name {{ '}' }}{{ '}' }}</code>.</p>
                  @for (field of outputFields(); track $index) {
                    <div class="output-field-row">
                      <mat-form-field appearance="outline" class="field-name">
                        <mat-label>Name</mat-label>
                        <input matInput [value]="field.name" (input)="updateOutputField($index, 'name', $event)" placeholder="e.g. detected" />
                      </mat-form-field>
                      <mat-form-field appearance="outline" class="field-type">
                        <mat-label>Type</mat-label>
                        <input matInput [matAutocomplete]="ofTypeAuto" [value]="field.type" readonly>
                        <mat-autocomplete #ofTypeAuto (optionSelected)="updateOutputField($index, 'type', { value: $event.option.value })">
                          <mat-option value="string">String</mat-option>
                          <mat-option value="number">Number</mat-option>
                          <mat-option value="boolean">Boolean</mat-option>
                        </mat-autocomplete>
                      </mat-form-field>
                      <mat-form-field appearance="outline" class="field-desc">
                        <mat-label>Description</mat-label>
                        <input matInput [value]="field.description" (input)="updateOutputField($index, 'description', $event)" placeholder="What this field represents" />
                      </mat-form-field>
                      <mat-checkbox
                        [checked]="field.required ?? false"
                        (change)="updateOutputField($index, 'required', { value: $event.checked })"
                        class="field-required"
                      >Req.</mat-checkbox>
                      <button mat-icon-button (click)="removeOutputField($index)" class="remove-field-btn">
                        <mat-icon>close</mat-icon>
                      </button>
                    </div>
                  }
                  <button mat-stroked-button (click)="addOutputField()" class="add-field-btn">
                    <mat-icon>add</mat-icon> Add Field
                  </button>
                </div>
              </mat-expansion-panel>
            }

            <!-- App Actions -->
            @if (node.type === 'trigger_backup') {
              <mat-form-field appearance="outline">
                <mat-label>Backup Type</mat-label>
                <input matInput [matAutocomplete]="backupTypeAuto"
                       [value]="backupTypeDisplayValue()"
                       (input)="backupTypeSearch.set($any($event.target).value)">
                <mat-autocomplete #backupTypeAuto (optionSelected)="form.get('backup_type')!.setValue($event.option.value)">
                  @for (opt of filteredBackupTypes(); track opt.value) {
                    <mat-option [value]="opt.value">{{ opt.label }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>
              @if (form.get('backup_type')?.value === 'manual') {
                <mat-form-field appearance="outline">
                  <mat-label>Object Type</mat-label>
                  <input matInput formControlName="backup_object_type" placeholder="e.g. org:wlans, site:maps" />
                </mat-form-field>
              }
              <mat-form-field appearance="outline">
                <mat-label>Site ID (optional)</mat-label>
                <input matInput formControlName="backup_site_id" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('backup_site_id')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
            }

            @if (node.type === 'restore_backup') {
              <mat-form-field appearance="outline">
                <mat-label>Version ID</mat-label>
                <input matInput formControlName="restore_version_id" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('restore_version_id')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
              <mat-checkbox formControlName="restore_dry_run">Dry run (preview only)</mat-checkbox>
              <mat-checkbox formControlName="restore_cascade">Cascade (include dependencies)</mat-checkbox>
            }

            @if (node.type === 'compare_backups') {
              <mat-form-field appearance="outline">
                <mat-label>Backup ID 1</mat-label>
                <input matInput formControlName="compare_backup_id_1" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('compare_backup_id_1')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Backup ID 2</mat-label>
                <input matInput formControlName="compare_backup_id_2" [appTemplateValidation]="variableTree" />
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu2">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu2="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('compare_backup_id_2')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
            }

            <!-- Sub-Flow Input: parameter list editor -->
            @if (node.type === 'subflow_input') {
              <div class="section-title">Input Parameters</div>
              @for (param of subflowInputParams; track $index; let i = $index) {
                <div class="subflow-param-row">
                  <mat-form-field appearance="outline">
                    <mat-label>Name</mat-label>
                    <input matInput [value]="param.name" (input)="updateSubflowInputParam(i, 'name', $any($event.target).value)" />
                  </mat-form-field>
                  <mat-form-field appearance="outline">
                    <mat-label>Type</mat-label>
                    <input matInput [matAutocomplete]="sfInTypeAuto" [value]="param.type" readonly>
                    <mat-autocomplete #sfInTypeAuto (optionSelected)="updateSubflowInputParam(i, 'type', $event.option.value)">
                      @for (opt of paramTypeOptions; track opt) {
                        <mat-option [value]="opt">{{ opt }}</mat-option>
                      }
                    </mat-autocomplete>
                  </mat-form-field>
                  <mat-checkbox [checked]="param.required" (change)="updateSubflowInputParam(i, 'required', $event.checked)">Required</mat-checkbox>
                  <mat-form-field appearance="outline">
                    <mat-label>Description</mat-label>
                    <input matInput [value]="param.description" (input)="updateSubflowInputParam(i, 'description', $any($event.target).value)" />
                  </mat-form-field>
                  <button mat-icon-button (click)="removeSubflowInputParam(i)">
                    <mat-icon>close</mat-icon>
                  </button>
                </div>
              }
              <button mat-button (click)="addSubflowInputParam()">
                <mat-icon>add</mat-icon> Add Parameter
              </button>
            }

            <!-- Invoke Sub-Flow: target selection + input mappings -->
            @if (node.type === 'invoke_subflow') {
              <mat-form-field appearance="outline">
                <mat-label>Target Sub-Flow</mat-label>
                <input matInput [matAutocomplete]="subflowTargetAuto"
                       [value]="subflowTargetDisplayValue()"
                       (input)="subflowSearch.set($any($event.target).value)">
                <mat-autocomplete #subflowTargetAuto (optionSelected)="form.get('target_workflow_id')!.setValue($event.option.value); onSubflowTargetChanged($event.option.value)">
                  @for (sf of filteredSubflows(); track sf.id) {
                    <mat-option [value]="sf.id">{{ sf.name }}</mat-option>
                  }
                </mat-autocomplete>
              </mat-form-field>

              @if (selectedSubflowSchema) {
                <div class="section-title">Input Mappings</div>
                @for (param of selectedSubflowSchema.input_parameters; track param.name) {
                  <mat-form-field appearance="outline">
                    <mat-label>{{ param.name }}{{ param.required ? ' *' : '' }} ({{ param.type }})</mat-label>
                    <textarea matInput [value]="getInputMapping(param.name)"
                      (input)="setInputMapping(param.name, $any($event.target).value)"
                      rows="1"
                      [placeholder]="param.description || ''"></textarea>
                    <button mat-icon-button matSuffix [matMenuTriggerFor]="sfVarMenu">
                      <mat-icon>data_object</mat-icon>
                    </button>
                    <mat-menu #sfVarMenu="matMenu">
                      <app-variable-picker
                        [variableTree]="variableTree"
                        (variableSelected)="appendInputMapping(param.name, $event)"
                      />
                    </mat-menu>
                  </mat-form-field>
                }

                @if (selectedSubflowSchema.output_parameters.length > 0) {
                  <div class="section-title">Outputs (read-only)</div>
                  @for (param of selectedSubflowSchema.output_parameters; track param.name) {
                    <div class="subflow-output-info">
                      <span class="param-name">{{ param.name }}</span>
                      <span class="param-type">({{ param.type }})</span>
                      @if (param.description) {
                        <span class="param-desc">{{ param.description }}</span>
                      }
                    </div>
                  }
                }
              }
            }

            <!-- Sub-Flow Output: define parameters + map output expressions -->
            @if (node.type === 'subflow_output') {
              <div class="section-title">Output Parameters</div>
              @for (param of subflowOutputParams; track $index; let i = $index) {
                <div class="subflow-param-row">
                  <mat-form-field appearance="outline">
                    <mat-label>Name</mat-label>
                    <input matInput [value]="param.name" (input)="updateSubflowOutputParam(i, 'name', $any($event.target).value)" />
                  </mat-form-field>
                  <mat-form-field appearance="outline">
                    <mat-label>Type</mat-label>
                    <input matInput [matAutocomplete]="sfOutTypeAuto" [value]="param.type" readonly>
                    <mat-autocomplete #sfOutTypeAuto (optionSelected)="updateSubflowOutputParam(i, 'type', $event.option.value)">
                      @for (opt of paramTypeOptions; track opt) {
                        <mat-option [value]="opt">{{ opt }}</mat-option>
                      }
                    </mat-autocomplete>
                  </mat-form-field>
                  <button mat-icon-button (click)="removeSubflowOutputParam(i)">
                    <mat-icon>close</mat-icon>
                  </button>
                </div>
                <!-- Value mapping for this parameter -->
                <mat-form-field appearance="outline" class="output-mapping-field">
                  <mat-label>{{ param.name }} value</mat-label>
                  <textarea matInput [value]="getSubflowOutputValue(param.name)"
                    (input)="setSubflowOutputValue(param.name, $any($event.target).value)"
                    rows="1"
                    placeholder="e.g. {{ '{{' }} nodes.Some_Node.body {{ '}}' }}"></textarea>
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="outVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #outVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="appendSubflowOutputValue(param.name, $event)"
                    />
                  </mat-menu>
                </mat-form-field>
              }
              <button mat-button (click)="addSubflowOutputParam()">
                <mat-icon>add</mat-icon> Add Output
              </button>
            }

            <!-- Condition Branches -->
            @if (node.type === 'condition') {
              <app-json-section-toggle
                sectionLabel="Condition Branches"
                [sectionData]="branchesArray.getRawValue()"
                (dataChanged)="applyBranchesJson($event)"
              >
                @for (branch of branchesArray.controls; track $index; let i = $index) {
                  <div class="branch-row" [formGroup]="$any(branch)">
                    <span class="branch-label">{{ i === 0 ? 'If' : 'Else If' }}</span>
                    <mat-form-field appearance="outline" class="branch-field">
                      <input matInput formControlName="condition" placeholder="Expression..." />
                      <button mat-icon-button matSuffix [matMenuTriggerFor]="branchVarMenu">
                        <mat-icon>data_object</mat-icon>
                      </button>
                      <mat-menu #branchVarMenu="matMenu">
                        <app-variable-picker
                          [variableTree]="variableTree"
                          (variableSelected)="insertIntoControl($any(branch).controls.condition, $event)"
                        />
                      </mat-menu>
                    </mat-form-field>
                    @if (i > 0) {
                      <button mat-icon-button (click)="removeBranch(i)">
                        <mat-icon>close</mat-icon>
                      </button>
                    }
                  </div>
                }
                <button mat-button (click)="addBranch()">
                  <mat-icon>add</mat-icon> Add Branch
                </button>
              </app-json-section-toggle>
            }

            <!-- Advanced section (collapsed by default) -->
            @if (hasOutput || hasErrorHandling) {
              <mat-expansion-panel class="advanced-panel">
                <mat-expansion-panel-header>
                  <mat-panel-title>Advanced</mat-panel-title>
                </mat-expansion-panel-header>

                <!-- Save As bindings -->
                @if (hasOutput) {
                  @if (outputHint) {
                    <div class="output-hint">Available: {{ outputHint }}</div>
                  }
                  <app-json-section-toggle
                    sectionLabel="Save Output As Variables"
                    [sectionData]="saveAsArray.getRawValue()"
                    (dataChanged)="applySaveAsJson($event)"
                  >
                    @for (binding of saveAsArray.controls; track $index; let i = $index) {
                      <div class="save-as-row" [formGroup]="$any(binding)">
                        <mat-form-field appearance="outline" class="save-as-name">
                          <mat-label>Name</mat-label>
                          <input matInput formControlName="name" />
                        </mat-form-field>
                        <mat-form-field appearance="outline" class="save-as-expr">
                          <mat-label>Expression</mat-label>
                          <input matInput formControlName="expression" [placeholder]="'e.g. {{ output.data }}'" />
                          <button mat-icon-button matSuffix [matMenuTriggerFor]="saveAsVarMenu">
                            <mat-icon>data_object</mat-icon>
                          </button>
                          <mat-menu #saveAsVarMenu="matMenu">
                            <app-variable-picker
                              [variableTree]="variableTree"
                              (variableSelected)="insertIntoControl($any(binding).controls.expression, $event)"
                            />
                          </mat-menu>
                        </mat-form-field>
                        <button mat-icon-button (click)="removeSaveAsBinding(i)">
                          <mat-icon>close</mat-icon>
                        </button>
                      </div>
                    }
                    <button mat-button (click)="addSaveAsBinding()">
                      <mat-icon>add</mat-icon> Add Variable
                    </button>
                  </app-json-section-toggle>
                }

                <!-- Error handling -->
                @if (hasErrorHandling) {
                  <div class="section-title">Error Handling</div>
                  @if (hasRetry) {
                    <div class="error-row">
                      <mat-form-field appearance="outline">
                        <mat-label>Max Retries</mat-label>
                        <input matInput type="number" formControlName="max_retries" />
                      </mat-form-field>
                      <mat-form-field appearance="outline">
                        <mat-label>Retry Delay (s)</mat-label>
                        <input matInput type="number" formControlName="retry_delay" />
                      </mat-form-field>
                    </div>
                  }
                  <mat-checkbox formControlName="continue_on_error">Continue on error</mat-checkbox>
                }
              </mat-expansion-panel>
            }
          }
        </form>
      </div>
    }
  `,
  styles: [
    `
      .config-panel {
        height: 100%;
        overflow-y: auto;
        padding: 12px;
      }

      .panel-header {
        margin-bottom: 12px;
      }

      .panel-title {
        margin: 0;
        font-size: 14px;
        font-weight: 500;
      }

      .config-form {
        display: flex;
        flex-direction: column;
        gap: 4px;

        mat-form-field {
          width: 100%;
        }
      }

      .output-hint {
        font-size: 11px;
        color: var(--mat-sys-on-surface-variant, #888);
        font-family: monospace;
        padding: 4px 8px;
        margin-top: 8px;
        background: var(--mat-sys-surface-variant, #f5f5f5);
        border-radius: 4px;
      }

      .section-title {
        font-size: 12px;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-top: 12px;
        margin-bottom: 4px;
        letter-spacing: 0.5px;
      }

      .selected-entry {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px;
        background: var(--mat-sys-primary-container, #e3f2fd);
        border-radius: 8px;
        margin-bottom: 8px;
      }

      .entry-method {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.08);
      }

      .entry-label {
        flex: 1;
        font-size: 13px;
      }

      .catalog-label {
        font-weight: 500;
        display: block;
      }

      .catalog-desc {
        font-size: 11px;
        color: var(--mat-sys-on-surface-variant, #666);
      }

      .branch-row {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .branch-label {
        font-size: 12px;
        font-weight: 500;
        min-width: 42px;
      }

      .branch-field {
        flex: 1;
      }

      .subflow-param-row {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 8px;
        border: 1px solid var(--mat-sys-outline-variant, #ccc);
        border-radius: 8px;
        margin-bottom: 8px;
        position: relative;

        button[mat-icon-button] {
          position: absolute;
          top: 4px;
          right: 4px;
        }
      }

      .subflow-output-info {
        display: flex;
        gap: 4px;
        align-items: center;
        padding: 4px 8px;
        font-size: 13px;

        .param-name {
          font-weight: 500;
        }

        .param-type {
          color: var(--mat-sys-on-surface-variant, #666);
        }

        .param-desc {
          color: var(--mat-sys-on-surface-variant, #888);
          font-size: 12px;
        }
      }

      .hint-text {
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant, #888);
        padding: 8px 0;
      }

      .save-as-row {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      .save-as-name {
        flex: 1;
      }

      .save-as-expr {
        flex: 2;
      }

      .error-row {
        display: flex;
        gap: 8px;
      }

      .advanced-panel {
        margin-top: 8px;
        box-shadow: none;
        border: 1px solid var(--mat-sys-outline-variant, #e0e0e0);
        border-radius: 8px;
      }

      .output-fields-editor {
        display: flex;
        flex-direction: column;
        gap: 8px;

        .field-hint {
          font-size: 12px;
          color: var(--app-neutral);
          margin: 0 0 4px;
          code { font-size: 11px; background: rgba(128,128,128,0.12); padding: 1px 4px; border-radius: 3px; }
        }
      }

      .output-field-row {
        display: flex;
        gap: 8px;
        align-items: flex-start;

        .field-name { flex: 1; min-width: 0; }
        .field-type { width: 100px; flex-shrink: 0; }
        .field-desc { flex: 2; min-width: 0; }
        .field-required { flex-shrink: 0; margin-top: 12px; font-size: 12px; }
        .remove-field-btn { flex-shrink: 0; margin-top: 8px; }
      }

      .add-field-btn {
        align-self: flex-start;
        font-size: 13px;
        mat-icon { font-size: 16px; width: 16px; height: 16px; margin-right: 4px; }
      }

      .params-section {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding-left: 8px;
        border-left: 2px solid var(--mat-sys-outline-variant, #e0e0e0);
        margin-bottom: 8px;
      }

      .config-hint {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant, #666);
        margin-top: 4px;

        mat-icon {
          font-size: 16px;
          width: 16px;
          height: 16px;
          flex-shrink: 0;
          margin-top: 1px;
        }
      }

      .slack-guidance {
        display: flex;
        gap: 8px;
        padding: 12px;
        margin: 12px 0;
        background-color: var(--mat-sys-surface-container, #f5f5f5);
        border-radius: 8px;
        border-left: 3px solid var(--mat-sys-primary, #1976d2);
      }
      .slack-guidance-text {
        flex: 1;
        font-size: 0.875rem;
        line-height: 1.5;
      }
      .slack-guidance-text p {
        margin: 0 0 8px 0;
      }
      .slack-guidance-text p:last-child {
        margin-bottom: 0;
      }
      .slack-guidance-more summary {
        cursor: pointer;
        color: var(--mat-sys-primary);
        font-weight: 500;
      }

      .syslog-row {
        display: flex;
        gap: 12px;
      }
      .syslog-row mat-form-field {
        flex: 1;
      }
      .syslog-host {
        flex: 2 !important;
      }
      .syslog-port {
        flex: 0 0 100px !important;
      }

      .variable-row {
        display: flex;
        gap: 8px;
        align-items: flex-start;
      }
      .var-name {
        flex: 0 0 140px;
      }
      .var-expr {
        flex: 1;
      }
      .var-remove {
        margin-top: 8px;
      }
      .add-variable-btn {
        font-size: 12px;
        margin-bottom: 12px;
      }

      .code-editor {
        font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 12px;
        line-height: 1.5;
        tab-size: 2;
        white-space: pre;
      }

      .field-help {
        font-size: 12px;
        color: var(--app-neutral, #6b7280);
        margin: 0 0 12px;
        line-height: 1.5;
      }
      .field-help code {
        background: rgba(0, 0, 0, 0.06);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 11px;
      }
    `,
  ],
})
export class NodeConfigPanelComponent implements OnChanges, OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly workflowService = inject(WorkflowService);
  private readonly llmService = inject(LlmService);
  availableLlmConfigs = signal<LlmConfigAvailable[]>([]);
  llmConfigSearch = signal('');
  filteredLlmConfigs = computed(() => {
    const term = this.llmConfigSearch().toLowerCase();
    return term
      ? this.availableLlmConfigs().filter(
          (c) => c.name.toLowerCase().includes(term) || c.provider.toLowerCase().includes(term),
        )
      : this.availableLlmConfigs();
  });
  availableMcpConfigs = signal<McpConfigAvailable[]>([]);
  mcpConfigSearch = signal('');
  filteredMcpConfigs = computed(() => {
    const term = this.mcpConfigSearch().toLowerCase();
    const selected = new Set(this.selectedMcpIds());
    const available = this.availableMcpConfigs().filter((c) => !selected.has(c.id));
    return term ? available.filter((c) => c.name.toLowerCase().includes(term)) : available;
  });
  eventPairs = signal<EventPair[]>([]);
  eventPairSearch = signal('');
  filteredEventPairs = computed(() => {
    const term = this.eventPairSearch().toLowerCase();
    return term
      ? this.eventPairs().filter((p) => p.label.toLowerCase().includes(term))
      : this.eventPairs();
  });
  duFunctionSearch = signal('');
  searchFilteredDeviceFunctions = computed(() => {
    const term = this.duFunctionSearch().toLowerCase();
    return term
      ? this.filteredDeviceFunctions.filter((e) => e.label.toLowerCase().includes(term))
      : this.filteredDeviceFunctions;
  });
  subflowSearch = signal('');
  filteredSubflows = computed(() => {
    const term = this.subflowSearch().toLowerCase();
    return term
      ? this.availableSubflows.filter((sf) => sf.name.toLowerCase().includes(term))
      : this.availableSubflows;
  });
  outputFields = signal<Array<{ name: string; type: string; description: string; required?: boolean }>>([]);

  // --- Option arrays and search/display helpers for autocomplete selects ---
  readonly triggerTypeOptions = [
    { value: 'webhook', label: 'Webhook' },
    { value: 'aggregated_webhook', label: 'Aggregated Webhook' },
    { value: 'cron', label: 'Cron Schedule' },
    { value: 'manual', label: 'Manual' },
  ];
  triggerTypeSearch = signal('');
  filteredTriggerTypes = computed(() => {
    const term = this.triggerTypeSearch().toLowerCase();
    return term
      ? this.triggerTypeOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.triggerTypeOptions;
  });
  triggerTypeDisplayValue = computed(() => {
    const val = this.form?.get('trigger_type')?.value;
    return this.triggerTypeOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly webhookTopicOptions = [
    { value: 'alarms', label: 'Alarms' },
    { value: 'audits', label: 'Audits' },
    { value: 'device-updowns', label: 'Device Up/Downs' },
    { value: 'device-events', label: 'Device Events' },
    { value: 'occupancy-alerts', label: 'Occupancy Alerts' },
    { value: 'sdkclient-scan-data', label: 'SDK Client Scan' },
  ];
  webhookTopicSearch = signal('');
  filteredWebhookTopics = computed(() => {
    const term = this.webhookTopicSearch().toLowerCase();
    return term
      ? this.webhookTopicOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.webhookTopicOptions;
  });
  webhookTopicDisplayValue = computed(() => {
    const val = this.form?.get('webhook_topic')?.value;
    return this.webhookTopicOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly aggWebhookTopicOptions = [
    { value: 'device-events', label: 'Device Events' },
    { value: 'mxedge-events', label: 'Mist Edge Events' },
    { value: 'nac-events', label: 'NAC Events' },
    { value: 'alarms', label: 'Alarms' },
    { value: 'device-updowns', label: 'Device Up/Downs' },
  ];
  aggWebhookTopicSearch = signal('');
  filteredAggWebhookTopics = computed(() => {
    const term = this.aggWebhookTopicSearch().toLowerCase();
    return term
      ? this.aggWebhookTopicOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.aggWebhookTopicOptions;
  });
  aggWebhookTopicDisplayValue = computed(() => {
    const val = this.form?.get('webhook_topic')?.value;
    return this.aggWebhookTopicOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly groupByOptions = [
    { value: 'site_id', label: 'Site' },
    { value: 'org_id', label: 'Organization' },
    { value: 'device_mac', label: 'Device' },
  ];
  groupBySearch = signal('');
  filteredGroupByOptions = computed(() => {
    const term = this.groupBySearch().toLowerCase();
    return term
      ? this.groupByOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.groupByOptions;
  });
  groupByDisplayValue = computed(() => {
    const val = this.form?.get('group_by')?.value;
    return this.groupByOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly webhookAuthOptions = [
    { value: 'none', label: 'None' },
    { value: 'oauth2_password', label: 'OAuth 2.0 Password Grant' },
  ];
  webhookAuthSearch = signal('');
  filteredWebhookAuthTypes = computed(() => {
    const term = this.webhookAuthSearch().toLowerCase();
    return term
      ? this.webhookAuthOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.webhookAuthOptions;
  });
  webhookAuthDisplayValue = computed(() => {
    const val = this.form?.get('webhook_auth_type')?.value;
    return this.webhookAuthOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly snowMethodOptions = [
    { value: 'GET', label: 'GET' },
    { value: 'POST', label: 'POST' },
    { value: 'PUT', label: 'PUT' },
    { value: 'DELETE', label: 'DELETE' },
  ];
  snowMethodSearch = signal('');
  filteredSnowMethods = computed(() => {
    const term = this.snowMethodSearch().toLowerCase();
    return term
      ? this.snowMethodOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.snowMethodOptions;
  });
  snowMethodDisplayValue = computed(() => {
    const val = this.form?.get('servicenow_method')?.value;
    return this.snowMethodOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly snowAuthOptions = [
    { value: 'basic', label: 'Basic Auth' },
    { value: 'oauth2_password', label: 'OAuth 2.0 Password Grant' },
  ];
  snowAuthSearch = signal('');
  filteredSnowAuthTypes = computed(() => {
    const term = this.snowAuthSearch().toLowerCase();
    return term
      ? this.snowAuthOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.snowAuthOptions;
  });
  snowAuthDisplayValue = computed(() => {
    const val = this.form?.get('servicenow_auth_type')?.value;
    return this.snowAuthOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly waitStyleOptions = [
    { value: '', label: 'Default' },
    { value: 'primary', label: 'Primary' },
    { value: 'danger', label: 'Danger' },
  ];
  waitStyleDisplay(val: string): string {
    return this.waitStyleOptions.find((o) => o.value === val)?.label ?? val ?? 'Default';
  }

  readonly frFormatOptions = [
    { value: 'markdown', label: 'Markdown' },
    { value: 'slack', label: 'Slack' },
    { value: 'csv', label: 'CSV' },
    { value: 'text', label: 'Plain Text' },
  ];
  frFormatSearch = signal('');
  filteredFrFormats = computed(() => {
    const term = this.frFormatSearch().toLowerCase();
    return term
      ? this.frFormatOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.frFormatOptions;
  });
  frFormatDisplayValue = computed(() => {
    const val = this.form?.get('fr_format')?.value;
    return this.frFormatOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly syslogProtocolOptions = [
    { value: 'udp', label: 'UDP' },
    { value: 'tcp', label: 'TCP' },
  ];
  syslogProtocolSearch = signal('');
  filteredSyslogProtocols = computed(() => {
    const term = this.syslogProtocolSearch().toLowerCase();
    return term
      ? this.syslogProtocolOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.syslogProtocolOptions;
  });
  syslogProtocolDisplayValue = computed(() => {
    const val = this.form?.get('syslog_protocol')?.value;
    return this.syslogProtocolOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly syslogFormatOptions = [
    { value: 'rfc5424', label: 'RFC 5424' },
    { value: 'cef', label: 'CEF' },
  ];
  syslogFormatSearch = signal('');
  filteredSyslogFormats = computed(() => {
    const term = this.syslogFormatSearch().toLowerCase();
    return term
      ? this.syslogFormatOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.syslogFormatOptions;
  });
  syslogFormatDisplayValue = computed(() => {
    const val = this.form?.get('syslog_format')?.value;
    return this.syslogFormatOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly syslogFacilityOptions = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => ({
    value: 'local' + i,
    label: 'local' + i,
  }));
  syslogFacilitySearch = signal('');
  filteredSyslogFacilities = computed(() => {
    const term = this.syslogFacilitySearch().toLowerCase();
    return term
      ? this.syslogFacilityOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.syslogFacilityOptions;
  });
  syslogFacilityDisplayValue = computed(() => {
    const val = this.form?.get('syslog_facility')?.value;
    return this.syslogFacilityOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly syslogSeverityOptions = [
    { value: 'emergency', label: 'Emergency' },
    { value: 'alert', label: 'Alert' },
    { value: 'critical', label: 'Critical' },
    { value: 'error', label: 'Error' },
    { value: 'warning', label: 'Warning' },
    { value: 'notice', label: 'Notice' },
    { value: 'informational', label: 'Informational' },
    { value: 'debug', label: 'Debug' },
  ];
  syslogSeveritySearch = signal('');
  filteredSyslogSeverities = computed(() => {
    const term = this.syslogSeveritySearch().toLowerCase();
    return term
      ? this.syslogSeverityOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.syslogSeverityOptions;
  });
  syslogSeverityDisplayValue = computed(() => {
    const val = this.form?.get('syslog_severity')?.value;
    return this.syslogSeverityOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly duDeviceTypeOptions = [
    { value: 'ap', label: 'AP (Access Point)' },
    { value: 'ex', label: 'EX (Switch)' },
    { value: 'srx', label: 'SRX (Firewall)' },
    { value: 'ssr', label: 'SSR (Router)' },
  ];
  duDeviceTypeSearch = signal('');
  filteredDuDeviceTypes = computed(() => {
    const term = this.duDeviceTypeSearch().toLowerCase();
    return term
      ? this.duDeviceTypeOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.duDeviceTypeOptions;
  });
  duDeviceTypeDisplayValue = computed(() => {
    const val = this.form?.get('du_device_type')?.value;
    return this.duDeviceTypeOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  duFunctionDisplayValue = computed(() => {
    const val = this.form?.get('du_function')?.value;
    const entry = this.filteredDeviceFunctions.find((e) => e.function === val);
    return entry?.label ?? val ?? '';
  });

  llmConfigDisplayValue = computed(() => {
    const val = this.form?.get('llm_config_id')?.value;
    if (!val) return 'Default';
    const cfg = this.availableLlmConfigs().find((c) => c.id === val);
    return cfg ? `${cfg.name} (${cfg.provider})` : val;
  });

  selectedMcpIds = signal<string[]>([]);

  mcpDisplayName(id: string): string {
    return this.availableMcpConfigs().find((c) => c.id === id)?.name ?? id;
  }

  addMcpConfig(event: MatAutocompleteSelectedEvent): void {
    const id = event.option.value;
    const current = this.selectedMcpIds();
    if (!current.includes(id)) {
      const updated = [...current, id];
      this.selectedMcpIds.set(updated);
      this.form.get('mcp_config_ids')?.setValue(updated);
    }
    this.mcpConfigSearch.set('');
  }

  removeMcpConfig(id: string): void {
    const updated = this.selectedMcpIds().filter((i) => i !== id);
    this.selectedMcpIds.set(updated);
    this.form.get('mcp_config_ids')?.setValue(updated);
  }

  readonly backupTypeOptions = [
    { value: 'full', label: 'Full Backup' },
    { value: 'manual', label: 'Manual (selective)' },
  ];
  backupTypeSearch = signal('');
  filteredBackupTypes = computed(() => {
    const term = this.backupTypeSearch().toLowerCase();
    return term
      ? this.backupTypeOptions.filter((o) => o.label.toLowerCase().includes(term))
      : this.backupTypeOptions;
  });
  backupTypeDisplayValue = computed(() => {
    const val = this.form?.get('backup_type')?.value;
    return this.backupTypeOptions.find((o) => o.value === val)?.label ?? val ?? '';
  });

  readonly paramTypeOptions = ['any', 'string', 'number', 'boolean', 'object', 'array'];

  subflowTargetDisplayValue = computed(() => {
    const val = this.form?.get('target_workflow_id')?.value;
    if (!val) return '';
    return this.availableSubflows.find((sf) => sf.id === val)?.name ?? val;
  });

  private readonly destroyRef = inject(DestroyRef);
  private readonly rebuild$ = new Subject<void>();

  @Input() node!: WorkflowNode;
  @Input() workflowId: string | null = null;
  @Input() workflowType: WorkflowType = 'standard';
  @Input() inputParameters: SubflowParameter[] = [];
  @Input() outputParameters: SubflowParameter[] = [];
  @Input() variableTree: VariableTree | null = null;
  @Output() configChanged = new EventEmitter<WorkflowNode>();
  @Output() inputParametersChanged = new EventEmitter<SubflowParameter[]>();
  @Output() outputParametersChanged = new EventEmitter<SubflowParameter[]>();

  // Sub-flow state
  availableSubflows: WorkflowResponse[] = [];
  selectedSubflowSchema: SubflowSchemaResponse | null = null;

  form!: FormGroup;
  catalogEntries: ApiCatalogEntry[] = [];
  filteredCatalog: ApiCatalogEntry[] = [];
  useCustomEndpoint = false;
  selectedCatalogEntry: ApiCatalogEntry | null = null;
  pathParamControls: FormGroup | null = null;
  queryParamControls: FormGroup | null = null;
  catalogSearchControl = new FormControl('');

  // Device utils state
  deviceUtilsCatalog: DeviceUtilEntry[] = [];
  filteredDeviceFunctions: DeviceUtilEntry[] = [];
  selectedDeviceEntry: DeviceUtilEntry | null = null;
  deviceParamControls: FormGroup | null = null;

  private emitting = false;

  ngOnInit(): void {
    this.workflowService
      .getApiCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (entries) => {
          this.catalogEntries = entries;
          this.applyMethodFilter();
          this.tryAutoSelectCatalogEntry();
        },
      });

    this.catalogSearchControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((value) => this.filterCatalog(value || ''));

    this.workflowService
      .getDeviceUtilsCatalog()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (entries) => {
          this.deviceUtilsCatalog = entries;
          this.tryAutoSelectDeviceUtil();
        },
      });

    this.workflowService
      .getEventPairs()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (pairs) => this.eventPairs.set(pairs) });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['node']) {
      if (this.emitting) {
        this.emitting = false;
        return;
      }
      this.buildForm();
    }
  }

  private buildForm(): void {
    this.rebuild$.next();
    const config = this.node.config || {};

    if (this.node.type === 'trigger') {
      this.buildTriggerForm(config);
    } else if (this.node.type === 'subflow_input') {
      this.buildSubflowInputForm(config);
    } else {
      this.buildActionForm(config);
    }

    if (this.node.type === 'subflow_output') {
      this.initSubflowOutputParams();
    }

    this.form.valueChanges.pipe(takeUntil(this.rebuild$)).subscribe(() => this.emitChanges());

    // Load subflow list when configuring invoke_subflow
    if (this.node.type === 'invoke_subflow') {
      this.loadAvailableSubflows();
    }

    // Load available LLM and MCP configs when configuring ai_agent
    if (this.node.type === 'ai_agent') {
      this.llmService.listAvailableConfigs().pipe(takeUntil(this.rebuild$)).subscribe({
        next: (configs) => this.availableLlmConfigs.set(configs),
      });
      this.llmService.listAvailableMcpConfigs().pipe(takeUntil(this.rebuild$)).subscribe({
        next: (configs) => this.availableMcpConfigs.set(configs),
      });
      this.outputFields.set((config['output_fields'] as Array<{ name: string; type: string; description: string }>) || []);
      this.selectedMcpIds.set((config['mcp_config_ids'] as string[]) || []);
    }
  }

  private buildSubflowInputForm(config: Record<string, unknown>): void {
    this.initSubflowInputParams();
    this.form = this.fb.group({
      name: [this.node.name || ''],
    });
  }

  private buildTriggerForm(config: Record<string, unknown>): void {
    const saveAsControls = ((this.node.save_as || []) as VariableBinding[]).map((b) =>
      this.fb.group({ name: [b.name || ''], expression: [b.expression || ''] })
    );

    this.form = this.fb.group({
      name: [this.node.name || ''],
      trigger_type: [config['trigger_type'] || 'webhook'],
      webhook_topic: [(config['webhook_topic'] || config['webhook_type'] || '') as string],
      event_type_filter: [(config['event_type_filter'] || config['webhook_topic'] || '') as string],
      // Aggregated webhook fields
      closing_event_type: [(config['closing_event_type'] || '') as string],
      device_key: [(config['device_key'] || 'device_mac') as string],
      window_seconds: [config['window_seconds'] || 120],
      group_by: [(config['group_by'] || 'site_id') as string],
      min_events: [config['min_events'] || 1],
      // Cron fields
      cron_expression: [config['cron_expression'] || ''],
      timezone: [config['timezone'] || 'UTC'],
      skip_if_running: [config['skip_if_running'] ?? true],
      condition: [config['condition'] || ''],
      save_as: this.fb.array(saveAsControls),
    });
  }

  private buildActionForm(config: Record<string, unknown>): void {
    this.selectedCatalogEntry = null;
    this.pathParamControls = null;
    this.queryParamControls = null;
    this.catalogSearchControl.setValue('', { emitEvent: false });

    const branchControls = ((config['branches'] as { condition: string }[]) || []).map((b) =>
      this.fb.group({ condition: [b.condition || ''] })
    );

    const saveAsControls = ((this.node.save_as || []) as VariableBinding[]).map((b) =>
      this.fb.group({ name: [b.name || ''], expression: [b.expression || ''] })
    );

    this.form = this.fb.group({
      name: [this.node.name || ''],
      enabled: [this.node.enabled ?? true],
      api_endpoint: [config['api_endpoint'] || ''],
      api_body: [config['api_body'] ? JSON.stringify(config['api_body'], null, 2) : ''],
      webhook_url: [config['webhook_url'] || ''],
      webhook_headers: [
        config['webhook_headers'] ? JSON.stringify(config['webhook_headers'], null, 2) : '',
      ],
      webhook_body: [config['webhook_body'] ? JSON.stringify(config['webhook_body'], null, 2) : ''],
      webhook_auth_type: [config['webhook_auth_type'] || 'none'],
      oauth2_token_url: [config['oauth2_token_url'] || ''],
      oauth2_client_id: [config['oauth2_client_id'] || ''],
      oauth2_client_secret: [''],
      oauth2_username: [config['oauth2_username'] || ''],
      oauth2_password: [''],
      servicenow_method: [config['servicenow_method'] || 'POST'],
      servicenow_instance_url: [config['servicenow_instance_url'] || config['notification_channel'] || ''],
      servicenow_table: [config['servicenow_table'] || 'incident'],
      servicenow_auth_type: [config['servicenow_auth_type'] || 'basic'],
      servicenow_username: [config['servicenow_username'] || ''],
      servicenow_password: [''],
      servicenow_body: [
        config['servicenow_body'] ? JSON.stringify(config['servicenow_body'], null, 2) : '',
      ],
      servicenow_query_params: [
        config['servicenow_query_params']
          ? JSON.stringify(config['servicenow_query_params'], null, 2)
          : '',
      ],
      notification_template: [config['notification_template'] || ''],
      notification_channel: [config['notification_channel'] || ''],
      branches: this.fb.array(branchControls),
      delay_seconds: [config['delay_seconds'] || 0],
      save_as: this.fb.array(saveAsControls),
      variables: this.fb.array(
        (() => {
          const vars = (config['variables'] as { name: string; expression: string }[])
            ?? (config['variable_name'] ? [{ name: config['variable_name'] as string, expression: (config['variable_expression'] || '') as string }] : []);
          const initial = vars.length > 0 ? vars : [{ name: '', expression: '' }];
          return initial.map((v: { name: string; expression: string }) => this.fb.group({ name: [v.name || ''], expression: [v.expression || ''] }));
        })()
      ),
      loop_over: [config['loop_over'] || ''],
      loop_variable: [config['loop_variable'] || 'item'],
      max_iterations: [config['max_iterations'] ?? 100],
      parallel: [config['parallel'] || false],
      max_concurrent: [config['max_concurrent'] ?? 5],
      dt_source: [config['source'] || ''],
      dt_filter: [config['filter'] || ''],
      dt_fields: this.fb.array(
        ((config['fields'] as { path: string; label: string }[]) || [{ path: '', label: '' }]).map(
          (f) => this.fb.group({ path: [f.path || ''], label: [f.label || ''] })
        )
      ),
      fr_data_source: [config['data_source'] || ''],
      fr_columns_source: [config['columns_source'] || ''],
      fr_format: [config['format'] || 'markdown'],
      fr_title: [config['title'] || ''],
      fr_footer_template: [config['footer_template'] || ''],
      slack_header: [config['slack_header'] || ''],
      slack_fields: this.fb.array(
        ((config['slack_fields'] as { label: string; value: string }[]) || []).map((f) =>
          this.fb.group({ label: [f.label || ''], value: [f.value || ''] })
        )
      ),
      slack_footer: [config['slack_footer'] || ''],
      slack_json_variable: [config['slack_json_variable'] || ''],
      auto_convert_markdown: [config['auto_convert_markdown'] ?? true],
      email_subject: [config['email_subject'] || ''],
      email_html: [config['email_html'] ?? false],
      // Syslog
      syslog_host: [config['syslog_host'] || ''],
      syslog_port: [config['syslog_port'] || 514],
      syslog_protocol: [config['syslog_protocol'] || 'udp'],
      syslog_format: [config['syslog_format'] || 'rfc5424'],
      syslog_facility: [config['syslog_facility'] || 'local0'],
      syslog_severity: [config['syslog_severity'] || 'informational'],
      cef_device_vendor: [config['cef_device_vendor'] || 'Juniper'],
      cef_device_product: [config['cef_device_product'] || 'Mist'],
      cef_event_class_id: [config['cef_event_class_id'] || ''],
      cef_name: [config['cef_name'] || ''],
      // Script
      script_code: [config['script_code'] || ''],
      target_workflow_id: [config['target_workflow_id'] || ''],
      du_device_type: [config['device_type'] || ''],
      du_function: [config['function'] || ''],
      du_site_id: [config['site_id'] || ''],
      du_device_id: [config['device_id'] || ''],
      agent_task: [config['agent_task'] || ''],
      agent_system_prompt: [config['agent_system_prompt'] || ''],
      agent_max_iterations: [config['max_iterations'] ?? 10],
      llm_config_id: [config['llm_config_id'] || ''],
      mcp_config_ids: [(config['mcp_config_ids'] as string[]) || []],
      // App actions
      backup_type: [config['backup_type'] || 'full'],
      backup_site_id: [config['site_id'] || ''],
      backup_object_type: [config['object_type'] || ''],
      restore_version_id: [config['version_id'] || ''],
      restore_dry_run: [config['dry_run'] ?? false],
      restore_cascade: [config['cascade'] ?? false],
      compare_backup_id_1: [config['backup_id_1'] || ''],
      compare_backup_id_2: [config['backup_id_2'] || ''],
      // Wait for callback
      wait_actions: this.fb.array(
        ((config['slack_actions'] as { text: string; action_id: string; style: string }[]) || [
          { text: 'Approve', action_id: 'approve', style: 'primary' },
          { text: 'Reject', action_id: 'reject', style: 'danger' },
        ]).map((a) =>
          this.fb.group({
            text: [a.text || ''],
            action_id: [a.action_id || ''],
            style: [a.style || ''],
          })
        )
      ),
      timeout_seconds: [config['timeout_seconds'] || 0],
      max_retries: [this.node.max_retries ?? 3],
      retry_delay: [this.node.retry_delay ?? 5],
      continue_on_error: [this.node.continue_on_error ?? false],
    });

    // Device utils: subscribe to device_type and function changes
    if (this.isDeviceUtilAction) {
      this.selectedDeviceEntry = null;
      this.deviceParamControls = null;

      this.form
        .get('du_device_type')!
        .valueChanges.pipe(takeUntil(this.rebuild$))
        .subscribe((value) => {
          if (!this.emitting) {
            this.onDeviceTypeChange(value);
          }
        });

      this.form
        .get('du_function')!
        .valueChanges.pipe(takeUntil(this.rebuild$))
        .subscribe((value) => {
          if (!this.emitting) {
            this.onFunctionChange(value);
          }
        });

      // Restore selection from existing config
      const deviceType = config['device_type'] as string;
      if (deviceType) {
        this.filteredDeviceFunctions = this.deviceUtilsCatalog.filter(
          (e) => e.device_type === deviceType
        );
        const fn = config['function'] as string;
        if (fn) {
          const entry = this.filteredDeviceFunctions.find((e) => e.function === fn);
          if (entry) {
            this.selectedDeviceEntry = entry;
            this.rebuildDeviceParamControls(config['params'] as Record<string, unknown>);
          }
        }
      }
    }

    this.applyMethodFilter();
    const matched = this.tryAutoSelectCatalogEntry();
    this.useCustomEndpoint = !!(config['api_endpoint'] as string) && !matched;
  }

  // ── Branches ──────────────────────────────────────────────────────

  get branchesArray(): FormArray {
    return this.form?.get('branches') as FormArray;
  }

  addBranch(): void {
    this.branchesArray.push(this.fb.group({ condition: [''] }));
  }

  removeBranch(index: number): void {
    this.branchesArray.removeAt(index);
  }

  // ── Save As ───────────────────────────────────────────────────────

  get saveAsArray(): FormArray {
    return this.form?.get('save_as') as FormArray;
  }

  addSaveAsBinding(): void {
    this.saveAsArray.push(this.fb.group({ name: [''], expression: [''] }));
  }

  removeSaveAsBinding(index: number): void {
    this.saveAsArray.removeAt(index);
  }

  // ── Set Variable (multi) ────────────────────────────────────────

  get variablesArray(): FormArray {
    return this.form?.get('variables') as FormArray;
  }

  addVariable(): void {
    this.variablesArray.push(this.fb.group({ name: [''], expression: [''] }));
  }

  removeVariable(index: number): void {
    this.variablesArray.removeAt(index);
  }

  // ── Variable picker helper ────────────────────────────────────────

  insertIntoControl(control: FormControl | any, value: string): void {
    const current = control.value || '';
    control.setValue(current + value);
  }

  insertJsonVariablePath(value: string): void {
    const ctrl = this.form?.get('slack_json_variable');
    if (!ctrl) return;
    ctrl.setValue(value.replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, ''));
  }

  insertDtFieldPath(index: number, value: string): void {
    const group = this.dtFieldsArray.at(index);
    if (!group) return;
    const pathCtrl = (group as any).get('path');
    if (pathCtrl) {
      // Strip {{ }} wrappers — data transform paths use plain dot-notation with optional pipe
      let plain = value.replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '');
      const current = pathCtrl.value || '';
      pathCtrl.setValue(current + plain);
    }
  }

  // ── Catalog helpers ───────────────────────────────────────────────

  private getMethodForActionType(): string | null {
    switch (this.node.type) {
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
      ? this.catalogEntries.filter((e) => e.method === method)
      : this.catalogEntries;
  }

  filterCatalog(value: string): void {
    const search = (value || '').toLowerCase();
    const method = this.getMethodForActionType();
    this.filteredCatalog = this.catalogEntries.filter(
      (e) =>
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
    const existingParams = (this.node.config['api_params'] || {}) as Record<string, unknown>;
    for (const qp of entry.query_params) {
      queryGroup[qp.name] = new FormControl(existingParams[qp.name] || '');
    }
    this.queryParamControls = this.fb.group(queryGroup);

    this.pathParamControls.valueChanges.pipe(takeUntil(this.rebuild$)).subscribe(() => {
      this.rebuildEndpoint();
      this.emitChanges();
    });
    this.queryParamControls.valueChanges.pipe(takeUntil(this.rebuild$)).subscribe(() => this.emitChanges());

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
      if (value) endpoint = endpoint.replace(`{${param}}`, value as string);
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

  private tryAutoSelectCatalogEntry(): boolean {
    if (!this.isApiAction) return false;
    const endpoint = this.node.config['api_endpoint'] as string;
    if (!endpoint) return false;
    const method = this.getMethodForActionType();
    for (const entry of this.catalogEntries) {
      if (method && entry.method !== method) continue;
      const regex = new RegExp('^' + entry.endpoint.replace(/\{[^}]+\}/g, '[^/]+') + '$');
      if (regex.test(endpoint)) {
        this.selectCatalogEntry(entry);
        return true;
      }
    }
    return false;
  }

  // ── Emit ──────────────────────────────────────────────────────────

  private emitChanges(): void {
    const raw = this.form.getRawValue();
    const updatedNode: WorkflowNode = { ...this.node };

    if (this.node.type === 'subflow_input') {
      updatedNode.name = raw.name;
      this.emitting = true;
      this.configChanged.emit(updatedNode);
      return;
    }

    if (this.node.type === 'trigger') {
      updatedNode.name = raw.name;
      updatedNode.config = {
        trigger_type: raw.trigger_type,
        webhook_topic: raw.webhook_topic || undefined,
        event_type_filter: raw.event_type_filter || undefined,
        cron_expression: raw.cron_expression || undefined,
        timezone: raw.timezone || 'UTC',
        skip_if_running: raw.skip_if_running,
        condition: raw.condition || undefined,
        // Aggregated webhook fields (only included when relevant)
        ...(raw.trigger_type === 'aggregated_webhook'
          ? {
              closing_event_type: raw.closing_event_type || undefined,
              device_key: raw.device_key || 'device_mac',
              window_seconds: raw.window_seconds || 120,
              group_by: raw.group_by || 'site_id',
              min_events: raw.min_events || 1,
            }
          : {}),
      };
      updatedNode.save_as = (raw.save_as || []).filter((b: VariableBinding) => b.name);
    } else {
      updatedNode.name = raw.name;
      updatedNode.enabled = raw.enabled;
      updatedNode.max_retries = raw.max_retries;
      updatedNode.retry_delay = raw.retry_delay;
      updatedNode.continue_on_error = raw.continue_on_error;
      updatedNode.save_as = (raw.save_as || []).filter((b: VariableBinding) => b.name);

      // Build config from type-specific fields
      const config: Record<string, unknown> = { ...this.node.config };

      if (this.isApiAction) {
        config['api_endpoint'] = raw.api_endpoint || '';
        if (raw.api_body) {
          try { config['api_body'] = JSON.parse(raw.api_body); } catch { /* keep */ }
        }
        if (this.queryParamControls) {
          const qp: Record<string, string> = {};
          for (const [k, v] of Object.entries(this.queryParamControls.getRawValue())) {
            if (v) qp[k] = v as string;
          }
          if (Object.keys(qp).length) config['api_params'] = qp;
        }
      }

      if (this.node.type === 'webhook') {
        config['webhook_url'] = raw.webhook_url;
        config['webhook_auth_type'] = raw.webhook_auth_type || 'none';
        if (raw.webhook_auth_type === 'oauth2_password') {
          config['oauth2_token_url'] = raw.oauth2_token_url || '';
          config['oauth2_client_id'] = raw.oauth2_client_id || '';
          config['oauth2_username'] = raw.oauth2_username || '';
          if (raw.oauth2_client_secret) {
            config['oauth2_client_secret'] = raw.oauth2_client_secret;
          }
          if (raw.oauth2_password) {
            config['oauth2_password'] = raw.oauth2_password;
          }
        }
        if (raw.webhook_headers) {
          try { config['webhook_headers'] = JSON.parse(raw.webhook_headers); } catch { /* */ }
        }
        if (raw.webhook_body) {
          try { config['webhook_body'] = JSON.parse(raw.webhook_body); } catch { /* */ }
        }
      }

      if (this.node.type === 'servicenow') {
        config['servicenow_method'] = raw.servicenow_method || 'POST';
        config['servicenow_instance_url'] = raw.servicenow_instance_url || '';
        config['servicenow_table'] = raw.servicenow_table || 'incident';
        config['servicenow_auth_type'] = raw.servicenow_auth_type || 'basic';
        if (raw.servicenow_auth_type === 'basic') {
          config['servicenow_username'] = raw.servicenow_username || '';
          if (raw.servicenow_password) {
            config['servicenow_password'] = raw.servicenow_password;
          }
        }
        if (raw.servicenow_auth_type === 'oauth2_password') {
          config['oauth2_token_url'] = raw.oauth2_token_url || '';
          config['oauth2_client_id'] = raw.oauth2_client_id || '';
          config['oauth2_username'] = raw.oauth2_username || '';
          if (raw.oauth2_client_secret) {
            config['oauth2_client_secret'] = raw.oauth2_client_secret;
          }
          if (raw.oauth2_password) {
            config['oauth2_password'] = raw.oauth2_password;
          }
        }
        if (raw.servicenow_body) {
          try { config['servicenow_body'] = JSON.parse(raw.servicenow_body); } catch { /* */ }
        }
        if (raw.servicenow_query_params) {
          try {
            config['servicenow_query_params'] = JSON.parse(raw.servicenow_query_params);
          } catch { /* */ }
        }
      }

      if (this.isNotificationAction) {
        config['notification_channel'] = raw.notification_channel;
        config['notification_template'] = raw.notification_template;
        if (this.node.type === 'slack') {
          config['slack_header'] = raw.slack_header || undefined;
          config['slack_fields'] = (raw.slack_fields || []).filter(
            (f: { label: string; value: string }) => f.label
          );
          config['slack_footer'] = raw.slack_footer || undefined;
          config['slack_json_variable'] = raw.slack_json_variable || undefined;
          config['auto_convert_markdown'] = raw.auto_convert_markdown ?? true;
        }
      }

      if (this.node.type === 'syslog') {
        config['syslog_host'] = raw.syslog_host || '';
        config['syslog_port'] = raw.syslog_port || 514;
        config['syslog_protocol'] = raw.syslog_protocol || 'udp';
        config['syslog_format'] = raw.syslog_format || 'rfc5424';
        config['syslog_facility'] = raw.syslog_facility || 'local0';
        config['syslog_severity'] = raw.syslog_severity || 'informational';
        config['notification_template'] = raw.notification_template || '';
        if (raw.syslog_format === 'cef') {
          config['cef_device_vendor'] = raw.cef_device_vendor || 'Juniper';
          config['cef_device_product'] = raw.cef_device_product || 'Mist';
          config['cef_event_class_id'] = raw.cef_event_class_id || '';
          config['cef_name'] = raw.cef_name || '';
        }
      }

      if (this.node.type === 'script') {
        config['script_code'] = raw.script_code || '';
      }

      if (this.node.type === 'wait_for_callback') {
        config['notification_channel'] = raw.notification_channel;
        config['notification_template'] = raw.notification_template;
        config['slack_header'] = raw.slack_header || undefined;
        config['slack_actions'] = (raw.wait_actions || []).filter(
          (a: { text: string; action_id: string }) => a.text && a.action_id
        );
        config['timeout_seconds'] = raw.timeout_seconds || undefined;
        // Generate output ports from actions
        updatedNode.output_ports = (config['slack_actions'] as { action_id: string; text: string }[]).map(
          (a: { action_id: string; text: string }) => ({
            id: a.action_id,
            label: a.text,
            type: 'branch' as const,
          })
        );
      }

      if (this.node.type === 'delay') {
        config['delay_seconds'] = raw.delay_seconds;
      }

      if (this.node.type === 'set_variable') {
        config['variables'] = (raw.variables || []).filter(
          (v: { name: string; expression: string }) => v.name || v.expression
        );
      }

      if (this.node.type === 'for_each') {
        config['loop_over'] = raw.loop_over;
        config['loop_variable'] = raw.loop_variable;
        config['max_iterations'] = raw.max_iterations;
        config['parallel'] = raw.parallel;
        config['max_concurrent'] = raw.max_concurrent;
      }

      if (this.node.type === 'condition') {
        config['branches'] = raw.branches;
      }

      if (this.node.type === 'data_transform') {
        config['source'] = raw.dt_source;
        config['fields'] = raw.dt_fields;
        config['filter'] = raw.dt_filter || undefined;
      }

      if (this.node.type === 'format_report') {
        config['data_source'] = raw.fr_data_source;
        config['columns_source'] = raw.fr_columns_source || undefined;
        config['format'] = raw.fr_format;
        config['title'] = raw.fr_title || undefined;
        config['footer_template'] = raw.fr_footer_template || undefined;
      }

      if (this.node.type === 'email') {
        config['email_subject'] = raw.email_subject;
        config['email_html'] = raw.email_html;
      }

      if (this.node.type === 'invoke_subflow') {
        config['target_workflow_id'] = raw.target_workflow_id;
        // input_mappings and _output_schema are managed directly on node.config
      }

      if (this.node.type === 'subflow_output') {
        // outputs are managed directly on node.config
      }

      if (this.isDeviceUtilAction) {
        config['device_type'] = raw.du_device_type || '';
        config['function'] = raw.du_function || '';
        config['site_id'] = raw.du_site_id || '';
        config['device_id'] = raw.du_device_id || '';
        if (this.deviceParamControls) {
          const params: Record<string, string> = {};
          for (const [k, v] of Object.entries(this.deviceParamControls.getRawValue())) {
            if (v) params[k] = v as string;
          }
          config['params'] = params;
        }
      }

      if (this.node.type === 'ai_agent') {
        config['agent_task'] = raw.agent_task || '';
        config['agent_system_prompt'] = raw.agent_system_prompt || '';
        config['max_iterations'] = raw.agent_max_iterations ?? 10;
        config['llm_config_id'] = raw.llm_config_id || null;
        config['mcp_config_ids'] = raw.mcp_config_ids || [];
        config['output_fields'] = this.outputFields().filter((f) => f.name.trim());
      }

      if (this.node.type === 'trigger_backup') {
        config['backup_type'] = raw.backup_type || 'full';
        config['site_id'] = raw.backup_site_id || undefined;
        config['object_type'] = raw.backup_object_type || undefined;
      }

      if (this.node.type === 'restore_backup') {
        config['version_id'] = raw.restore_version_id || '';
        config['dry_run'] = raw.restore_dry_run ?? false;
        config['cascade'] = raw.restore_cascade ?? false;
      }

      if (this.node.type === 'compare_backups') {
        config['backup_id_1'] = raw.compare_backup_id_1 || '';
        config['backup_id_2'] = raw.compare_backup_id_2 || '';
      }

      updatedNode.config = config;
    }

    this.emitting = true;
    this.configChanged.emit(updatedNode);
  }

  // ── Getters ───────────────────────────────────────────────────────

  // ── Sub-flow input parameter management ──────────────────────────

  subflowInputParams: SubflowParameter[] = [];

  private initSubflowInputParams(): void {
    this.subflowInputParams = [...this.inputParameters];
  }

  addSubflowInputParam(): void {
    this.subflowInputParams = [
      ...this.subflowInputParams,
      { name: '', type: 'any', description: '', required: true, default_value: null },
    ];
    this.emitSubflowInputParams();
  }

  removeSubflowInputParam(index: number): void {
    this.subflowInputParams = this.subflowInputParams.filter((_, i) => i !== index);
    this.emitSubflowInputParams();
  }

  updateSubflowInputParam(index: number, field: string, value: unknown): void {
    this.subflowInputParams = this.subflowInputParams.map((p, i) =>
      i === index ? { ...p, [field]: value } : p
    );
    this.emitSubflowInputParams();
  }

  private emitSubflowInputParams(): void {
    this.inputParametersChanged.emit(this.subflowInputParams);
  }

  // ── Sub-flow output parameter management ─────────────────────────

  subflowOutputParams: SubflowParameter[] = [];

  private initSubflowOutputParams(): void {
    this.subflowOutputParams = [...this.outputParameters];
  }

  addSubflowOutputParam(): void {
    this.subflowOutputParams = [
      ...this.subflowOutputParams,
      { name: '', type: 'any', description: '', required: true, default_value: null },
    ];
    this.emitSubflowOutputParams();
  }

  removeSubflowOutputParam(index: number): void {
    this.subflowOutputParams = this.subflowOutputParams.filter((_, i) => i !== index);
    this.emitSubflowOutputParams();
  }

  updateSubflowOutputParam(index: number, field: string, value: unknown): void {
    this.subflowOutputParams = this.subflowOutputParams.map((p, i) =>
      i === index ? { ...p, [field]: value } : p
    );
    this.emitSubflowOutputParams();
  }

  private emitSubflowOutputParams(): void {
    this.outputParametersChanged.emit(this.subflowOutputParams);
  }

  // ── Invoke sub-flow ──────────────────────────────────────────────

  private loadAvailableSubflows(): void {
    this.workflowService
      .listSubflows()
      .pipe(takeUntil(this.rebuild$))
      .subscribe({
        next: (res) => {
          this.availableSubflows = res.workflows;
          // Auto-load schema if target is already set
          const targetId = this.node.config['target_workflow_id'] as string;
          if (targetId) {
            this.loadSubflowSchema(targetId);
          }
        },
      });
  }

  onEventPairSelected(opening: string): void {
    const pair = this.eventPairs().find((p) => p.opening === opening);
    if (pair) {
      this.form.patchValue({
        webhook_topic: pair.topic,
        event_type_filter: pair.opening,
        closing_event_type: pair.closing,
        device_key: pair.device_key,
      });
    }
  }

  onSubflowTargetChanged(targetId: string): void {
    this.loadSubflowSchema(targetId);
    this.emitChanges();
  }

  private loadSubflowSchema(targetId: string): void {
    if (!targetId) {
      this.selectedSubflowSchema = null;
      return;
    }
    this.workflowService
      .getSubflowSchema(targetId)
      .pipe(takeUntil(this.rebuild$))
      .subscribe({
        next: (schema) => {
          this.selectedSubflowSchema = schema;
          // Cache output schema in node config for variable autocomplete
          const outputSchema: Record<string, string> = {};
          for (const p of schema.output_parameters) {
            outputSchema[p.name] = p.type;
          }
          const updatedNode = {
            ...this.node,
            config: { ...this.node.config, _output_schema: outputSchema },
          };
          this.emitting = true;
          this.configChanged.emit(updatedNode);
        },
        error: () => {
          this.selectedSubflowSchema = null;
        },
      });
  }

  getInputMapping(paramName: string): string {
    const mappings = (this.node.config['input_mappings'] || {}) as Record<string, string>;
    return mappings[paramName] || '';
  }

  setInputMapping(paramName: string, value: string): void {
    const mappings = { ...((this.node.config['input_mappings'] || {}) as Record<string, string>) };
    mappings[paramName] = value;
    const updatedNode = { ...this.node, config: { ...this.node.config, input_mappings: mappings } };
    this.emitting = true;
    this.configChanged.emit(updatedNode);
  }

  appendInputMapping(paramName: string, variablePath: string): void {
    const current = this.getInputMapping(paramName);
    this.setInputMapping(paramName, current + variablePath);
  }

  // ── Sub-flow output ──────────────────────────────────────────────

  getSubflowOutputValue(paramName: string): string {
    const outputs = (this.node.config['outputs'] || {}) as Record<string, string>;
    return outputs[paramName] || '';
  }

  setSubflowOutputValue(paramName: string, value: string): void {
    const outputs = { ...((this.node.config['outputs'] || {}) as Record<string, string>) };
    outputs[paramName] = value;
    const updatedNode = { ...this.node, config: { ...this.node.config, outputs } };
    this.emitting = true;
    this.configChanged.emit(updatedNode);
  }

  appendSubflowOutputValue(paramName: string, variablePath: string): void {
    const current = this.getSubflowOutputValue(paramName);
    this.setSubflowOutputValue(paramName, current + variablePath);
  }

  get isApiAction(): boolean {
    return this.node.type.startsWith('mist_api_');
  }

  get isDeviceUtilAction(): boolean {
    return this.node.type === 'device_utils';
  }

  get isNotificationAction(): boolean {
    return ['slack', 'pagerduty', 'email'].includes(this.node.type);
  }

  get isAiAgentAction(): boolean {
    return this.node.type === 'ai_agent';
  }

  addOutputField(): void {
    this.outputFields.update((fields) => [...fields, { name: '', type: 'string', description: '', required: false }]);
    this._emitOutputFieldsChange();
  }

  removeOutputField(index: number): void {
    this.outputFields.update((fields) => fields.filter((_, i) => i !== index));
    this._emitOutputFieldsChange();
  }

  updateOutputField(index: number, key: string, event: Event | { value: string | boolean }): void {
    const value = 'value' in event ? event.value : (event.target as HTMLInputElement).value;
    this.outputFields.update((fields) =>
      fields.map((f, i) => (i === index ? { ...f, [key]: value } : f)),
    );
    this._emitOutputFieldsChange();
  }

  private _emitOutputFieldsChange(): void {
    if (this.emitting) return;
    this.emitting = true;
    const node = { ...this.node, config: { ...this.node.config, output_fields: this.outputFields() } };
    this.configChanged.emit(node);
    this.emitting = false;
  }


  get hasOutput(): boolean {
    return (
      this.isApiAction ||
      this.isDeviceUtilAction ||
      this.isAiAgentAction ||
      this.node.type === 'webhook' ||
      this.node.type === 'servicenow' ||
      this.node.type === 'data_transform' ||
      this.node.type === 'format_report' ||
      this.node.type === 'trigger_backup' ||
      this.node.type === 'restore_backup' ||
      this.node.type === 'compare_backups'
    );
  }

  get outputHint(): string {
    const t = this.node.type;
    if (this.isApiAction) return 'output.status_code, output.body';
    if (this.isDeviceUtilAction) return 'output.status, output.device_type, output.function, output.data';
    if (this.isAiAgentAction) {
      const base = 'output.status, output.result, output.tool_calls, output.iterations';
      const custom = this.outputFields().filter((f) => f.name).map((f) => `output.${f.name}`);
      return custom.length > 0 ? `${base}, ${custom.join(', ')}` : base;
    }
    if (t === 'webhook') return 'output.status_code, output.response';
    if (t === 'servicenow') return 'output.status_code, output.response';
    if (t === 'data_transform') return 'output.rows, output.columns, output.row_count';
    if (t === 'format_report') return 'output.report, output.format, output.row_count';
    if (t === 'trigger_backup') return 'output.backup_id, output.status, output.object_count';
    if (t === 'restore_backup') return 'output.status, output.version_id, output.result';
    if (t === 'compare_backups') return 'output.differences, output.added_count, output.removed_count, output.modified_count';
    return '';
  }

  get hasErrorHandling(): boolean {
    return !['set_variable', 'for_each', 'condition', 'delay', 'subflow_input', 'subflow_output'].includes(
      this.node.type
    );
  }

  get hasRetry(): boolean {
    return [
      'mist_api_get',
      'mist_api_post',
      'mist_api_put',
      'mist_api_delete',
      'webhook',
      'slack',
      'servicenow',
      'pagerduty',
      'email',
      'device_utils',
    ].includes(this.node.type);
  }

  // ── Device Utils ─────────────────────────────────────────────────

  onDeviceTypeChange(value: string): void {
    this.filteredDeviceFunctions = this.deviceUtilsCatalog.filter(
      (e) => e.device_type === value
    );
    this.selectedDeviceEntry = null;
    this.deviceParamControls = null;
    this.form.get('du_function')?.setValue('', { emitEvent: false });
  }

  onFunctionChange(value: string): void {
    if (!value) {
      this.selectedDeviceEntry = null;
      this.deviceParamControls = null;
      return;
    }
    const entry = this.filteredDeviceFunctions.find((e) => e.function === value);
    this.selectedDeviceEntry = entry || null;
    this.rebuildDeviceParamControls();
  }

  private rebuildDeviceParamControls(
    existingParams?: Record<string, unknown> | null | undefined
  ): void {
    if (!this.selectedDeviceEntry) {
      this.deviceParamControls = null;
      return;
    }
    const controls: Record<string, FormControl> = {};
    const existing = existingParams || {};
    for (const param of this.selectedDeviceEntry.params) {
      controls[param.name] = new FormControl((existing[param.name] as string) || '');
    }
    this.deviceParamControls = this.fb.group(controls);
    this.deviceParamControls.valueChanges
      .pipe(takeUntil(this.rebuild$))
      .subscribe(() => this.emitChanges());
  }

  private tryAutoSelectDeviceUtil(): void {
    if (!this.isDeviceUtilAction) return;
    const config = this.node.config || {};
    const deviceType = config['device_type'] as string;
    if (!deviceType) return;
    this.filteredDeviceFunctions = this.deviceUtilsCatalog.filter(
      (e) => e.device_type === deviceType
    );
    const fn = config['function'] as string;
    if (fn) {
      const entry = this.filteredDeviceFunctions.find((e) => e.function === fn);
      if (entry) {
        this.selectedDeviceEntry = entry;
        this.rebuildDeviceParamControls(config['params'] as Record<string, unknown>);
      }
    }
  }

  // ── Slack Fields ─────────────────────────────────────────────────

  get slackFieldsArray(): FormArray {
    return this.form?.get('slack_fields') as FormArray;
  }

  get waitActionsArray(): FormArray {
    return this.form?.get('wait_actions') as FormArray;
  }

  addWaitAction(): void {
    this.waitActionsArray.push(
      this.fb.group({ text: [''], action_id: [''], style: [''] })
    );
  }

  removeWaitAction(index: number): void {
    this.waitActionsArray.removeAt(index);
  }

  addSlackField(): void {
    this.slackFieldsArray.push(this.fb.group({ label: [''], value: [''] }));
  }

  removeSlackField(index: number): void {
    this.slackFieldsArray.removeAt(index);
  }

  // ── Data Transform fields ──────────────────────────────────────

  get dtFieldsArray(): FormArray {
    return this.form?.get('dt_fields') as FormArray;
  }

  addDtField(): void {
    this.dtFieldsArray.push(this.fb.group({ path: [''], label: [''] }));
  }

  removeDtField(index: number): void {
    this.dtFieldsArray.removeAt(index);
  }

  // ── JSON apply handlers ────────────────────────────────────────

  applySlackFieldsJson(data: unknown[]): void {
    this.slackFieldsArray.clear();
    for (const item of data) {
      const f = item as { label?: string; value?: string };
      this.slackFieldsArray.push(
        this.fb.group({ label: [f.label || ''], value: [f.value || ''] })
      );
    }
  }

  applyDtFieldsJson(data: unknown[]): void {
    this.dtFieldsArray.clear();
    for (const item of data) {
      const f = item as { path?: string; label?: string };
      this.dtFieldsArray.push(
        this.fb.group({ path: [f.path || ''], label: [f.label || ''] })
      );
    }
  }

  applyBranchesJson(data: unknown[]): void {
    this.branchesArray.clear();
    for (const item of data) {
      const b = item as { condition?: string };
      this.branchesArray.push(this.fb.group({ condition: [b.condition || ''] }));
    }
  }

  applySaveAsJson(data: unknown[]): void {
    this.saveAsArray.clear();
    for (const item of data) {
      const b = item as { name?: string; expression?: string };
      this.saveAsArray.push(
        this.fb.group({ name: [b.name || ''], expression: [b.expression || ''] })
      );
    }
  }
}
