# Sesiones de las plataformas

Este directorio se monta en el contenedor como `/sessions`.

Coloque aquí, con permisos `600` y dueño uid 1000 si es posible:

- `uber_cookie` — copia del archivo `~/.uber_cookie` del dueño (cookie de Uber Eats Manager).
- `pya_tokens.json` — copia de `~/.pya_tokens.json` (tokens de PedidosYa).

No los genere el panel. No caducan de forma mágica ni se migra la rutina del navegador local.
Si Uber responde 401/403, copie de nuevo la cookie. PedidosYa puede renovar el access token
con su refresh token si este archivo es escribible.

Nunca versionar ni comprimir estos archivos con secretos reales.
