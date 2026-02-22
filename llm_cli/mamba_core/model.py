from typing import Any, cast

import torch
import torch.nn as nn

from .mamba import Mamba


class RMSNorm(nn.Module):
    def __init__(self, d_model: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(d_model))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return cast(torch.Tensor, output * self.weight)


class MambaBlock(nn.Module):
    def __init__(self, d_model: int, **kwargs: Any) -> None:
        super().__init__()
        self.norm = RMSNorm(d_model)
        self.mamba = Mamba(d_model=d_model, **kwargs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, L, D)
        return cast(torch.Tensor, x + self.mamba(self.norm(x)))

    def step(
        self,
        x: torch.Tensor,
        conv_state: torch.Tensor | None,
        ssm_state: torch.Tensor | None,
        prev_Bx: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        # x: (B, 1, D)
        x_norm = self.norm(x)
        out, conv_state, ssm_state, current_Bx = self.mamba.step(
            x_norm, conv_state, ssm_state, prev_Bx
        )
        return x + out, conv_state, ssm_state, current_Bx


class MambaLM(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        d_model: int = 512,
        n_layers: int = 12,
        d_state: int = 16,
        d_conv: int = 4,
        expand: int = 2,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, d_model)
        self.layers = nn.ModuleList(
            [
                MambaBlock(
                    d_model=d_model, d_state=d_state, d_conv=d_conv, expand=expand
                )
                for _ in range(n_layers)
            ]
        )
        self.norm_f = RMSNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)

        # Initialize weights
        nn.init.normal_(self.embedding.weight, std=0.02)
        # Tie weights
        self.lm_head.weight = self.embedding.weight

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        # input_ids: (B, L)
        x = self.embedding(input_ids)
        for layer in self.layers:
            x = layer(x)
        x = self.norm_f(x)
        logits = self.lm_head(x)
        return cast(torch.Tensor, logits)

    @torch.no_grad()
    def step(
        self, input_ids: torch.Tensor, states: list[Any] | None = None
    ) -> tuple[torch.Tensor, list[Any]]:
        """
        Step function for inference.
        states: List of (conv_state, ssm_state, prev_Bx) for each layer.
        """
        if input_ids.shape[1] > 1:
            all_logits = []
            current_states = states
            for t in range(input_ids.shape[1]):
                logits, current_states = self.step(
                    input_ids[:, t : t + 1], current_states
                )
                all_logits.append(logits)
            return torch.cat(all_logits, dim=1), current_states or []

        x = self.embedding(input_ids)
        new_states = []
        if states is None:
            states = [None] * len(self.layers)

        for i, layer in enumerate(self.layers):
            if states[i] is not None:
                c_s, s_s, p_Bx = states[i]
            else:
                c_s, s_s, p_Bx = None, None, None

            mamba_layer = cast(MambaBlock, layer)
            x, c_s, s_s, p_Bx = mamba_layer.step(x, c_s, s_s, p_Bx)
            new_states.append((c_s, s_s, p_Bx))

        x = self.norm_f(x)
        logits = self.lm_head(x)
        return logits, new_states
