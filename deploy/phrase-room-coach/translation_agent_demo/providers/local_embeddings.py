"""CPU-only sentence embeddings. Run this module once to download the pinned model."""

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
import os

from .embedding_protocol import EMBEDDING_DIMENSIONS, EmbeddingBatch, EmbeddingError

REPOSITORY = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL = f"{REPOSITORY}@{REVISION[:12]}-mean256-pad1536"
DIRECTORY = Path(__file__).resolve().parents[1] / ".local/models" / REVISION


class LocalEmbeddings:
    model = MODEL
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(os.environ.get("COACH_LOCAL_MODEL_DIR", DIRECTORY))
        graph = directory / "onnx/model.onnx"
        vocabulary = directory / "tokenizer.json"
        if not graph.is_file() or not vocabulary.is_file():
            raise EmbeddingError("First run python -m translation_agent_demo.providers.local_embeddings.")
        self.tokenizer = Tokenizer.from_file(str(vocabulary))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.encoder = ort.InferenceSession(str(graph), options, providers=["CPUExecutionProvider"])

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        import numpy as np

        if isinstance(texts, (str, bytes)) or not 1 <= len(texts) <= 32:
            raise ValueError("Expected 1 to 32 texts.")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Expected nonblank text.")
        rows = self.tokenizer.encode_batch(list(texts))
        ids = np.asarray([row.ids for row in rows], dtype=np.int64)
        masks = np.asarray([row.attention_mask for row in rows], dtype=np.int64)
        states = self.encoder.run(["last_hidden_state"], {
            "input_ids": ids, "attention_mask": masks, "token_type_ids": np.zeros_like(ids)
        })[0]
        # Mean-pool non-padding tokens, as specified by the model's pooling layer.
        pooled = (states * masks[:, :, None].astype(np.float32)).sum(axis=1) / masks.sum(axis=1, keepdims=True)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        if pooled.shape != (len(rows), 384) or not np.all(np.isfinite(norms) & (norms > 0)):
            raise EmbeddingError("Invalid local encoder output.")
        # pgvector uses a fixed 1536-column width. Zero padding preserves cosine distance.
        padded = np.pad((pooled / norms).astype(np.float32), ((0, 0), (0, self.dimensions - 384)))
        return EmbeddingBatch(self.model, self.dimensions, tuple(tuple(row.tolist()) for row in padded), 0)


@lru_cache(maxsize=1)
def local_client() -> LocalEmbeddings:
    return LocalEmbeddings()


if __name__ == "__main__":
    from huggingface_hub import snapshot_download

    snapshot_download(REPOSITORY, revision=REVISION, local_dir=DIRECTORY,
                      allow_patterns=["onnx/model.onnx", "tokenizer.json", "LICENSE"])
    print(DIRECTORY)
