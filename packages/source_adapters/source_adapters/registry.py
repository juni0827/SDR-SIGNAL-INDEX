from collections.abc import Callable
from typing import Any

from .adapters import (
    CSVAdapter,
    HTMLTableAdapter,
    JSONAdapter,
    ManualFrequencyAdapter,
    ManualReceiverAdapter,
    RSSAtomAdapter,
    StaticSourceAdapter,
)

AdapterFactory = Callable[..., Any]

adapter_registry: dict[str, AdapterFactory] = {
    "csv": CSVAdapter,
    "json": JSONAdapter,
    "manual_frequency_list": ManualFrequencyAdapter,
    "manual_receiver_list": ManualReceiverAdapter,
    "rss_atom": RSSAtomAdapter,
    "generic_html_table": HTMLTableAdapter,
    "user_defined_static": StaticSourceAdapter,
}


def register_adapter(name: str, factory: AdapterFactory) -> None:
    if not name or name in adapter_registry:
        raise ValueError(f"adapter name is empty or already registered: {name!r}")
    adapter_registry[name] = factory
