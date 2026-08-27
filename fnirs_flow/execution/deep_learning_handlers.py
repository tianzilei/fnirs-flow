"""PyTorch implementations for deep-learning MethodAtoms.

These handlers deliberately require explicit ``X`` and (for supervised
models) ``y`` inputs.  They build and train real models; no catalogue atom is
reported as executed merely because a class can be instantiated.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fnirs_flow.execution.operations import CallableOperationHandler, OperationContext, OperationSpec

DEEP_LEARNING_OPERATIONS = frozenset(
    {
        "cnn",
        "lstm",
        "transformer",
        "1d_cnn_classification",
        "2d_cnn_classification",
        "eegnet_classification",
        "shallow_convnet_classification",
        "lstm_classification",
        "gru_classification",
        "bidirectional_lstm_classification",
        "transformer_classification",
        "temporal_transformer_classification",
        "cnn_lstm_hybrid_classification",
        "cnn_transformer_hybrid_classification",
        "vae_representation",
        "transfer_learning",
        "dl_short_channel_prediction",
    }
)


def _execute(operation: str, context: OperationContext) -> dict[str, Any]:
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        raise ImportError("Deep-learning MethodAtoms require fnirs-flow[deep-learning]") from None

    p = {k: v for k, v in context.parameters.items() if not k.startswith("_")}
    X = np.asarray(p.get("X", context.raw), dtype=np.float32)
    if X.ndim == 2:
        X = X[:, None, :]
    if X.ndim not in {3, 4}:
        raise ValueError(f"{operation} expects X with samples×channels×time (or image) dimensions")
    epochs = int(p.get("epochs", 1))
    hidden = int(p.get("hidden_size", 16))

    if operation == "vae_representation":
        flat = X.reshape(X.shape[0], -1)
        latent = int(p.get("latent_dim", min(8, flat.shape[1])))
        encoder = nn.Sequential(nn.Linear(flat.shape[1], hidden), nn.ReLU(), nn.Linear(hidden, latent))
        decoder = nn.Sequential(nn.Linear(latent, hidden), nn.ReLU(), nn.Linear(hidden, flat.shape[1]))
        tx = torch.tensor(flat)
        optimizer = torch.optim.Adam(
            [*encoder.parameters(), *decoder.parameters()], lr=float(p.get("learning_rate", 1e-3))
        )
        loss_value = 0.0
        for _ in range(epochs):
            optimizer.zero_grad()
            z = encoder(tx)
            reconstructed = decoder(z)
            loss = nn.functional.mse_loss(reconstructed, tx)
            loss.backward()
            optimizer.step()
            loss_value = float(loss.detach())
        return {"embedding": encoder(tx).detach().numpy(), "loss": loss_value, "model": "autoencoder"}

    y_value = p.get("y")
    if y_value is None:
        raise ValueError(f"{operation} requires y labels")
    y = np.asarray(y_value, dtype=np.int64)
    classes = int(np.unique(y).size)
    channels = X.shape[1]

    if "lstm" in operation or "gru" in operation:
        recurrent = (
            nn.GRU(channels, hidden, batch_first=True)
            if "gru" in operation
            else nn.LSTM(channels, hidden, batch_first=True, bidirectional="bidirectional" in operation)
        )
        width = hidden * (2 if "bidirectional" in operation else 1)

        class RecurrentClassifier(nn.Module):
            def __init__(self):
                super().__init__()
                self.rnn = recurrent
                self.fc = nn.Linear(width, classes)

            def forward(self, x):
                out, _ = self.rnn(x.transpose(1, 2))
                return self.fc(out[:, -1])

        model: Any = RecurrentClassifier()
    elif "transformer" in operation:
        heads = int(p.get("n_heads", 1))
        transformer_encoder = nn.TransformerEncoderLayer(channels, heads, hidden, batch_first=True)

        class TransformerClassifier(nn.Module):
            def __init__(self):
                super().__init__()
                self.enc = transformer_encoder
                self.fc = nn.Linear(channels, classes)

            def forward(self, x):
                return self.fc(self.enc(x.transpose(1, 2)).mean(1))

        model = TransformerClassifier()
    else:
        model = nn.Sequential(
            nn.Conv1d(channels, hidden, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(hidden, classes),
        )

    dataset = TensorDataset(torch.tensor(X), torch.tensor(y))
    loader = DataLoader(dataset, batch_size=min(int(p.get("batch_size", 16)), len(dataset)), shuffle=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(p.get("learning_rate", 1e-3)))
    loss_value = 0.0
    model.train()
    for _ in range(epochs):
        for bx, by in loader:
            optimizer.zero_grad()
            logits = model(bx)
            loss = nn.functional.cross_entropy(logits, by)
            loss.backward()
            optimizer.step()
            loss_value = float(loss.detach())
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X))
        predictions = logits.argmax(1).numpy()
    return {
        "model": type(model).__name__,
        "loss": loss_value,
        "predictions": predictions,
        "accuracy": float(np.mean(predictions == y)),
    }


def deep_learning_handler_factory(spec: OperationSpec) -> CallableOperationHandler:
    return CallableOperationHandler(spec, lambda context: _execute(spec.operation_id, context))
