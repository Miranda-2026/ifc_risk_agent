# Install crash/hang/exception diagnostics before importing agent code so
# startup failures and unhandled exceptions land in the Apps log stream.
from scripts.app_diagnostics import install_diagnostics  # noqa: E402

install_diagnostics()

from pathlib import Path

from dotenv import load_dotenv
from mlflow.genai.agent_server import AgentServer, setup_mlflow_git_based_version_tracking

# Load env vars from .env before importing the agent for proper auth
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

# Need to import the agent to register the functions with the server
import agent_server.agent  # noqa: E402

agent_server = AgentServer("ResponsesAgent", enable_chat_proxy=True)
# Define the app as a module level variable to enable multiple workers
app = agent_server.app  # noqa: F841
setup_mlflow_git_based_version_tracking()

# --- Dashboard embedding ---
# Serves the IFC Project Portfolio Overview dashboard at /dashboard
from fastapi.responses import HTMLResponse

DASHBOARD_URL = (
    "https://dbc-3e5b0d11-f3e0.cloud.databricks.com/dashboardsv3"
    "/01f1de13749f12779d1d9ab2c3b51f66/published?o=7474649226576612"
)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Render the IFC Project Portfolio Overview dashboard in an iframe."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IFC Project Portfolio Overview</title>
  <style>
    html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; }}
    iframe {{ border: 0; width: 100%; height: 100vh; }}
  </style>
</head>
<body>
  <iframe src="{DASHBOARD_URL}" allowfullscreen></iframe>
</body>
</html>"""


def main():
    agent_server.run(app_import_string="agent_server.start_server:app")
