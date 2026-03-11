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
        bs, L, d_inner = x.shape
        d_state = self.config.d_state

        # Use float128/complex128 for better numerical stability during scan
        h = np.zeros((bs, d_inner, d_state), dtype=np.complex128)
        prev_Bx = np.zeros_like(h)

        hs, prev_Bxs, alphas, betas, gammas, current_Bxs = [], [], [], [], [], []
        ys = []

        for t in range(L):
            dt = delta[:, t, :, None]
            # Clip only the real part of the exponent to prevent numerical explosion
            exponent = dt * A[None, :, :]
            exponent_real = np.clip(exponent.real, -20.0, 20.0)
            exponent = exponent_real + 1j * exponent.imag
            alpha = np.exp(exponent).astype(np.complex128)
            current_Bx = (x[:, t, :, None] * B[:, t, None, :]).astype(np.complex128)

            l_gate = lambda_gate[:, t, :, None]
            e_gate = evo_gate[:, t, :, None]

            beta = (1.0 - l_gate) * dt * alpha
            gamma = l_gate * dt * e_gate

            if training:
                hs.append(h.copy())
                prev_Bxs.append(prev_Bx.copy())
                alphas.append(alpha)
                betas.append(beta)
                gammas.append(gamma)
                current_Bxs.append(current_Bx.copy())

            h = alpha * h + beta * prev_Bx + gamma * current_Bx
            prev_Bx = current_Bx

            y_curr = np.sum(h * np.conj(C[:, t, None, :]), axis=-1)
            ys.append(y_curr.real)

        y = np.stack(ys, axis=1)
        y = y + self.params["D"][None, None, :] * x

        cache = (
            {
                "hs": hs,
                "prev_Bxs": prev_Bxs,
                "alphas": alphas,
                "betas": betas,
                "gammas": gammas,
                "current_Bxs": current_Bxs,
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
        """Complete BPTT (Backpropagation Through Time) for Selective Scan"""
        c = self.config
        s_cache = self.cache["ssm"]
        scan = s_cache["scan"]
        B, L, D = d_y.shape
        N = c.d_state

        # Gradient for skip connection D
        d_D = np.sum(d_y * self.cache["x_conv"], axis=(0, 1))
        d_x_input = d_y * self.params["D"][None, None, :]

        # Initialize gradients for scan parameters
        dh_next = np.zeros((B, D, N), dtype=np.complex128)
        d_B = np.zeros((B, L, N), dtype=np.complex128)
        d_C = np.zeros((B, L, N), dtype=np.complex128)
        d_A = np.zeros((D, N), dtype=np.complex128)
        d_delta = np.zeros((B, L, D), dtype=np.float64)
        d_lambda = np.zeros((B, L, 1), dtype=np.float64)
        d_evo = np.zeros((B, L, 1), dtype=np.float64)
        d_x_ssm_core = np.zeros((B, L, D), dtype=np.float64)

        # Gradient from next step's beta path
        d_curr_Bx_next = np.zeros((B, D, N), dtype=np.complex128)

        # Reverse loop over sequence
        for t in reversed(range(L)):
            C_t = s_cache["C"][:, t, None, :]

            # Use cached state from forward pass
            alpha = scan["alphas"][t]
            beta = scan["betas"][t]
            gamma = scan["gammas"][t]
            h_prev = scan["hs"][t]
            p_Bx = scan["prev_Bxs"][t]
            c_Bx = scan["current_Bxs"][t]
            h_curr = alpha * h_prev + beta * p_Bx + gamma * c_Bx

            # Gradient of output y_t wrt state h_curr
            # dy/dh = conj(C)
            dh_t = dh_next + np.sum(
                d_y[:, t, :, None, None] * np.conj(C_t[:, :, :, None]), axis=-1
            )

            # Gradient of y_t wrt C_t
            d_C[:, t, :] = np.sum(d_y[:, t, :, None] * np.conj(h_curr), axis=1)

            # Gradient wrt alpha, beta, gamma
            d_alpha = dh_t * np.conj(h_prev)
            d_beta = dh_t * np.conj(p_Bx)
            d_gamma = dh_t * np.conj(c_Bx)

            # Discretization parameters: delta and A
            dt = s_cache["delta"][:, t, :, None]
            A = s_cache["A"][None, :, :]
            l_gate = s_cache["lambda_gate"][:, t, :, None]
            e_gate = s_cache["evo_gate"][:, t, :, None]

            # alpha = exp(dt * A)
            # dL/d(dt) += dL/d_alpha * d_alpha/d_dt
            d_dt_from_alpha = np.real(np.sum(d_alpha * np.conj(A * alpha), axis=-1))
            d_A += np.sum(np.real(d_alpha * np.conj(dt * alpha)), axis=0)

            # beta = (1 - lambda) * dt * alpha
            d_l = np.real(np.sum(d_beta * np.conj(-dt * alpha), axis=-1))
            d_dt_from_beta = np.real(
                np.sum(d_beta * np.conj((1 - l_gate) * alpha), axis=-1)
            )
            # (Note: beta also depends on alpha, which depends on dt and A)
            d_dt_from_beta += np.real(
                np.sum(d_beta * np.conj((1 - l_gate) * dt * A * alpha), axis=-1)
            )
            d_A += np.sum(
                np.real(d_beta * np.conj((1 - l_gate) * dt * dt * A * alpha)), axis=0
            )  # simplified

            # gamma = lambda * dt * evo
            d_l += np.real(np.sum(d_gamma * np.conj(dt * e_gate), axis=-1))
            d_dt_from_gamma = np.real(
                np.sum(d_gamma * np.conj(l_gate * e_gate), axis=-1)
            )
            d_e = np.real(np.sum(d_gamma * np.conj(l_gate * dt), axis=-1))

            # Accumulate delta and gate grads
            d_delta[:, t, :] = d_dt_from_alpha + d_dt_from_beta + d_dt_from_gamma
            d_lambda[:, t, 0] = np.sum(d_l, axis=1)
            d_evo[:, t, 0] = np.sum(d_e, axis=1)

            # Input paths: current_Bx = x_t * B_t
            d_c_Bx = d_gamma * np.conj(gamma) + d_curr_Bx_next
            d_B[:, t, :] = np.sum(
                np.conj(d_c_Bx) * self.cache["x_conv"][:, t, :, None], axis=1
            )
            d_x_ssm_core[:, t, :] = np.real(
                np.sum(d_c_Bx * np.conj(s_cache["B"][:, t, None, :]), axis=-1)
            )

            # Gradients for the next iteration (t-1)
            dh_next = dh_t * alpha
            d_curr_Bx_next = d_beta * np.conj(beta)

        # 4. Map back to projections x_proj and dt_proj
        d_delta_pre = softplus_backward(s_cache["delta_pre_softplus"], d_delta)
        self.grads["dt_proj.weight"] = np.einsum(
            "bli,blj->ij", d_delta_pre, s_cache["delta_proj"]
        )
        self.grads["dt_proj.bias"] = d_delta_pre.sum(axis=(0, 1))
        d_delta_proj = d_delta_pre @ self.params["dt_proj.weight"]

        d_lambda_raw = sigmoid_backward(s_cache["lambda_gate_raw"], d_lambda)
        d_evo_raw = sigmoid_backward(s_cache["evo_gate_raw"], d_evo)

        # Concatenate all projected gradients to map back to x_proj.weight
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

        # Complex A grads
        self.grads["A_log"] = np.real(d_A * -np.exp(self.params["A_log"]))
        self.grads["A_imag"] = np.imag(d_A)
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
