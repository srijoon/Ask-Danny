class Reranker:
    def __init__(self, model_name, *, device="cpu", max_length=512):
        import torch
        from sentence_transformers import CrossEncoder

        # sigmoid keeps scores in 0..1 for RERANK_MIN_SCORE
        self.model = CrossEncoder(
            model_name, device=device, max_length=max_length, activation_fn=torch.nn.Sigmoid()
        )

    def score(self, query, passages):
        if not passages:
            return []
        scores = self.model.predict(
            [(query, passage) for passage in passages], batch_size=16, show_progress_bar=False
        )
        return [float(s) for s in scores]
