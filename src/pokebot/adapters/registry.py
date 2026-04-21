from __future__ import annotations

from typing import Callable

from .base import SourceAdapter

_ADAPTER_FACTORIES: dict[str, Callable[..., SourceAdapter]] = {}


def register_adapter(source_name: str):
    """Decorator to register adapter factory."""
    def wrap(cls):
        _ADAPTER_FACTORIES[source_name] = cls
        cls.source_name = source_name
        return cls
    return wrap


class AdapterRegistry:
    @staticmethod
    def get(source_name: str, **kwargs) -> SourceAdapter | None:
        factory = _ADAPTER_FACTORIES.get(source_name)
        if not factory:
            return None
        return factory(**kwargs)

    @staticmethod
    def all_names() -> list[str]:
        return sorted(_ADAPTER_FACTORIES.keys())
