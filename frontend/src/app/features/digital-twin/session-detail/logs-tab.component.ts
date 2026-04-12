import { Component, Input, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { debounceTime, switchMap, startWith } from 'rxjs/operators';
import { combineLatest } from 'rxjs';

import { DigitalTwinService } from '../digital-twin.service';
import { SimulationLogEntry } from '../models/twin-session.model';
import { DateTimePipe } from '../../../shared/pipes/date-time.pipe';

type Phase = 'simulate' | 'remediate' | 'approve' | 'execute' | 'other';
const PHASE_ORDER: Phase[] = ['simulate', 'remediate', 'approve', 'execute', 'other'];

@Component({
  selector: 'app-digital-twin-logs-tab',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatIconModule,
    DateTimePipe,
  ],
  templateUrl: './logs-tab.component.html',
  styleUrl: './logs-tab.component.scss',
})
export class LogsTabComponent implements OnInit {
  @Input({ required: true }) sessionId!: string;

  private readonly service = inject(DigitalTwinService);

  readonly levelControl = new FormControl<string>('');
  readonly searchControl = new FormControl<string>('');

  readonly entries = signal<SimulationLogEntry[]>([]);
  readonly loading = signal(false);
  readonly collapsedPhases = signal(new Set<Phase>());

  readonly grouped = computed(() => {
    const byPhase = new Map<Phase, SimulationLogEntry[]>();
    for (const phase of PHASE_ORDER) byPhase.set(phase, []);
    for (const entry of this.entries()) {
      byPhase.get(entry.phase as Phase)?.push(entry);
    }
    return PHASE_ORDER.map((phase) => ({
      phase,
      entries: byPhase.get(phase) ?? [],
    })).filter((g) => g.entries.length > 0);
  });

  ngOnInit(): void {
    combineLatest([
      this.levelControl.valueChanges.pipe(startWith(this.levelControl.value)),
      this.searchControl.valueChanges.pipe(
        startWith(this.searchControl.value),
        debounceTime(200),
      ),
    ])
      .pipe(
        switchMap(([level, search]) => {
          this.loading.set(true);
          return this.service.getSessionLogs(this.sessionId, {
            level: level || undefined,
            search: search || undefined,
          });
        }),
      )
      .subscribe((entries) => {
        this.entries.set(entries);
        this.loading.set(false);
        // First group with entries starts expanded, rest collapsed
        const collapsed = new Set<Phase>();
        let firstFound = false;
        for (const phase of PHASE_ORDER) {
          if (entries.some((e) => e.phase === phase)) {
            if (firstFound) collapsed.add(phase);
            firstFound = true;
          }
        }
        this.collapsedPhases.set(collapsed);
      });
  }

  togglePhase(phase: Phase): void {
    this.collapsedPhases.update((set) => {
      const next = new Set(set);
      if (next.has(phase)) {
        next.delete(phase);
      } else {
        next.add(phase);
      }
      return next;
    });
  }

  isCollapsed(phase: Phase): boolean {
    return this.collapsedPhases().has(phase);
  }

  contextEntries(context: Record<string, unknown>): { key: string; value: string }[] {
    return Object.entries(context).map(([key, value]) => ({
      key,
      value: typeof value === 'object' ? JSON.stringify(value) : String(value),
    }));
  }

  phaseLabel(phase: Phase): string {
    return {
      simulate: 'Simulate',
      remediate: 'Remediation',
      approve: 'Approve',
      execute: 'Execute',
      other: 'Other',
    }[phase];
  }
}
