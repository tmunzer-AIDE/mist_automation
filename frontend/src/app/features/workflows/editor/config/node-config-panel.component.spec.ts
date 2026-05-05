import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { SimpleChange } from '@angular/core';
import { of } from 'rxjs';

import { NodeConfigPanelComponent } from './node-config-panel.component';
import { WorkflowService } from '../../../../core/services/workflow.service';
import { LlmService } from '../../../../core/services/llm.service';
import { WorkflowNode } from '../../../../core/models/workflow.model';

function makeNode(overrides: Partial<WorkflowNode> = {}): WorkflowNode {
  return {
    id: 'node-1',
    type: 'slack',
    name: 'Slack Notification',
    position: { x: 0, y: 0 },
    config: {},
    output_ports: [{ id: 'default', label: 'Default', type: 'default' }],
    enabled: true,
    continue_on_error: false,
    max_retries: 0,
    retry_delay: 0,
    save_as: [],
    ...overrides,
  };
}

async function createComponent(node: WorkflowNode) {
  const workflowService = {
    getApiCatalog: () => of([]),
    getDeviceUtilsCatalog: () => of([]),
    getEventPairs: () => of([]),
  };
  const llmService = {
    listAvailableConfigs: () => of([]),
    listAvailableMcpConfigs: () => of([]),
  };

  await TestBed.configureTestingModule({
    imports: [NodeConfigPanelComponent],
    providers: [
      provideAnimationsAsync('noop'),
      { provide: WorkflowService, useValue: workflowService },
      { provide: LlmService, useValue: llmService },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(NodeConfigPanelComponent);
  fixture.componentRef.setInput('node', node);
  // Manually trigger ngOnChanges so the form is built (mirrors what Angular does
  // when the parent binds the [node] input).
  fixture.componentInstance.ngOnChanges({
    node: new SimpleChange(null, node, true),
  });
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('NodeConfigPanelComponent — Slack notification config', () => {
  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('shows "Slack Webhook URL" label for notification_channel on Slack nodes', async () => {
    const fixture = await createComponent(makeNode({ type: 'slack' }));
    const html = fixture.nativeElement as HTMLElement;
    const labels = Array.from(html.querySelectorAll('mat-label')).map(
      (el) => (el.textContent || '').trim()
    );
    expect(labels).toContain('Slack Webhook URL');
    expect(labels).not.toContain('Channel');
  });

  it('shows "Channel" label for notification_channel on non-Slack notification nodes', async () => {
    const fixture = await createComponent(makeNode({ type: 'pagerduty' }));
    const html = fixture.nativeElement as HTMLElement;
    const labels = Array.from(html.querySelectorAll('mat-label')).map(
      (el) => (el.textContent || '').trim()
    );
    expect(labels).toContain('Channel');
    expect(labels).not.toContain('Slack Webhook URL');
  });

  it('exposes auto_convert_markdown form control defaulting to true for new Slack nodes', async () => {
    const fixture = await createComponent(makeNode({ type: 'slack' }));
    const ctrl = fixture.componentInstance.form.get('auto_convert_markdown');
    expect(ctrl).toBeTruthy();
    expect(ctrl!.value).toBe(true);
  });

  it('renders the .slack-guidance block in the Slack node config panel', async () => {
    const fixture = await createComponent(makeNode({ type: 'slack' }));
    const html = fixture.nativeElement as HTMLElement;
    const guidance = html.querySelector('.slack-guidance');
    expect(guidance).toBeTruthy();
    expect((guidance!.textContent || '')).toContain('Message Template');
    const details = html.querySelector('.slack-guidance-more') as HTMLDetailsElement | null;
    expect(details).toBeTruthy();
    expect(details!.querySelector('summary')).toBeTruthy();
    expect(details!.hasAttribute('open')).toBe(false);
  });

  it('persists auto_convert_markdown=false on Slack node config when checkbox is unchecked', async () => {
    const fixture = await createComponent(makeNode({ type: 'slack' }));
    const component = fixture.componentInstance;
    let emitted: WorkflowNode | null = null;
    component.configChanged.subscribe((node) => (emitted = node));

    component.form.get('auto_convert_markdown')!.setValue(false);
    await fixture.whenStable();

    expect(emitted).not.toBeNull();
    expect((emitted as unknown as WorkflowNode).config['auto_convert_markdown']).toBe(false);
  });

  it('does not persist auto_convert_markdown on non-Slack notification nodes (e.g., pagerduty)', async () => {
    const fixture = await createComponent(makeNode({ type: 'pagerduty' }));
    const component = fixture.componentInstance;
    let emitted: WorkflowNode | null = null;
    component.configChanged.subscribe((node) => (emitted = node));

    // Trigger an emit by changing some unrelated control on this node type.
    component.form.get('notification_channel')!.setValue('#alerts');
    await fixture.whenStable();

    expect(emitted).not.toBeNull();
    expect(
      Object.prototype.hasOwnProperty.call(
        (emitted as unknown as WorkflowNode).config,
        'auto_convert_markdown'
      )
    ).toBe(false);
  });
});
