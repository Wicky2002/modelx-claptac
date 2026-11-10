"""U-Net with a pretrained ResNet encoder, and full-tile prediction by overlapping windows."""

from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torchvision.models import ResNet34_Weights, ResNet50_Weights, resnet34, resnet50

from training.flood.data import CHANNELS


def _conv(in_ch: int, out_ch: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
        nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
    )


class Up(nn.Module):
    def __init__(self, in_ch: int, skip_ch: int, out_ch: int) -> None:
        super().__init__()
        self.conv = _conv(in_ch + skip_ch, out_ch)

    def forward(self, x, skip=None):
        size = skip.shape[2:] if skip is not None else [s * 2 for s in x.shape[2:]]
        x = nn.functional.interpolate(x, size=size, mode="bilinear", align_corners=False)
        return self.conv(x if skip is None else torch.cat([x, skip], 1))


ENCODERS = {
    # name: (builder, ImageNet weights, channels of layer1..layer4)
    "resnet34": (resnet34, ResNet34_Weights.IMAGENET1K_V1, (64, 128, 256, 512)),
    "resnet50": (resnet50, ResNet50_Weights.IMAGENET1K_V2, (256, 512, 1024, 2048)),
}


class FloodUNet(nn.Module):
    def __init__(
        self, channels: int = CHANNELS, pretrained: bool = True, encoder: str = "resnet34"
    ) -> None:
        super().__init__()
        build, weights, (c1, c2, c3, c4) = ENCODERS[encoder]
        net = build(weights=weights if pretrained else None)
        first = nn.Conv2d(channels, 64, 7, stride=2, padding=3, bias=False)
        with torch.no_grad():  # every new input channel starts from the average of the RGB filters
            first.weight[:] = net.conv1.weight.mean(1, keepdim=True).repeat(1, channels, 1, 1)
        self.stem = nn.Sequential(first, net.bn1, net.relu)
        self.pool = net.maxpool
        self.encoder = nn.ModuleList([net.layer1, net.layer2, net.layer3, net.layer4])
        self.up4 = Up(c4, c3, 256)
        self.up3 = Up(256, c2, 128)
        self.up2 = Up(128, c1, 64)
        self.up1 = Up(64, 64, 32)
        self.up0 = Up(32, 0, 16)
        self.head = nn.Conv2d(16, 1, 1)

    def forward(self, x):
        s0 = self.stem(x)
        s1 = self.encoder[0](self.pool(s0))
        s2 = self.encoder[1](s1)
        s3 = self.encoder[2](s2)
        s4 = self.encoder[3](s3)
        d = self.up4(s4, s3)
        d = self.up3(d, s2)
        d = self.up2(d, s1)
        d = self.up1(d, s0)
        return self.head(self.up0(d)).squeeze(1)


def _starts(length: int, window: int, stride: int) -> list[int]:
    starts = list(range(0, max(length - window, 0) + 1, stride))
    if starts[-1] != max(length - window, 0):
        starts.append(max(length - window, 0))
    return starts


@torch.no_grad()
def predict_tile(model, x: np.ndarray, device, window=448, batch=8) -> np.ndarray:
    """Flood probability for a whole normalised tile (channels, height, width)."""
    stride = window * 2 // 3
    _, height, width = x.shape
    total = np.zeros((height, width), dtype=np.float32)
    count = np.zeros((height, width), dtype=np.float32)
    spots = [(t, s) for t in _starts(height, window, stride) for s in _starts(width, window, stride)]
    for i in range(0, len(spots), batch):
        part = spots[i : i + batch]
        inputs = torch.from_numpy(
            np.stack([x[:, t : t + window, s : s + window] for t, s in part])
        ).to(device)
        with torch.autocast(device.type, enabled=device.type == "cuda"):
            probs = torch.sigmoid(model(inputs)).float().cpu().numpy()
        for (t, s), p in zip(part, probs):
            total[t : t + window, s : s + window] += p
            count[t : t + window, s : s + window] += 1
    return total / count
