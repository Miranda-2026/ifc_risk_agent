"""Same-origin IFC UI. Financial answers still go through /invocations."""

import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_server.ui_contract import dashboard_url

STATIC_DIR = Path(__file__).with_name("static")


def register_ui(app):
    app.mount("/ifc-assets", StaticFiles(directory=STATIC_DIR), name="ifc-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/ui-config", include_in_schema=False)
    async def ui_config():
        return {
            "dashboard_url": dashboard_url(os.getenv("IFC_DASHBOARD_URL")),
            "portfolio_configured": bool(os.getenv("IFC_GENIE_SPACE_ID", "").strip()),
            "preview": False,
        }
