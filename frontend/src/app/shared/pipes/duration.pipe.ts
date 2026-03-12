import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'duration', standalone: true, pure: true })
export class DurationPipe implements PipeTransform {
  transform(ms: number | null): string {
    if (!ms) return '\u2014';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
}
