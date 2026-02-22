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
    data_path = "mamba_distill_data.jsonl"
    from pathlib import Path

    if not Path(data_path).exists():
        print(f"Error: Training data not found at {data_path}")
        print("Please run 'python -m llm_cli.mamba_core.collect_data' first.")
        return

    print(f"Starting training on {data_path}...")
    trainer = Trainer(
        model=model,
        train_data_path=data_path,
        lr=2e-4,  # Slightly higher LR for smaller model
        batch_size=1,  # Reduced from 4
        max_length=512,  # Reduced from 2048
    )

    # Enable gradient accumulation (effective batch size = 4)
    trainer.accumulation_steps = 4
    trainer.train(epochs=10)

    # Final save for the client
    torch.save(model.state_dict(), "mamba_model.pt")
    print("Training complete. Model saved as mamba_model.pt")


if __name__ == "__main__":
    main()
