import logging
import json
import os
import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import mlflow
from agents import Agent, Runner, function_tool, set_default_openai_api, set_default_openai_client
from agents.tracing import set_trace_processors
from databricks.sdk import WorkspaceClient
from databricks_openai import AsyncDatabricksOpenAI
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

from agent_server.history import normalize_history_items
from agent_server.connection_errors import classify_connection_error
from agent_server.genie_client import GenieConversation
from agent_server.ui_contract import CARD_INSTRUCTIONS, normalize_weights
from agent_server.utils import (
    get_session_id,
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


def create_agent(portfolio_tool=None, request=None) -> Agent:
    settings = (request.custom_inputs or {}) if request else {}
    weights = normalize_weights(settings.get("weights"))
    instructions = ANALYST_PROMPT + "\n\n" + CARD_INSTRUCTIONS
    instructions += "\nLatest UI scoring weights (percent): " + json.dumps(weights)
    instructions += "\nUI mode: " + str(settings.get("ui_mode", "chat"))
    instructions += "\nUse query_ifc_portfolio to obtain real SQL and results through the native Genie Conversation API. If a tool returns an error, unavailable data, or truncated rows, do not invent values or rank clients from that partial population. Request an SQL aggregation/ranking over the full eligible population and return only the needed summary rows."
    return Agent(
        name="IFC Investment Intelligence",
        instructions=instructions,
        model=os.getenv("IFC_MODEL_ENDPOINT", "databricks-gpt-oss-20b"),
        tools=[get_current_time] + ([portfolio_tool] if portfolio_tool else []),
    )


async def create_request_agent(request):
    """Use native Genie APIs; Managed MCP Servers preview is not required."""
    space_id = os.getenv("IFC_GENIE_SPACE_ID", "").strip()
    if not space_id:
        return None, "The portfolio data connection is not configured yet. Connect your IFC Genie Agent to enable quantitative analysis and client recommendations. No portfolio figures or recommendations have been generated."
    try:
        client = WorkspaceClient()
        await asyncio.to_thread(client.genie.get_space, space_id=space_id)
    except Exception as error:
        issue = classify_connection_error(error)
        logger.warning("IFC Genie access check failed [%s]: %s", issue.code, issue.message, exc_info=True)
        return None, f"Genie connection failed [{issue.code}]. {issue.message}"
    conversation = GenieConversation(client, space_id)

    @function_tool
    async def query_ifc_portfolio(question: str) -> str:
        """Ask IFC Genie to query portfolio, news or industry tables with SQL.

        Request explicit SQL calculations and the resulting rows. Check returned
        query completeness before using the data for comparisons or rankings.
        """
        try:
            evidence = await conversation.ask(question)
        except Exception as error:
            issue = classify_connection_error(error)
            logger.warning("IFC Genie query failed [%s]: %s", issue.code, issue.message, exc_info=True)
            evidence = {"error": issue.code, "message": issue.message, "has_verified_sql": False}
        return json.dumps(evidence, ensure_ascii=False)

    return create_agent(query_ifc_portfolio, request), None


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
    agent, error = await create_request_agent(request)
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
    agent, error = await create_request_agent(request)
    if error:
        yield ResponsesAgentStreamEvent(type="response.output_item.done", item=connection_message(error))
        return
    messages = normalize_history_items([i.model_dump() for i in request.input])
    result = Runner.run_streamed(agent, input=messages, max_turns=25)

    async for event in process_agent_stream_events(result.stream_events()):
        yield event
