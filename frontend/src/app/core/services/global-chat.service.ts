import { Injectable, signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';

export interface PageContext {
  /** Current page name (e.g., "Backup Object Detail", "Workflow Editor") */
  page: string;
  /** Key details about what the user is viewing */
  details?: Record<string, string | number | null>;
  /** Hide the persistent AI panel (page has its own embedded chat) */
  hidePanel?: boolean;
}

@Injectable({ providedIn: 'root' })
export class GlobalChatService {
  private readonly openChat$ = new Subject<{ message?: string }>();

  /** Current page context — set by each page component on init */
  readonly context = signal<PageContext | null>(null);

  /** Whether the AI panel is open */
  readonly panelOpen = signal(true);

  /** Set the current page context (called by page components) */
  setContext(ctx: PageContext): void {
    this.context.set(ctx);
  }

  /** Clear context (called on component destroy if needed) */
  clearContext(): void {
    this.context.set(null);
  }

  /** Toggle the AI panel open/closed */
  toggle(): void {
    this.panelOpen.update((v) => !v);
  }

  /** Open the global chat, optionally with a pre-filled message */
  open(message?: string): void {
    this.panelOpen.set(true);
    this.openChat$.next({ message });
  }

  /** Observable for chat open events */
  onOpen(): Observable<{ message?: string }> {
    return this.openChat$.asObservable();
  }

  /** Build a context string for the LLM from current page state */
  buildContextString(): string {
    const ctx = this.context();
    if (!ctx) return '';

    const parts = [`The user is currently viewing: ${ctx.page}`];
    if (ctx.details) {
      for (const [key, value] of Object.entries(ctx.details)) {
        if (value !== null && value !== undefined && value !== '') {
          parts.push(`${key}: ${value}`);
        }
      }
    }
    return parts.join('\n');
  }
}
