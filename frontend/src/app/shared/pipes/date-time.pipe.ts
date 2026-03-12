import { DestroyRef, inject, Pipe, PipeTransform } from '@angular/core';
import { Store } from '@ngrx/store';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { selectCurrentUser } from '../../core/state/auth/auth.selectors';

/**
 * Timezone-aware date/time pipe using Intl.DateTimeFormat.
 *
 * Reads the authenticated user's IANA timezone (e.g. 'Europe/Paris')
 * from NgRx auth state and formats dates accordingly, with full DST support.
 *
 * All backend dates are UTC. Strings without a timezone suffix (Z or +00:00)
 * are treated as UTC to avoid browser-local misinterpretation.
 *
 * Format presets:
 *   (default)  → 11/03/2026, 21:27:13
 *   'short'    → 11 Mar 2026, 21:27:13
 *   'date'     → 11 Mar 2026
 *   'time-ms'  → 21:27:13.456
 */
@Pipe({ name: 'dateTime', standalone: true, pure: false })
export class DateTimePipe implements PipeTransform {
  private readonly store = inject(Store);
  private readonly destroyRef = inject(DestroyRef);
  private userTimezone: string | undefined;
  private formatCache = new Map<string, Intl.DateTimeFormat>();

  constructor() {
    this.store
      .select(selectCurrentUser)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((user) => {
        const tz = user?.timezone || undefined;
        if (tz !== this.userTimezone) {
          this.userTimezone = tz;
          this.formatCache.clear();
        }
      });
  }

  private getFormatter(key: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
    let fmt = this.formatCache.get(key);
    if (!fmt) {
      fmt = new Intl.DateTimeFormat('en-GB', options);
      this.formatCache.set(key, fmt);
    }
    return fmt;
  }

  transform(value: string | Date | null | undefined, format?: string): string {
    if (!value) return '';
    try {
      const date = typeof value === 'string' ? new Date(this.ensureUtc(value)) : value;
      if (isNaN(date.getTime())) return '';
      const tz = this.userTimezone;
      const tzOpt: Intl.DateTimeFormatOptions = tz ? { timeZone: tz } : {};

      switch (format) {
        case 'short':
          return this.getFormatter('short', {
            ...tzOpt,
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          }).format(date);

        case 'date':
          return this.getFormatter('date', {
            ...tzOpt,
            day: '2-digit',
            month: 'short',
            year: 'numeric',
          }).format(date);

        case 'time-ms': {
          const parts = this.getFormatter('time-ms', {
            ...tzOpt,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            fractionalSecondDigits: 3 as 1 | 2 | 3,
            hour12: false,
          }).formatToParts(date);
          const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';
          return `${get('hour')}:${get('minute')}:${get('second')}.${get('fractionalSecond')}`;
        }

        default:
          return this.getFormatter('default', {
            ...tzOpt,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          }).format(date);
      }
    } catch {
      return '';
    }
  }

  /** Append Z to ISO strings that have no timezone indicator, since all backend dates are UTC. */
  private ensureUtc(value: string): string {
    if (/[Zz]$/.test(value) || /[+-]\d{2}:\d{2}$/.test(value)) return value;
    return value + 'Z';
  }
}
