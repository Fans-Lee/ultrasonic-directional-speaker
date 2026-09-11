"""Readable and machine-readable transport diagnostics."""

from dataclasses import asdict

from ..domain.audio import AudioStreamTelemetry
from ..domain.control import SerialLinkStatus


def diagnostic_record(
    serial: SerialLinkStatus, audio: AudioStreamTelemetry, elapsed_s: float
) -> dict:
    record = asdict(audio)
    record["state"] = audio.state.name
    record.update(
        elapsed_s=round(elapsed_s, 3),
        connected=serial.connected,
        serial_error=serial.last_error,
    )
    return record


def format_diagnostics(record: dict) -> str:
    fields = (
        ("connected", "connected"), ("state", "state"), ("muted", "muted"),
        ("under", "underrun_count"), ("over", "overrun_count"),
        ("crc", "crc_error_count"), ("gap", "sequence_gap_count"),
        ("skip", "timer_skipped_samples"), ("host_drop", "host_tx_overrun_count"),
        ("capture_drop", "host_capture_overrun_count"),
        ("rx_error", "host_rx_error_count"), ("clip", "quantizer_clip_count"),
        ("tx_samples", "host_sent_samples"), ("tx_queue", "host_tx_queue_packets"),
        ("audio_age_ms", "last_audio_age_ms"), ("status_age_ms", "status_age_ms"),
    )
    text = " ".join(f"{label}={record[key]}" for label, key in fields)
    text += f" buffer={record['buffer_fill_samples']}/{record['buffer_capacity_samples']}"
    if record.get("serial_error"):
        text += f" error={record['serial_error']}"
    return text
