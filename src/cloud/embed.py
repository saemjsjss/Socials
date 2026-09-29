"""gte-small embeddings, on the CPU, for the text form of every record.

The model is thenlper/gte-small at the revision pinned in settings (CLOUD_EMBED_MODEL,
CLOUD_EMBED_REVISION): 384 dimensions, mean pooling, L2-normalised, float32. Jeannie embeds her
questions with the same model (Supabase/gte-small, its ONNX export), so the vectors must come
from exactly this model. It is loaded once per process, lazily, and only in a process that was
started to embed: the publisher process (python -m src.cloud.publish --from ...) and the backfill
call prepare_process() before anything can import torch, so CUDA is hidden (CUDA_VISIBLE_DEVICES
is "-1": no device has that index, so the CUDA runtime sees none) and the 8 GB GPU stays with
Ollama and the document OCR (R12). Not "": on Windows, CPython removes a variable set to an empty
value from the process's real environment, so CUDA never saw it and torch still found the GPU.
Measured on this PC: ~14 ms a record, about 1 GB of RAM.

gte-small reads at most 512 tokens, so a long text is cut into chunks of at most MAX_WORDS words
on paragraph or sentence boundaries (then checked against the tokenizer); a record whose text has
a short first line (a heading such as "Document <file> of <name>, page 3:") repeats that line at
the top of every chunk, so each chunk says what it is.

Tests use StubEmbedder (set_embedder): deterministic vectors, no torch.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sys
import threading
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger("hangeul.cloud")

DIMENSIONS = 384
MAX_WORDS = 350            # per chunk, so gte-small does not truncate at 512 tokens
MAX_TOKENS = 510           # its 512 minus [CLS] and [SEP]
HEADING_WORDS = 40         # a first line this short is repeated on every chunk
ENCODE_BATCH = 32


# CUDA_VISIBLE_DEVICES for a process that must not use the GPU (the publisher, the backfill, the
# full picture and the handoff's child all set this very value; "" does not survive on Windows).
NO_GPU = "-1"
# The libraries that load the model log at INFO ("No modules.json found for thenlper/gte-small..."
# when the model is missing), and the embedding processes log at INFO: they are kept at WARNING, so
# a missing model costs the run exactly its one hangeul.cloud warning.
QUIET_LOGGERS = ("sentence_transformers", "transformers", "huggingface_hub")


class EmbedError(RuntimeError):
    """The model could not be loaded or used here (reason in the message, no text in it)."""


def model_id() -> str:
    """The embed_model string every chunk carries: "thenlper/gte-small@<revision>"."""
    from src.config import settings
    return f"{settings.CLOUD_EMBED_MODEL}@{settings.CLOUD_EMBED_REVISION}"


def prepare_process() -> None:
    """Make this process a CPU-only embedding process. Call it first thing, before anything imports
    torch (the publisher's and the backfill's entry points do): the GPU is hidden, the Hugging Face
    hub is offline (the pinned model must already be in the cache: nothing is downloaded), and no
    progress bars or library INFO lines are written into the log (quiet_libraries)."""
    if "torch" in sys.modules and os.environ.get("CUDA_VISIBLE_DEVICES") != NO_GPU:
        raise EmbedError("torch was imported before prepare_process(), so CUDA cannot be hidden")
    os.environ["CUDA_VISIBLE_DEVICES"] = NO_GPU
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    quiet_libraries()


def quiet_libraries() -> None:
    """The model libraries' loggers (QUIET_LOGGERS) at WARNING at least: a logger left at NOTSET or
    set lower would pass the process's INFO on; one already stricter (transformers' own ERROR,
    from TRANSFORMERS_VERBOSITY) is left as it is. Called by prepare_process and again once the
    libraries are imported, which may set their own level."""
    for name in QUIET_LOGGERS:
        lib = logging.getLogger(name)
        if lib.level < logging.WARNING:            # NOTSET (0) or DEBUG / INFO
            lib.setLevel(logging.WARNING)


def cpu_only_process() -> bool:
    """Whether this process may load the model: it hid CUDA (prepare_process) before torch."""
    return os.environ.get("CUDA_VISIBLE_DEVICES") == NO_GPU


# --------------------------------------------------------------------------- splitting text

_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")
# A sentence ends at . ! ? followed by space, or at a line break (OCR text is line-shaped).
_SENTENCE_RE = re.compile(r"(?<=[.!?])[ \t]+|\n+")


def _words(text: str) -> int:
    return len(text.split())


def _cut(text: str, max_words: int) -> List[str]:
    """A text longer than max_words, cut on word boundaries into pieces of at most max_words."""
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _units(text: str, max_words: int) -> List[tuple]:
    """The text's units, each at most max_words words, with the separator that stood before it:
    whole paragraphs when they fit, else their sentences (or lines), else word-cut pieces."""
    units: List[tuple] = []

    def add(piece: str, sep: str) -> None:
        pieces = _cut(piece, max_words) if _words(piece) > max_words else [piece]
        for i, cut in enumerate(pieces):
            units.append((cut, sep if i == 0 else " "))

    for para in _PARAGRAPH_RE.split(text or ""):
        para = para.strip()
        if not para:
            continue
        if _words(para) <= max_words:
            units.append((para, "\n\n"))
            continue
        sep, pos = "\n\n", 0
        for m in _SENTENCE_RE.finditer(para):
            piece = para[pos:m.start()].strip()
            if piece:
                add(piece, sep)
                sep = "\n" if "\n" in m.group(0) else " "
            pos = m.end()
        piece = para[pos:].strip()
        if piece:
            add(piece, sep)
    return units


def split_text(text: str, max_words: int = MAX_WORDS) -> List[str]:
    """`text` as chunks of at most `max_words` words each, cut between paragraphs where it can, else
    between sentences (or lines), else between words; [] for a text with no words. Whole units are
    packed together while they fit; the original breaks are kept inside a chunk."""
    max_words = max(1, int(max_words))
    units = _units(text, max_words)
    chunks: List[str] = []
    current, size = "", 0
    for piece, sep in units:
        n = _words(piece)
        if current and size + n <= max_words:
            current, size = current + sep + piece, size + n
        else:
            if current:
                chunks.append(current)
            current, size = piece, n
    if current:
        chunks.append(current)
    return chunks


def chunk_texts(content: str, max_words: int = MAX_WORDS,
                count_tokens: Optional[Callable[[str], int]] = None,
                max_tokens: int = MAX_TOKENS) -> List[str]:
    """The chunks of one record's text: the whole text when it fits, else split_text pieces, each
    led by the text's short first line (its heading) when it has one. With `count_tokens` (the
    model's tokenizer) a chunk that still reads as more than `max_tokens` is halved until it fits."""
    content = (content or "").strip()
    if not content:
        return []
    fits = (lambda t: count_tokens(t) <= max_tokens) if count_tokens else (lambda t: True)
    if _words(content) <= max_words and fits(content):
        return [content]
    head, _, body = content.partition("\n")
    if not body.strip() or _words(head) > HEADING_WORDS:
        head, body = "", content
    budget = max(20, max_words - _words(head))

    def lead(part: str) -> str:
        return f"{head}\n{part}" if head else part

    out: List[str] = []

    def place(part: str) -> None:
        if fits(lead(part)) or _words(part) <= 20:
            out.append(lead(part))
            return
        half = max(1, _words(part) // 2)
        for piece in _cut(part, half):
            place(piece)

    for part in split_text(body, budget):
        place(part)
    return out


# --------------------------------------------------------------------------- the embedders

class GteSmall:
    """thenlper/gte-small, pinned revision, float32 on the CPU; loaded on first use."""

    def __init__(self):
        from src.config import settings
        self.name = settings.CLOUD_EMBED_MODEL
        self.revision = settings.CLOUD_EMBED_REVISION
        self.model_id = f"{self.name}@{self.revision}"
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not cpu_only_process():
                raise EmbedError("this process did not hide CUDA before torch (call prepare_process first)")
            quiet_libraries()
            try:
                import torch
                from sentence_transformers import SentenceTransformer
                quiet_libraries()                  # the imports may have set their own levels
                model = SentenceTransformer(self.name, revision=self.revision, device="cpu",
                                            model_kwargs={"dtype": torch.float32})
            except Exception as e:
                raise EmbedError(f"gte-small could not be loaded ({type(e).__name__})") from e
            self._model = model
            return model

    def count_tokens(self, text: str) -> int:
        tok = self._load().tokenizer
        return len(tok(text, add_special_tokens=True, truncation=False)["input_ids"])

    def chunks(self, content: str) -> List[str]:
        return chunk_texts(content, MAX_WORDS, self.count_tokens)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._load()
        try:
            vecs = model.encode(list(texts), batch_size=ENCODE_BATCH, normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
        except Exception as e:
            raise EmbedError(f"gte-small could not embed ({type(e).__name__})") from e
        return [_checked([float(x) for x in v.astype("float32")]) for v in vecs]


class StubEmbedder:
    """For tests only: a deterministic 384-number unit vector per text (from its sha256), no torch.
    Records every text it was asked to embed."""

    def __init__(self, model_id: str = "stub/gte-small@test"):
        self.model_id = model_id
        self.calls: List[List[str]] = []

    def chunks(self, content: str) -> List[str]:
        return chunk_texts(content, MAX_WORDS)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        self.calls.append(list(texts))
        out = []
        for t in texts:
            seed = hashlib.sha256(t.encode("utf-8")).digest()
            raw = [((seed[i % 32] + 7 * i) % 251) - 125.0 for i in range(DIMENSIONS)]
            norm = math.sqrt(sum(x * x for x in raw)) or 1.0
            out.append(_checked([x / norm for x in raw]))
        return out


def _checked(vec: List[float]) -> List[float]:
    if len(vec) != DIMENSIONS or not all(math.isfinite(x) for x in vec):
        raise EmbedError(f"an embedding had {len(vec)} numbers or a non-finite one (want {DIMENSIONS})")
    return vec


_embedder = None
_embedder_lock = threading.Lock()


def get_embedder():
    """The process's one embedder (gte-small unless set_embedder chose another)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = GteSmall()
    return _embedder


def set_embedder(embedder):
    """Use `embedder` (e.g. StubEmbedder()) from now on; None goes back to gte-small. -> the old one."""
    global _embedder
    old, _embedder = _embedder, embedder
    return old


def custom_embedder() -> bool:
    """Whether a stand-in embedder was set (tests): it needs no CPU-only process."""
    return _embedder is not None and not isinstance(_embedder, GteSmall)
