"""Stub: pyworld has no cp312 Windows wheel. CosyVoice only uses it for training-time F0
extraction (cosyvoice.dataset.processor.compute_f0), never during inference."""


def _unavailable(*a, **k):
    raise RuntimeError("pyworld stub: not available in this inference-only install")


harvest = dio = stonemask = _unavailable
