"""Convert an MLX LoRA adapter to PEFT/HF layout.

MLX stores  lora_a [in, r]  and  lora_b [r, out];
PEFT expects lora_A.weight [r, in] and lora_B.weight [out, r] — both transposed.
MLX's `scale` is PEFT's lora_alpha / r, so lora_alpha = scale * r.
"""
import json, re, sys
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)

mlx_cfg = json.loads((src / "adapter_config.json").read_text())
params = mlx_cfg["lora_parameters"]
rank, scale = int(params["rank"]), float(params["scale"])

tensors = load_file(src / "adapters.safetensors")
out, targets, layers = {}, set(), set()

for key, value in tensors.items():
    m = re.match(r"model\.layers\.(\d+)\.(\S+)\.lora_(a|b)$", key)
    if not m:
        raise SystemExit(f"unexpected tensor name: {key}")
    layer, module, which = m.group(1), m.group(2), m.group(3)
    targets.add(module.split(".")[-1])
    layers.add(int(layer))
    letter = "A" if which == "a" else "B"
    name = f"base_model.model.model.layers.{layer}.{module}.lora_{letter}.weight"
    out[name] = value.T.contiguous().to(torch.float32)

save_file(out, str(dst / "adapter_model.safetensors"))
(dst / "adapter_config.json").write_text(json.dumps({
    "peft_type": "LORA",
    "task_type": "CAUSAL_LM",
    "base_model_name_or_path": mlx_cfg.get("model", ""),
    "r": rank,
    "lora_alpha": scale * rank,
    "lora_dropout": float(params.get("dropout", 0.0)),
    "bias": "none",
    "fan_in_fan_out": False,
    "inference_mode": True,
    "target_modules": sorted(targets),
    "layers_to_transform": sorted(layers),
    "modules_to_save": None,
}, indent=2))

print(f"{src.name}: {len(out)} tensors, r={rank}, alpha={scale*rank:g}, "
      f"layers {min(layers)}-{max(layers)}, targets={sorted(targets)}")
