def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_hello_default(client):
    res = client.get("/api/hello")
    assert res.get_json() == {"message": "Hello, world!"}


def test_hello_with_name(client):
    res = client.get("/api/hello?name=Srijon")
    assert res.get_json() == {"message": "Hello, Srijon!"}
