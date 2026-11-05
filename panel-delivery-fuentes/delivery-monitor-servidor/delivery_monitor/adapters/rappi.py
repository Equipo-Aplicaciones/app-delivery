"""Rappi: integración pendiente. No inventa cifras ni reutiliza listados viejos."""
from __future__ import annotations

from ..parseutil import iso_chile
from .base import ProviderResult

PENDING_NOTE = (
    "API del Portal Aliados verificada en el navegador (Bearer Auth0), "
    "pero no hay cliente CLI ni credenciales de API disponibles para este panel. "
    "Integración pendiente: no se listan tiendas ni disputas, y no se reúsan cifras anteriores."
)


class RappiAdapter:
    platform = "rappi"

    def fetch(self) -> ProviderResult:
        return ProviderResult(
            platform="rappi",
            status="pending",
            fetched_at=iso_chile(),
            error=PENDING_NOTE,
            stores=None,
            disputes=None,
            disputes_status="pending",
            disputes_error=PENDING_NOTE,
            extra={"reason": "no_cli_credentials"},
        )
