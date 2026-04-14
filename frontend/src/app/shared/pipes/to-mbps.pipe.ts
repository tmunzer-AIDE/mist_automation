import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'toMbps', standalone: true })
export class ToMbpsPipe implements PipeTransform {
  transform(bps: number | null | undefined, digits = 1, withUnit = true): string {
    if (bps == null) return '\u2014';
    const mbps = bps / 1_000_000;
    const formatted = mbps.toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    return withUnit ? `${formatted} Mbps` : formatted;
  }
}
