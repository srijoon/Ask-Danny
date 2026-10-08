import hashlib

import mongomock
import numpy as np
import pytest

from app import create_app
from app.auth.users import create_user
from app.config import TestConfig


class FakeEmbedder:
    dim = 384

    def _vector(self, text):
        vec = np.zeros(self.dim, dtype=np.float32)
        for word in text.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def embed_documents(self, texts, batch_size=32):
        return np.stack([self._vector(t) for t in texts])

    def embed_query(self, text):
        return self._vector(text).tolist()

    def count_tokens(self, text):
        return len(text.split())


class FakeReranker:
    def score(self, query, passages):
        words = set(query.lower().split())
        return [len(words & set(p.lower().split())) / max(len(words), 1) for p in passages]


@pytest.fixture
def app():
    app = create_app(TestConfig)
    app.extensions["mongo_db"] = mongomock.MongoClient().db
    app.extensions["embedder"] = FakeEmbedder()
    app.extensions["reranker"] = FakeReranker()
    return app


@pytest.fixture
def db(app):
    return app.extensions["mongo_db"]


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def users(db):
    return {
        "admin": create_user(db, "admin", "password123", groups=["hr"], is_admin=True),
        "alice": create_user(db, "alice", "password123", groups=["hr"]),
        "bob": create_user(db, "bob", "password123", groups=["finance"]),
    }


def login(client, username):
    return client.post("/login", data={"username": username, "password": "password123"})
