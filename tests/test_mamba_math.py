import numpy as np
import pytest

from llm_cli.mamba_core.mamba_numpy import MambaConfig, MambaNumpy
from llm_cli.mamba_core.utils import NumPyLinear, NumPyRMSNorm


def numerical_gradient(f, x, eps=1e-6):
    """
    Computes numerical gradient of function f at x using finite differences.
    """
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"], op_flags=["readwrite"])
    while not it.finished:
        ix = it.multi_index
        old_val = x[ix]

        x[ix] = old_val + eps
        pos = f(x).copy()

        x[ix] = old_val - eps
        neg = f(x).copy()

        grad[ix] = np.sum(pos - neg) / (2 * eps)
        x[ix] = old_val
        it.iternext()
    return grad


class TestMambaMathConsistency:
    def test_rms_norm_gradient(self):
        """Verify RMSNorm analytical gradient against numerical gradient."""
        dim = 8
        norm = NumPyRMSNorm(dim)
        x = np.random.randn(2, 4, dim).astype(np.float64)

        # Forward pass to cache values
        _ = norm.forward(x)

        # We want to check gradient wrt x
        # Let loss L = sum(norm.forward(x)^2)
        def func(x_in):
            return 0.5 * np.sum(norm.forward(x_in) ** 2)

        # Analytical gradient
        out = norm.forward(x)
        grad_out = out  # dL/dout = out
        grad_x_analytical = norm.backward(grad_out)

        # Numerical gradient
        grad_x_numerical = numerical_gradient(func, x)

        np.testing.assert_allclose(
            grad_x_analytical, grad_x_numerical, rtol=1e-5, atol=1e-5
        )

    def test_linear_gradient(self):
        """Verify Linear layer analytical gradient against numerical gradient."""
        in_dim, out_dim = 4, 6
        layer = NumPyLinear(in_dim, out_dim, bias=True)
        x = np.random.randn(2, in_dim).astype(np.float64)

        def func(x_in):
            layer.cache["x"] = x_in
            out = x_in @ layer.weight.T + layer.bias
            return 0.5 * np.sum(out**2)

        # Analytical
        out = layer.forward(x)
        grad_out = out
        grad_x_analytical = layer.backward(grad_out)

        # Numerical
        grad_x_numerical = numerical_gradient(func, x)

        np.testing.assert_allclose(
            grad_x_analytical, grad_x_numerical, rtol=1e-5, atol=1e-5
        )

        # Check weight gradient
        def func_w(w_in):
            old_w = layer.weight
            layer.weight = w_in
            out = x @ layer.weight.T + layer.bias
            res = 0.5 * np.sum(out**2)
            layer.weight = old_w
            return res

        grad_w_numerical = numerical_gradient(func_w, layer.weight.copy())
        np.testing.assert_allclose(
            layer.grad_weight, grad_w_numerical, rtol=1e-5, atol=1e-5
        )

    def test_mamba_numpy_forward_step_equivalence(self):
        """
        Critical test: Ensure that the parallel 'forward' pass matches
        the recurrent 'step' pass for the same input.
        """
        config = MambaConfig(d_model=16, d_state=8, d_conv=3, expand=2, n_heads=2)
        mamba = MambaNumpy(config)

        # Input sequence (Batch=1, Length=5, Dim=16)
        L = 5
        x = np.random.randn(1, L, config.d_model).astype(np.float64)

        # Parallel forward
        y_forward = mamba.forward(x, training=False)

        # Sequential step
        y_steps = []
        conv_state = None
        ssm_state = None
        prev_Bx = None

        for i in range(L):
            x_step = x[:, i : i + 1, :]
            out_step, conv_state, ssm_state, prev_Bx = mamba.step(
                x_step, conv_state, ssm_state, prev_Bx
            )
            y_steps.append(out_step)

        y_step_concat = np.concatenate(y_steps, axis=1)

        # They should be identical
        np.testing.assert_allclose(y_forward, y_step_concat, rtol=1e-6, atol=1e-6)

    @pytest.mark.slow
    def test_mamba_numpy_gradient_check(self):
        """
        Verify MambaNumpy's full backward pass using numerical gradients.
        This ensures the complex MIMO SSM gradient logic is correct.
        """
        config = MambaConfig(d_model=8, d_state=4, d_conv=2, expand=1, n_heads=2)
        mamba = MambaNumpy(config)

        B, L = 1, 3
        x = np.random.randn(B, L, config.d_model).astype(np.float64)

        def func(x_in):
            out = mamba.forward(x_in, training=True)
            return 0.5 * np.sum(out**2)

        # Analytical
        y = mamba.forward(x, training=True)
        grad_y = y
        grad_x_analytical, _ = mamba.backward(grad_y)

        # Numerical
        grad_x_numerical = numerical_gradient(func, x)

        # We expect some numerical noise due to complex operations and scans,
        # but it should be relatively close.
        np.testing.assert_allclose(
            grad_x_analytical, grad_x_numerical, rtol=1e-4, atol=1e-4
        )

    def test_mamba_numpy_parameter_gradients(self):
        """Check gradients for specific Mamba parameters (A_log, D, etc.)"""
        config = MambaConfig(d_model=8, d_state=4, d_conv=2, expand=1, n_heads=1)
        mamba = MambaNumpy(config)

        B, L = 1, 2
        x = np.random.randn(B, L, config.d_model).astype(np.float64)

        # Target: Gradient of A_log
        def func_alog(alog_in):
            old_alog = mamba.params["A_log"]
            mamba.params["A_log"] = alog_in
            out = mamba.forward(x, training=True)
            res = 0.5 * np.sum(out**2)
            mamba.params["A_log"] = old_alog
            return res

        mamba.forward(x, training=True)
        mamba.backward(mamba.cache["y"])  # dummy backward to populate grads

        # Re-run backward with proper grad_output
        y = mamba.forward(x, training=True)
        mamba.backward(y)

        grad_alog_analytical = mamba.grads["A_log"]
        grad_alog_numerical = numerical_gradient(
            func_alog, mamba.params["A_log"].copy()
        )

        np.testing.assert_allclose(
            grad_alog_analytical, grad_alog_numerical, rtol=1e-4, atol=1e-4
        )
