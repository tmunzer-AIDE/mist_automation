import { HttpErrorResponse } from '@angular/common/http';

export function extractErrorMessage(err: HttpErrorResponse): string {
  if (err.status >= 500) return 'A server error occurred';
  return err.error?.detail || err.error?.message || err.statusText || 'An error occurred';
}
