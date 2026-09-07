"""Translate Qt key events into semantic manual directions."""

from PySide6.QtCore import QEvent, QObject, Qt, Signal

from ..domain.intents import ManualDirection

_KEY_MAP = {
    Qt.Key.Key_D: ManualDirection.LEFT,
    Qt.Key.Key_A: ManualDirection.RIGHT,
    Qt.Key.Key_W: ManualDirection.UP,
    Qt.Key.Key_S: ManualDirection.DOWN,
}


class ManualKeyFilter(QObject):
    direction_changed = Signal(object, bool)
    clear_requested = Signal()

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            direction = _KEY_MAP.get(event.key())
            if direction is not None:
                if not event.isAutoRepeat():
                    self.direction_changed.emit(
                        direction,
                        event_type == QEvent.Type.KeyPress,
                    )
                return True
        if event_type in (
            QEvent.Type.ApplicationDeactivate,
            QEvent.Type.WindowDeactivate,
        ):
            self.clear_requested.emit()
        return super().eventFilter(watched, event)
