from __future__ import annotations

from typing import Any

import torch


class RegionalSD3IPAdapterProcessor(torch.nn.Module):
    """Spatially gate the image-conditioned delta of an SD3 IP-Adapter processor."""

    def __init__(self, base_processor: torch.nn.Module) -> None:
        super().__init__()
        self.base_processor = base_processor

    @property
    def scale(self) -> float:
        return float(self.base_processor.scale)

    @scale.setter
    def scale(self, value: float) -> None:
        self.base_processor.scale = float(value)

    def __call__(
        self,
        attn: Any,
        hidden_states: torch.Tensor,
        encoder_hidden_states: torch.Tensor | None = None,
        attention_mask: torch.Tensor | None = None,
        ip_hidden_states: torch.Tensor | None = None,
        temb: torch.Tensor | None = None,
        regional_attention_mask: torch.Tensor | None = None,
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        if regional_attention_mask is None or ip_hidden_states is None or self.scale == 0:
            return self.base_processor(
                attn,
                hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
                ip_hidden_states=ip_hidden_states,
                temb=temb,
            )
        if regional_attention_mask.ndim != 3 or regional_attention_mask.shape[-1] != 1:
            raise ValueError("regional_attention_mask must have shape [batch|1, tokens, 1]")
        if regional_attention_mask.shape[1] != hidden_states.shape[1]:
            raise ValueError("regional_attention_mask token count must match hidden states")
        original_scale = self.scale
        try:
            self.scale = 0.0
            baseline = self.base_processor(
                attn,
                hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
                ip_hidden_states=ip_hidden_states,
                temb=temb,
            )
            self.scale = original_scale
            conditioned = self.base_processor(
                attn,
                hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
                ip_hidden_states=ip_hidden_states,
                temb=temb,
            )
        finally:
            self.scale = original_scale

        mask = regional_attention_mask.to(device=hidden_states.device, dtype=hidden_states.dtype)
        if isinstance(baseline, tuple):
            baseline_image, baseline_context = baseline
            conditioned_image, _ = conditioned
            output = baseline_image + (conditioned_image - baseline_image) * mask
            return output, baseline_context
        return baseline + (conditioned - baseline) * mask
