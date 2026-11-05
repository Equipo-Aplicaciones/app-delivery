export const AGGREGATORS = ['uber', 'pedidosya'] as const;

export type Aggregator = (typeof AGGREGATORS)[number];

export type AggregatorResult =
  | { ok: true; agregador: Aggregator }
  | { ok: false; error: string };

export function parseAggregator(raw: string | null): AggregatorResult {
  if (raw === 'uber' || raw === 'pedidosya') {
    return { ok: true, agregador: raw };
  }
  return { ok: false, error: 'Falta un agregador válido' };
}

export function aggregatorLabel(value: Aggregator): string {
  if (value === 'uber') return 'Uber';
  return 'PedidosYa';
}
