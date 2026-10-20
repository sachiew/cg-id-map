"""Provider adapters. Each non-CG provider implements `Provider` and is registered here."""

from __future__ import annotations

from collections.abc import Callable

from cg_id_map.providers.base import Provider

PROVIDERS: dict[str, Callable[..., Provider]] = {}


def register(name: str) -> Callable[[Callable[..., Provider]], Callable[..., Provider]]:
    def deco(factory: Callable[..., Provider]) -> Callable[..., Provider]:
        PROVIDERS[name] = factory
        return factory

    return deco


def _load_builtin() -> None:
    from cg_id_map.providers import cmc  # noqa: F401  (registers itself)


_load_builtin()
