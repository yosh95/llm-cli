import math
from typing import Any, cast

import numpy as np

# --- Activation Functions and Their Derivatives ---


def silu(x: np.ndarray) -> np.ndarray:
    return cast(np.ndarray, x * (1.0 / (1.0 + np.exp(-x))))


def silu_backward(x: np.ndarray, grad_output: np.ndarray) -> np.ndarray:
    """Derivative of SiLU: sigmoid(x) * (1 + x * (1 - sigmoid(x)))"""
    sig = 1.0 / (1.0 + np.exp(-x))
    return cast(np.ndarray, grad_output * (sig * (1.0 + x * (1.0 - sig))))


def softplus(x: np.ndarray) -> np.ndarray:
    return cast(np.ndarray, np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0))


def softplus_backward(x: np.ndarray, grad_output: np.ndarray) -> np.ndarray:
    """Derivative of softplus is sigmoid"""
    return cast(np.ndarray, grad_output * (1.0 / (1.0 + np.exp(-x))))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return cast(np.ndarray, 1.0 / (1.0 + np.exp(-x)))


def sigmoid_backward(x: np.ndarray, grad_output: np.ndarray) -> np.ndarray:
    """Derivative of sigmoid: s * (1 - s)"""
    s = sigmoid(x)
    return cast(np.ndarray, grad_output * s * (1.0 - s))


class MambaConfig:
    def __init__(
        self,
        d_model: int = 128,
        d_state: int = 16,
        d_conv: int = 3,
        expand: int = 2,
        dt_min: float = 0.001,
        dt_max: float = 0.1,
        dt_scale: float = 1.0,
        dt_init_floor: float = 1e-4,
        bias: bool = False,
        conv_bias: bool = True,
    ) -> None:
        self.d_model = d_model
        self.d_state = d_state
        self.d_conv = d_conv
        self.expand = expand
        self.dt_min = dt_min
        self.dt_max = dt_max
        self.dt_scale = dt_scale
        self.dt_init_floor = dt_init_floor
        self.bias = bias
        self.conv_bias = conv_bias
        self.d_inner = expand * d_model
        self.dt_rank = math.ceil(d_model / 16)


