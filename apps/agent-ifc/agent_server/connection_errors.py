"""Safe connection diagnostics. Never send raw credentials or exception text to a model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionIssue:
    code: str
    message: str


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
