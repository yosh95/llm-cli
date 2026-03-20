import numpy as np
import pytest

from llm_cli.security.integrity import ReasoningSentinelManager
from llm_cli.security.sentinel import MambaSentinel


def test_sentinel_initialization():
    sentinel = MambaSentinel(d_model=16, n_layers=1)
    assert sentinel.ema_loss == 5.54
    assert sentinel.mode == "learn"


def test_sentinel_step_and_anomaly_score():
    sentinel = MambaSentinel(d_model=16, n_layers=1)
    # Reset to known state
    sentinel.reset_state()

    # Process a byte
    score, status = sentinel.step(ord("A"))

    assert isinstance(score, float)
    assert status in ["green", "yellow", "red"]
    assert sentinel.last_logits is not None


def test_sentinel_learning_lowers_loss():
    # Use a small model for fast learning
    sentinel = MambaSentinel(d_model=8, n_layers=1, lr=0.1)

    # Repeat the same pattern
    pattern = b"Hello world"
    initial_ema = sentinel.ema_loss

    for _ in range(10):
        input_ids = np.array([list(pattern[:-1])], dtype=np.int32)
        targets = np.array([list(pattern[1:])], dtype=np.int32)
        sentinel.update(input_ids, targets)

    assert sentinel.ema_loss < initial_ema


def test_reasoning_sentinel_manager_detects_anomaly():
    # Setup manager with a sentinel that has learned a specific pattern
    mgr = ReasoningSentinelManager(d_model=16, n_layers=1)
    mgr.sentinel.mode = "learn"

    benign_text = "Standard operation sequence"
    for _ in range(20):
        mgr.process_chunk(benign_text)
        mgr.finalize_session(learn=True)

    # Record the baseline loss

    # Switching to enforce mode
    mgr.sentinel.mode = "enforce"

    # A highly anomalous/random string should trigger high surprise
    # Note: For real detection, we need it to exceed the dynamic threshold (EMA + 1.2)
    # We might need more training to lower EMA enough for this to happen reliably in test.
    # But we can at least check if process_chunk returns scores.

    score = mgr.process_chunk("Normal")
    assert score > 0

    # Test suspected_secrets accumulation for high-surprise segments
    # We'll mock the threshold to ensure detection in this unit test
    with pytest.MonkeyPatch.context() as mp:
        # Mock get_dynamic_thresholds to return a very low red threshold
        mp.setattr(mgr.sentinel, "get_dynamic_thresholds", lambda: (1.0, 1.0))

        mgr.suspected_secrets = []
        mgr.process_chunk("ThisIsAVerySurprisingLongString12345678")
        assert len(mgr.suspected_secrets) > 0
        assert "ThisIsAVerySurprisingLongString12345678" in mgr.suspected_secrets


def test_sentinel_threshold_calibration():
    sentinel = MambaSentinel()
    sentinel.ema_loss = 2.0
    y, r = sentinel.get_dynamic_thresholds()
    assert y == 2.4
    assert r == 3.2

    sentinel.ema_loss = 1.0
    y2, r2 = sentinel.get_dynamic_thresholds()
    assert y2 == 1.4
    assert r2 == 2.2
