"""Load TOML configuration into immutable dataclasses."""

from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Optional

from .schema import AppConfig


def _toml_load(path: Path) -> Mapping[str, Any]:
    try:
        import tomllib
    except ImportError:  # Python 3.9 and 3.10
        import tomli as tomllib

    with path.open("rb") as stream:
        return tomllib.load(stream)


def _merge_dataclass(instance, values: Mapping[str, Any], prefix: str = ""):
    known = {field.name for field in fields(instance)}
    unknown = sorted(set(values) - known)
    if unknown:
        location = prefix or type(instance).__name__
        raise ValueError("unknown configuration key(s) in %s: %s" % (
            location,
            ", ".join(unknown),
        ))

    changes = {}
    for name, value in values.items():
        current = getattr(instance, name)
        if is_dataclass(current):
            if not isinstance(value, Mapping):
                raise ValueError("configuration section %s%s must be a table" % (
                    prefix,
                    name,
                ))
            value = _merge_dataclass(current, value, prefix + name + ".")
        changes[name] = value
    return replace(instance, **changes)


def load_config(path: Optional[Path] = None) -> AppConfig:
    config = AppConfig()
    if path is None:
        return config

    path = Path(path).resolve()
    loaded = _merge_dataclass(config, _toml_load(path))
    vision = loaded.vision
    model_path = Path(vision.model_path)
    tracker_path = Path(vision.tracker_config_path)
    if not model_path.is_absolute():
        model_path = (path.parent / model_path).resolve()
    if not tracker_path.is_absolute():
        tracker_path = (path.parent / tracker_path).resolve()
    return replace(
        loaded,
        vision=replace(
            vision,
            model_path=str(model_path),
            tracker_config_path=str(tracker_path),
        ),
    )
