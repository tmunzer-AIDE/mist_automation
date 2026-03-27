import { Component, inject, signal, HostListener } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { Router, RouterOutlet, NavigationEnd, ActivatedRoute } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatSidenavModule } from '@angular/material/sidenav';
import { SidebarComponent } from './sidebar/sidebar.component';
import { TopbarComponent } from './topbar/topbar.component';
import { AiPanelComponent } from '../shared/components/ai-panel/ai-panel.component';
import { LlmService } from '../core/services/llm.service';
import { GlobalChatService } from '../core/services/global-chat.service';
import { PanelStateService } from '../core/services/panel-state.service';
import { filter, map } from 'rxjs';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterOutlet, MatSidenavModule, SidebarComponent, TopbarComponent, AiPanelComponent],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent {
  private readonly router = inject(Router);
  private readonly activatedRoute = inject(ActivatedRoute);
  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly llmService = inject(LlmService);
  readonly globalChatService = inject(GlobalChatService);
  readonly panelState = inject(PanelStateService);

  isMobile = signal(false);
  sidebarOpen = signal(true);
  sidebarCollapsed = signal(false);
  isFullWidth = signal(false);
  llmAvailable = signal(false);
  maintenanceMode = signal(false);
  resizing = signal(false);

  constructor() {
    inject(HttpClient)
      .get<any>('/health')
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (h: any) => this.maintenanceMode.set(h.maintenance_mode ?? false),
        error: () => {},
      });

    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => this.llmAvailable.set(false),
    });

    this.breakpointObserver
      .observe([Breakpoints.Handset])
      .pipe(takeUntilDestroyed())
      .subscribe((result) => {
        this.isMobile.set(result.matches);
        this.sidebarOpen.set(!result.matches);
      });

    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        map(() => {
          let route = this.activatedRoute;
          while (route.firstChild) route = route.firstChild;
          return route.snapshot.data;
        }),
        takeUntilDestroyed(),
      )
      .subscribe((data) => {
        this.isFullWidth.set(!!data['fullWidth']);
      });
  }

  toggleSidebar(): void {
    if (this.isMobile()) {
      this.sidebarOpen.update((v) => !v);
    } else {
      this.sidebarCollapsed.update((v) => !v);
    }
  }

  /** Whether the AI panel should render (LLM available + not mobile) */
  get showAiPanel(): boolean {
    return this.llmAvailable() && !this.isMobile() && this.globalChatService.panelOpen();
  }

  // ── Resize handle ──────────────────────────────────────

  onResizeStart(event: MouseEvent): void {
    event.preventDefault();
    this.resizing.set(true);

    const onMove = (e: MouseEvent) => {
      // Panel is on the left of content; width = mouse X - sidebar width
      const sidebarWidth = this.sidebarCollapsed() ? 56 : 240;
      const newWidth = e.clientX - sidebarWidth;
      this.panelState.setWidth(newWidth);
    };

    const onUp = () => {
      this.resizing.set(false);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Keyboard shortcut (Ctrl+\) ────────────────────────

  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (event.ctrlKey && event.key === '\\') {
      event.preventDefault();
      this.globalChatService.toggle();
    }
  }
}
