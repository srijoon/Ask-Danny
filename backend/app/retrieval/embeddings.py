# The local embedding model (bge-small) wrapped for this app: passages get the
# title prepended, queries get the bge instruction prefix, and vectors are stored
# as BSON binary. Chunk budgets elsewhere are counted in this model's tokens.
import numpy as np
from bson.binary import Binary, BinaryVectorDtype


def passage_text(title, text):
    """The exact string fed to the models — title + text, shared by ingest and rerank."""
    # prepend the title so a chunk embeds with its document's context — used at
    # ingest time (embed_documents) and again at rerank time, so keep it shared
    return f"{title}\n\n{text}" if title else text


def to_bson_vector(vector):
    """Pack a numpy vector as BSON float32 BinData — much smaller than a double array."""
    # binData is much smaller than an array of doubles (M0 has 512 MB)
    return Binary.from_vector(np.asarray(vector, dtype=np.float32), BinaryVectorDtype.FLOAT32)


class Embedder:
    """Sentence-transformer wrapper: embed passages/queries and count tokens."""

    def __init__(self, model_name, *, dim, query_prefix="", device="cpu"):
        """Load the model and verify its output dimension matches config."""
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)
        # fail at load, not at query time: a dimension mismatch would silently
        # break every vector search until someone re-creates the Atlas index
        actual = self.model.get_embedding_dimension()
        if actual != dim:
            raise ValueError(
                f"{model_name} produces {actual}-dimensional vectors but EMBEDDING_DIM={dim}. "
                "Update EMBEDDING_DIM, recreate the vector index, and re-ingest documents."
            )
        self.dim = dim
        self.query_prefix = query_prefix

    def embed_documents(self, texts, batch_size=32):
        """Encode passage texts in batches (ingest stores these on chunks)."""
        # normalize_embeddings makes cosine similarity a plain dot product in the index
        return self.model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def embed_query(self, text):
        """Encode one query (with the bge prefix) into a plain list for $vectorSearch."""
        # bge models want a short instruction prefixed to queries only —
        # passages are embedded bare (the title prepend lives in passage_text)
        vector = self.model.encode(
            [text],
            prompt=self.query_prefix or None,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()

    def count_tokens(self, text):
        """Token length in this model's vocabulary — the chunker's measuring stick."""
        # chunk budgets are measured in the embedder's own tokens, so a chunk that
        # fits the budget always fits the model's input window
        return len(self.model.tokenizer(text, add_special_tokens=False, verbose=False)["input_ids"])
