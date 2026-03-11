import { Injectable, TemplateRef } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class TopbarService {
  readonly title$ = new BehaviorSubject<string>('');
  readonly actionsTemplate$ = new BehaviorSubject<TemplateRef<unknown> | null>(null);

  setTitle(title: string): void {
    this.title$.next(title);
  }

  setActions(tpl: TemplateRef<unknown>): void {
    this.actionsTemplate$.next(tpl);
  }

  clearActions(): void {
    this.actionsTemplate$.next(null);
  }
}
