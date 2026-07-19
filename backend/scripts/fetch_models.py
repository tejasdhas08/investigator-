"""Download detection model weights into ./models.

Two backends (see app/pipeline/tasks.py::resolve_stage2_backend):

FULL (GPU-oriented; weights hosted on github.com — needs open internet):
  - yolov8m.pt (ultralytics auto-download) + insightface buffalo_l
  - optional fine-tuned weapons_yolov8m.pt placed manually

LITE (CPU, restricted-network friendly):
  - efficientdet_lite0.tflite from storage.googleapis.com (MediaPipe model zoo)
  - dlib face weights need no download at all — they ship inside the
    `face-recognition-models` wheel from PyPI

Usage: python -m scripts.fetch_models [--lite-only]
Fetches whatever is reachable; prints a per-model status line either way.
"""
import pathlib
import sys
import urllib.request

MODELS_DIR = pathlib.Path(__file__).resolve().parents[2] / "models"
EFFICIENTDET_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/float32/1/efficientdet_lite0.tflite"
)


def fetch_lite() -> None:
    target = MODELS_DIR / "efficientdet_lite0.tflite"
    if target.exists():
        print(f"efficientdet_lite0: ok ({target})")
        return
    try:
        print("efficientdet_lite0: downloading...")
        urllib.request.urlretrieve(EFFICIENTDET_URL, target)
        print(f"efficientdet_lite0: ok ({target})")
    except Exception as exc:
        print(f"efficientdet_lite0: FAILED ({exc}) — lite object detection unavailable")


def fetch_full() -> None:
    try:
        from ultralytics import YOLO

        YOLO(str(MODELS_DIR / "yolov8m.pt"))
        print("yolov8m: ok")
    except Exception as exc:
        print(f"yolov8m: FAILED ({exc}) — full backend unavailable, lite backend still works")
        return
    try:
        from insightface.app import FaceAnalysis

        FaceAnalysis(name="buffalo_l", root=str(MODELS_DIR / "insightface")).prepare(ctx_id=-1)
        print("insightface buffalo_l: ok")
    except Exception as exc:
        print(f"insightface buffalo_l: FAILED ({exc})")
    weapons = MODELS_DIR / "weapons_yolov8m.pt"
    print(f"weapons model: {'ok' if weapons.exists() else 'MISSING (optional) — COCO fallback active'}")


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    fetch_lite()
    if "--lite-only" not in sys.argv:
        fetch_full()


if __name__ == "__main__":
    main()
