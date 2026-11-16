import unittest
from types import SimpleNamespace

from agent_server.connection_errors import classify_connection_error, classify_genie_message_error, redact_error_detail


class ConnectionErrorTest(unittest.TestCase):
    def test_nested_http_error_is_reported_without_response_body(self):
        inner = RuntimeError("secret-token-should-not-leak")
        inner.response = SimpleNamespace(status_code=403, text="private response")
        result = classify_connection_error(ExceptionGroup("task group", [ValueError("cleanup"), inner]))
        self.assertEqual(result.code, "PERMISSION_DENIED/HTTP_403")
        self.assertNotIn("secret-token", result.message)
        self.assertNotIn("private response", result.message)

    def test_typed_http_statuses(self):
        for status, name in [(401, "AUTHENTICATION_FAILED"), (404, "NOT_FOUND"),
                             (429, "RATE_LIMITED"), (500, "SERVICE_ERROR"), (504, "TIMEOUT")]:
            with self.subTest(status=status):
                error = RuntimeError()
                error.status_code = status
                self.assertEqual(classify_connection_error(error).code, f"{name}/HTTP_{status}")

    def test_sdk_permission_error(self):
        error = RuntimeError("raw config with secret")
        error.error_code = "PERMISSION_DENIED"
        self.assertEqual(classify_connection_error(error).code, "PERMISSION_DENIED")

    def test_timeout_and_wrapped_causes(self):
        outer = RuntimeError()
        outer.__cause__ = TimeoutError("private URL")
        self.assertEqual(classify_connection_error(outer).code, "TIMEOUT")

    def test_cyclic_causes_terminate(self):
        first, second = RuntimeError(), RuntimeError()
        first.__cause__, second.__cause__ = second, first
        self.assertEqual(classify_connection_error(first).code, "CONNECTION_FAILED")

    def test_conflicting_statuses_are_not_misrepresented(self):
        first, second = RuntimeError(), RuntimeError()
        first.status_code, second.status_code = 403, 404
        result = classify_connection_error(ExceptionGroup("multiple", [first, second]))
        self.assertEqual(result.code, "MULTIPLE_HTTP_ERRORS")
        self.assertIn("403, 404", result.message)

    def test_exception_text_is_not_used_or_interpreted_as_a_status(self):
        class PrivateError(Exception):
            def __str__(self):
                raise AssertionError("Exception text must not be read")
        self.assertEqual(classify_connection_error(PrivateError()).code, "CONNECTION_FAILED")
        self.assertEqual(classify_connection_error(RuntimeError("Secret contains 403")).code, "CONNECTION_FAILED")

    def test_genie_error_categories_do_not_conflate_sql_and_permissions(self):
        warehouse = classify_genie_message_error("WAREHOUSE_ACCESS_MISSING_EXCEPTION")
        self.assertIn("Can use", warehouse.message)
        schema = classify_genie_message_error("COULD_NOT_GET_UC_SCHEMA_EXCEPTION")
        self.assertIn("USE SCHEMA", schema.message)
        sql = classify_genie_message_error("SQL_EXECUTION_EXCEPTION")
        self.assertIn("query failed", sql.message)
        unknown = classify_genie_message_error("UNRECOGNIZED_ERROR")
        self.assertEqual(unknown.code, "GENIE_QUERY_FAILED")
        self.assertIn("cause is not yet identified", unknown.message)

    def test_server_reason_omits_credentials_urls_and_config(self):
        value = 'Schema denied; token=SECRET_A client_secret="SECRET B" Authorization: Bearer SECRET_C https://example.test?signature=SECRET_D Config: secret=SECRET_E'
        redacted = redact_error_detail(value)
        for secret in ["SECRET_A", "SECRET B", "SECRET_C", "SECRET_D", "SECRET_E"]:
            self.assertNotIn(secret, redacted)
        self.assertIn("Schema denied", redacted)
        self.assertLessEqual(len(redact_error_detail("x" * 2000)), 1200)


if __name__ == "__main__":
    unittest.main()