class MambaNumpy:
    def __init__(self, config: MambaConfig):
        self.config = config
        self.params: dict[str, np.ndarray] = {}
        self.grads: dict[str, np.ndarray] = {}
        self.cache: dict[str, Any] = {}
        self._init_random_params()

    def _init_random_params(self) -> None:
        c = self.config
        rng = np.random.default_rng(42)

        # Use float64 for all real parameters
        dtype_real = np.float64

        # in_proj weights
        self.params["in_proj.weight"] = (
            rng.standard_normal((2 * c.d_inner, c.d_model), dtype=dtype_real) * 0.02
        )
        if c.bias:
            self.params["in_proj.bias"] = np.zeros(2 * c.d_inner, dtype=dtype_real)

        # conv1d weights (depthwise)
        self.params["conv1d.weight"] = (
            rng.standard_normal((c.d_inner, c.d_conv), dtype=dtype_real) * 0.02
        )
        if c.conv_bias:
            self.params["conv1d.bias"] = np.zeros(c.d_inner, dtype=dtype_real)

        # x_proj and dt_proj weights
        out_dim = c.dt_rank + 4 * c.d_state + 2
        self.params["x_proj.weight"] = (
            rng.standard_normal((out_dim, c.d_inner), dtype=dtype_real) * 0.02
        )
        self.params["dt_proj.weight"] = (
            rng.standard_normal((c.d_inner, c.dt_rank), dtype=dtype_real) * 0.02
        )
        self.params["dt_proj.bias"] = (
            rng.standard_normal(c.d_inner, dtype=dtype_real) * 0.02
        )

        # Complex A parameters - Initializing as float64,
        # they will form complex128 later
        A_real = np.arange(1, c.d_state + 1, dtype=dtype_real)
        self.params["A_log"] = np.log(A_real)[None, :].repeat(c.d_inner, axis=0)
        self.params["A_imag"] = np.pi * rng.random(
            (c.d_inner, c.d_state), dtype=dtype_real
        )

        # D parameter (skip connection)
        self.params["D"] = np.ones(c.d_inner, dtype=dtype_real)

        # out_proj weights
        self.params["out_proj.weight"] = (
            rng.standard_normal((c.d_model, c.d_inner), dtype=dtype_real) * 0.02
        )
        if c.bias:
            self.params["out_proj.bias"] = np.zeros(c.d_model, dtype=dtype_real)

    def forward(self, x: np.ndarray, training: bool = False) -> np.ndarray:
        B, L, _ = x.shape
        c = self.config

        # 1. in_proj
        xz = x @ self.params["in_proj.weight"].T
        if "in_proj.bias" in self.params:
            xz += self.params["in_proj.bias"]
        x_in, z = np.split(xz, 2, axis=-1)

        # 2. conv1d
        x_t = x_in.transpose(0, 2, 1)  # (B, D, L)
        padding = c.d_conv - 1
        x_padded = np.pad(x_t, ((0, 0), (0, 0), (padding, 0)), mode="constant")

        conv_out = np.zeros_like(x_t)
        weight = self.params["conv1d.weight"]
        bias = self.params["conv1d.bias"] if c.conv_bias else 0

        for i in range(L):
            window = x_padded[:, :, i : i + c.d_conv]
            conv_out[:, :, i] = np.sum(window * weight[None, :, :], axis=2) + bias

        x_conv_pre_act = conv_out.transpose(0, 2, 1)
        x_conv = silu(x_conv_pre_act)

        # 3. SSM
        y, ssm_cache = self.ssm(x_conv, training=training)

        # 4. Gating
        z_act = silu(z)
        gated_y = y * z_act

        # 5. out_proj
        output = gated_y @ self.params["out_proj.weight"].T
        if "out_proj.bias" in self.params:
            output += self.params["out_proj.bias"]

        if training:
            self.cache = {
                "x": x,
                "xz": xz,
                "x_in": x_in,
                "z": z,
                "z_act": z_act,
                "x_padded": x_padded,
                "x_conv_pre_act": x_conv_pre_act,
                "x_conv": x_conv,
                "y": y,
                "gated_y": gated_y,
                "ssm": ssm_cache,
            }

        return cast(np.ndarray, output)

    def ssm(
        self, x: np.ndarray, training: bool = False
    ) -> tuple[np.ndarray, dict[str, Any]]:
        B, L, D_inner = x.shape
        c = self.config

        A = -np.exp(self.params["A_log"]) + 1j * self.params["A_imag"]
        proj_out = x @ self.params["x_proj.weight"].T

        delta_proj = proj_out[..., : c.dt_rank]
        B_re = proj_out[..., c.dt_rank : c.dt_rank + c.d_state]
        B_im = proj_out[..., c.dt_rank + c.d_state : c.dt_rank + 2 * c.d_state]
        C_re = proj_out[..., c.dt_rank + 2 * c.d_state : c.dt_rank + 3 * c.d_state]
        C_im = proj_out[..., c.dt_rank + 3 * c.d_state : c.dt_rank + 4 * c.d_state]
        lambda_gate_raw = proj_out[..., -2:-1]
        evo_gate_raw = proj_out[..., -1:]

        lambda_gate = sigmoid(lambda_gate_raw)
        evo_gate = sigmoid(evo_gate_raw)

        delta_pre_softplus = (
            delta_proj @ self.params["dt_proj.weight"].T + self.params["dt_proj.bias"]
        )
        delta = softplus(delta_pre_softplus)

        B_complex = B_re + 1j * B_im
        C_complex = C_re + 1j * C_im

        y, scan_cache = self.selective_scan_v3(
            x, delta, A, B_complex, C_complex, lambda_gate, evo_gate, training=training
        )

        ssm_cache = {
            "proj_out": proj_out,
            "delta_proj": delta_proj,
            "delta_pre_softplus": delta_pre_softplus,
            "delta": delta,
            "A": A,
            "B": B_complex,
            "C": C_complex,
            "lambda_gate": lambda_gate,
            "evo_gate": evo_gate,
            "lambda_gate_raw": lambda_gate_raw,
            "evo_gate_raw": evo_gate_raw,
            "scan": scan_cache,
        }
        return y, ssm_cache

    def selective_scan_v3(
        self,
        x: np.ndarray,
        delta: np.ndarray,
        A: np.ndarray,
        B: np.ndarray,
        C: np.ndarray,
        lambda_gate: np.ndarray,
        evo_gate: np.ndarray,
        training: bool = False,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """
        Parallel Associative Scan implementation in NumPy.
        Reduces Python loop overhead from O(L) to O(log L).
        """
        bs, L, d_inner = x.shape

        # 1. Precompute all parameters for the entire sequence (Vectorized)
        dt_all = delta[:, :, :, None]
        A_expanded = A[None, None, :, :]

        exponent = dt_all * A_expanded
        exponent_real = np.clip(exponent.real, -20.0, 20.0)
        alphas = np.exp(exponent_real + 1j * exponent.imag).astype(np.complex128)

        # current_Bx: (B, L, D, N)
        current_Bxs = (x[:, :, :, None] * B[:, :, None, :]).astype(np.complex128)

        l_gate = lambda_gate[:, :, :, None]
        e_gate = evo_gate[:, :, :, None]

        betas = (1.0 - l_gate) * dt_all * alphas
        gammas = l_gate * dt_all * e_gate

        # h_t = alpha_t * h_{t-1} + u_t
        # u_t = beta_t * current_Bx_{t-1} + gamma_t * current_Bx_t
        us = gammas * current_Bxs
        us[:, 1:] += betas[:, 1:] * current_Bxs[:, :-1]

        # 2. Parallel Associative Scan (Kogge-Stone Algorithm)
        res_A = alphas.copy()
        res_U = us.copy()

        step = 1
        while step < L:
            # A_new = A_t * A_{t-step}
            # U_new = A_t * U_{t-step} + U_t
            A_t = res_A[:, step:]
            U_t = res_U[:, step:]
            A_prev = res_A[:, :-step]
            U_prev = res_U[:, :-step]

            res_U[:, step:] = A_t * U_prev + U_t
            res_A[:, step:] = A_t * A_prev
            step *= 2

        h_all = res_U

        # 3. Compute output y
        y = np.sum(h_all * np.conj(C[:, :, None, :]), axis=-1).real
        y = y + self.params["D"][None, None, :] * x

        cache = (
            {
                "alphas": alphas,
                "betas": betas,
                "gammas": gammas,
                "current_Bxs": current_Bxs,
                "h_all": h_all,
            }
            if training
            else {}
        )
        return y, cache

    def step(
        self,
        x: np.ndarray,
        conv_state: np.ndarray | None,
        ssm_state: np.ndarray | None,
        prev_Bx: np.ndarray | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """One-step inference for Mamba"""
        batch = x.shape[0]
        c = self.config

        # 1. in_proj
        xz = x @ self.params["in_proj.weight"].T
        if "in_proj.bias" in self.params:
            xz += self.params["in_proj.bias"]
        x_in, z = np.split(xz, 2, axis=-1)
        x_in = x_in.squeeze(1)
        z = z.squeeze(1)

        # 2. conv1d
        if conv_state is None:
            conv_state = np.zeros((batch, c.d_inner, c.d_conv))
        conv_state = np.roll(conv_state, shift=-1, axis=-1)
        conv_state[:, :, -1] = x_in

        weight = self.params["conv1d.weight"]
        bias = self.params["conv1d.bias"] if c.conv_bias else 0
        x_conv = np.sum(conv_state * weight[None, :, :], axis=2) + bias
        x_conv = silu(x_conv)

        # 3. SSM
        A = -np.exp(self.params["A_log"]) + 1j * self.params["A_imag"]
        proj_out = x_conv @ self.params["x_proj.weight"].T

        delta_proj = proj_out[..., : c.dt_rank]
        B_re = proj_out[..., c.dt_rank : c.dt_rank + c.d_state]
        B_im = proj_out[..., c.dt_rank + c.d_state : c.dt_rank + 2 * c.d_state]
        C_re = proj_out[..., c.dt_rank + 2 * c.d_state : c.dt_rank + 3 * c.d_state]
        C_im = proj_out[..., c.dt_rank + 3 * c.d_state : c.dt_rank + 4 * c.d_state]
        lambda_gate = sigmoid(proj_out[..., -2:-1])
        evo_gate = sigmoid(proj_out[..., -1:])

        delta_pre = (
            delta_proj @ self.params["dt_proj.weight"].T + self.params["dt_proj.bias"]
        )
        delta = softplus(delta_pre)

        B = B_re + 1j * B_im
        C = C_re + 1j * C_im

        # Clip exponent for numerical stability
        exponent = delta[..., None] * A[None, :, :]
        exponent_real = np.clip(exponent.real, -20.0, 20.0)
        alpha = np.exp(exponent_real + 1j * exponent.imag).astype(np.complex128)

        current_Bx = (x_conv[..., None] * B[..., None, :]).astype(np.complex128)

        if ssm_state is None:
            ssm_state = np.zeros((batch, c.d_inner, c.d_state), dtype=np.complex128)
        if prev_Bx is None:
            prev_Bx = np.zeros_like(current_Bx)

        beta = (1.0 - lambda_gate[..., None]) * delta[..., None] * alpha
        gamma = lambda_gate[..., None] * delta[..., None] * evo_gate[..., None]

        ssm_state = alpha * ssm_state + beta * prev_Bx + gamma * current_Bx

        y_complex = np.sum(ssm_state * np.conj(C[..., None, :]), axis=-1)
        y = y_complex.real
        y = y + self.params["D"][None, :] * x_conv

        # 4. Gating
        z_act = silu(z)
        gated_y = y * z_act

        # 5. out_proj
        output = gated_y @ self.params["out_proj.weight"].T
        if "out_proj.bias" in self.params:
            output += self.params["out_proj.bias"]

        return output[:, None, :], conv_state, ssm_state, current_Bx

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        """Load parameters from a state dictionary (PyTorch names or direct)"""
        for k, v in state_dict.items():
            # Handle PyTorch's state_dict if it's still a Tensor
            val = v.numpy() if hasattr(v, "numpy") else v

            # Map name
            name = k
            if name.startswith("mamba."):
                name = name[len("mamba.") :]

            if name in self.params:
                # Specialized handling for conv1d weight shape
                if name == "conv1d.weight" and val.ndim == 3:
                    val = val.squeeze(1)

                if self.params[name].shape != val.shape:
                    raise ValueError(
                        f"Shape mismatch for {name}: "
                        f"{self.params[name].shape} vs {val.shape}"
                    )
                self.params[name] = val.copy()

    def backward(
        self, grad_output: np.ndarray
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Full backpropagation through the Mamba architecture"""
        cache = self.cache

        # 5. out_proj backward
        self.grads["out_proj.weight"] = np.einsum(
            "bli,blj->ij", grad_output, cache["gated_y"]
        )
        if "out_proj.bias" in self.params:
            self.grads["out_proj.bias"] = grad_output.sum(axis=(0, 1))

        d_gated_y = grad_output @ self.params["out_proj.weight"]

        # 4. Gating backward
        d_y = d_gated_y * cache["z_act"]
        d_z_act = d_gated_y * cache["y"]
        d_z = silu_backward(cache["z"], d_z_act)

        # 3. SSM backward (Selective Scan BPTT)
        d_x_ssm, d_ssm_params = self.ssm_backward(d_y)
        self.grads.update(d_ssm_params)

        # 2. conv1d backward
        d_x_conv_pre_act = silu_backward(cache["x_conv_pre_act"], d_x_ssm)
        d_x_in, d_conv_weight, d_conv_bias = self.conv1d_backward(d_x_conv_pre_act)
        self.grads["conv1d.weight"] = d_conv_weight
        if d_conv_bias is not None:
            self.grads["conv1d.bias"] = d_conv_bias

        # 1. in_proj backward
        d_xz = np.concatenate([d_x_in, d_z], axis=-1)
        self.grads["in_proj.weight"] = np.einsum("bli,blj->ij", d_xz, cache["x"])
        if "in_proj.bias" in self.params:
            self.grads["in_proj.bias"] = d_xz.sum(axis=(0, 1))

        # d_xz is (B, L, 2 * d_inner)
        # weight is (2 * d_inner, d_model)
        # d_x is (B, L, d_model)
        d_x = d_xz @ self.params["in_proj.weight"]

        return d_x, self.grads

    def conv1d_backward(
        self, d_x_conv: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Depthwise Conv1d backward implementation"""
        c = self.config
        B, L, D = d_x_conv.shape
        x_padded = self.cache["x_padded"]

        d_weight = np.zeros_like(self.params["conv1d.weight"])
        d_x_padded = np.zeros_like(x_padded)
        d_x_conv_t = d_x_conv.transpose(0, 2, 1)

        for i in range(L):
            window = x_padded[:, :, i : i + c.d_conv]
            d_weight += np.sum(d_x_conv_t[:, :, i, None] * window, axis=0)
            d_x_padded[:, :, i : i + c.d_conv] += (
                d_x_conv_t[:, :, i, None] * self.params["conv1d.weight"][None, :, :]
            )

        d_x_in = d_x_padded[:, :, c.d_conv - 1 :].transpose(0, 2, 1)
        d_bias = d_x_conv.sum(axis=(0, 1)) if "conv1d.bias" in self.params else None

        return d_x_in, d_weight, d_bias

    def ssm_backward(self, d_y: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Complete Vectorized BPTT for Selective Scan using Parallel Scan"""
        s_cache = self.cache["ssm"]
        scan = s_cache["scan"]
        B, L, D = d_y.shape

        # Gradient for skip connection D
        d_D = np.sum(d_y * self.cache["x_conv"], axis=(0, 1))
        d_x_input = d_y * self.params["D"][None, None, :]

        # 1. Recover parameters and states
        alphas = scan["alphas"]
        betas = scan["betas"]
        gammas = scan["gammas"]
        current_Bxs = scan["current_Bxs"]
        h_all = scan["h_all"]

        # h_prev[t] is h_{t-1}
        h_prev = np.zeros_like(h_all)
        h_prev[:, 1:] = h_all[:, :-1]

        # p_Bx[t] is current_Bx_{t-1}
        p_Bxs = np.zeros_like(current_Bxs)
        p_Bxs[:, 1:] = current_Bxs[:, :-1]

        # 2. Parallel Backward Scan for dh
        # dh_{t-1} = dy_t * conj(C_t) + alpha_t * dh_t (simplified logic)
        C_complex = s_cache["C"]
        sources = d_y[:, :, :, None] * np.conj(C_complex[:, :, None, :])

        # Reverse Scan
        # dh_t = source_t + alpha_{t+1} * dh_{t+1}
        rev_alphas = np.zeros_like(alphas)
        rev_alphas[:, :-1] = alphas[:, 1:]

        res_dh = sources.copy()
        res_da = rev_alphas.copy()

        step = 1
        while step < L:
            # Backward slice
            A_curr = res_da[:, :-step]
            U_curr = res_dh[:, :-step]
            A_next = res_da[:, step:]
            U_next = res_dh[:, step:]

            res_dh[:, :-step] = A_curr * U_next + U_curr
            res_da[:, :-step] = A_curr * A_next
            step *= 2

        dh_all = res_dh

        # 3. Parameter Gradients
        d_C = np.sum(d_y[:, :, :, None] * np.conj(h_all), axis=2)
        d_alphas = dh_all * np.conj(h_prev)
        d_betas = dh_all * np.conj(p_Bxs)
        d_gammas = dh_all * np.conj(current_Bxs)

        # Map to A, delta, gates
        dt = s_cache["delta"][:, :, :, None]
        A = s_cache["A"][None, None, :, :]
        l_gate = s_cache["lambda_gate"][:, :, :, None]
        e_gate = s_cache["evo_gate"][:, :, :, None]

        d_dt_from_alpha = np.real(np.sum(d_alphas * np.conj(A * alphas), axis=-1))
        d_A_vec = np.sum(np.real(d_alphas * np.conj(dt * alphas)), axis=(0, 1))

        d_l = np.real(np.sum(d_betas * np.conj(-dt * alphas), axis=-1))
        d_dt_from_beta = np.real(
            np.sum(d_betas * np.conj((1 - l_gate) * alphas), axis=-1)
        )
        d_dt_from_beta += np.real(
            np.sum(d_betas * np.conj((1 - l_gate) * dt * A * alphas), axis=-1)
        )
        d_A_vec += np.sum(
            np.real(d_betas * np.conj((1 - l_gate) * dt * dt * A * alphas)), axis=(0, 1)
        )

        d_l += np.real(np.sum(d_gammas * np.conj(dt * e_gate), axis=-1))
        d_dt_from_gamma = np.real(np.sum(d_gammas * np.conj(l_gate * e_gate), axis=-1))
        d_e = np.real(np.sum(d_gammas * np.conj(l_gate * dt), axis=-1))

        d_delta = d_dt_from_alpha + d_dt_from_beta + d_dt_from_gamma
        d_lambda = np.sum(d_l, axis=2, keepdims=True)
        d_evo = np.sum(d_e, axis=2, keepdims=True)

        # d_c_Bx_t = conj(gamma_t)*dh_t + conj(beta_{t+1})*dh_{t+1}
        d_c_Bx = dh_all * np.conj(gammas)
        d_c_Bx[:, :-1] += dh_all[:, 1:] * np.conj(betas[:, 1:])

        d_B = np.sum(np.conj(d_c_Bx) * self.cache["x_conv"][:, :, :, None], axis=2)
        d_x_ssm_core = np.real(
            np.sum(d_c_Bx * np.conj(s_cache["B"][:, :, None, :]), axis=-1)
        )

        # Map to projections
        d_delta_pre = softplus_backward(s_cache["delta_pre_softplus"], d_delta)
        self.grads["dt_proj.weight"] = np.einsum(
            "bli,blj->ij", d_delta_pre, s_cache["delta_proj"]
        )
        self.grads["dt_proj.bias"] = d_delta_pre.sum(axis=(0, 1))
        d_delta_proj = d_delta_pre @ self.params["dt_proj.weight"]

        d_lambda_raw = sigmoid_backward(s_cache["lambda_gate_raw"], d_lambda)
        d_evo_raw = sigmoid_backward(s_cache["evo_gate_raw"], d_evo)

        d_proj_out = np.concatenate(
            [
                d_delta_proj,
                np.real(d_B),
                np.imag(d_B),
                np.real(d_C),
                np.imag(d_C),
                d_lambda_raw,
                d_evo_raw,
            ],
            axis=-1,
        )

        self.grads["x_proj.weight"] = np.einsum(
            "bli,blj->ij", d_proj_out, self.cache["x_conv"]
        )
        self.grads["A_log"] = np.real(d_A_vec * -np.exp(self.params["A_log"]))
        self.grads["A_imag"] = np.imag(d_A_vec)
        self.grads["D"] = d_D

        return d_x_input + d_x_ssm_core, self.grads


class AdamOptimizer:
    """Pure NumPy Adam Optimizer implementation"""

    def __init__(
        self,
        params: dict[str, np.ndarray],
        lr: float = 1e-3,
        betas: tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
    ):
        self.params = params
        self.lr = lr
        self.betas = betas
        self.eps = eps
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}
        self.t = 0

    def step(self, grads: dict[str, np.ndarray]) -> None:
        self.t += 1
        for k in self.params:
            if k not in grads:
                continue
            g = grads[k]
            # Update biased first moment estimate
            self.m[k] = self.betas[0] * self.m[k] + (1 - self.betas[0]) * g
            # Update biased second raw moment estimate
            self.v[k] = self.betas[1] * self.v[k] + (1 - self.betas[1]) * (g**2)

            # Compute bias-corrected first moment estimate
            m_hat = self.m[k] / (1 - self.betas[0] ** self.t)
            # Compute bias-corrected second raw moment estimate
            v_hat = self.v[k] / (1 - self.betas[1] ** self.t)

            # Update parameters
            self.params[k] -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
