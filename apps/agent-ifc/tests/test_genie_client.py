"""Exercise native Genie evidence retrieval without Databricks dependencies."""

import asyncio
import copy
import json
import threading
import unittest
from datetime import timedelta
from types import SimpleNamespace

from agent_server.genie_client import GenieConversation


class SDKObject:
    def __init__(self, value):
        self.value = value

    def as_dict(self):
        return copy.deepcopy(self.value)


def make_message(conversation_id="conversation-A", message_id="message-1", **changes):
    message = {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "status": "COMPLETED",
        "content": "The original user question",
        "attachments": [
            {"attachment_id": "text-1", "text": {"content": "Portfolio query completed."}},
            {
                "attachment_id": "query-1",
                "query": {
                    "query": "SELECT client_id, disbursed_musd FROM client_metrics",
                    "statement_id": "statement-1",
                },
            },
        ],
    }
    message.update(changes)
    return message


def make_result(rows=None, total_row_count=None):
    rows = [["CL-1", "12.50"]] if rows is None else rows
    if total_row_count is None:
        total_row_count = len(rows)
    return {
        "statement_response": {
            "statement_id": "statement-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {
                "schema": {
                    "columns": [
                        {"name": "client_id", "type_name": "STRING"},
                        {"name": "disbursed_musd", "type_name": "DECIMAL"},
                    ]
                },
                "total_row_count": total_row_count,
                "truncated": False,
            },
            "result": {"data_array": rows, "row_count": len(rows)},
        }
    }


class FakeWait:
    """Match SDK callback ordering, including the final FAILED poll."""

    def __init__(self, message, calls, plan=None):
        self.message = message
        self.calls = calls
        self.plan = plan or {}
        value = message if isinstance(message, dict) else message.as_dict()
        initial = self.plan.get("initial", {
            "conversation_id": value.get("conversation_id"),
            "message_id": value.get("message_id") or value.get("id"),
        })
        self.response = SDKObject(initial)

    def result(self, *, timeout, callback=None):
        self.calls.append(("wait", timeout, callable(callback)))
        for update in self.plan.get("updates", []):
            if callback:
                callback(SDKObject(update))
        if self.plan.get("error"):
            raise self.plan["error"]
        return self.message


