from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderResult:
    platform: str
    status: str
    fetched_at: str
    error: str | None = None
    stores: list[dict] | None = None
    disputes: list[dict] | None = None
    disputes_status: str | None = None
    disputes_error: str | None = None
    disputes_window: dict | None = None
    disputes_counters: dict | None = None
    disputes_truncated: bool = False
    extra: dict = field(default_factory=dict)

    def source_dict(self) -> dict:
        stores_count = len(self.stores) if isinstance(self.stores, list) else None
        disputes_count = len(self.disputes) if isinstance(self.disputes, list) else None
        return {
            "status": self.status,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "stores_count": stores_count,
            "disputes_status": self.disputes_status,
            "disputes_error": self.disputes_error,
            "disputes_count": disputes_count,
            "disputes_window": self.disputes_window,
            "disputes_counters": self.disputes_counters,
            "disputes_truncated": self.disputes_truncated or None,
            "extra": self.extra or None,
        }
