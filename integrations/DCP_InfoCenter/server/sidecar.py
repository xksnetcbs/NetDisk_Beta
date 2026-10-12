"""NetDisk-owned HTTP sidecar sharing existing stores without starting workers."""

import os
from pathlib import Path

from flask import Flask, Request

from desktop_api import DesktopStore, mount as mount_desktop
from terminal_backend import Store, mount as mount_terminal


class SidecarRequest(Request):
    @property
    def max_content_length(self):
        # Terminal keeps its existing 2 MiB JSON limit. Desktop send carries
        # base64 for the original 20 MiB attachments; this works on Flask 2.0
        # without changing the app-wide limit or using Flask 3.1's setter.
        actions = ("prepare", "select", "submit", "cancel", "status")
        if self.method == "POST" and self.path in {
            "/api/terminal/desktop/send/" + action for action in actions
        }:
            return 30 * 1024 * 1024
        return super().max_content_length


def create_app():
    home = Path(os.environ.get("DCP_TERMINAL_HOME") or Path.home() / "dcp-terminal")
    capture = Path(os.environ.get("DCP_CAPTURE_DB") or Path(os.environ.get("DCP_CAPTURE_ROOT") or Path.home() / "wechat-capture") / "runtime/memory/wechat_memory.sqlite")
    # Require provisioned stores; never initialize a new account by a typo.
    if not (home / "config.json").is_file() or not (home / "terminal.sqlite").is_file() or not capture.is_file():
        raise RuntimeError("Existing Terminal configuration and databases are required")
    app = Flask(__name__)
    app.request_class = SidecarRequest
    terminal = Store(home, wechat=capture)
    mount_terminal(app, store=terminal, start=False)
    desktop = DesktopStore(home=home, memory=capture, account=os.environ.get("DCP_WECHAT_ACCOUNT_DIR"))
    mount_desktop(app, store=desktop)
    app.extensions["desktop"] = desktop
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.environ.get("DCP_INFOCENTER_SIDECAR_PORT", "8767")), threaded=True, use_reloader=False)
