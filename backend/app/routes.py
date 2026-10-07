from flask import Blueprint, jsonify, request

api = Blueprint("api", __name__)


@api.get("/health")
def health():
    return jsonify(status="ok")


@api.get("/hello")
def hello():
    name = request.args.get("name", "world")
    return jsonify(message=f"Hello, {name}!")
