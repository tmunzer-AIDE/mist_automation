import { Injectable, signal, computed, effect } from '@angular/core';

export type ThemePreference = 'light' | 'dark' | 'auto';

const STORAGE_KEY = 'theme_preference';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly preference = signal<ThemePreference>(this.loadPreference());

  private readonly osDark = signal(this.osPrefersDark());

  readonly isDark = computed(() => {
    const pref = this.preference();
    if (pref === 'auto') return this.osDark();
    return pref === 'dark';
  });

  private osPrefersDark(): boolean {
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    } catch {
      return false;
    }
  }

  constructor() {
    try {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        this.osDark.set(e.matches);
      });
    } catch {
      // Not in a browser environment
    }

    effect(() => {
      const dark = this.isDark();
      try {
        const html = document.documentElement;
        if (dark) {
          html.classList.add('dark-theme');
        } else {
          html.classList.remove('dark-theme');
        }
        document.body.style.colorScheme = dark ? 'dark' : 'light';
      } catch {
        // Not in a browser environment
      }
    });
  }

  toggle(): void {
    this.setPreference(this.isDark() ? 'light' : 'dark');
  }

  setPreference(pref: ThemePreference): void {
    this.preference.set(pref);
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      // localStorage not available
    }
  }

  private loadPreference(): ThemePreference {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'light' || stored === 'dark' || stored === 'auto') return stored;
    } catch {
      // localStorage not available
    }
    return 'auto';
  }
}
