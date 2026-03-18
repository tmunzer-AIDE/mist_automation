import {
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnChanges,
  OnInit,
  Output,
  SimpleChanges,
  inject,
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
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { Subject, takeUntil } from 'rxjs';
import {
  WorkflowNode,
  ActionType,
  ApiCatalogEntry,
  DeviceUtilEntry,
  VariableBinding,
  VariableTree,
  WorkflowType,
  SubflowParameter,
  WorkflowResponse,
  SubflowSchemaResponse,
} from '../../../../core/models/workflow.model';
import { WorkflowService } from '../../../../core/services/workflow.service';
import { VariablePickerComponent } from './variable-picker.component';
import { JsonSectionToggleComponent } from './json-section-toggle.component';

@Component({
  selector: 'app-node-config-panel',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatIconModule,
    MatButtonModule,
    MatAutocompleteModule,
    MatMenuModule,
    MatSlideToggleModule,
    VariablePickerComponent,
    JsonSectionToggleComponent,
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
              <mat-select formControlName="trigger_type">
                <mat-option value="webhook">Webhook</mat-option>
                <mat-option value="cron">Cron Schedule</mat-option>
                <mat-option value="manual">Manual</mat-option>
              </mat-select>
            </mat-form-field>

            @if (form.get('trigger_type')?.value === 'webhook') {
              <mat-form-field appearance="outline">
                <mat-label>Webhook Topic</mat-label>
                <mat-select formControlName="webhook_topic">
                  <mat-option value="alarms">Alarms</mat-option>
                  <mat-option value="audits">Audits</mat-option>
                  <mat-option value="device-updowns">Device Up/Downs</mat-option>
                  <mat-option value="device-events">Device Events</mat-option>
                  <mat-option value="occupancy-alerts">Occupancy Alerts</mat-option>
                  <mat-option value="sdkclient-scan-data">SDK Client Scan</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Event Type Filter (optional)</mat-label>
                <input matInput formControlName="event_type_filter" />
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

            <mat-form-field appearance="outline">
              <mat-label>Condition (optional)</mat-label>
              <textarea matInput formControlName="condition" rows="2"
                placeholder="{{ '{{' }} events[0].type == 'ap_offline' {{ '}}' }}"></textarea>
            </mat-form-field>

            <mat-checkbox formControlName="skip_if_running">Skip if already running</mat-checkbox>
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
                  <input matInput formControlName="api_endpoint" />
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
                <input matInput formControlName="webhook_url" />
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Headers (JSON)</mat-label>
                <textarea matInput formControlName="webhook_headers" rows="2"></textarea>
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Body (JSON)</mat-label>
                <textarea matInput formControlName="webhook_body" rows="3"></textarea>
              </mat-form-field>
            }

            <!-- Notification fields -->
            @if (isNotificationAction) {
              <mat-form-field appearance="outline">
                <mat-label>Channel</mat-label>
                <input matInput formControlName="notification_channel" />
              </mat-form-field>

              @if (node.type === 'slack') {
                <mat-form-field appearance="outline">
                  <mat-label>Header (optional)</mat-label>
                  <input matInput formControlName="slack_header" />
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
                <textarea matInput formControlName="notification_template" rows="3"></textarea>
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
                  <input matInput formControlName="slack_footer" />
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
                  <input matInput formControlName="slack_json_variable" placeholder="trigger" />
                  <button mat-icon-button matSuffix [matMenuTriggerFor]="jsonVarMenu">
                    <mat-icon>data_object</mat-icon>
                  </button>
                  <mat-menu #jsonVarMenu="matMenu">
                    <app-variable-picker
                      [variableTree]="variableTree"
                      (variableSelected)="insertJsonVariablePath($event)"
                    />
                  </mat-menu>
                  <mat-hint>Dumps the variable as a formatted JSON code block</mat-hint>
                </mat-form-field>

                <div class="config-hint">
                  <mat-icon>info_outline</mat-icon>
                  If an upstream Format Report uses Slack format, its table is automatically
                  included below the message.
                </div>
              }
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
              <mat-form-field appearance="outline">
                <mat-label>Variable Name</mat-label>
                <input matInput formControlName="variable_name" />
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Expression</mat-label>
                <textarea matInput formControlName="variable_expression" rows="2"></textarea>
                <button mat-icon-button matSuffix [matMenuTriggerFor]="varMenu">
                  <mat-icon>data_object</mat-icon>
                </button>
                <mat-menu #varMenu="matMenu">
                  <app-variable-picker
                    [variableTree]="variableTree"
                    (variableSelected)="insertIntoControl(form.get('variable_expression')!, $event)"
                  />
                </mat-menu>
              </mat-form-field>
            }

            <!-- For Each -->
            @if (node.type === 'for_each') {
              <mat-form-field appearance="outline">
                <mat-label>Loop Over (dot path)</mat-label>
                <input matInput formControlName="loop_over" placeholder="nodes.MyApiCall.body.results" />
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
                <input matInput formControlName="dt_source" placeholder="nodes.Get_Devices.body" />
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
                <input matInput formControlName="dt_filter"
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
                <input matInput formControlName="fr_data_source"
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
                <mat-select formControlName="fr_format">
                  <mat-option value="markdown">Markdown</mat-option>
                  <mat-option value="slack">Slack</mat-option>
                  <mat-option value="csv">CSV</mat-option>
                  <mat-option value="text">Plain Text</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline">
                <mat-label>Title (optional)</mat-label>
                <input matInput formControlName="fr_title"
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
                <input matInput formControlName="fr_footer_template"
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
                <input matInput formControlName="email_subject"
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

            <!-- Device Utils -->
            @if (isDeviceUtilAction) {
              <mat-form-field appearance="outline">
                <mat-label>Device Type</mat-label>
                <mat-select formControlName="du_device_type">
                  <mat-option value="ap">AP (Access Point)</mat-option>
                  <mat-option value="ex">EX (Switch)</mat-option>
                  <mat-option value="srx">SRX (Firewall)</mat-option>
                  <mat-option value="ssr">SSR (Router)</mat-option>
                </mat-select>
              </mat-form-field>

              @if (form.get('du_device_type')?.value) {
                <mat-form-field appearance="outline">
                  <mat-label>Utility Function</mat-label>
                  <mat-select formControlName="du_function">
                    @for (entry of filteredDeviceFunctions; track entry.id) {
                      <mat-option [value]="entry.function">{{ entry.label }}</mat-option>
                    }
                  </mat-select>
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
                    <mat-select [value]="param.type" (selectionChange)="updateSubflowInputParam(i, 'type', $event.value)">
                      <mat-option value="any">Any</mat-option>
                      <mat-option value="string">String</mat-option>
                      <mat-option value="number">Number</mat-option>
                      <mat-option value="boolean">Boolean</mat-option>
                      <mat-option value="object">Object</mat-option>
                      <mat-option value="array">Array</mat-option>
                    </mat-select>
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
                <mat-select formControlName="target_workflow_id" (selectionChange)="onSubflowTargetChanged($event.value)">
                  @for (sf of availableSubflows; track sf.id) {
                    <mat-option [value]="sf.id">{{ sf.name }}</mat-option>
                  }
                </mat-select>
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
                    <mat-select [value]="param.type" (selectionChange)="updateSubflowOutputParam(i, 'type', $event.value)">
                      <mat-option value="any">Any</mat-option>
                      <mat-option value="string">String</mat-option>
                      <mat-option value="number">Number</mat-option>
                      <mat-option value="boolean">Boolean</mat-option>
                      <mat-option value="object">Object</mat-option>
                      <mat-option value="array">Array</mat-option>
                    </mat-select>
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
    `,
  ],
})
export class NodeConfigPanelComponent implements OnChanges, OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly workflowService = inject(WorkflowService);
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
      notification_template: [config['notification_template'] || ''],
      notification_channel: [config['notification_channel'] || ''],
      branches: this.fb.array(branchControls),
      delay_seconds: [config['delay_seconds'] || 0],
      save_as: this.fb.array(saveAsControls),
      variable_name: [config['variable_name'] || ''],
      variable_expression: [config['variable_expression'] || ''],
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
      email_subject: [config['email_subject'] || ''],
      email_html: [config['email_html'] ?? false],
      target_workflow_id: [config['target_workflow_id'] || ''],
      du_device_type: [config['device_type'] || ''],
      du_function: [config['function'] || ''],
      du_site_id: [config['site_id'] || ''],
      du_device_id: [config['device_id'] || ''],
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
        if (raw.webhook_headers) {
          try { config['webhook_headers'] = JSON.parse(raw.webhook_headers); } catch { /* */ }
        }
        if (raw.webhook_body) {
          try { config['webhook_body'] = JSON.parse(raw.webhook_body); } catch { /* */ }
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
        }
      }

      if (this.node.type === 'delay') {
        config['delay_seconds'] = raw.delay_seconds;
      }

      if (this.node.type === 'set_variable') {
        config['variable_name'] = raw.variable_name;
        config['variable_expression'] = raw.variable_expression;
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
          this.node.config['_output_schema'] = outputSchema;
          this.emitChanges();
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
    this.node.config['input_mappings'] = mappings;
    this.emitChanges();
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
    this.node.config['outputs'] = outputs;
    this.emitChanges();
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
    return ['slack', 'servicenow', 'pagerduty', 'email'].includes(this.node.type);
  }

  get hasOutput(): boolean {
    return (
      this.isApiAction ||
      this.isDeviceUtilAction ||
      this.node.type === 'webhook' ||
      this.node.type === 'data_transform' ||
      this.node.type === 'format_report'
    );
  }

  get outputHint(): string {
    const t = this.node.type;
    if (this.isApiAction) return 'output.status_code, output.body';
    if (this.isDeviceUtilAction) return 'output.status, output.device_type, output.function, output.data';
    if (t === 'webhook') return 'output.status_code, output.response';
    if (t === 'data_transform') return 'output.rows, output.columns, output.row_count';
    if (t === 'format_report') return 'output.report, output.format, output.row_count';
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
