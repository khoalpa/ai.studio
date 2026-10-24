from __future__ import annotations

import torch
import torch.nn.functional as functional
from torch import nn
from torch.utils.hooks import RemovableHandle


def raster_controls_to_tokens(
    controls: torch.Tensor,
    grid_size: tuple[int, int],
    *,
    threshold: float = 0.5,
) -> torch.Tensor:
    """Convert [B,C,H,W] control rasters into binary [B,T,C] token controls."""
    if controls.ndim != 4:
        raise ValueError("controls must have shape [batch, channels, height, width]")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be within [0, 1]")
    sampled = functional.interpolate(controls.float(), size=grid_size, mode="area")
    return (
        (sampled >= threshold)
        .permute(0, 2, 3, 1)
        .reshape(controls.shape[0], grid_size[0] * grid_size[1], controls.shape[1])
    )


class ExplicitSpatialControlResidual(nn.Module):
    """Apply bounded spatial residuals without altering the attention path."""

    def __init__(
        self,
        channel_vectors: torch.Tensor,
        *,
        accumulate_in_fp32: bool = False,
        error_feedback: bool = False,
    ) -> None:
        super().__init__()
        if channel_vectors.ndim != 2:
            raise ValueError("channel_vectors must have shape [channels, hidden_size]")
        normalized = functional.normalize(channel_vectors.float(), dim=-1)
        self.register_buffer("channel_vectors", normalized)
        self.accumulate_in_fp32 = bool(accumulate_in_fp32)
        self.error_feedback = bool(error_feedback)
        self._quantization_error: torch.Tensor | None = None

    def reset_error_feedback(self) -> None:
        self._quantization_error = None

    @property
    def pending_error(self) -> torch.Tensor | None:
        return self._quantization_error

    def forward(
        self,
        hidden_states: torch.Tensor,
        token_controls: torch.Tensor,
        *,
        scale: float,
    ) -> torch.Tensor:
        if token_controls.ndim != 3:
            raise ValueError("token_controls must have shape [batch, tokens, channels]")
        if hidden_states.shape[1] != token_controls.shape[1]:
            raise ValueError("control token dimension must match hidden_states")
        if token_controls.shape[0] not in (1, hidden_states.shape[0]):
            raise ValueError("control batch must be one or match the hidden_states batch")
        if token_controls.shape[-1] != self.channel_vectors.shape[0]:
            raise ValueError("control channel count must match channel_vectors")
        if scale == 0.0:
            return hidden_states
        if self.accumulate_in_fp32 or self.error_feedback:
            controls = token_controls.to(device=hidden_states.device, dtype=torch.float32)
            vectors = self.channel_vectors.to(device=hidden_states.device, dtype=torch.float32)
            residual = torch.matmul(controls, vectors) * float(scale)
            target = residual
            if self.error_feedback:
                prior_error = self._quantization_error
                if prior_error is not None and prior_error.shape == residual.shape:
                    target = target + prior_error.to(residual)
            written = (hidden_states.float() + target).to(hidden_states.dtype)
            if self.error_feedback:
                observed = written.float() - hidden_states.float()
                self._quantization_error = (target - observed).detach()
            return written
        controls = token_controls.to(hidden_states)
        vectors = self.channel_vectors.to(hidden_states)
        return hidden_states + torch.matmul(controls, vectors) * float(scale)


class ExplicitControlRegistration:
    """Register one shared explicit-control residual across SD3 transformer blocks."""

    module_name = "explicit_spatial_control"

    def __init__(
        self,
        transformer: nn.Module,
        adapter: ExplicitSpatialControlResidual,
    ) -> None:
        blocks = getattr(transformer, "transformer_blocks", None)
        if blocks is None:
            raise ValueError("transformer must expose transformer_blocks")
        if hasattr(transformer, self.module_name):
            raise RuntimeError("explicit control is already registered")
        self.transformer = transformer
        self.adapter = adapter
        self.token_controls: torch.Tensor | None = None
        self.block_scales = [0.0] * len(blocks)
        transformer.add_module(self.module_name, adapter)
        self.handles: list[RemovableHandle] = []
        for index, block in enumerate(blocks):
            self.handles.append(block.register_forward_hook(self._hook(index)))

    def _hook(self, index: int):
        def apply_control(
            _module: nn.Module,
            _inputs: tuple[object, ...],
            output: tuple[torch.Tensor | None, torch.Tensor],
        ) -> tuple[torch.Tensor | None, torch.Tensor]:
            if not isinstance(output, tuple) or len(output) != 2:
                raise ValueError("SD3 transformer block output must be a pair")
            context, hidden_states = output
            controls = self.token_controls
            scale = self.block_scales[index]
            if controls is None or scale == 0.0:
                return output
            controlled = self.adapter(hidden_states, controls, scale=scale)
            return context, controlled

        return apply_control

    def configure(
        self,
        token_controls: torch.Tensor | None,
        block_scales: list[float],
    ) -> None:
        if len(block_scales) != len(self.handles):
            raise ValueError("block_scales must match registered block count")
        self.token_controls = token_controls
        self.block_scales = [float(scale) for scale in block_scales]

    def unregister(self) -> None:
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        if hasattr(self.transformer, self.module_name):
            delattr(self.transformer, self.module_name)
        self.token_controls = None
        self.block_scales = []


class StagedExplicitControlRegistration:
    """Register independent structural controls on one set of transformer blocks."""

    module_name = "staged_explicit_controls"

    def __init__(
        self,
        transformer: nn.Module,
        adapters: dict[str, ExplicitSpatialControlResidual],
    ) -> None:
        blocks = getattr(transformer, "transformer_blocks", None)
        if blocks is None:
            raise ValueError("transformer must expose transformer_blocks")
        if not adapters:
            raise ValueError("at least one staged control adapter is required")
        if hasattr(transformer, self.module_name):
            raise RuntimeError("staged explicit controls are already registered")
        self.transformer = transformer
        self.adapters = nn.ModuleDict(adapters)
        self.controls: dict[str, torch.Tensor | None] = {name: None for name in adapters}
        self.block_scales: dict[str, list[float]] = {name: [0.0] * len(blocks) for name in adapters}
        transformer.add_module(self.module_name, self.adapters)
        self.handles: list[RemovableHandle] = []
        for index, block in enumerate(blocks):
            self.handles.append(block.register_forward_hook(self._hook(index)))

    def _hook(self, index: int):
        def apply_controls(
            _module: nn.Module,
            _inputs: tuple[object, ...],
            output: tuple[torch.Tensor | None, torch.Tensor],
        ) -> tuple[torch.Tensor | None, torch.Tensor]:
            if not isinstance(output, tuple) or len(output) != 2:
                raise ValueError("SD3 transformer block output must be a pair")
            context, hidden_states = output
            for name, adapter in self.adapters.items():
                controls = self.controls[name]
                scale = self.block_scales[name][index]
                if controls is not None and scale != 0.0:
                    hidden_states = adapter(hidden_states, controls, scale=scale)
            return context, hidden_states

        return apply_controls

    def configure_stage(
        self,
        name: str,
        token_controls: torch.Tensor | None,
        block_scales: list[float],
    ) -> None:
        if name not in self.adapters:
            raise KeyError(f"unknown staged control: {name}")
        if len(block_scales) != len(self.handles):
            raise ValueError("block_scales must match registered block count")
        self.controls[name] = token_controls
        self.block_scales[name] = [float(scale) for scale in block_scales]

    def unregister(self) -> None:
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        if hasattr(self.transformer, self.module_name):
            delattr(self.transformer, self.module_name)
        self.controls.clear()
        self.block_scales.clear()
