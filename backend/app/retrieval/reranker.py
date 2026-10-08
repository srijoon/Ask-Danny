# Thin wrapper over a cross-encoder (bge-reranker-base) that scores
# (query, passage) pairs in 0..1. Loaded via ml.get_reranker() and used by
# retrieval/pipeline.py as the last quality gate before the LLM.
class Reranker:
    """Cross-encoder scoring (query, passage) pairs — the last quality gate."""

    def __init__(self, model_name, *, device="cpu", max_length=512):
        """Load the cross-encoder; sigmoid keeps scores in 0..1 for RERANK_MIN_SCORE."""
        import torch
        from sentence_transformers import CrossEncoder

        # sigmoid keeps scores in 0..1 for RERANK_MIN_SCORE
        self.model = CrossEncoder(
            model_name, device=device, max_length=max_length, activation_fn=torch.nn.Sigmoid()
        )

    def score(self, query, passages):
        """Score each (query, passage) pair in 0..1; empty input returns []."""
        if not passages:
            return []  # predict() on an empty batch raises inside the model
        scores = self.model.predict(
            [(query, passage) for passage in passages], batch_size=16, show_progress_bar=False
        )
        return [float(s) for s in scores]
