"""Download Stage 2 model weights into ./models (Phase 5).

- yolov8m.pt: fetched automatically by ultralytics on first use; this script pre-fetches.
- insightface buffalo_l: fetched automatically by insightface on first FaceAnalysis(...).
- weapons_yolov8m.pt: OPTIONAL fine-tuned weapons model. Place it at models/weapons_yolov8m.pt
  manually (see ARCHITECTURE.md Section 9, assumption 9). Without it, weapon detection
  falls back to COCO 'knife'/'baseball bat'/'scissors' classes only.

Usage: python -m scripts.fetch_models
"""
import pathlib

MODELS_DIR = pathlib.Path(__file__).resolve().parents[2] / "models"


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    from ultralytics import YOLO

    YOLO(str(MODELS_DIR / "yolov8m.pt"))  # downloads if missing
    from insightface.app import FaceAnalysis

    FaceAnalysis(name="buffalo_l", root=str(MODELS_DIR / "insightface")).prepare(ctx_id=-1)
    weapons = MODELS_DIR / "weapons_yolov8m.pt"
    print("yolov8m: ok")
    print("insightface buffalo_l: ok")
    print(f"weapons model: {'ok' if weapons.exists() else 'MISSING (optional) — COCO fallback active'}")


if __name__ == "__main__":
    main()
