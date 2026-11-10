"""Model profile loading for the EDA-Lite simulator.

The profile format is intentionally small and explicit. It represents a
simplified sequential model, not a full ONNX graph.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_LAYER_FIELDS = {
    "name",
    "op_type",
    "input_kb",
    "output_kb",
    "weight_kb",
    "compute_macs",
    "fusible",
}

# Consecutive layers must agree on the tensor passed between them:
# layers[i].output_kb == layers[i + 1].input_kb within this relative tolerance.
CHAIN_REL_TOL = 1e-6


@dataclass(frozen=True)
class LayerProfile:
    """Simplified layer/block profile used by EDA-Lite."""

    name: str
    op_type: str
    input_kb: float
    output_kb: float
    weight_kb: float
    compute_macs: float
    fusible: bool


@dataclass(frozen=True)
class ModelProfile:
    """A sequential model profile made of simplified layer/block entries."""

    model_name: str
    layers: tuple[LayerProfile, ...]
    # Optional: the ROS2 model this simplified profile stands for (e.g.
    # "mobilevit_xxs"). Runtime-derived OS profiles measured on another model
    # are never applied to this one.
    runtime_model_name: str | None = None


def load_model_profile(path: str | Path) -> ModelProfile:
    """Load and validate a simplified model profile JSON file."""

    profile_path = Path(path)
    with profile_path.open("r", encoding="utf-8") as file:
        raw_profile = json.load(file)

    if not isinstance(raw_profile, dict):
        raise ValueError("Model profile must be a JSON object.")

    model_name = raw_profile.get("model_name")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("Model profile requires a non-empty string 'model_name'.")

    raw_layers = raw_profile.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ValueError("Model profile requires a non-empty 'layers' list.")

    layers = tuple(_parse_layer(index, layer) for index, layer in enumerate(raw_layers))
    validate_layer_chain(layers)
    runtime_model_name = raw_profile.get("runtime_model_name")
    if runtime_model_name is not None and (
        not isinstance(runtime_model_name, str) or not runtime_model_name.strip()
    ):
        raise ValueError("'runtime_model_name' must be a non-empty string when present.")
    return ModelProfile(model_name=model_name, layers=layers, runtime_model_name=runtime_model_name)


def validate_layer_chain(layers: tuple[LayerProfile, ...] | list[LayerProfile]) -> None:
    """Reject duplicate layer names and broken producer/consumer sizes.

    The profile is a sequential chain, so the output of layer ``i`` is the input
    of layer ``i + 1``. A mismatch would make DRAM-traffic and SRAM estimates
    count a tensor that no layer produces.
    """

    seen: dict[str, int] = {}
    for index, layer in enumerate(layers):
        if layer.name in seen:
            raise ValueError(
                f"layers[{index}].name '{layer.name}' duplicates layers[{seen[layer.name]}].name."
            )
        seen[layer.name] = index
    for index in range(len(layers) - 1):
        produced = layers[index].output_kb
        consumed = layers[index + 1].input_kb
        if not math.isclose(produced, consumed, rel_tol=CHAIN_REL_TOL, abs_tol=1e-9):
            raise ValueError(
                f"layers[{index}].output_kb ({produced:g}) != layers[{index + 1}].input_kb "
                f"({consumed:g}): '{layers[index].name}' -> '{layers[index + 1].name}' must "
                "pass the same tensor in a sequential profile."
            )


def _parse_layer(index: int, raw_layer: Any) -> LayerProfile:
    if not isinstance(raw_layer, dict):
        raise ValueError(f"Layer {index} must be a JSON object.")

    missing_fields = REQUIRED_LAYER_FIELDS.difference(raw_layer)
    if missing_fields:
        fields = ", ".join(sorted(missing_fields))
        raise ValueError(f"Layer {index} is missing required fields: {fields}.")

    name = _require_non_empty_string(raw_layer["name"], f"layers[{index}].name")
    op_type = _require_non_empty_string(raw_layer["op_type"], f"layers[{index}].op_type")
    input_kb = _require_non_negative_number(raw_layer["input_kb"], f"layers[{index}].input_kb")
    output_kb = _require_non_negative_number(raw_layer["output_kb"], f"layers[{index}].output_kb")
    weight_kb = _require_non_negative_number(raw_layer["weight_kb"], f"layers[{index}].weight_kb")
    compute_macs = _require_non_negative_number(
        raw_layer["compute_macs"], f"layers[{index}].compute_macs"
    )

    fusible = raw_layer["fusible"]
    if not isinstance(fusible, bool):
        raise ValueError(f"layers[{index}].fusible must be a boolean.")

    return LayerProfile(
        name=name,
        op_type=op_type,
        input_kb=input_kb,
        output_kb=output_kb,
        weight_kb=weight_kb,
        compute_macs=compute_macs,
        fusible=fusible,
    )


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _require_non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number.")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite (got {value}).")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return float(value)
