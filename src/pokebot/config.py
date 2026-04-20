from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from .monitors.base import Monitor
from .monitors.feed import FeedMonitor
from .monitors.html import HtmlMonitor


def _resolve_parser(path: str):
    if "." not in path:
        raise ValueError(f"invalid parser path: {path}")
    module_name, func_name = path.rsplit(".", 1)
    try:
        module = importlib.import_module(f"pokebot.parsers.{module_name}")
    except ModuleNotFoundError as e:
        raise ValueError(f"parser module not found: {module_name}") from e
    try:
        return getattr(module, func_name)
    except AttributeError as e:
        raise ValueError(f"parser function not found: {path}") from e


def load_sources(yaml_path: Path) -> list[Monitor]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    monitors: list[Monitor] = []
    for s in data.get("sources", []):
        if not s.get("enabled", False):
            continue
        parser_fn = _resolve_parser(s["parser"])
        common = dict(
            id_=s["id"],
            url=s["url"],
            interval_sec=int(s["interval_sec"]),
            parser=parser_fn,
        )
        kind = s["kind"]
        if kind == "html":
            monitors.append(HtmlMonitor(**common))
        elif kind == "feed":
            monitors.append(FeedMonitor(**common))
        else:
            raise ValueError(f"unknown kind: {kind}")
    return monitors
