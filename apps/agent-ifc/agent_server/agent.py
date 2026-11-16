import logging
import json
import os
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import mlflow
from agents import Agent, Runner, function_tool, set_default_openai_api, set_default_openai_client
from agents.tracing import set_trace_processors
from databricks.sdk import WorkspaceClient
from databricks_openai import AsyncDatabricksOpenAI
from databricks_openai.agents import McpServer
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

from agent_server.history import normalize_history_items
from agent_server.ui_contract import CARD_INSTRUCTIONS, normalize_weights
from agent_server.utils import (
    build_mcp_url,
    get_session_id,
    get_user_workspace_client,
    process_agent_stream_events,
)

logger = logging.getLogger(__name__)
ANALYST_PROMPT = (Path(__file__).with_name("prompts") / "ifc_analyst.md").read_text(encoding="utf-8")

# NOTE: this will work for all databricks models OTHER than GPT-OSS, which uses a slightly different API
set_default_openai_client(AsyncDatabricksOpenAI())
set_default_openai_api("chat_completions")
set_trace_processors([])  # only use mlflow for trace processing
mlflow.openai.autolog()
logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)


@function_tool
def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().isoformat()


async def init_mcp_server(workspace_client: WorkspaceClient):
    return McpServer(
        url=build_mcp_url("/api/2.0/mcp/functions/system/ai", workspace_client=workspace_client),
        name="system.ai UC function MCP server",
        workspace_client=workspace_client,
    )


async def connect_healthy_mcp_servers(
    stack: AsyncExitStack, servers: list[McpServer]
) -> tuple[list[McpServer], list[str]]:
    """Connect each MCP server and verify it can actually list its tools.

    The Agents SDK lists each server's tools lazily inside ``Runner.run``, so a server that
    connects but fails at list time (e.g. an unauthorized Genie space) would otherwise crash
    the whole request — including unrelated turns. We list tools here, per server: healthy
    servers are kept; any that fails to connect OR to list is dropped and its name returned,
    so the agent runs with whatever is available instead of erroring out.

    Returns (healthy_servers, unavailable_names).
    """
    healthy: list[McpServer] = []
    unavailable: list[str] = []
    for server in servers:
        name = getattr(server, "name", "MCP server")
        try:
            connected = await stack.enter_async_context(server)
            await connected.list_tools()  # forces the connectivity + authorization check now
            healthy.append(connected)
        except Exception:
            logger.warning("MCP server %r unavailable; continuing without it.", name, exc_info=True)
            unavailable.append(name)
    return healthy, unavailable


def create_agent(mcp_servers: list[McpServer] | None = None, request=None) -> Agent:
    settings = (request.custom_inputs or {}) if request else {}
    weights = normalize_weights(settings.get("weights"))
    instructions = ANALYST_PROMPT + "\n\n" + CARD_INSTRUCTIONS
    instructions += "\nLatest UI scoring weights (percent): " + json.dumps(weights)
    instructions += "\nUI mode: " + str(settings.get("ui_mode", "chat"))
    return Agent(
        name="IFC Investment Intelligence",
        instructions=instructions,
        model=os.getenv("IFC_MODEL_ENDPOINT", "databricks-gpt-oss-20b"),
        tools=[get_current_time],
        mcp_servers=mcp_servers or [],
    )


async def create_request_agent(stack, request):
    """Connect the configured Genie before allowing portfolio recommendations."""
    space_id = os.getenv("IFC_GENIE_SPACE_ID", "").strip()
    if not space_id:
        return None, "The portfolio data connection is not configured yet. Connect your IFC Genie Agent to enable quantitative analysis and client recommendations. No portfolio figures or recommendations have been generated."
    client = WorkspaceClient()
    server = McpServer(
        url=build_mcp_url(f"/api/2.0/mcp/genie/{space_id}", workspace_client=client),
        name="IFC portfolio Genie",
        workspace_client=client,
        timeout=300.0,
    )
    servers, unavailable = await connect_healthy_mcp_servers(stack, [server])
    if unavailable:
        return None, "The IFC portfolio data connection is currently unavailable. Please check the Genie Agent access and try again. I cannot calculate verified portfolio metrics or recommendations without that connection."
    return create_agent(servers, request), None


def connection_message(text):
    return {
        "id": "msg_" + uuid4().hex,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
    async with AsyncExitStack() as stack:
        agent, error = await create_request_agent(stack, request)
        if error:
            return ResponsesAgentResponse(output=[connection_message(error)])
        messages = normalize_history_items([i.model_dump() for i in request.input])
        result = await Runner.run(agent, messages, max_turns=25)
        return ResponsesAgentResponse(output=[item.to_input_item() for item in result.new_items])


@stream()
async def stream_handler(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
    async with AsyncExitStack() as stack:
        agent, error = await create_request_agent(stack, request)
        if error:
            yield ResponsesAgentStreamEvent(type="response.output_item.done", item=connection_message(error))
            return
        messages = normalize_history_items([i.model_dump() for i in request.input])
        result = Runner.run_streamed(agent, input=messages, max_turns=25)

        async for event in process_agent_stream_events(result.stream_events()):
            yield event
