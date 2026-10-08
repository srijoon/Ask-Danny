# App factory: wires config, Mongo, CSRF, the LLM provider and every blueprint
# together, then warms the local models. Entry point for `flask run` and tests.
import logging

from flask import Flask

from .config import Config


def create_app(config_class=Config):
    """Build and wire the app — entry point for `flask run` and the tests."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # the openai/openrouter client logs every request at INFO otherwise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # "dev" signs sessions with a guessable key; fine for tests, worthless in production
    if app.config["SECRET_KEY"] == "dev" and not app.testing:
        logging.getLogger(__name__).warning("FLASK_SECRET_KEY is not set; sessions are insecure.")

    from . import cli, db, ml, security
    from .generation.llm import create_llm

    # db and security first: routes assume get_db() and the CSRF check are wired up
    db.init_app(app)
    security.init_app(app)
    cli.init_app(app)
    # shared provider instance; creating it is cheap (the HTTP session is lazy)
    app.extensions["llm"] = create_llm(app.config)

    from .admin.routes import bp as admin_bp
    from .auth.routes import bp as auth_bp
    from .chat.routes import bp as chat_bp
    from .routes import api

    app.register_blueprint(api, url_prefix="/api")
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)

    # load embedder + reranker at boot so the first request doesn't stall for seconds
    ml.preload(app)

    return app
