const DEFAULT_URL = 'http://comparador.tarrainnova.cloud:8787/v1/evidencia';

export type EvidenceConfig = {
  url: string;
  apiKey: string;
};

export function readEvidenceConfig(): EvidenceConfig {
  const url = (process.env.EXPO_PUBLIC_EVIDENCIA_URL ?? DEFAULT_URL).replace(/\/$/, '');
  const apiKey = process.env.EXPO_PUBLIC_EVIDENCIA_API_KEY ?? '';
  return { url, apiKey };
}

export function functionUrl(config: EvidenceConfig): string {
  return config.url;
}
