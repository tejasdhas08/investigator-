"""OpenCLIP zero-shot appearance description over a fixed prompt bank (Stage 2 step 7)."""
import functools

GARMENTS = ["jacket", "coat", "hoodie", "t-shirt", "shirt", "dress", "uniform", "suit"]
COLORS = ["black", "white", "gray", "red", "blue", "green", "yellow", "brown", "light", "dark"]
EXTRAS = [
    "a person wearing a hat", "a person wearing a hood", "a person wearing a helmet",
    "a person carrying a backpack", "a person carrying a handbag",
    "a person carrying a shoulder bag", "a person wearing a face mask",
]
SOFTMAX_KEEP = 0.3
TOP_K = 3


@functools.lru_cache(maxsize=1)
def _load():
    import open_clip
    import torch

    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    prompts = [f"a person wearing a {c} {g}" for c in COLORS for g in GARMENTS] + EXTRAS
    with torch.no_grad():
        text_feats = model.encode_text(tokenizer(prompts))
        text_feats /= text_feats.norm(dim=-1, keepdim=True)
    return model, preprocess, prompts, text_feats


def describe_person(crop_jpeg: bytes) -> str | None:
    import io

    import torch
    from PIL import Image

    model, preprocess, prompts, text_feats = _load()
    img = preprocess(Image.open(io.BytesIO(crop_jpeg)).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        feat = model.encode_image(img)
        feat /= feat.norm(dim=-1, keepdim=True)
        probs = (100.0 * feat @ text_feats.T).softmax(dim=-1)[0]
    scored = sorted(zip(prompts, probs.tolist()), key=lambda x: -x[1])
    kept = [p.replace("a person wearing ", "").replace("a person carrying ", "carrying ")
            for p, s in scored[:TOP_K] if s > SOFTMAX_KEEP / TOP_K]
    return ", ".join(kept) if kept else None
