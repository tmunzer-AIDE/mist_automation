export function getStatusClass(code: number): string {
  if (code >= 200 && code < 300) return 'status-ok';
  if (code >= 400 && code < 500) return 'status-client-error';
  if (code >= 500) return 'status-server-error';
  return '';
}
