"""Load TOML configuration into immutable dataclasses."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from .schema import AppConfig


def _toml_load(path: Path) -> Mapping[str, Any]:
    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib

    with path.open("rb") as stream:
        return tomllib.load(stream)


def _merge_dataclass(instance, values: Mapping[str, Any], prefix: str = ""):
    known = {field.name for field in fields(instance)}
    unknown = sorted(set(values) - known)
    if unknown:
        location = prefix or type(instance).__name__
        unknown_text = ", ".join(unknown)
        raise ValueError(f"unknown configuration key(s) in {location}: {unknown_text}")

    changes = {}
    for name, value in values.items():
        current = getattr(instance, name)
        if is_dataclass(current):
            if not isinstance(value, Mapping):
                raise ValueError(
                    f"configuration section {prefix}{name} must be a table"
                )
            value = _merge_dataclass(current, value, prefix + name + ".")
        changes[name] = value
    return replace(instance, **changes)


def load_config(path: Path | None = None) -> AppConfig:
    config = AppConfig()
    if path is None:
        return config

    path = Path(path).resolve()
    loaded = _merge_dataclass(config, _toml_load(path))
    vision = loaded.vision
    model_path = Path(vision.model_path)
    tracker_path = Path(vision.tracker_config_path)
    recording_path = Path(loaded.audio.recording.path)
    process_loopback_helper = loaded.audio.capture.process_loopback_helper
    spatial_model_path = Path(loaded.spatial_field.depth.model_path)
    if not model_path.is_absolute():
        model_path = (path.parent / model_path).resolve()
    if not tracker_path.is_absolute():
        tracker_path = (path.parent / tracker_path).resolve()
    if not recording_path.is_absolute():
        recording_path = (path.parent / recording_path).resolve()
    if process_loopback_helper:
        helper_path = Path(process_loopback_helper)
        if not helper_path.is_absolute():
            helper_path = (path.parent / helper_path).resolve()
        process_loopback_helper = str(helper_path)
    if not spatial_model_path.is_absolute():
        spatial_model_path = (path.parent / spatial_model_path).resolve()
    return replace(
        loaded,
        vision=replace(
            vision,
            model_path=str(model_path),
            tracker_config_path=str(tracker_path),
        ),
        audio=replace(
            loaded.audio,
            capture=replace(
                loaded.audio.capture,
                process_loopback_helper=process_loopback_helper,
            ),
            recording=replace(
                loaded.audio.recording,
                path=str(recording_path),
            ),
        ),
        spatial_field=replace(
            loaded.spatial_field,
            depth=replace(
                loaded.spatial_field.depth,
                model_path=str(spatial_model_path),
            ),
        ),
    )
