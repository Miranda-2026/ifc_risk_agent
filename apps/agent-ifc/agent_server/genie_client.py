"""Request-local Genie Conversation API adapter, with no managed-MCP dependency.

The workspace client is injected, keeping result handling independently testable.
Only allowlisted evidence is returned; signed external download links stay private.
"""

import asyncio
from datetime import timedelta


def _as_dict(value):
    if value is None:
        return {}
    return value if isinstance(value, dict) else value.as_dict()


class GenieConversation:
    def __init__(self, client, space_id: str, row_limit: int = 500):
        if type(row_limit) is not int or row_limit <= 0:
            raise ValueError("row_limit must be a positive integer")
        self.client = client
        self.space_id = space_id
        self.row_limit = row_limit
        self.conversation_id = None
        self.timeout = timedelta(seconds=240)
        self._lock = asyncio.Lock()

    async def ask(self, question: str) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Provide a nonempty question for Genie.")
        # The SDK is synchronous. Keep the event loop responsive and serialize
        # parallel model tool calls so messages remain in the right conversation.
        async with self._lock:
            return await asyncio.to_thread(self._ask_sync, question)

    def _ask_sync(self, question):
        arguments = dict(space_id=self.space_id, content=question, timeout=self.timeout)
        if self.conversation_id is None:
            message = self.client.genie.start_conversation_and_wait(**arguments)
        else:
            message = self.client.genie.create_message_and_wait(
                conversation_id=self.conversation_id, **arguments
            )
        message = _as_dict(message)
        conversation_id = message.get("conversation_id") or self.conversation_id
        message_id = message.get("message_id") or message.get("id")
        if conversation_id:
            self.conversation_id = conversation_id
        response = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "status": message.get("status"),
            "text": [],
            "queries": [],
            "has_verified_sql": False,
        }
        if message.get("status") != "COMPLETED":
            response["message"] = "Genie did not complete this request; no result should be used as portfolio evidence."
            return response
        for attachment in message.get("attachments") or []:
            text = attachment.get("text") or {}
            if isinstance(text.get("content"), str):
                response["text"].append(text["content"])
            query = attachment.get("query")
            if not query:
                continue
            attachment_id = attachment.get("attachment_id")
            if not all((conversation_id, message_id, attachment_id)):
                response["queries"].append({"sql": query.get("query"), "data_available": False,
                                             "truncated": True, "status": "MISSING_ATTACHMENT_ID"})
                continue
            result = self.client.genie.get_message_attachment_query_result(
                space_id=self.space_id, conversation_id=conversation_id,
                message_id=message_id, attachment_id=attachment_id,
            )
            statement = _as_dict(result).get("statement_response") or {}
            response["queries"].append(self._query_evidence(query, statement))
        response["has_verified_sql"] = any(item["data_available"] for item in response["queries"])
        return response

    def _query_evidence(self, query, statement):
        manifest = statement.get("manifest") or {}
        result = statement.get("result") or {}
        metadata = query.get("query_result_metadata") or {}
        status = (statement.get("status") or {}).get("state")
        total = manifest.get("total_row_count")
        if total is None:
            total = metadata.get("row_count")
        data = result.get("data_array")
        available = status == "SUCCEEDED" and (isinstance(data, list) or total == 0)
        rows = data[:self.row_limit] if available and isinstance(data, list) else []
        truncated = bool(
            manifest.get("truncated") or metadata.get("is_truncated")
            or result.get("next_chunk_index") is not None
            or result.get("next_chunk_internal_link")
            or (manifest.get("total_chunk_count") or 0) > 1
            or (isinstance(data, list) and len(data) > self.row_limit)
            or (isinstance(total, int) and total > len(rows))
            or not available
        )
        columns = (manifest.get("schema") or {}).get("columns") or []
        return {
            "sql": query.get("query"),
            "statement_id": statement.get("statement_id") or query.get("statement_id"),
            "status": status,
            "columns": [{"name": col.get("name"), "type_name": col.get("type_name")} for col in columns],
            "rows": rows,
            "returned_row_count": len(rows),
            "total_row_count": total,
            "data_available": available,
            "truncated": truncated,
        }
