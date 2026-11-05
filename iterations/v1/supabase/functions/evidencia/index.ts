import { createClient } from "jsr:@supabase/supabase-js@2";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-evidencia-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const AGGREGATORS = new Set(["uber", "pedidosya"]);

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

function client() {
  return createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  );
}

async function expectedKey(): Promise<string | null> {
  const { data, error } = await client()
    .from("evidencia_clave")
    .select("api_key")
    .eq("id", 1)
    .maybeSingle();
  if (error || !data?.api_key) return null;
  return data.api_key;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  const provided = req.headers.get("x-evidencia-key");
  const expected = await expectedKey();
  if (!expected || provided !== expected) return json({ error: "no autorizado" }, 401);

  if (req.method === "GET") return pedir(req);
  if (req.method === "POST") return enviar(req);
  return json({ error: "método no permitido" }, 405);
});

function readKey(url: URL): { agregador: string; numeroOrden: string } | { error: string } {
  const agregador = url.searchParams.get("agregador") ?? "";
  const numeroOrden = (url.searchParams.get("numero_orden") ?? "").trim();
  if (!AGGREGATORS.has(agregador)) return { error: "Falta un agregador válido" };
  if (!numeroOrden) return { error: "Falta el número de orden" };
  return { agregador, numeroOrden };
}

async function pedir(req: Request): Promise<Response> {
  const key = readKey(new URL(req.url));
  if ("error" in key) return json({ error: key.error }, 400);

  const db = client();
  const { data, error } = await db
    .from("evidencia")
    .select("id, created_at, storage_path")
    .eq("agregador", key.agregador)
    .eq("numero_orden", key.numeroOrden)
    .order("created_at", { ascending: true });
  if (error) return json({ error: "No se pudo consultar la evidencia" }, 500);
  if (!data || data.length === 0) return json({ images: [] });

  const images = [];
  for (const row of data) {
    const signed = await db.storage.from("evidencia").createSignedUrl(row.storage_path, 600);
    if (signed.error || !signed.data?.signedUrl) {
      return json({ error: "No se pudo consultar la evidencia" }, 500);
    }
    images.push({ id: row.id, created_at: row.created_at, url: signed.data.signedUrl });
  }
  return json({ images });
}

async function enviar(req: Request): Promise<Response> {
  const form = await req.formData();
  const agregador = String(form.get("agregador") ?? "");
  const numeroOrden = String(form.get("numero_orden") ?? "").trim();
  const file = form.get("imagen");
  if (!AGGREGATORS.has(agregador)) return json({ error: "Falta un agregador válido" }, 400);
  if (!numeroOrden) return json({ error: "Falta el número de orden" }, 400);
  if (!(file instanceof File) || file.size === 0) return json({ error: "Falta la foto del pedido" }, 400);

  const storagePath = `${agregador}/${numeroOrden}/${crypto.randomUUID()}.jpg`;
  const bytes = new Uint8Array(await file.arrayBuffer());
  const db = client();
  const uploaded = await db.storage.from("evidencia").upload(storagePath, bytes, {
    contentType: "image/jpeg",
    upsert: false,
  });
  if (uploaded.error) return json({ error: "La base no recibió la imagen" }, 500);

  const inserted = await db.from("evidencia").insert({
    agregador,
    numero_orden: numeroOrden,
    storage_path: storagePath,
  });
  if (inserted.error) {
    await db.storage.from("evidencia").remove([storagePath]);
    return json({ error: "La base no recibió la imagen" }, 500);
  }
  return json({ saved: true }, 201);
}
