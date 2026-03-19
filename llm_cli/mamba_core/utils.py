from typing import Any, cast

import numpy as np


class NumPyEmbedding:
    def __init__(self, vocab_size: int, d_model: int):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.weight = np.random.normal(0, 0.02, (vocab_size, d_model)).astype(
            np.float64
        )
        self.grad_weight = np.zeros_like(self.weight)

    def forward(self, input_ids: np.ndarray) -> np.ndarray:
        self.input_ids = input_ids
        return cast(np.ndarray, self.weight[input_ids])

    def backward(self, grad_output: np.ndarray) -> np.ndarray:
        self.grad_weight.fill(0)
        # Using np.add.at for efficient scatter-add in NumPy
        np.add.at(self.grad_weight, self.input_ids, grad_output)
        return self.grad_weight


class NumPyRMSNorm:
    def __init__(self, d_model: int, eps: float = 1e-5):
        self.eps = eps
        self.weight = np.ones(d_model, dtype=np.float64)
        self.grad_weight = np.zeros_like(self.weight)
        self.cache: dict[str, Any] = {}

    def forward(self, x: np.ndarray) -> np.ndarray:
        # x: (B, L, D) or (B, D)
        # RMS = sqrt(mean(x^2) + eps)
        ms = np.mean(x**2, axis=-1, keepdims=True)
        rsqrt = 1.0 / np.sqrt(ms + self.eps)
        norm_x = x * rsqrt
        output = norm_x * self.weight

        self.cache = {"x": x, "norm_x": norm_x, "rsqrt": rsqrt}
        return cast(np.ndarray, output)

    def backward(self, grad_output: np.ndarray) -> np.ndarray:
        x = self.cache["x"]
        norm_x = self.cache["norm_x"]
        rsqrt = self.cache["rsqrt"]
        d_model = x.shape[-1]

        # Gradient wrt weight
        self.grad_weight = np.sum(
            grad_output * norm_x, axis=tuple(range(grad_output.ndim - 1))
        )

        # Gradient wrt x
        # d_x = (grad_output * weight * rsqrt) -
        #       (x * weight * rsqrt^3 * mean(x * grad_output))
        # More stable version:
        d_norm_x = grad_output * self.weight
        d_ms = np.sum(d_norm_x * x * (-0.5) * (rsqrt**3), axis=-1, keepdims=True)
        d_x = d_norm_x * rsqrt + d_ms * (2.0 * x / d_model)

        return cast(np.ndarray, d_x)


class NumPyLinear:
    def __init__(self, in_features: int, out_features: int, bias: bool = True):
        self.in_features = in_features
        self.out_features = out_features
        self.weight = np.random.normal(0, 0.02, (out_features, in_features)).astype(
            np.float64
        )
        self.bias = np.zeros(out_features, dtype=np.float64) if bias else None

        self.grad_weight = np.zeros_like(self.weight)
        self.grad_bias = np.zeros_like(self.bias) if bias else None
        self.cache: dict[str, Any] = {}

    def forward(self, x: np.ndarray) -> np.ndarray:
        # x: (..., in_features)
        self.cache["x"] = x
        out = x @ self.weight.T
        if self.bias is not None:
            out += self.bias
        return cast(np.ndarray, out)

    def backward(self, grad_output: np.ndarray) -> np.ndarray:
        x = self.cache["x"]

        # grad_weight = sum over all dimensions except the last one:
        # (B, L, out_features).T @ (B, L, in_features) -> (out_features, in_features)
        x_flat = x.reshape(-1, x.shape[-1])
        grad_output_flat = grad_output.reshape(-1, grad_output.shape[-1])
        self.grad_weight = grad_output_flat.T @ x_flat

        if self.bias is not None:
            self.grad_bias = np.sum(
                grad_output, axis=tuple(range(grad_output.ndim - 1))
            )

        d_x = grad_output @ self.weight
        return cast(np.ndarray, d_x)
