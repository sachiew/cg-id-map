"""Provider adapters. Each non-CG provider implements `Provider` and is registered here."""

from __future__ import annotations

from typing import Protocol

from cg_id_map.config import Config
from cg_id_map.providers.base import Provider


class ProviderFactory(Protocol):
    """Builds a provider from config, reading its own credentials (if any) from the env."""

    def __call__(self, config: Config, *, refresh: bool = False) -> Provider: ...


PROVIDERS: dict[str, ProviderFactory] = {}


def register(name: str, factory: ProviderFactory) -> None:
    if name in PROVIDERS:
        raise ValueError(f"provider {name!r} registered twice")
    PROVIDERS[name] = factory


def _load_builtin() -> None:
    from cg_id_map.providers import cmc  # noqa: F401  (registers itself)


_load_builtin()
