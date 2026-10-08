import logging

from flask import Flask

from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if app.config["SECRET_KEY"] == "dev" and not app.testing:
        logging.getLogger(__name__).warning("FLASK_SECRET_KEY is not set; sessions are insecure.")

    from . import cli, db, ml, security
    from .generation.llm import create_llm

    db.init_app(app)
    security.init_app(app)
    cli.init_app(app)
    app.extensions["llm"] = create_llm(app.config)

    from .admin.routes import bp as admin_bp
    from .auth.routes import bp as auth_bp
    from .chat.routes import bp as chat_bp
    from .routes import api

    app.register_blueprint(api, url_prefix="/api")
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)

    ml.preload(app)

    return app
