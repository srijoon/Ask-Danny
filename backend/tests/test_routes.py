import io

import mongomock
import pytest

from app import create_app
from app.auth.users import create_user
from app.chat import answer as answer_module
from app.config import TestConfig
from app.retrieval.pipeline import RetrievalResult
from conftest import login
from test_answer import FakeLLM

CHUNK = {"_id": "c1", "doc_id": "d1", "title": "Handbook", "filename": "handbook.pdf", "page": 3,
         "text": "New hires get 15 vacation days.", "rerank_score": 0.9}


@pytest.fixture
def fake_rag(app, monkeypatch):
    seen = {"principals": [], "queries": []}

    def fake_retrieve(query, principals):
        seen["queries"].append(query)
        seen["principals"].append(principals)
        return RetrievalResult(chunks=[dict(CHUNK)], mode="hybrid", candidates=1, top_score=0.9)

    monkeypatch.setattr(answer_module, "retrieve", fake_retrieve)
    app.extensions["llm"] = FakeLLM("15 days [1].", "vacation days for new hires", "Yes [1].")
    return seen


def test_pages_require_login(client):
    res = client.get("/")
    assert res.status_code == 302 and "/login" in res.headers["Location"]
    assert client.post("/chat/ask", json={"question": "hi"}).status_code == 401


def test_login_logout_and_safe_redirect(client, users):
    assert client.post("/login", data={"username": "alice", "password": "nope"}).status_code == 200
    res = client.post("/login?next=//evil.example", data={"username": "alice", "password": "password123"})
    assert res.headers["Location"] == "/"
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/").status_code == 302


def test_ask_saves_conversation_and_uses_history(client, users, db, fake_rag):
    login(client, "alice")
    first = client.post("/chat/ask", json={"question": "How many vacation days?"}).get_json()
    assert first["answer"]["status"] == "ok"
    assert first["answer"]["sources"][0]["page"] == 3
    assert fake_rag["principals"][0] == ["everyone", "user:alice", "group:hr"]

    second = client.post("/chat/ask", json={"question": "And for new hires?",
                                            "conversation_id": first["conversation_id"]}).get_json()
    assert second["conversation_id"] == first["conversation_id"]
    assert fake_rag["queries"][1] == "vacation days for new hires"
    conversation = db.conversations.find_one()
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant"] * 2

    page = client.get(f"/?c={first['conversation_id']}")
    assert page.status_code == 200 and b"How many vacation days?" in page.data


def test_conversations_are_private(client, users, fake_rag):
    login(client, "alice")
    cid = client.post("/chat/ask", json={"question": "Vacation?"}).get_json()["conversation_id"]
    client.post("/logout")
    login(client, "bob")
    assert client.get(f"/?c={cid}").status_code == 404
    assert client.post("/chat/ask", json={"question": "x", "conversation_id": cid}).status_code == 404


def test_ask_validates_question(client, users):
    login(client, "alice")
    assert client.post("/chat/ask", json={"question": "  "}).status_code == 400
    assert client.post("/chat/ask", json={"question": "x" * 2001}).status_code == 400


def test_admin_pages_are_admin_only(client, users, monkeypatch):
    monkeypatch.setattr("app.admin.routes.search_index_status", lambda db, cfg: {})
    login(client, "alice")
    assert client.get("/admin/documents").status_code == 403
    client.post("/logout")
    login(client, "admin")
    page = client.get("/admin/documents")
    assert page.status_code == 200 and b"Vector only" in page.data and b"MISSING" in page.data


def test_admin_upload_and_change_access(client, users, db, monkeypatch):
    monkeypatch.setattr("app.admin.routes.search_index_status", lambda db, cfg: {})
    login(client, "admin")
    res = client.post("/admin/documents", data={
        "files": (io.BytesIO(b"# Benefits\n\nDental starts on day one."), "benefits.md"),
        "groups": ["hr"], "new_groups": "finance",
    }, content_type="multipart/form-data")
    assert res.status_code == 302
    doc = db.documents.find_one()
    assert doc["access"] == ["group:finance", "group:hr", "user:admin"]
    assert db.chunks.count_documents({"doc_id": doc["_id"], "access": doc["access"]}) == 1

    client.post(f"/admin/documents/{doc['_id']}/access", data={"everyone": "1"})
    assert db.chunks.find_one()["access"] == ["everyone"]
    client.post(f"/admin/documents/{doc['_id']}/access", data={"groups": ["finance"]})
    assert db.chunks.find_one()["access"] == ["group:finance"]

    client.post(f"/admin/documents/{doc['_id']}/delete")
    assert db.documents.count_documents({}) == 0 and db.chunks.count_documents({}) == 0


def test_admin_manages_users(client, users, db):
    login(client, "admin")
    client.post("/admin/users", data={"username": "Carol", "password": "password123", "groups": "hr, legal"})
    carol = db.users.find_one({"username": "carol"})
    assert carol["groups"] == ["hr", "legal"] and not carol["is_admin"]
    client.post(f"/admin/users/{carol['_id']}", data={"groups": "legal", "is_admin": "1"})
    assert db.users.find_one({"_id": carol["_id"]})["groups"] == ["legal"]
    admin_id = users["admin"]["_id"]
    client.post(f"/admin/users/{admin_id}", data={"groups": "hr"})
    assert db.users.find_one({"_id": admin_id})["is_admin"]


def test_csrf_is_enforced():
    class CsrfConfig(TestConfig):
        CSRF_ENABLED = True

    app = create_app(CsrfConfig)
    app.extensions["mongo_db"] = mongomock.MongoClient().db
    create_user(app.extensions["mongo_db"], "alice", "password123")
    client = app.test_client()
    assert login(client, "alice").status_code == 400
    client.get("/login")
    with client.session_transaction() as session:
        token = session["_csrf"]
    res = client.post("/login", data={"username": "alice", "password": "password123", "csrf_token": token})
    assert res.status_code == 302


def test_existing_api_still_works(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}
