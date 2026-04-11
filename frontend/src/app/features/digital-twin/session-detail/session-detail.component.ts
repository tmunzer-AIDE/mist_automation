import {
  Component,
  OnDestroy,
  OnInit,
  TemplateRef,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { JsonPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { StatusBadgeComponent } from '../../../shared/components/status-badge/status-badge.component';
import {
  ConfirmDialogComponent,
  ConfirmDialogData,
} from '../../../shared/components/confirm-dialog/confirm-dialog.component';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';
import { TopbarService } from '../../../core/services/topbar.service';
import { DigitalTwinService } from '../digital-twin.service';
import { CheckResultModel, TwinSessionDetail } from '../models/twin-session.model';

interface LayerInfo {
  number: number;
  name: string;
}

const LAYERS: LayerInfo[] = [
  { number: 0, name: 'Input Validation' },
  { number: 1, name: 'Config Conflicts' },
  { number: 2, name: 'Topology' },
  { number: 3, name: 'Routing' },
  { number: 4, name: 'Security' },
  { number: 5, name: 'L2 Loops / STP' },
];

@Component({
  selector: 'app-session-detail',
  standalone: true,
  imports: [
    JsonPipe,
    RouterLink,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressBarModule,
    MatTabsModule,
    MatSnackBarModule,
    MatTooltipModule,
    StatusBadgeComponent,
    DateTimePipe,
  ],
  templateUrl: './session-detail.component.html',
  styleUrl: './session-detail.component.scss',
})
export class SessionDetailComponent implements OnInit, OnDestroy {
  @ViewChild('actionsTemplate', { static: true }) actionsTemplate!: TemplateRef<unknown>;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly service = inject(DigitalTwinService);
  private readonly topbarService = inject(TopbarService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  session = signal<TwinSessionDetail | null>(null);
  loading = signal(true);
  expandedChecks = signal<Set<string>>(new Set());
  expandedWrites = signal<Set<number>>(new Set());
  expandedLayers = signal<Set<number>>(new Set([1, 2, 3, 4, 5]));

  isAwaitingApproval = computed(() => this.session()?.status === 'awaiting_approval');
  canApprove = computed(() => {
    const s = this.session();
    return !!s && s.status === 'awaiting_approval' && s.execution_safe && !this.hasBlockingPreflightErrors(s);
  });

  checksByLayer = computed(() => {
    const checks = this.session()?.prediction_report?.check_results ?? [];
    const map = new Map<number, CheckResultModel[]>();
    for (const c of checks) {
      if (c.status === 'skipped') continue;
      const list = map.get(c.layer) ?? [];
      list.push(c);
      map.set(c.layer, list);
    }
    return map;
  });

  readonly layers = LAYERS;

  private sessionId = '';

  ngOnInit(): void {
    this.topbarService.setTitle('Digital Twin');
    this.topbarService.setActions(this.actionsTemplate);
    this.sessionId = this.route.snapshot.paramMap.get('id') ?? '';
    this.loadSession(this.sessionId);
  }

  ngOnDestroy(): void {
    this.topbarService.clearActions();
  }

  loadSession(id: string): void {
    this.loading.set(true);
    this.service.getSession(id).subscribe({
      next: (s) => {
        this.session.set(s);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.router.navigate(['/digital-twin']);
      },
    });
  }

  checksForLayer(layer: number): CheckResultModel[] {
    return this.checksByLayer().get(layer) ?? [];
  }

  issueCountForLayer(layer: number): number {
    return this.checksForLayer(layer).filter(
      (c) => c.status === 'warning' || c.status === 'error' || c.status === 'critical',
    ).length;
  }

  isLayerExpanded(layer: number): boolean {
    return this.expandedLayers().has(layer);
  }

  toggleLayer(layer: number): void {
    const set = new Set(this.expandedLayers());
    if (set.has(layer)) {
      set.delete(layer);
    } else {
      set.add(layer);
    }
    this.expandedLayers.set(set);
  }

  isCheckExpanded(checkId: string): boolean {
    return this.expandedChecks().has(checkId);
  }

  toggleCheck(checkId: string): void {
    const set = new Set(this.expandedChecks());
    if (set.has(checkId)) {
      set.delete(checkId);
    } else {
      set.add(checkId);
    }
    this.expandedChecks.set(set);
  }

  isWriteExpanded(seq: number): boolean {
    return this.expandedWrites().has(seq);
  }

  toggleWrite(seq: number): void {
    const set = new Set(this.expandedWrites());
    if (set.has(seq)) {
      set.delete(seq);
    } else {
      set.add(seq);
    }
    this.expandedWrites.set(set);
  }

  severityLabel(severity: string): string {
    if (!severity || severity === 'clean') return 'Safe';
    if (severity === 'info') return 'Info';
    return severity.charAt(0).toUpperCase() + severity.slice(1);
  }

  sourceLabel(source: string): string {
    switch (source) {
      case 'llm_chat':
        return 'LLM Chat';
      case 'workflow':
        return 'Workflow';
      case 'backup_restore':
        return 'Backup Restore';
      default:
        return source;
    }
  }

  methodClass(method: string): string {
    switch (method.toUpperCase()) {
      case 'POST':
        return 'method-post';
      case 'PUT':
        return 'method-put';
      case 'DELETE':
        return 'method-delete';
      default:
        return 'method-other';
    }
  }

  private hasBlockingPreflightErrors(session: TwinSessionDetail): boolean {
    return (session.prediction_report?.check_results ?? []).some(
      (check) =>
        check.layer === 0 &&
        check.check_id.startsWith('SYS-') &&
        (check.status === 'error' || check.status === 'critical'),
    );
  }

  approve(): void {
    const s = this.session();
    if (!s) return;
    if (!this.canApprove()) {
      const message = this.hasBlockingPreflightErrors(s)
        ? 'Cannot deploy: preflight validation failed. Fix SYS checks and re-simulate.'
        : 'Cannot deploy: session has blocking validation issues.';
      this.snackBar.open(message, 'Dismiss', { duration: 5000 });
      return;
    }
    const writesCount = s.staged_writes.length;
    this.dialog
      .open(ConfirmDialogComponent, {
        data: {
          title: 'Approve & Deploy',
          message: `This will apply ${writesCount} staged write${writesCount !== 1 ? 's' : ''} to your Mist organization. This action cannot be undone.`,
          confirmText: 'Deploy',
          warn: false,
        } satisfies ConfirmDialogData,
      })
      .afterClosed()
      .subscribe((confirmed) => {
        if (!confirmed) return;
        this.loading.set(true);
        this.service.approveSession(this.sessionId).subscribe({
          next: (updated) => {
            this.session.set(updated);
            this.loading.set(false);
          },
          error: () => {
            this.loading.set(false);
            this.snackBar.open('Failed to approve session', 'Dismiss', { duration: 5000 });
          },
        });
      });
  }

  reject(): void {
    this.dialog
      .open(ConfirmDialogComponent, {
        data: {
          title: 'Reject Session',
          message: 'Are you sure you want to reject this session? All staged writes will be discarded.',
          confirmText: 'Reject',
          warn: true,
        } satisfies ConfirmDialogData,
      })
      .afterClosed()
      .subscribe((confirmed) => {
        if (!confirmed) return;
        this.loading.set(true);
        this.service.cancelSession(this.sessionId).subscribe({
          next: () => {
            this.loading.set(false);
            this.router.navigate(['/digital-twin']);
          },
          error: () => {
            this.loading.set(false);
            this.snackBar.open('Failed to reject session', 'Dismiss', { duration: 5000 });
          },
        });
      });
  }
}
