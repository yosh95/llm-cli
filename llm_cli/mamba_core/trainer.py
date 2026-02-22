import json
from pathlib import Path
from typing import Any

import tiktoken
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

from .model import MambaLM


class SFTDataset(Dataset):
    def __init__(self, data_path: str, tokenizer: Any, max_length: int = 2048) -> None:
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples: list[dict[str, Any]] = []

        with Path(data_path).open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.samples.append(json.loads(line))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self.samples[idx]
        full_text = ""
        for msg in sample["messages"]:
            role = msg["role"]
            content = msg["content"]
            full_text += f"<|im_start|>{role}\n{content}<|im_end|>\n"

        tokens = self.tokenizer.encode(full_text)
        if len(tokens) > self.max_length:
            tokens = tokens[: self.max_length]

        input_ids = torch.tensor(tokens[:-1], dtype=torch.long)
        labels = torch.tensor(tokens[1:], dtype=torch.long)

        # Masking padding if needed, but here we assume samples are packed or short
        return input_ids, labels


def collate_fn(
    batch: list[tuple[torch.Tensor, torch.Tensor]],
) -> tuple[torch.Tensor, torch.Tensor]:
    input_ids_list = [s[0] for s in batch]
    labels_list = [s[1] for s in batch]

    input_ids = nn.utils.rnn.pad_sequence(
        input_ids_list, batch_first=True, padding_value=0
    )
    labels = nn.utils.rnn.pad_sequence(
        labels_list, batch_first=True, padding_value=-100
    )

    return input_ids, labels


class Trainer:
    def __init__(
        self,
        model: MambaLM,
        train_data_path: str,
        lr: float = 1e-4,
        batch_size: int = 4,
        max_length: int = 2048,
    ) -> None:
        self.model = model
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.dataset = SFTDataset(train_data_path, self.tokenizer, max_length)
        self.dataloader = DataLoader(
            self.dataset, batch_size=batch_size, shuffle=True, collate_fn=collate_fn
        )
        self.optimizer = optim.AdamW(model.parameters(), lr=lr)
        self.criterion = nn.CrossEntropyLoss(ignore_index=-100)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.accumulation_steps = 1

    def train(self, epochs: int = 3) -> None:
        self.model.train()
        for epoch in range(epochs):
            total_loss = 0.0
            self.optimizer.zero_grad()
            num_batches = len(self.dataloader)

            for batch_idx, (input_ids, labels) in enumerate(self.dataloader):
                input_ids = input_ids.to(self.device)
                labels = labels.to(self.device)

                # Check for empty labels
                if (labels != -100).sum() == 0:
                    continue

                logits = self.model(input_ids)

                loss = self.criterion(logits.view(-1, logits.size(-1)), labels.view(-1))

                if torch.isnan(loss) or torch.isinf(loss):
                    print(f"Warning: NaN/Inf loss detected at batch {batch_idx}")
                    continue

                loss = loss / self.accumulation_steps
                loss.backward()

                if (batch_idx + 1) % self.accumulation_steps == 0 or (
                    batch_idx + 1
                ) == num_batches:
                    # Gradient clipping
                    torch.nn.utils.clip_grad_norm_(
                        self.model.parameters(), max_norm=1.0
                    )
                    self.optimizer.step()
                    self.optimizer.zero_grad()

                total_loss += loss.item() * self.accumulation_steps
                if batch_idx % 1 == 0:  # Log every batch since we have few
                    print(
                        f"Epoch {epoch}, Batch {batch_idx}/{num_batches}, "
                        f"Loss: {loss.item() * self.accumulation_steps:.4f}"
                    )

            avg_loss = total_loss / max(1, num_batches)
            print(f"Epoch {epoch} finished. Average Loss: {avg_loss:.4f}")
            self.save_checkpoint(f"checkpoint_epoch_{epoch}.pt")

    def save_checkpoint(self, path: str) -> None:
        torch.save(self.model.state_dict(), path)
        print(f"Saved checkpoint to {path}")
