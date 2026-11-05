import type { Aggregator } from '../../engine/aggregator';
import { functionUrl, type EvidenceConfig } from './config';

export type EvidenceImage = {
  id: string;
  createdAt: string;
  url: string;
};

export type ApiOk<T> = { ok: true; data: T };
export type ApiErr = { ok: false; error: string };
export type ApiResult<T> = ApiOk<T> | ApiErr;

type ImageBody = {
  images?: Array<{ id?: string; created_at?: string; url?: string }>;
  error?: string;
};

function missingKey(): ApiErr {
  return { ok: false, error: 'Falta la clave de prueba' };
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    if (body.error) return body.error;
  } catch {
    // La respuesta no trae JSON.
  }
  return 'La base no recibió la imagen';
}

export async function enviar(
  config: EvidenceConfig,
  input: { agregador: Aggregator; numeroOrden: string; imageUri: string },
): Promise<ApiResult<{ saved: true }>> {
  if (!config.apiKey) return missingKey();
  const body = new FormData();
  body.append('agregador', input.agregador);
  body.append('numero_orden', input.numeroOrden);
  body.append('imagen', {
    uri: input.imageUri,
    name: 'pedido.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);

  let response: Response;
  try {
    response = await fetch(functionUrl(config), {
      method: 'POST',
      headers: { 'x-evidencia-key': config.apiKey },
      body,
    });
  } catch {
    return { ok: false, error: 'La base no recibió la imagen' };
  }
  if (!response.ok) {
    return { ok: false, error: await readError(response) };
  }
  return { ok: true, data: { saved: true } };
}

export async function pedir(
  config: EvidenceConfig,
  input: { agregador: Aggregator; numeroOrden: string },
): Promise<ApiResult<{ images: EvidenceImage[] }>> {
  if (!config.apiKey) return missingKey();
  const url = new URL(functionUrl(config));
  url.searchParams.set('agregador', input.agregador);
  url.searchParams.set('numero_orden', input.numeroOrden);

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      headers: { 'x-evidencia-key': config.apiKey },
    });
  } catch {
    return { ok: false, error: 'No se pudo consultar la evidencia' };
  }
  if (!response.ok) {
    return { ok: false, error: await readError(response) };
  }
  const body = (await response.json()) as ImageBody;
  const images = (body.images ?? []).flatMap((row) => {
    if (!row.id || !row.created_at || !row.url) return [];
    return [{ id: row.id, createdAt: row.created_at, url: row.url }];
  });
  return { ok: true, data: { images } };
}
