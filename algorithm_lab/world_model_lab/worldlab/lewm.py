"""Load pinned first-party upstream architecture with a local state_dict only."""
import importlib.util
from pathlib import Path
from .lewm_contract import checked_assets


def source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(root, device="cpu"):
    import json
    import torch
    from torch import nn
    from transformers import ViTConfig, ViTModel
    root = checked_assets(root)
    version = tuple(int(x) for x in torch.__version__.split("+")[0].split(".")[:2])
    if version < (2, 6):
        raise ValueError("TORCH_2_6_OR_NEWER_REQUIRED")
    cfg = json.loads((root / "model/config.json").read_text(encoding="utf-8"))
    core = source_module("_worldlab_lewm_core", root / "vendor/le-wm/module.py")
    jepa = source_module("_worldlab_lewm_jepa", root / "vendor/le-wm/jepa.py")
    # Equivalent to pinned stable-pretraining vit_hf('tiny', pretrained=False).
    # Direct config construction: no Hub loader, remote code, or fallback model.
    encoder = ViTModel(ViTConfig(hidden_size=192, num_hidden_layers=12, num_attention_heads=3,
                                intermediate_size=768, image_size=224, patch_size=14),
                       add_pooling_layer=False, use_mask_token=False)
    def kwargs(name):
        return {k: v for k, v in cfg[name].items() if k not in {"_target_", "norm_fn"}}
    model = jepa.JEPA(encoder=encoder, predictor=core.ARPredictor(**kwargs("predictor")),
                      action_encoder=core.Embedder(**kwargs("action_encoder")),
                      projector=core.MLP(**kwargs("projector"), norm_fn=nn.BatchNorm1d),
                      pred_proj=core.MLP(**kwargs("pred_proj"), norm_fn=nn.BatchNorm1d))
    weights = torch.load(root / "model/weights.pt", weights_only=True, map_location="cpu", mmap=True)
    result = model.load_state_dict(weights, strict=True)
    if result.missing_keys or result.unexpected_keys:
        raise ValueError("CHECKPOINT_KEYS_MISMATCH")
    model.eval().requires_grad_(False)
    return model.to(device), cfg, len(weights)


def image_tensor(paths, device):
    import numpy as np
    import torch
    from PIL import Image
    frames = []
    for path in paths:
        with Image.open(path) as image:
            if image.mode != "RGB" or image.size != (224, 224):
                raise ValueError("RGB_224_BY_224_REQUIRED")
            frames.append(torch.from_numpy(np.array(image, dtype=np.float32)).permute(2, 0, 1) / 255)
    pixels = torch.stack(frames)[None].to(device)
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 1, 3, 1, 1)
    return (pixels - mean) / std
