import tiktoken
import torch

from llm_cli.clients.config import get_setting
from llm_cli.mamba_core.model import MambaLM
from llm_cli.mamba_core.trainer import Trainer


def main() -> None:
    # Model parameters (Adjusted for memory efficiency)
    tokenizer = tiktoken.get_encoding("o200k_base")
    vocab_size = tokenizer.n_vocab
    d_model = get_setting("d_model", "mamba") or 128
    n_layers = get_setting("n_layers", "mamba") or 4

    print(
        f"Initializing MambaLM with vocab_size={vocab_size}, "
        f"d_model={d_model}, n_layers={n_layers}"
    )
    model = MambaLM(vocab_size=vocab_size, d_model=d_model, n_layers=n_layers)

    # Check for existing data
    from pathlib import Path

    from llm_cli.consts import DISTILL_DATA_PATH, MAMBA_MODEL_PATH

    data_path_setting = get_setting("train_data_path", "mamba")
    data_path = Path(data_path_setting) if data_path_setting else DISTILL_DATA_PATH

    if not data_path.exists():
        print(f"Error: Training data not found at {data_path}")
        print(
            "Please ensure data has been collected (e.g., via daily use "
            "or collect_data.py)."
        )
        return

    print(f"Starting training on {data_path}...")

    # Load training params from config
    lr = float(get_setting("learning_rate", "mamba") or 2e-4)
    batch_size = int(get_setting("batch_size", "mamba") or 1)
    max_length = int(get_setting("max_length", "mamba") or 512)
    accumulation_steps = int(get_setting("accumulation_steps", "mamba") or 4)
    epochs = int(get_setting("epochs", "mamba") or 10)

    trainer = Trainer(
        model=model,
        train_data_path=str(data_path),
        lr=lr,
        batch_size=batch_size,
        max_length=max_length,
    )

    # Enable gradient accumulation
    trainer.accumulation_steps = accumulation_steps
    trainer.train(epochs=epochs)

    # Final save for the client
    model_path_setting = get_setting("model_path", "mamba")
    model_path = Path(model_path_setting) if model_path_setting else MAMBA_MODEL_PATH
    torch.save(model.state_dict(), model_path)
    print(f"Training complete. Model saved as {model_path}")


if __name__ == "__main__":
    main()
