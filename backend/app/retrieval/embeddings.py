import numpy as np
from bson.binary import Binary, BinaryVectorDtype


def passage_text(title, text):
    return f"{title}\n\n{text}" if title else text


def to_bson_vector(vector):
    # binData is much smaller than an array of doubles (M0 has 512 MB)
    return Binary.from_vector(np.asarray(vector, dtype=np.float32), BinaryVectorDtype.FLOAT32)


class Embedder:
    def __init__(self, model_name, *, dim, query_prefix="", device="cpu"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)
        actual = self.model.get_embedding_dimension()
        if actual != dim:
            raise ValueError(
                f"{model_name} produces {actual}-dimensional vectors but EMBEDDING_DIM={dim}. "
                "Update EMBEDDING_DIM, recreate the vector index, and re-ingest documents."
            )
        self.dim = dim
        self.query_prefix = query_prefix

    def embed_documents(self, texts, batch_size=32):
        return self.model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def embed_query(self, text):
        vector = self.model.encode(
            [text],
            prompt=self.query_prefix or None,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()

    def count_tokens(self, text):
        return len(self.model.tokenizer(text, add_special_tokens=False, verbose=False)["input_ids"])
