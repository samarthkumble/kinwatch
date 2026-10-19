"""Pull a still frame out of a Ring MP4 clip so the vision step gets a picture
even when the snapshot endpoint is unavailable."""
from __future__ import annotations

from pathlib import Path


def extract_frame(video_path: str | Path, out_path: str | Path | None = None,
                  at_fraction: float = 0.5) -> Path | None:
    """Save the frame at `at_fraction` of the clip (0.5 = middle) as JPEG.
    Returns the JPEG path, or None if OpenCV is missing or the clip can't be read."""
    try:
        import cv2  # opencv-python-headless
    except ImportError:
        print("      (install opencv-python-headless to extract frames from clips)")
        return None
    video_path = Path(video_path)
    out_path = Path(out_path) if out_path else video_path.with_suffix(".jpg")
    cap = cv2.VideoCapture(str(video_path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total * at_fraction)))
        ok, frame = cap.read()
        if not ok:                       # some streams don't seek: read from start
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok:
            return None
        cv2.imwrite(str(out_path), frame)
        return out_path
    finally:
        cap.release()
