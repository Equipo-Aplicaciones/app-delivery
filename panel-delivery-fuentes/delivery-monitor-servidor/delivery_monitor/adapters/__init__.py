from .base import ProviderResult
from .uber import UberAdapter
from .pya import PedidosYaAdapter
from .rappi import RappiAdapter

ADAPTERS = {
    "uber": UberAdapter,
    "pedidosya": PedidosYaAdapter,
    "rappi": RappiAdapter,
}

__all__ = ["ProviderResult", "UberAdapter", "PedidosYaAdapter", "RappiAdapter", "ADAPTERS"]
