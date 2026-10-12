from flask import Flask

from .api import api_bp
from .config import load_config
from .extensions import cors, db, jwt, migrate
from .auth_sessions import register_auth_callbacks
from .storage import register_storage_commands
from .readable_storage import register_readable_storage
from .infocenter import infocenter_bp
from .mobile import mobile_bp
from .message_bridge import register_message_bridge
from .wechat_files import register_wechat_files


def create_app():
    app = Flask(__name__)
    app.config.from_object(load_config())

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    register_auth_callbacks(jwt)
    register_storage_commands(app)
    register_readable_storage(app)
    register_message_bridge(app)
    register_wechat_files(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config.get("FRONTEND_ORIGIN")}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-DCP-Session"],
    )

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(infocenter_bp, url_prefix="/api/infocenter")
    app.register_blueprint(mobile_bp, url_prefix="/api/mobile/terminal")

    @app.get("/")
    def index():
        return "DCP_NetDisk API"

    return app
