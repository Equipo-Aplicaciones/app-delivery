export function hasCapture(uri: string | null | undefined): boolean {
  return typeof uri === 'string' && uri.trim().length > 0;
}
