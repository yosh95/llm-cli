import threading
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
    A NumPy-based Mamba implementation for monitoring LLM output patterns.
    Calculates anomaly scores based on byte-level sequence probability.
    """

    def __init__(
        self,
        d_model: int = 128,
        n_layers: int = 2,
        d_state: int = 8,
        d_conv: int = 4,
        expand: int = 1,
        lr: float = 1e-3,
        checkpoint_path: str = "sentinel_state.npz",
        mode: str = "train",
    ):
        self.config = MambaConfig(
            d_model=d_model, d_state=d_state, d_conv=d_conv, expand=expand
        )
        self.n_layers = n_layers
        self.vocab_size = 256
        self.checkpoint_path = checkpoint_path
        self.mode = mode  # "train" or "predict"
        self.update_count = 0
        self._lock = threading.RLock()

        # Self-calibration: Start at random entropy (ln(256) ≈ 5.54)
        self.ema_loss = 5.54

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

    @property
    def thresholds(self) -> dict[str, float]:
        """Returns the current dynamic thresholds for compatibility."""
        y, r = self.get_dynamic_thresholds()
        return {"yellow": y, "red": r}

    def reset_state(self) -> None:
        with self._lock:
            self.states = None
            self.last_logits = None

    def get_states(self) -> dict[str, Any]:
        """Returns a deep copy of the current inference states."""
        import copy

        with self._lock:
            return {
                "states": copy.deepcopy(self.states),
                "last_logits": self.last_logits.copy()
                if self.last_logits is not None
                else None,
            }

    def set_states(self, states_data: dict[str, Any]) -> None:
        """Restores inference states from a saved dictionary."""
        with self._lock:
            self.states = states_data["states"]
            self.last_logits = states_data["last_logits"]

    def _get_params(self) -> dict[str, np.ndarray]:
        params: dict[str, np.ndarray] = {
            "embedding.weight": self.embedding.weight,
            "norm_f.weight": self.norm_f.weight,
            "meta.update_count": np.array([self.update_count], dtype=np.int64),
            "meta.ema_loss": np.array([self.ema_loss], dtype=np.float64),
        }
        for i in range(self.n_layers):
            for k, v in self.mamba_layers[i].params.items():
                params[f"layer.{i}.mamba.{k}"] = v
            params[f"layer.{i}.norm.weight"] = self.norms[i].weight
        return params

    def get_dynamic_thresholds(self) -> tuple[float, float]:
        """
        Calculates adaptive thresholds based on the model's own performance.
        Status is determined relative to the exponential moving average of loss.
        """
        # Yellow: A significant deviation from the learned pattern (+0.4)
        # Red: A structural deviation (highly surprising for the model) (+1.2)
        # Using margins above EMA ensures we follow the loss curve down.
        with self._lock:
            current_yellow = self.ema_loss + 0.4
            current_red = self.ema_loss + 1.2

        return current_yellow, current_red

    def forward(self, input_ids: np.ndarray, training: bool = False) -> np.ndarray:
        # input_ids: (B, L)
        # Assuming lock is held by caller if needed, but forward() is usually
        # called by update() or process_text()
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
        Calculates the anomaly score for a single token based on the previous context.
        Returns: (anomaly_score, status)
        """
        with self._lock:
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
                m_out, c_s, s_s, p_Bx = self.mamba_layers[i].step(
                    norm_x, c_s, s_s, p_Bx
                )
                x = x + m_out
                new_states.append((c_s, s_s, p_Bx))

            x_final = self.norm_f.forward(x)
            self.last_logits = self.lm_head.forward(x_final)
            self.states = new_states

            # Determine status using dynamic thresholds
            t_yellow, t_red = self.get_dynamic_thresholds()
            status = "green"
            if score > t_red:
                status = "red"
            elif score > t_yellow:
                status = "yellow"

        return score, status

    def compute_anomaly_score(self, logits: np.ndarray, target_token: int) -> float:
        """
        Compute Cross-Entropy loss for a single token.
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
        Process a sequence of text and return anomaly scores for each byte.
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

        if self.mode == "train":
            # Train on this sequence
            ids = np.array([list(tokens)], dtype=np.int32)
            # Targets are shifted tokens
            if ids.shape[1] > 1:
                targets = ids[:, 1:]
                inputs = ids[:, :-1]
                self.update(inputs, targets)
                self.save()

        return results

    def analyze(self, data: str | bytes) -> list[dict]:
        """
        High-level entry point for anomaly detection.
        Handles both string and byte inputs.
        """
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data
        return self.process_text(text)

    def update(self, input_ids: np.ndarray, targets: np.ndarray) -> None:
        """
        Online learning update (one epoch of backprop)
        input_ids: (1, L)
        targets: (1, L)
        """
        with self._lock:
            self.update_count += 1
            # Forward pass
            logits = self.forward(input_ids, training=True)

            # Softmax and Loss gradient
            # logits: (B, L, V), targets: (B, L)
            B, L, V = logits.shape
            # Numerical stability
            logits_max = np.max(logits, axis=-1, keepdims=True)
            exp_logits = np.exp(logits - logits_max)
            probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

            # Track loss for self-calibration
            batch_loss = 0.0
            grad_logits = probs.copy()
            for b in range(B):
                for l_idx in range(L):
                    target = targets[b, l_idx]
                    grad_logits[b, l_idx, target] -= 1.0
                    batch_loss += -np.log(probs[b, l_idx, target] + 1e-10)

            avg_loss = batch_loss / (B * L)

            # Update EMA: faster adaptation early on, then stabilizes
            # This allows the thresholds to follow the loss curve down.
            alpha = max(0.01, 1.0 / (10.0 + self.update_count * 0.1))
            self.ema_loss = (1 - alpha) * self.ema_loss + alpha * avg_loss

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
                # Forward: x_next = x_curr + mamba(norm(x_curr))
                # Backward: dL/dx_curr = dL/dx_next +
                #           dL/d(mamba) * d(mamba)/d(norm) * d(norm)/d(x_curr)

                # 1. Gradient through Mamba layer and its internal RMSNorm
                grad_mamba_in, mamba_grads = self.mamba_layers[i].backward(grad_x)
                grad_norm_in = self.norms[i].backward(grad_mamba_in)

                # 2. Add residual connection gradient (identity path)
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

        with self._lock:
            params = self._get_params()
            # Save state as a compressed NumPy file
            path = Path(self.checkpoint_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(str(path), **params)  # type: ignore[arg-type]

    def load(self) -> None:
        from pathlib import Path

        with self._lock:
            if Path(self.checkpoint_path).exists():
                try:
                    import io

                    # Read entire file into memory first to avoid resource leaks
                    # during subsequent processing or if exceptions occur.
                    file_content = Path(self.checkpoint_path).read_bytes()
                    with np.load(io.BytesIO(file_content)) as data:
                        loaded_data = {k: np.array(v) for k, v in data.items()}

                    # 0. Metadata
                    if "meta.update_count" in loaded_data:
                        self.update_count = int(loaded_data["meta.update_count"][0])
                    if "meta.ema_loss" in loaded_data:
                        self.ema_loss = float(loaded_data["meta.ema_loss"][0])

                    # 1. Embedding
                    if "embedding.weight" in loaded_data:
                        self.embedding.weight[:] = loaded_data["embedding.weight"]

                    # 2. Final Norm
                    if "norm_f.weight" in loaded_data:
                        self.norm_f.weight[:] = loaded_data["norm_f.weight"]

                    # 3. Layers
                    for i in range(self.n_layers):
                        # Norm
                        nk = f"layer.{i}.norm.weight"
                        if nk in loaded_data:
                            self.norms[i].weight[:] = loaded_data[nk]

                        # Mamba
                        mamba_params = {}
                        prefix = f"layer.{i}.mamba."
                        for k in loaded_data:
                            if k.startswith(prefix):
                                mamba_params[k[len(prefix) :]] = loaded_data[k]

                        if mamba_params:
                            self.mamba_layers[i].load_state_dict(mamba_params)
                except Exception as e:
                    # If loading fails (e.g. shape mismatch), we just start fresh
                    print(f"Warning: Failed to load sentinel checkpoint: {e}")
