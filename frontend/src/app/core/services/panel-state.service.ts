import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'ai-panel-state';
const DEFAULT_WIDTH = 380;
const MIN_WIDTH = 280;
const MAX_WIDTH_RATIO = 0.6;

interface PersistedState {
  width: number;
  collapsed: boolean;
}

@Injectable({ providedIn: 'root' })
export class PanelStateService {
  readonly width = signal(DEFAULT_WIDTH);
  readonly collapsed = signal(false);

  constructor() {
    this._load();
  }

  setWidth(px: number): void {
    const clamped = Math.max(MIN_WIDTH, Math.min(px, window.innerWidth * MAX_WIDTH_RATIO));
    this.width.set(clamped);
    this._save();
  }

  toggleCollapsed(): void {
    this.collapsed.update((v) => !v);
    this._save();
  }

  setCollapsed(value: boolean): void {
    this.collapsed.set(value);
    this._save();
  }

  get minWidth(): number {
    return MIN_WIDTH;
  }

  get maxWidthRatio(): number {
    return MAX_WIDTH_RATIO;
  }

  private _load(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const state: PersistedState = JSON.parse(raw);
        if (typeof state.width === 'number') this.width.set(state.width);
        if (typeof state.collapsed === 'boolean') this.collapsed.set(state.collapsed);
      }
    } catch {
      // Ignore corrupt storage
    }
  }

  private _save(): void {
    const state: PersistedState = { width: this.width(), collapsed: this.collapsed() };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }
}
