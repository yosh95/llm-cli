from typing import Any, cast

import numpy as np

from ..mamba_core.mamba_numpy import (
    AdamOptimizer,
    MambaConfig,
    MambaNumpy,
)
from ..mamba_core.utils import NumPyEmbedding, NumPyLinear, NumPyRMSNorm


class MambaSentinel:
    """
    A NumPy-only Mamba-based Sentinel for real-time anomaly detection in LLM output.
    Uses byte-level modeling (vocab_size=256) for zero-dependency portability.
    """

    def __init__(
        self,
        d_model: int = 128,
        n_layers: int = 2,
        d_state: int = 16,
        d_conv: int = 4,
        expand: int = 2,
        lr: float = 1e-3,
        checkpoint_path: str = "sentinel_state.npz",
        mode: str = "detect",
        threshold_yellow: float = 3.5,
        threshold_red: float = 5.0,
    ):
        self.config = MambaConfig(
            d_model=d_model, d_state=d_state, d_conv=d_conv, expand=expand
        )
        self.n_layers = n_layers
        self.vocab_size = 256
        self.checkpoint_path = checkpoint_path
        self.mode = mode  # "collect" (training) or "detect" (blocking/reporting)
        self.thresholds = {"yellow": threshold_yellow, "red": threshold_red}

        # Layers
        self.embedding = NumPyEmbedding(self.vocab_size, d_model)
        self.mamba_layers = [MambaNumpy(self.config) for _ in range(n_layers)]
        self.norms = [NumPyRMSNorm(d_model) for _ in range(n_layers)]
        self.norm_f = NumPyRMSNorm(d_model)
        self.lm_head = NumPyLinear(d_model, self.vocab_size, bias=False)

        # Tie weights: lm_head.weight = embedding.weight (optional but common)
        self.lm_head.weight = self.embedding.weight

        # Optimizer
        params = self._get_params()
        self.optimizer = AdamOptimizer(params, lr=lr)

        # Inference state
        self.states: list[Any] | None = None
        self.last_logits: np.ndarray | None = None

    def reset_state(self) -> None:
        self.states = None
        self.last_logits = None

    def _get_params(self) -> dict[str, np.ndarray]:
        params = {
            "embedding.weight": self.embedding.weight,
            "norm_f.weight": self.norm_f.weight,
        }
        for i in range(self.n_layers):
            for k, v in self.mamba_layers[i].params.items():
                params[f"layer.{i}.mamba.{k}"] = v
            params[f"layer.{i}.norm.weight"] = self.norms[i].weight
        return params

    def forward(self, input_ids: np.ndarray, training: bool = False) -> np.ndarray:
        # input_ids: (B, L)
        x = self.embedding.forward(input_ids)
        for i in range(self.n_layers):
            norm_x = self.norms[i].forward(x)
            mamba_out = self.mamba_layers[i].forward(norm_x, training=training)
            x = x + mamba_out

        x = self.norm_f.forward(x)
        logits = self.lm_head.forward(x)
        return cast(np.ndarray, logits)

    def step(self, token: int) -> tuple[float, str]:
        """
        One-step inference and anomaly score calculation.
        Returns: (anomaly_score, status)
        """
        score = 0.0
        if self.last_logits is not None:
            score = self.compute_anomaly_score(self.last_logits, token)

        if self.states is None:
            self.states = [None] * self.n_layers

        input_ids = np.array([[token]], dtype=np.int32)

        # Forward pass for one step to get logits for NEXT token
        x = self.embedding.forward(input_ids)
        new_states = []
        for i in range(self.n_layers):
            if self.states[i] is not None:
                c_s, s_s, p_Bx = self.states[i]
            else:
                c_s, s_s, p_Bx = None, None, None

            norm_x = self.norms[i].forward(x)
            m_out, c_s, s_s, p_Bx = self.mamba_layers[i].step(norm_x, c_s, s_s, p_Bx)
            x = x + m_out
            new_states.append((c_s, s_s, p_Bx))

        x_final = self.norm_f.forward(x)
        self.last_logits = self.lm_head.forward(x_final)
        self.states = new_states

        # Determine status
        status = "green"
        if score > self.thresholds["red"]:
            status = "red"
        elif score > self.thresholds["yellow"]:
            status = "yellow"

        # In collect mode, we might want to update the model online
        if self.mode == "collect":
            # Very simple online update: we use current token as target
            # for previous prediction.
            # This is handled in process_text or similar.
            pass  # We'll do batch updates for stability

        return score, status

    def compute_anomaly_score(self, logits: np.ndarray, target_token: int) -> float:
        """
        Compute Cross-Entropy loss for a single token.
        logits: (1, 1, vocab_size) - prediction for the target_token
        """
        # Softmax
        logits_flat = logits.flatten()
        # Numerical stability
        l_max = np.max(logits_flat)
        exp_l = np.exp(logits_flat - l_max)
        probs = exp_l / np.sum(exp_l)

        # Cross Entropy
        eps = 1e-10
        loss = -np.log(probs[target_token] + eps)
        return float(loss)

    def process_text(self, text: str) -> list[dict]:
        """
        Process a sequence of text and return anomaly metadata for each byte.
        """
        tokens = text.encode("utf-8")
        results = []

        for token in tokens:
            score, status = self.step(token)
            results.append(
                {
                    "byte": token,
                    "char": chr(token) if token < 128 else f"\\x{token:02x}",
                    "score": score,
                    "status": status,
                }
            )

        if self.mode == "collect":
            # Train on this sequence
            ids = np.array([list(tokens)], dtype=np.int32)
            # Targets are shifted tokens
            if ids.shape[1] > 1:
                targets = ids[:, 1:]
                inputs = ids[:, :-1]
                self.update(inputs, targets)
                self.save()

        return results

    def update(self, input_ids: np.ndarray, targets: np.ndarray) -> None:
        """
        Online learning update (one epoch of backprop)
        input_ids: (1, L)
        targets: (1, L)
        """
        # Forward pass
        logits = self.forward(input_ids, training=True)

        # Softmax and Loss gradient
        # logits: (B, L, V), targets: (B, L)
        B, L, V = logits.shape
        # Numerical stability
        logits_max = np.max(logits, axis=-1, keepdims=True)
        exp_logits = np.exp(logits - logits_max)
        probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

        grad_logits = probs.copy()
        for b in range(B):
            for l_idx in range(L):
                target = targets[b, l_idx]
                grad_logits[b, l_idx, target] -= 1.0
        grad_logits /= B * L

        # Backward pass
        # 1. Output head
        grad_x = self.lm_head.backward(grad_logits)
        grad_x = self.norm_f.backward(grad_x)

        # 2. Residual Blocks
        all_grads = {
            "embedding.weight": self.embedding.grad_weight,
            "norm_f.weight": self.norm_f.grad_weight,
        }

        for i in reversed(range(self.n_layers)):
            # x_out = x_in + mamba_out
            # grad_x_in = grad_x_out + grad_mamba_out

            # The norm is inside the residual?
            # In my forward:
            # norm_x = norms[i].forward(x)
            # mamba_out = mamba_layers[i].forward(norm_x)
            # x = x + mamba_out

            # Backward:
            # grad_mamba_out = grad_x
            # grad_norm_x, mamba_grads = mamba_layers[i].backward(grad_x)
            # grad_x_norm_in = norms[i].backward(grad_norm_x)
            # grad_x = grad_x + grad_x_norm_in

            grad_mamba_in, mamba_grads = self.mamba_layers[i].backward(grad_x)
            grad_norm_in = self.norms[i].backward(grad_mamba_in)

            # Residual connection
            grad_x = grad_x + grad_norm_in

            # Store grads for optimizer
            for k, v in mamba_grads.items():
                all_grads[f"layer.{i}.mamba.{k}"] = v
            all_grads[f"layer.{i}.norm.weight"] = self.norms[i].grad_weight

        # 3. Embedding
        self.embedding.backward(grad_x)
        all_grads["embedding.weight"] = self.embedding.grad_weight

        # Update
        self.optimizer.step(all_grads)

    def save(self) -> None:
        from pathlib import Path

        params = self._get_params()
        # Save state as a compressed NumPy file
        path = Path(self.checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(path), **params)  # type: ignore[arg-type]

    def load(self) -> None:
        from pathlib import Path

        if Path(self.checkpoint_path).exists():
            try:
                data = np.load(self.checkpoint_path)

                # 1. Embedding
                if "embedding.weight" in data:
                    self.embedding.weight[:] = data["embedding.weight"]

                # 2. Final Norm
                if "norm_f.weight" in data:
                    self.norm_f.weight[:] = data["norm_f.weight"]

                # 3. Layers
                for i in range(self.n_layers):
                    # Norm
                    nk = f"layer.{i}.norm.weight"
                    if nk in data:
                        self.norms[i].weight[:] = data[nk]

                    # Mamba
                    mamba_params = {}
                    prefix = f"layer.{i}.mamba."
                    for k in data:
                        if k.startswith(prefix):
                            mamba_params[k[len(prefix) :]] = data[k]

                    if mamba_params:
                        self.mamba_layers[i].load_state_dict(mamba_params)

                # Reset optimizer state if needed or re-init
                # For simplicity, we just start Adam fresh or could save its state too
                # self.optimizer.m = ...
            except Exception as e:
                # If loading fails (e.g. shape mismatch), we just start fresh
                print(f"Warning: Failed to load sentinel checkpoint: {e}")
