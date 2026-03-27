import { Component, Output, EventEmitter, computed, inject, signal } from '@angular/core';
import { AsyncPipe, NgTemplateOutlet } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Store } from '@ngrx/store';
import { selectCurrentUser } from '../../core/state/auth/auth.selectors';
import { AuthActions } from '../../core/state/auth/auth.actions';
import { TopbarService } from '../../core/services/topbar.service';
import { GlobalChatService } from '../../core/services/global-chat.service';
import { LlmService } from '../../core/services/llm.service';
import { AiIconComponent } from '../../shared/components/ai-icon/ai-icon.component';

@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [
    AsyncPipe,
    NgTemplateOutlet,
    RouterModule,
    MatToolbarModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatTooltipModule,
    AiIconComponent,
  ],
  templateUrl: './topbar.component.html',
  styleUrl: './topbar.component.scss',
})
export class TopbarComponent {
  @Output() toggleSidebar = new EventEmitter<void>();

  private readonly store = inject(Store);
  private readonly llmService = inject(LlmService);
  readonly topbarService = inject(TopbarService);
  readonly globalChatService = inject(GlobalChatService);
  user$ = this.store.select(selectCurrentUser);
  llmAvailable = signal(false);
  panelHidden = computed(() => this.llmAvailable() && !this.globalChatService.panelOpen());

  constructor() {
    this.llmService.getStatus().subscribe({
      next: (s) => this.llmAvailable.set(s.enabled),
      error: () => {},
    });
  }

  userInitial(email: string): string {
    return (email || '?')[0].toUpperCase();
  }

  logout(): void {
    this.store.dispatch(AuthActions.logout());
  }
}