class FakeGenie:
    """The SDK surface is synchronous, including calls from asyncio.to_thread."""

    def __init__(self, messages=None, result=None, wait_plans=None):
        self.messages = list(messages or [make_message()])
        self.result = make_result() if result is None else result
        self.calls = []
        self.start_error = None
        self.wait_plans = list(wait_plans or [])

    def start_conversation(self, space_id, content):
        self.calls.append(("start", space_id, content))
        if self.start_error:
            raise self.start_error
        return self._next_waiter()

    def create_message(self, space_id, conversation_id, content):
        self.calls.append(("followup", space_id, conversation_id, content))
        return self._next_waiter()

    def _next_waiter(self):
        plan = self.wait_plans.pop(0) if self.wait_plans else None
        return FakeWait(self.messages.pop(0), self.calls, plan)

    def get_message_attachment_query_result(self, space_id, conversation_id, message_id, attachment_id):
        self.calls.append(("result", space_id, conversation_id, message_id, attachment_id))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class GenieConversationTest(unittest.IsolatedAsyncioTestCase):
    def make_conversation(self, genie=None, **kwargs):
        genie = genie or FakeGenie()
        client = SimpleNamespace(genie=genie)
        return GenieConversation(client, "space-123", **kwargs), genie

    async def test_returns_sql_and_actual_result_values(self):
        conversation, genie = self.make_conversation()
        answer = await conversation.ask("Show the client metrics")

        self.assertEqual(answer["conversation_id"], "conversation-A")
        self.assertEqual(answer["message_id"], "message-1")
        self.assertEqual(answer["status"], "COMPLETED")
        self.assertEqual(answer["text"], ["Portfolio query completed."])
        self.assertTrue(answer["has_verified_sql"])
        query = answer["queries"][0]
        self.assertEqual(query["sql"], "SELECT client_id, disbursed_musd FROM client_metrics")
        self.assertEqual(query["statement_id"], "statement-1")
        self.assertEqual(query["columns"], [
            {"name": "client_id", "type_name": "STRING"},
            {"name": "disbursed_musd", "type_name": "DECIMAL"},
        ])
        self.assertEqual(query["rows"], [["CL-1", "12.50"]])
        self.assertEqual(query["returned_row_count"], 1)
        self.assertEqual(query["total_row_count"], 1)
        self.assertFalse(query["truncated"])
        self.assertTrue(query["data_available"])
        self.assertEqual(query["status"], "SUCCEEDED")
        self.assertEqual(genie.calls[0], ("start", "space-123", "Show the client metrics"))
        self.assertEqual(genie.calls[1], ("wait", timedelta(seconds=240), True))
        self.assertEqual(genie.calls[2], ("result", "space-123", "conversation-A", "message-1", "query-1"))

    async def test_accepts_sdk_as_dict_responses(self):
        conversation, _ = self.make_conversation(FakeGenie(
            messages=[SDKObject(make_message())], result=SDKObject(make_result())
        ))
        answer = await conversation.ask("Show metrics")
        self.assertTrue(answer["has_verified_sql"])
        self.assertEqual(answer["queries"][0]["rows"], [["CL-1", "12.50"]])

    async def test_followups_use_this_conversations_returned_id(self):
        genie = FakeGenie(messages=[make_message(), make_message(message_id="message-2")])
        conversation, _ = self.make_conversation(genie)
        await conversation.ask("Initial question")
        await conversation.ask("Explain that result")

        followup = next(call for call in genie.calls if call[0] == "followup")
        self.assertEqual(followup, (
            "followup", "space-123", "conversation-A", "Explain that result"
        ))
        self.assertEqual(sum(call[0] == "start" for call in genie.calls), 1)
        self.assertEqual([call for call in genie.calls if call[0] == "wait"], [
            ("wait", timedelta(seconds=240), True), ("wait", timedelta(seconds=240), True)
        ])

    async def test_separate_conversations_do_not_share_ids(self):
        genie = FakeGenie(messages=[
            make_message("conversation-A"),
            make_message("conversation-B"),
            make_message("conversation-A", "message-A2"),
            make_message("conversation-B", "message-B2"),
        ])
        first, _ = self.make_conversation(genie)
        second, _ = self.make_conversation(genie)
        await first.ask("User A initial")
        await second.ask("User B initial")
        await first.ask("User A follow-up")
        await second.ask("User B follow-up")
        followups = [call for call in genie.calls if call[0] == "followup"]
        self.assertEqual([call[2] for call in followups], ["conversation-A", "conversation-B"])

    async def test_flags_each_source_of_incomplete_results(self):
        cases = ("genie_metadata", "manifest", "next_chunk", "total_rows")
        for source in cases:
            with self.subTest(source=source):
                message = make_message()
                result = make_result()
                statement = result["statement_response"]
                if source == "genie_metadata":
                    message["attachments"][1]["query"]["query_result_metadata"] = {"is_truncated": True}
                elif source == "manifest":
                    statement["manifest"]["truncated"] = True
                elif source == "next_chunk":
                    statement["result"]["next_chunk_index"] = 1
                else:
                    statement["manifest"]["total_row_count"] = 2
                conversation, _ = self.make_conversation(FakeGenie([message], result))
                answer = await conversation.ask("Show metrics")
                self.assertTrue(answer["queries"][0]["truncated"])

    async def test_caps_rows_and_discloses_local_truncation(self):
        rows = [[f"CL-{index}", "12.50"] for index in range(3)]
        conversation, _ = self.make_conversation(FakeGenie(result=make_result(rows)), row_limit=2)
        answer = await conversation.ask("Show metrics")
        query = answer["queries"][0]
        self.assertEqual(query["rows"], rows[:2])
        self.assertEqual(query["returned_row_count"], 2)
        self.assertEqual(query["total_row_count"], 3)
        self.assertTrue(query["truncated"])

    async def test_exact_local_limit_can_still_be_complete(self):
        rows = [["CL-1", "12.50"], ["CL-2", "22.50"]]
        conversation, _ = self.make_conversation(FakeGenie(result=make_result(rows)), row_limit=2)
        answer = await conversation.ask("Show metrics")
        self.assertFalse(answer["queries"][0]["truncated"])

    async def test_missing_expected_data_is_unavailable(self):
        result = make_result(total_row_count=2)
        del result["statement_response"]["result"]["data_array"]
        conversation, _ = self.make_conversation(FakeGenie(result=result))
        answer = await conversation.ask("Show metrics")
        query = answer["queries"][0]
        self.assertFalse(query["data_available"])
        self.assertFalse(answer["has_verified_sql"])
        self.assertEqual(query["rows"], [])
        self.assertTrue(query["truncated"])

    async def test_successful_zero_row_query_is_available(self):
        conversation, _ = self.make_conversation(FakeGenie(result=make_result([])))
        answer = await conversation.ask("Show matching clients")
        query = answer["queries"][0]
        self.assertTrue(query["data_available"])
        self.assertTrue(answer["has_verified_sql"])
        self.assertEqual(query["rows"], [])
        self.assertEqual(query["total_row_count"], 0)
        self.assertFalse(query["truncated"])

    async def test_unsuccessful_statement_does_not_verify_rows(self):
        result = make_result()
        result["statement_response"]["status"]["state"] = "FAILED"
        conversation, _ = self.make_conversation(FakeGenie(result=result))
        answer = await conversation.ask("Show metrics")
        self.assertFalse(answer["queries"][0]["data_available"])
        self.assertFalse(answer["has_verified_sql"])

    async def test_message_failure_does_not_fetch_query_evidence(self):
        conversation, genie = self.make_conversation(FakeGenie([
            make_message(status="FAILED", error={
                "type": "WAREHOUSE_ACCESS_MISSING_EXCEPTION", "error": "Private warehouse failure"
            })
        ]))
        answer = await conversation.ask("Show metrics")
        self.assertEqual(answer["status"], "FAILED")
        self.assertFalse(answer["has_verified_sql"])
        self.assertFalse(any(call[0] == "result" for call in genie.calls))

    async def test_failed_poll_retains_category_and_initial_identifiers(self):
        failed = make_message(status="FAILED", error={
            "type": "WAREHOUSE_ACCESS_MISSING_EXCEPTION", "error": "PRIVATE_WAREHOUSE_DETAIL"
        })
        failed.pop("conversation_id")
        failed.pop("message_id")
        genie = FakeGenie(wait_plans=[{
            "initial": {"conversation_id": "created-conversation", "message_id": "created-message"},
            "updates": [failed],
            "error": RuntimeError("failed to reach COMPLETED, got MessageStatus.FAILED"),
        }])
        conversation, _ = self.make_conversation(genie)
        answer = await conversation.ask("Show metrics")
        self.assertEqual(answer["status"], "FAILED")
        self.assertEqual(answer["error"], "GENIE/WAREHOUSE_ACCESS_MISSING_EXCEPTION")
        self.assertEqual(answer["genie_error_type"], "WAREHOUSE_ACCESS_MISSING_EXCEPTION")
        self.assertEqual(answer["conversation_id"], "created-conversation")
        self.assertEqual(answer["message_id"], "created-message")
        self.assertIn("warehouse", answer["message"].lower())
        self.assertFalse(answer["has_verified_sql"])
        self.assertEqual(answer["queries"], [])
        self.assertNotIn("PRIVATE_WAREHOUSE_DETAIL", json.dumps(answer))

    async def test_unknown_failed_detail_is_not_leaked(self):
        failed = make_message(status="FAILED", error={
            "type": "UNKNOWN_PRIVATE_ERROR_TYPE", "error": "SECRET_ACCESS_TOKEN=abc123"
        })
        genie = FakeGenie(wait_plans=[{
            "updates": [failed], "error": RuntimeError("Generic SDK failure")
        }])
        conversation, _ = self.make_conversation(genie)
        with self.assertLogs("agent_server.genie_client", level="WARNING") as logs:
            answer = await conversation.ask("Show metrics")
        self.assertEqual(answer["error"], "GENIE_QUERY_FAILED")
        self.assertFalse(answer["has_verified_sql"])
        self.assertNotIn("SECRET_ACCESS_TOKEN", json.dumps(answer))
        self.assertNotIn("UNKNOWN_PRIVATE_ERROR_TYPE", json.dumps(answer))
        self.assertNotIn("abc123", "\n".join(logs.output))
        self.assertIn("[REDACTED]", "\n".join(logs.output))

    async def test_followup_failed_poll_preserves_its_message_id(self):
        failed = make_message(message_id="message-2", status="FAILED", error={
            "type": "COULD_NOT_GET_UC_SCHEMA_EXCEPTION", "error": "PRIVATE_SCHEMA_DETAIL"
        })
        genie = FakeGenie(messages=[make_message(), make_message(message_id="message-2")], wait_plans=[
            {}, {"updates": [failed], "error": RuntimeError("SDK operation failed")}
        ])
        conversation, _ = self.make_conversation(genie)
        await conversation.ask("Initial metrics")
        answer = await conversation.ask("Explain these figures")
        self.assertEqual(answer["error"], "GENIE/COULD_NOT_GET_UC_SCHEMA_EXCEPTION")
        self.assertEqual(answer["message_id"], "message-2")
        self.assertEqual(answer["conversation_id"], "conversation-A")
        self.assertIn("schema", answer["message"].lower())
        self.assertFalse(answer["has_verified_sql"])

    async def test_sql_failure_is_reported_as_sql_execution(self):
        failed = make_message(status="FAILED", error={
            "type": "SQL_EXECUTION_EXCEPTION", "error": "PRIVATE_SQL_DETAIL"
        })
        conversation, _ = self.make_conversation(FakeGenie(wait_plans=[{
            "updates": [failed], "error": RuntimeError("SDK operation failed")
        }]))
        answer = await conversation.ask("Calculate rankings")
        self.assertEqual(answer["error"], "GENIE/SQL_EXECUTION_EXCEPTION")
        self.assertIn("sql", answer["message"].lower())
        self.assertNotIn("PRIVATE_SQL_DETAIL", json.dumps(answer))

    async def test_transport_error_after_pending_poll_propagates(self):
        conversation, _ = self.make_conversation(FakeGenie(wait_plans=[{
            "updates": [make_message(status="FETCHING_METADATA")],
            "error": RuntimeError("Connection was interrupted"),
        }]))
        with self.assertRaisesRegex(RuntimeError, "Connection was interrupted"):
            await conversation.ask("Show metrics")

    async def test_wait_timeout_remains_a_timeout(self):
        conversation, _ = self.make_conversation(FakeGenie(wait_plans=[{
            "updates": [make_message(status="PENDING_WAREHOUSE")],
            "error": TimeoutError("Timed out waiting for Genie"),
        }]))
        with self.assertRaises(TimeoutError):
            await conversation.ask("Show metrics")

    async def test_cancelled_and_expired_polls_return_without_waiting_for_timeout(self):
        for status in ("CANCELLED", "QUERY_RESULT_EXPIRED"):
            with self.subTest(status=status):
                genie = FakeGenie(wait_plans=[{
                    "updates": [make_message(status=status)],
                    "error": TimeoutError("The waiter would otherwise continue polling"),
                }])
                conversation, _ = self.make_conversation(genie)
                answer = await conversation.ask("Show metrics")
                self.assertEqual(answer["status"], status)
                self.assertFalse(answer["has_verified_sql"])
                self.assertEqual(answer["queries"], [])
                self.assertFalse(any(call[0] == "result" for call in genie.calls))

    async def test_initial_ids_are_retained_when_completed_message_omits_them(self):
        message = make_message()
        message.pop("conversation_id")
        message.pop("message_id")
        genie = FakeGenie(messages=[message], wait_plans=[{
            "initial": {"conversation_id": "created-conversation", "message_id": "created-message"}
        }])
        conversation, _ = self.make_conversation(genie)
        answer = await conversation.ask("Show metrics")
        self.assertEqual(answer["conversation_id"], "created-conversation")
        self.assertEqual(answer["message_id"], "created-message")
        self.assertTrue(answer["has_verified_sql"])
        self.assertEqual(next(call for call in genie.calls if call[0] == "result"),
                         ("result", "space-123", "created-conversation", "created-message", "query-1"))

    async def test_legacy_message_id_is_supported(self):
        message = make_message()
        del message["message_id"]
        message["id"] = "legacy-message-1"
        conversation, genie = self.make_conversation(FakeGenie([message]))
        answer = await conversation.ask("Show metrics")
        self.assertEqual(answer["message_id"], "legacy-message-1")
        result_call = next(call for call in genie.calls if call[0] == "result")
        self.assertEqual(result_call[3], "legacy-message-1")

    async def test_output_allowlist_excludes_signed_urls_and_raw_results(self):
        result = make_result()
        result["statement_response"]["result"]["external_links"] = [{
            "external_link": "https://storage.example.com/result?signature=SECRET_SIGNATURE"
        }]
        result["statement_response"]["secret_backend_field"] = "SECRET_BACKEND_VALUE"
        message = make_message()
        message["unrelated_backend_field"] = "SECRET_MESSAGE_VALUE"
        conversation, _ = self.make_conversation(FakeGenie([message], result))
        answer = await conversation.ask("Show metrics")
        serialized = json.dumps(answer)
        for secret in ["SECRET_SIGNATURE", "SECRET_BACKEND_VALUE", "SECRET_MESSAGE_VALUE", "external_links"]:
            self.assertNotIn(secret, serialized)

    async def test_empty_questions_fail_without_sdk_requests(self):
        for question in ["", " \n\t "]:
            with self.subTest(question=question):
                conversation, genie = self.make_conversation()
                with self.assertRaises(ValueError):
                    await conversation.ask(question)
                self.assertEqual(genie.calls, [])

    async def test_sdk_failures_propagate_to_the_tool_handler(self):
        genie = FakeGenie()
        genie.start_error = RuntimeError("Start operation failed")
        conversation, _ = self.make_conversation(genie)
        with self.assertRaisesRegex(RuntimeError, "Start operation failed"):
            await conversation.ask("Show metrics")

        conversation, _ = self.make_conversation(FakeGenie(result=RuntimeError("Result operation failed")))
        with self.assertRaisesRegex(RuntimeError, "Result operation failed"):
            await conversation.ask("Show metrics")

    async def test_parallel_asks_are_serialized_and_reuse_the_conversation(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingGenie(FakeGenie):
            def start_conversation(self, space_id, content):
                started.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("Test did not release the first SDK call")
                return super().start_conversation(space_id, content)

        genie = BlockingGenie(messages=[make_message(), make_message(message_id="message-2")])
        conversation, _ = self.make_conversation(genie)
        first = asyncio.create_task(conversation.ask("First question"))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            second = asyncio.create_task(conversation.ask("Second question"))
            await asyncio.sleep(0)
        finally:
            release.set()
        await asyncio.gather(first, second)
        operations = [call[0] for call in genie.calls if call[0] in {"start", "followup"}]
        self.assertEqual(operations, ["start", "followup"])
        self.assertEqual(next(call for call in genie.calls if call[0] == "followup")[2], "conversation-A")


if __name__ == "__main__":
    unittest.main()
