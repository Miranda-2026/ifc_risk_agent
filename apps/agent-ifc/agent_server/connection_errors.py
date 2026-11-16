"""Safe connection diagnostics. Never send raw credentials or exception text to a model."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ConnectionIssue:
    code: str
    message: str


_GENIE_MESSAGES = {
    "COULD_NOT_GET_UC_SCHEMA_EXCEPTION": "Genie could not read the Unity Catalog schema. Check the App service principal's USE CATALOG, USE SCHEMA and SELECT permissions and the tables configured in Genie.",
    "WAREHOUSE_ACCESS_MISSING_EXCEPTION": "Genie could not access its SQL warehouse. Grant the App service principal Can use on the warehouse selected in the Genie Agent's Settings.",
    "WAREHOUSE_NOT_FOUND_EXCEPTION": "The SQL warehouse configured for Genie was not found. Check the warehouse selection in the Genie Agent's Settings.",
    "SQL_EXECUTION_EXCEPTION": "Genie reached SQL execution, but the query failed. Inspect the detailed Genie error in App Logs; this status alone does not prove a connection or permissions problem.",
    "TABLES_MISSING_EXCEPTION": "Genie reported missing source tables. Check the tables configured in the Genie Agent and whether the App identity can read them.",
    "NO_TABLES_TO_QUERY_EXCEPTION": "Genie has no available tables to query. Check the configured tables and the App identity's data access.",
    "DESCRIBE_QUERY_INVALID_SQL_ERROR": "Genie generated a query that could not be described. Inspect the SQL error in App Logs before changing connection settings.",
    "INVALID_SQL_UNKNOWN_TABLE_EXCEPTION": "Genie's generated SQL references an unknown table. Check its table configuration and SQL details in App Logs.",
    "REPLY_PROCESS_TIMEOUT_EXCEPTION": "Genie timed out while processing the question. Retry a narrower query and check the configured warehouse.",
    "CHAT_COMPLETION_CLIENT_TIMEOUT_EXCEPTION": "Genie's model call timed out. Retry a narrower question.",
    "DESCRIBE_QUERY_TIMEOUT": "Genie timed out while describing the query. Check the SQL warehouse and retry.",
    "RATE_LIMIT_EXCEEDED_GENERIC_EXCEPTION": "Genie rate-limited the request. Please retry later.",
    "RATE_LIMIT_EXCEEDED_SPECIFIED_WAIT_EXCEPTION": "Genie rate-limited the request. Please retry later.",
}


def classify_genie_message_error(error_type, status="FAILED") -> ConnectionIssue:
    """Use Genie's explicit enum; never infer access failures from FAILED alone."""
    if isinstance(error_type, str) and error_type in _GENIE_MESSAGES:
        return ConnectionIssue("GENIE/" + error_type, _GENIE_MESSAGES[error_type])
    if status == "CANCELLED":
        return ConnectionIssue("GENIE_CANCELLED", "The Genie request was cancelled; it returned no verified query result.")
    if status == "QUERY_RESULT_EXPIRED":
        return ConnectionIssue("GENIE_RESULT_EXPIRED", "The Genie query result expired. Request a fresh query result.")
    return ConnectionIssue("GENIE_QUERY_FAILED", "Genie accepted the request but could not complete it. The cause is not yet identified. Inspect the Genie error details in App Logs; do not infer that the database is disconnected or that permissions are missing.")


def redact_error_detail(value) -> str:
    """Retain a bounded server-side failure reason without credential/config dumps."""
    if not isinstance(value, str):
        return "No detailed reason was supplied by Genie."
    value = re.split(r"\bConfig:\s*", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.sub(r"https?://[^\s<>]+", "[URL omitted]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", value)
    value = re.sub(r'''(?ix)(["']?(?:[a-z_]*token|[a-z_]*secret|password|authorization|api[_-]?key)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r"\1[REDACTED]", value)
    return value.replace("\r", " ").replace("\n", " ")[:1200]


_MESSAGES = {
    "AUTHENTICATION_FAILED": "The App could not authenticate to Databricks. Check its app authorization configuration.",
    "PERMISSION_DENIED": "The App was denied access. In agent-ifc Settings > Resources, check Genie Can run, SQL warehouse access, and the catalog/schema/table permissions of the App service principal.",
    "NOT_FOUND": "The requested Genie resource was not found or is not visible to the App. Check the configured workspace, Space ID, and Genie resource access.",
    "TIMEOUT": "The Genie request timed out. Retry a narrower question and inspect the latest App logs.",
    "RATE_LIMITED": "Genie temporarily rejected the request because of rate limits. Please retry later.",
    "SERVICE_ERROR": "Databricks returned a service error. Please retry and inspect the latest App logs.",
    "CONNECTION_FAILED": "The Genie request failed. Check the underlying exception in the App Logs; no verified data was returned.",
}
_STATUS_CODES = {401: "AUTHENTICATION_FAILED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
                 408: "TIMEOUT", 429: "RATE_LIMITED", 504: "TIMEOUT"}
_SDK_CODES = {"UNAUTHENTICATED": "AUTHENTICATION_FAILED", "PERMISSION_DENIED": "PERMISSION_DENIED",
              "NOT_FOUND": "NOT_FOUND", "RESOURCE_DOES_NOT_EXIST": "NOT_FOUND",
              "DEADLINE_EXCEEDED": "TIMEOUT", "REQUEST_LIMIT_EXCEEDED": "RATE_LIMITED"}
_TYPE_CODES = {"Unauthenticated": "AUTHENTICATION_FAILED", "PermissionDenied": "PERMISSION_DENIED",
               "NotFound": "NOT_FOUND", "ResourceDoesNotExist": "NOT_FOUND",
               "TooManyRequests": "RATE_LIMITED", "DeadlineExceeded": "TIMEOUT"}


def classify_connection_error(error: BaseException) -> ConnectionIssue:
    """Inspect typed error metadata, including nested SDK/task-group failures."""
    queue, seen, sdk_codes, timeouts, statuses = [error], set(), [], False, set()
    while queue and len(seen) < 64:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        for owner in (current, getattr(current, "response", None)):
            status = getattr(owner, "status_code", None)
            if type(status) is int and 400 <= status <= 599:
                statuses.add(status)
        sdk_code = _SDK_CODES.get(getattr(current, "error_code", None)) or _TYPE_CODES.get(type(current).__name__)
        if sdk_code:
            sdk_codes.append(sdk_code)
        if isinstance(current, TimeoutError) or type(current).__name__ in {
            "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException"
        }:
            timeouts = True
        queue.extend(child for child in getattr(current, "exceptions", ()) if isinstance(child, BaseException))
        cause = current.__cause__
        if cause is not None:
            queue.append(cause)
        elif current.__context__ is not None and not current.__suppress_context__:
            queue.append(current.__context__)
    if len(statuses) > 1:
        return ConnectionIssue("MULTIPLE_HTTP_ERRORS", "Databricks connection attempts returned HTTP " +
                               ", ".join(map(str, sorted(statuses))) + ". Inspect the App logs for the primary failure.")
    if statuses:
        status = statuses.pop()
        code = _STATUS_CODES.get(status, "SERVICE_ERROR" if status >= 500 else "CONNECTION_FAILED")
        return ConnectionIssue(f"{code}/HTTP_{status}", _MESSAGES[code])
    code = sdk_codes[0] if sdk_codes else "TIMEOUT" if timeouts else "CONNECTION_FAILED"
    return ConnectionIssue(code, _MESSAGES[code])
