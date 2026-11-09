"""One multilingual transformer that reads every sentence of an article.

Each sentence gets location and impact scores. The article's event scores come from the average of
its sentences, so all three tasks train from the same encoder.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from training.reports.data import LABELS, Article
from training.reports.scores import Outputs

NAME = "xlm-roberta-base"
MAX_TOKENS = 64


class ReportModel(nn.Module):
    def __init__(self, name: str = NAME) -> None:
        from transformers import AutoModel

        super().__init__()
        self.encoder = AutoModel.from_pretrained(name)
        size = self.encoder.config.hidden_size
        self.drop = nn.Dropout(0.1)
        self.sentence_head = nn.Linear(size, 2)
        self.event_head = nn.Linear(size, len(LABELS))

    def forward(self, input_ids, attention_mask, owners, articles: int):
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        first = self.drop(hidden[:, 0])
        total = torch.zeros(articles, first.shape[1], dtype=first.dtype, device=first.device)
        total = total.index_add(0, owners, first)
        count = torch.bincount(owners, minlength=articles).clamp(min=1).unsqueeze(1)
        return self.event_head(total / count), self.sentence_head(first)


def tokenize(tokenizer, articles: list[Article], device):
    texts = [s for article in articles for s in article.sentences]
    owners = [i for i, article in enumerate(articles) for _ in article.sentences]
    batch = tokenizer(
        texts, padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt"
    )
    return (
        batch["input_ids"].to(device),
        batch["attention_mask"].to(device),
        torch.tensor(owners, device=device),
    )


@torch.no_grad()
def predict(model, tokenizer, articles: list[Article], device, batch: int = 4) -> Outputs:
    model.eval()
    events, sentences = [], []
    order = sorted(range(len(articles)), key=lambda i: len(articles[i].sentences))
    slots: list = [None] * len(articles)
    for start in range(0, len(order), batch):
        part = order[start : start + batch]
        ids, mask, owners = tokenize(tokenizer, [articles[i] for i in part], device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            event, sentence = model(ids, mask, owners, len(part))
        event = torch.sigmoid(event).float().cpu().numpy()
        sentence = torch.sigmoid(sentence).float().cpu().numpy()
        owners = owners.cpu().numpy()
        for k, i in enumerate(part):
            slots[i] = (event[k], sentence[owners == k])
    for event, sentence in slots:
        events.append(event)
        sentences.append(sentence)
    joined = np.concatenate(sentences)
    return Outputs(np.stack(events), joined[:, 0], joined[:, 1])


def truth(articles: list[Article]) -> Outputs:
    return Outputs(
        np.stack([a.event for a in articles]),
        np.concatenate([a.location for a in articles]),
        np.concatenate([a.impact for a in articles]),
    )
