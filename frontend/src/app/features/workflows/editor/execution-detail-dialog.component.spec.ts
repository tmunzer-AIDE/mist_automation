import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { ExecutionDetailDialogComponent } from './execution-detail-dialog.component';
import { WorkflowService } from '../../../core/services/workflow.service';
import { LlmService } from '../../../core/services/llm.service';
import {
  NodeExecutionResult,
  WorkflowExecution,
} from '../../../core/models/workflow.model';

function makeNodeResult(overrides: Partial<NodeExecutionResult> = {}): NodeExecutionResult {
  return {
    node_id: 'node-1',
    node_name: 'Test Node',
    node_type: 'ai_agent',
    status: 'success',
    started_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
    duration_ms: 1000,
    error: null,
    output_data: null,
    input_snapshot: null,
    retry_count: 0,
    ...overrides,
  };
}

function makeExecution(nodeResult: NodeExecutionResult): WorkflowExecution {
  return {
    id: 'exec-1',
    workflow_id: 'wf-1',
    workflow_name: 'Test Workflow',
    status: 'success',
    trigger_type: 'manual',
    trigger_data: null,
    triggered_by: null,
    started_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
    duration_ms: 1000,
    trigger_condition_passed: null,
    trigger_condition: null,
    nodes_executed: 1,
    nodes_succeeded: 1,
    nodes_failed: 0,
    node_results: { [nodeResult.node_id]: nodeResult },
    node_snapshots: [],
    is_simulation: false,
    is_dry_run: false,
    parent_execution_id: null,
    parent_workflow_id: null,
    child_execution_ids: [],
    error: null,
    error_details: null,
  };
}

async function createComponentWith(nodeResult: NodeExecutionResult) {
  const execution = makeExecution(nodeResult);
  const workflowService = {
    getExecution: () => of(execution),
  };
  const llmService = {
    getStatus: () => of({ enabled: false }),
    debugExecution: () => of({ thread_id: 't-1', analysis: '' }),
  };
  const dialogRef = { close: () => undefined };

  await TestBed.configureTestingModule({
    imports: [ExecutionDetailDialogComponent],
    providers: [
      provideAnimationsAsync('noop'),
      { provide: MAT_DIALOG_DATA, useValue: { workflowId: 'wf-1', execution } },
      { provide: MatDialogRef, useValue: dialogRef },
      { provide: WorkflowService, useValue: workflowService },
      { provide: LlmService, useValue: llmService },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(ExecutionDetailDialogComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('ExecutionDetailDialogComponent — AI agent rendering', () => {
  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('renders AI card with status, iterations, result text, and field chips', async () => {
    const result = makeNodeResult({
      output_data: {
        result: 'AI generated answer',
        iterations: 3,
        output_fields: { severity: 'high', count: 5 },
        status: 'success',
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const card = html.querySelector('.ai-result-card');
    expect(card).toBeTruthy();

    expect(html.querySelector('.ai-result-title')?.textContent).toContain('AI Agent Result');
    expect(html.querySelector('.ai-result-meta')?.textContent).toContain('3 iterations');
    expect(html.querySelector('.ai-result-text')?.textContent).toContain('AI generated answer');

    const chips = html.querySelectorAll('mat-chip');
    expect(chips.length).toBe(2);
    const chipText = Array.from(chips).map((c) => c.textContent || '');
    expect(chipText.some((t) => t.includes('severity') && t.includes('high'))).toBe(true);
    expect(chipText.some((t) => t.includes('count') && t.includes('5'))).toBe(true);
  });

  it('renders the collapsible tool calls panel with tool name and preview', async () => {
    const result = makeNodeResult({
      output_data: {
        result: 'done',
        tool_calls: [
          { name: 'mist_get_sites', result: 'Returned 3 sites: site-a, site-b, site-c' },
        ],
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const panel = html.querySelector('.ai-tool-calls-panel');
    expect(panel).toBeTruthy();
    expect(panel?.textContent).toContain('1 tool call(s)');

    const row = html.querySelector('.ai-tool-call-row');
    expect(row).toBeTruthy();
    expect(row?.querySelector('strong')?.textContent).toContain('mist_get_sites');
    expect(row?.querySelector('.ai-tool-preview')?.textContent).toContain(
      'Returned 3 sites: site-a, site-b, site-c',
    );
  });

  it('shows fallback for unrecognized tool call format with raw JSON details', async () => {
    const weirdToolCall = { foo: 'bar', baz: 42 };
    const result = makeNodeResult({
      output_data: {
        result: 'done',
        tool_calls: [weirdToolCall],
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const row = html.querySelector('.ai-tool-call-row');
    expect(row).toBeTruthy();
    expect(row?.querySelector('strong')?.textContent).toContain('Tool call (format unrecognized)');

    const details = row?.querySelector('details.ai-tool-raw-json');
    expect(details).toBeTruthy();
    expect(details?.querySelector('summary')?.textContent).toContain('Raw tool call JSON');
    const pre = details?.querySelector('pre')?.textContent || '';
    expect(pre).toContain('foo');
    expect(pre).toContain('bar');
  });

  it('non-AI node types render only raw JSON output (no AI card)', async () => {
    const result = makeNodeResult({
      node_type: 'mist_api_get',
      output_data: { items: [1, 2, 3] },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    expect(html.querySelector('.ai-result-card')).toBeNull();

    const details = html.querySelector('details.action-output');
    expect(details).toBeTruthy();
    expect(details?.querySelector('pre')?.textContent).toContain('items');
  });

  it('shows error message when AI agent has error status', async () => {
    const result = makeNodeResult({
      status: 'failed',
      output_data: {
        status: 'error',
        error: 'Tool call failed: rate limited',
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const errorEl = html.querySelector('.ai-result-error');
    expect(errorEl).toBeTruthy();
    expect(errorEl?.textContent).toContain('Tool call failed: rate limited');
  });

  it('shows "No result" placeholder when AI agent result is empty', async () => {
    const result = makeNodeResult({
      output_data: {
        result: '',
        status: 'success',
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const empty = html.querySelector('.ai-result-empty');
    expect(empty).toBeTruthy();
    expect(empty?.textContent).toContain('No result');
  });

  it('renders very long result text without crashing', async () => {
    const longText = 'A'.repeat(2000);
    const result = makeNodeResult({
      output_data: {
        result: longText,
        status: 'success',
      },
    });
    const fixture = await createComponentWith(result);
    const html = fixture.nativeElement as HTMLElement;

    const textEl = html.querySelector('.ai-result-text');
    expect(textEl).toBeTruthy();
    expect(textEl?.textContent?.length).toBeGreaterThanOrEqual(2000);
  });
});
