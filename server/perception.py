"""Object detection — wraps whatever model we're using today (YOLOv8n)
behind a small interface so the rest of the app never touches
ultralytics/torch directly, and the detector can be swapped later
without changing any caller.
"""
from dataclasses import dataclass
from io import BytesIO
from typing import List

from PIL import Image
from pathlib import Path

# Full COCO vocabulary; vocabulary.py shares all 80 Spanish names and aliases.
CONFIDENCE_THRESHOLD = 0.4


@dataclass
class Detection:
    cls: str
    confidence: float
    x: float  # bbox-center, normalized -1 (left) .. 1 (right)
    y: float  # bbox-center, normalized -1 (top) .. 1 (bottom)
    bbox: List[float]  # [x1, y1, x2, y2] in source-frame pixel coords

    def as_dict(self) -> dict:
        return {
            "class": self.cls,
            "confidence": round(self.confidence, 2),
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "bbox": [round(v, 1) for v in self.bbox],
        }


class PerceptionService:
    """Runs object detection on a JPEG frame. To swap the model, rewrite
    only this class — callers just get back a list of Detection."""

    def __init__(self):
        from ultralytics import YOLO  # local import: keep torch out of every other module

        self._model = YOLO(str(Path(__file__).resolve().parent.parent / "yolov8n.pt"))

    def detect(self, jpeg_bytes: bytes) -> List[Detection]:
        image = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
        width, height = image.size

        results = self._model.predict(image, verbose=False, conf=CONFIDENCE_THRESHOLD)

        detections: List[Detection] = []
        for result in results:
            for box in result.boxes:
                cls_name = result.names[int(box.cls[0])]
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                detections.append(
                    Detection(
                        cls=cls_name,
                        confidence=float(box.conf[0]),
                        x=(cx / width) * 2 - 1,
                        y=(cy / height) * 2 - 1,
                        bbox=[x1, y1, x2, y2],
                    )
                )
        return detections
