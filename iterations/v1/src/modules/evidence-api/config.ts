const DEFAULT_URL = 'https://nfryurrhgaeepdwqtswo.supabase.co';

export type EvidenceConfig = {
  url: string;
  apiKey: string;
};

export function readEvidenceConfig(): EvidenceConfig {
  const url = (process.env.EXPO_PUBLIC_SUPABASE_URL ?? DEFAULT_URL).replace(/\/$/, '');
  const apiKey = process.env.EXPO_PUBLIC_EVIDENCIA_API_KEY ?? '';
  return { url, apiKey };
}

export function functionUrl(config: EvidenceConfig): string {
  return `${config.url}/functions/v1/evidencia`;
}
