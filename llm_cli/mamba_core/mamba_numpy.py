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
        n_heads: int = 8,  # Mamba-3: Number of heads for MIMO
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
        self.n_heads = n_heads
        self.dt_min = dt_min
        self.dt_max = dt_max
        self.dt_scale = dt_scale
        self.dt_init_floor = dt_init_floor
        self.bias = bias
        self.conv_bias = conv_bias
        self.d_inner = expand * d_model
        self.head_dim = self.d_inner // n_heads
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

        # x_proj (Mamba-3: MIMO projections for B, C and gates)
        out_dim = c.dt_rank + (2 * 2 * c.d_state * c.n_heads) + (2 * c.n_heads)
        self.params["x_proj.weight"] = (
            rng.standard_normal((out_dim, c.d_inner), dtype=dtype_real) * 0.02
        )

        # dt_proj
        self.params["dt_proj.weight"] = (
            rng.standard_normal((c.d_inner, c.dt_rank), dtype=dtype_real) * 0.02
        )
        self.params["dt_proj.bias"] = (
            rng.standard_normal(c.d_inner, dtype=dtype_real) * 0.02
        )

        # Complex A parameters (one per head per state)
        A_real = np.arange(1, c.d_state + 1, dtype=dtype_real)
        self.params["A_log"] = np.log(A_real)[None, :].repeat(c.n_heads, axis=0)
        self.params["A_imag"] = np.pi * rng.random(
            (c.n_heads, c.d_state), dtype=dtype_real
        )

        # D parameter
        self.params["D"] = np.ones(c.d_inner, dtype=dtype_real)

        # out_proj
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
        x_t = x_in.transpose(0, 2, 1)
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

        # 3. SSM (Mamba-3 MIMO version)
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

        offset = 0
        delta_proj = proj_out[..., offset : offset + c.dt_rank]
        offset += c.dt_rank
        B_re = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            B, L, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        B_im = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            B, L, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        C_re = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            B, L, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        C_im = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            B, L, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        lambda_gate_raw = proj_out[..., offset : offset + c.n_heads].reshape(
            B, L, c.n_heads, 1
        )
        offset += c.n_heads
        evo_gate_raw = proj_out[..., offset : offset + c.n_heads].reshape(
            B, L, c.n_heads, 1
        )
        offset += c.n_heads

        lambda_gate = sigmoid(lambda_gate_raw)
        evo_gate = sigmoid(evo_gate_raw)

        delta_pre = (
            delta_proj @ self.params["dt_proj.weight"].T + self.params["dt_proj.bias"]
        )
        delta = softplus(delta_pre).reshape(B, L, c.n_heads, c.head_dim)

        B_complex = B_re + 1j * B_im
        C_complex = C_re + 1j * C_im
        x_mimo = x.reshape(B, L, c.n_heads, c.head_dim)

        y, scan_cache = self.selective_scan_mimo(
            x_mimo,
            delta,
            A,
            B_complex,
            C_complex,
            lambda_gate,
            evo_gate,
            training=training,
        )

        y = y.reshape(B, L, D_inner)
        y = y + self.params["D"][None, None, :] * x

        ssm_cache = {
            "proj_out": proj_out,
            "delta": delta,
            "delta_pre": delta_pre,
            "A": A,
            "B": B_complex,
            "C": C_complex,
            "lambda_gate": lambda_gate,
            "evo_gate": evo_gate,
            "lambda_gate_raw": lambda_gate_raw,
            "evo_gate_raw": evo_gate_raw,
            "scan": scan_cache,
            "x_mimo": x_mimo,
        }
        return y, ssm_cache

    def selective_scan_mimo(
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
        B_size, L, H, head_dim = x.shape

        exponent = delta[:, :, :, :, None] * A[None, None, :, None, :]
        exponent_real = np.clip(exponent.real, -20.0, 20.0)
        alphas = np.exp(exponent_real + 1j * exponent.imag).astype(np.complex128)

        current_Bxs = (x[:, :, :, :, None] * B[:, :, :, None, :]).astype(np.complex128)
        l_gate = lambda_gate[:, :, :, :, None]
        e_gate = evo_gate[:, :, :, :, None]

        betas = (1.0 - l_gate) * delta[:, :, :, :, None] * alphas
        gammas = l_gate * delta[:, :, :, :, None] * e_gate

        us = gammas * current_Bxs
        us[:, 1:] += betas[:, 1:] * current_Bxs[:, :-1]

        res_A = alphas.copy()
        res_U = us.copy()
        step = 1
        while step < L:
            A_t = res_A[:, step:]
            U_t = res_U[:, step:]
            A_prev = res_A[:, :-step]
            U_prev = res_U[:, :-step]
            res_U[:, step:] = A_t * U_prev + U_t
            res_A[:, step:] = A_t * A_prev
            step *= 2

        h_all = res_U
        y = np.sum(h_all * np.conj(C[:, :, :, None, :]), axis=-1).real

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
        batch = x.shape[0]
        c = self.config

        xz = x @ self.params["in_proj.weight"].T
        if "in_proj.bias" in self.params:
            xz += self.params["in_proj.bias"]
        x_in, z = np.split(xz, 2, axis=-1)
        x_in = x_in.squeeze(1)
        z = z.squeeze(1)

        if conv_state is None:
            conv_state = np.zeros((batch, c.d_inner, c.d_conv))
        conv_state = np.roll(conv_state, shift=-1, axis=-1)
        conv_state[:, :, -1] = x_in
        x_conv = np.sum(conv_state * self.params["conv1d.weight"][None, :, :], axis=2)
        if c.conv_bias:
            x_conv += self.params["conv1d.bias"]
        x_conv = silu(x_conv)

        A = -np.exp(self.params["A_log"]) + 1j * self.params["A_imag"]
        proj_out = x_conv @ self.params["x_proj.weight"].T

        offset = 0
        delta_proj = proj_out[..., offset : offset + c.dt_rank]
        offset += c.dt_rank
        B_re = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            batch, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        B_im = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            batch, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        C_re = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            batch, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        C_im = proj_out[..., offset : offset + c.n_heads * c.d_state].reshape(
            batch, c.n_heads, c.d_state
        )
        offset += c.n_heads * c.d_state
        lambda_gate = sigmoid(proj_out[..., offset : offset + c.n_heads]).reshape(
            batch, c.n_heads, 1
        )
        offset += c.n_heads
        evo_gate = sigmoid(proj_out[..., offset : offset + c.n_heads]).reshape(
            batch, c.n_heads, 1
        )
        offset += c.n_heads

        delta = softplus(
            delta_proj @ self.params["dt_proj.weight"].T + self.params["dt_proj.bias"]
        ).reshape(batch, c.n_heads, c.head_dim)

        B_c = B_re + 1j * B_im
        C_c = C_re + 1j * C_im
        x_mimo = x_conv.reshape(batch, c.n_heads, c.head_dim)

        exponent = delta[..., None] * A[None, :, None, :]
        alpha = np.exp(np.clip(exponent.real, -20, 20) + 1j * exponent.imag)
        current_Bx = (x_mimo[..., None] * B_c[:, :, None, :]).astype(np.complex128)

        if ssm_state is None:
            ssm_state = np.zeros(
                (batch, c.n_heads, c.head_dim, c.d_state), dtype=np.complex128
            )
        if prev_Bx is None:
            prev_Bx = np.zeros_like(current_Bx)

        beta = (1.0 - lambda_gate[..., None]) * delta[..., None] * alpha
        gamma = lambda_gate[..., None] * delta[..., None] * evo_gate[..., None]

        ssm_state = alpha * ssm_state + beta * prev_Bx + gamma * current_Bx
        y_mimo = np.sum(ssm_state * np.conj(C_c[:, :, None, :]), axis=-1).real
        y = y_mimo.reshape(batch, c.d_inner) + self.params["D"][None, :] * x_conv

        output = (y * silu(z)) @ self.params["out_proj.weight"].T
        if "out_proj.bias" in self.params:
            output += self.params["out_proj.bias"]

        return output[:, None, :], conv_state, ssm_state, current_Bx

    def backward(
        self, grad_output: np.ndarray
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Mamba-3 Backward Pass"""
        cache = self.cache

        self.grads["out_proj.weight"] = np.einsum(
            "bli,blj->ij", grad_output, cache["gated_y"]
        )
        if "out_proj.bias" in self.params:
            self.grads["out_proj.bias"] = grad_output.sum(axis=(0, 1))

        d_gated_y = grad_output @ self.params["out_proj.weight"]
        d_y = d_gated_y * cache["z_act"]
        d_z_act = d_gated_y * cache["y"]
        d_z = silu_backward(cache["z"], d_z_act)

        d_x_ssm, d_ssm_params = self.ssm_backward(d_y)
        self.grads.update(d_ssm_params)

        d_x_conv_pre_act = silu_backward(cache["x_conv_pre_act"], d_x_ssm)
        d_x_in, d_conv_weight, d_conv_bias = self.conv1d_backward(d_x_conv_pre_act)
        self.grads["conv1d.weight"] = d_conv_weight
        if d_conv_bias is not None:
            self.grads["conv1d.bias"] = d_conv_bias

        d_xz = np.concatenate([d_x_in, d_z], axis=-1)
        self.grads["in_proj.weight"] = np.einsum("bli,blj->ij", d_xz, cache["x"])
        if "in_proj.bias" in self.params:
            self.grads["in_proj.bias"] = d_xz.sum(axis=(0, 1))

        d_x = d_xz @ self.params["in_proj.weight"]
        return d_x, self.grads

    def conv1d_backward(
        self, d_x_conv: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
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
        """Mamba-3 MIMO BPTT using Parallel Reverse Scan"""
        s_cache = self.cache["ssm"]
        scan = s_cache["scan"]
        B, L, D_inner = d_y.shape
        c = self.config
        H = c.n_heads
        head_dim = c.head_dim

        d_D = np.sum(d_y * self.cache["x_conv"], axis=(0, 1))
        d_x_input = d_y * self.params["D"][None, None, :]

        alphas = scan["alphas"]
        betas = scan["betas"]
        gammas = scan["gammas"]
        current_Bxs = scan["current_Bxs"]
        h_all = scan["h_all"]

        h_prev = np.zeros_like(h_all)
        h_prev[:, 1:] = h_all[:, :-1]
        p_Bxs = np.zeros_like(current_Bxs)
        p_Bxs[:, 1:] = current_Bxs[:, :-1]

        C_complex = s_cache["C"]
        sources = d_y.reshape(B, L, H, head_dim)[:, :, :, :, None] * np.conj(
            C_complex[:, :, :, None, :]
        )

        rev_alphas = np.zeros_like(alphas)
        rev_alphas[:, :-1] = alphas[:, 1:]
        res_dh = sources.copy()
        res_da = rev_alphas.copy()

        step = 1
        while step < L:
            A_curr = res_da[:, :-step]
            U_curr = res_dh[:, :-step]
            A_next = res_da[:, step:]
            U_next = res_dh[:, step:]
            res_dh[:, :-step] = A_curr * U_next + U_curr
            res_da[:, :-step] = A_curr * A_next
            step *= 2
        dh_all = res_dh

        d_C = np.sum(
            d_y.reshape(B, L, H, head_dim)[:, :, :, :, None] * np.conj(h_all), axis=3
        )
        d_alphas = dh_all * np.conj(h_prev)
        d_betas = dh_all * np.conj(p_Bxs)
        d_gammas = dh_all * np.conj(current_Bxs)

        dt = s_cache["delta"][:, :, :, :, None]
        A = s_cache["A"][None, None, :, None, :]
        l_gate = s_cache["lambda_gate"][:, :, :, :, None]
        e_gate = s_cache["evo_gate"][:, :, :, :, None]

        d_dt = np.real(np.sum(d_alphas * np.conj(A * alphas), axis=-1))
        d_A_vec = np.sum(np.real(d_alphas * np.conj(dt * alphas)), axis=(0, 1, 3))

        d_l = np.real(np.sum(d_betas * np.conj(-dt * alphas), axis=-1))
        d_dt += np.real(np.sum(d_betas * np.conj((1 - l_gate) * alphas), axis=-1))
        d_dt += np.real(
            np.sum(d_betas * np.conj((1 - l_gate) * dt * A * alphas), axis=-1)
        )
        d_A_vec += np.sum(
            np.real(d_betas * np.conj((1 - l_gate) * dt * dt * A * alphas)),
            axis=(0, 1, 3),
        )

        d_l += np.real(np.sum(d_gammas * np.conj(dt * e_gate), axis=-1))
        d_dt += np.real(np.sum(d_gammas * np.conj(l_gate * e_gate), axis=-1))
        d_e = np.real(np.sum(d_gammas * np.conj(l_gate * dt), axis=-1))

        d_c_Bx = dh_all * np.conj(gammas)
        d_c_Bx[:, :-1] += dh_all[:, 1:] * np.conj(betas[:, 1:])

        d_x_mimo = np.real(
            np.sum(d_c_Bx * np.conj(s_cache["B"][:, :, :, None, :]), axis=-1)
        )
        d_B = np.sum(np.conj(d_c_Bx) * s_cache["x_mimo"][:, :, :, :, None], axis=3)

        d_delta_pre = softplus_backward(
            s_cache["delta_pre"], d_dt.reshape(B, L, D_inner)
        )
        self.grads["dt_proj.weight"] = np.einsum(
            "bli,blj->ij", d_delta_pre, s_cache["proj_out"][..., : c.dt_rank]
        )
        self.grads["dt_proj.bias"] = d_delta_pre.sum(axis=(0, 1))
        d_dt_proj = d_delta_pre @ self.params["dt_proj.weight"]

        d_l_raw = sigmoid_backward(
            s_cache["lambda_gate_raw"], d_l.sum(axis=3, keepdims=True)
        )
        d_e_raw = sigmoid_backward(
            s_cache["evo_gate_raw"], d_e.sum(axis=3, keepdims=True)
        )

        d_proj_out = np.concatenate(
            [
                d_dt_proj,
                np.real(d_B).reshape(B, L, -1),
                np.imag(d_B).reshape(B, L, -1),
                np.real(d_C).reshape(B, L, -1),
                np.imag(d_C).reshape(B, L, -1),
                d_l_raw.reshape(B, L, -1),
                d_e_raw.reshape(B, L, -1),
            ],
            axis=-1,
        )

        self.grads["x_proj.weight"] = np.einsum(
            "bli,blj->ij", d_proj_out, self.cache["x_conv"]
        )
        self.grads["A_log"] = np.real(d_A_vec * -np.exp(self.params["A_log"]))
        self.grads["A_imag"] = np.imag(d_A_vec)
        self.grads["D"] = d_D

        return d_x_input + d_x_mimo.reshape(B, L, D_inner), self.grads

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        """Load parameters from a state dictionary (PyTorch names or direct)"""
        for k, v in state_dict.items():
            val = v.numpy() if hasattr(v, "numpy") else v
            name = k
            if name.startswith("mamba."):
                name = name[len("mamba.") :]

            if name in self.params:
                if name == "conv1d.weight" and val.ndim == 3:
                    val = val.squeeze(1)
                if self.params[name].shape != val.shape:
                    raise ValueError(
                        f"Shape mismatch for {name}: "
                        f"{self.params[name].shape} vs {val.shape}"
                    )
                self.params[name] = val.copy()


class AdamOptimizer:
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
            self.m[k] = self.betas[0] * self.m[k] + (1 - self.betas[0]) * g
            self.v[k] = self.betas[1] * self.v[k] + (1 - self.betas[1]) * (g**2)
            m_hat = self.m[k] / (1 - self.betas[0] ** self.t)
            v_hat = self.v[k] / (1 - self.betas[1] ** self.t)
            self.params[k] -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
