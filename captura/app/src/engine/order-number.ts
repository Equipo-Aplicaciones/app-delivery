export type OrderResult =
  | { ok: true; numeroOrden: string }
  | { ok: false; error: string };

export function normalizeOrder(raw: string): OrderResult {
  const numeroOrden = raw.trim();
  if (numeroOrden.length === 0) {
    return { ok: false, error: 'Falta el número de orden' };
  }
  return { ok: true, numeroOrden };
}
