"""Person detection, tracking, and trajectory smoothing."""

__all__ = ["VisionPipeline", "YOLOByteTrackPeopleTracker"]


def __getattr__(name):
    if name == "VisionPipeline":
        from .pipeline import VisionPipeline

        return VisionPipeline
    if name == "YOLOByteTrackPeopleTracker":
        from .yolo_bytetrack import YOLOByteTrackPeopleTracker

        return YOLOByteTrackPeopleTracker
    raise AttributeError(name)
