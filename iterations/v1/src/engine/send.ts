import { parseAggregator, type Aggregator } from './aggregator';
import { hasCapture } from './camera';
import { normalizeOrder } from './order-number';

export type EvidenceKey = {
  agregador: Aggregator;
  numeroOrden: string;
};

export type KeyReady = { ok: true; key: EvidenceKey } | { ok: false; error: string };

export type SendPayload = EvidenceKey & { imageUri: string };

export type SendReady = { ok: true; payload: SendPayload } | { ok: false; error: string };

export function prepareLookup(input: { order: string; aggregator: string | null }): KeyReady {
  const order = normalizeOrder(input.order);
  if (!order.ok) return order;
  const aggregator = parseAggregator(input.aggregator);
  if (!aggregator.ok) return aggregator;
  return {
    ok: true,
    key: { agregador: aggregator.agregador, numeroOrden: order.numeroOrden },
  };
}

export function prepareSend(input: {
  imageUri: string | null;
  order: string;
  aggregator: string | null;
}): SendReady {
  if (!hasCapture(input.imageUri)) {
    return { ok: false, error: 'Falta la foto del pedido' };
  }
  const key = prepareLookup(input);
  if (!key.ok) return key;
  return {
    ok: true,
    payload: { ...key.key, imageUri: input.imageUri as string },
  };
}
