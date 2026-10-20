"""Optional reviewed DenseNet121 adaptation; Apache-2.0 and BSD notices accompany it.

Sources and local changes: third_party/torchxrayvision/NOTICE. No image decoding,
cropping, resizing, threshold normalization or repository-code loading occurs
here. Scores describe this research model, not calibrated disease probability.
"""

from app.ai.imaging_model import LABELS, read_verified_file, verify_model


def create_network():
    """Preserve the author's exact 727-key single-channel DenseNet121 schema."""
    from collections import OrderedDict

    import torch
    from torch import nn
    from torch.nn import functional as functional

    class DenseLayer(nn.Sequential):
        def __init__(self, incoming):
            super().__init__(
                OrderedDict(
                    [
                        ("norm1", nn.BatchNorm2d(incoming)),
                        ("relu1", nn.ReLU(inplace=True)),
                        ("conv1", nn.Conv2d(incoming, 128, kernel_size=1, bias=False)),
                        ("norm2", nn.BatchNorm2d(128)),
                        ("relu2", nn.ReLU(inplace=True)),
                        ("conv2", nn.Conv2d(128, 32, kernel_size=3, padding=1, bias=False)),
                    ]
                )
            )

        def forward(self, values):
            return torch.cat([values, super().forward(values)], 1)

    class DenseBlock(nn.Sequential):
        def __init__(self, incoming, layers):
            super().__init__()
            for index in range(layers):
                self.add_module(f"denselayer{index + 1}", DenseLayer(incoming + index * 32))

    class Transition(nn.Sequential):
        def __init__(self, incoming):
            super().__init__(
                OrderedDict(
                    [
                        ("norm", nn.BatchNorm2d(incoming)),
                        ("relu", nn.ReLU(inplace=True)),
                        ("conv", nn.Conv2d(incoming, incoming // 2, kernel_size=1, bias=False)),
                        ("pool", nn.AvgPool2d(kernel_size=2, stride=2)),
                    ]
                )
            )

    class DenseNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                OrderedDict(
                    [
                        ("conv0", nn.Conv2d(1, 64, kernel_size=7, stride=2, padding=3, bias=False)),
                        ("norm0", nn.BatchNorm2d(64)),
                        ("relu0", nn.ReLU(inplace=True)),
                        ("pool0", nn.MaxPool2d(kernel_size=3, stride=2, padding=1)),
                    ]
                )
            )
            incoming = 64
            for index, layers in enumerate((6, 12, 24, 16)):
                self.features.add_module(f"denseblock{index + 1}", DenseBlock(incoming, layers))
                incoming += layers * 32
                if index < 3:
                    self.features.add_module(f"transition{index + 1}", Transition(incoming))
                    incoming //= 2
            self.features.add_module("norm5", nn.BatchNorm2d(incoming))
            self.classifier = nn.Linear(incoming, len(LABELS))

        def forward(self, values):
            features = functional.relu(self.features(values), inplace=True)
            pooled = functional.adaptive_avg_pool2d(features, (1, 1)).flatten(1)
            return self.classifier(pooled)

    return DenseNet()


def load_network(directory, cpu_threads=4):
    if type(cpu_threads) is not int or not 1 <= cpu_threads <= 64:
        raise ValueError("影像 CPU 线程数须为1至64的整数")
    verify_model(directory)
    # Use precisely these hash-verified bytes, rather than reopening a path
    # inside safetensors after verification. Import heavy dependencies lazily.
    raw = read_verified_file(directory, "model.safetensors")
    import torch
    from safetensors.torch import load

    torch.set_num_threads(cpu_threads)
    model = create_network().cpu()
    model.load_state_dict(load(raw), strict=True)
    model.eval()
    return model


def predict_scores(model, values):
    """Return all 18 original sigmoid scores for an already prepared tensor."""
    import torch

    if not isinstance(values, torch.Tensor) or values.dtype != torch.float32 or values.device.type != "cpu" or tuple(values.shape) != (1, 1, 224, 224):
        raise ValueError("影像网络仅接受已处理的 CPU float32 [1,1,224,224] 张量")
    if not torch.isfinite(values).all().item() or values.min().item() < -1024.01 or values.max().item() > 1024.01:
        raise ValueError("影像网络输入须为归一化范围内的有限数值；仅容许固定双线性float32舍入的1e-2边界误差")
    with torch.inference_mode():
        logits = model(values)
    if tuple(logits.shape) != (1, 18) or not torch.isfinite(logits).all().item():
        raise ValueError("影像网络未返回18项有限原始分数")
    return torch.sigmoid(logits)[0].tolist()
