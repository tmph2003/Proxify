"""Export captured requests to various formats: JSON, HAR, Python, cURL."""

import json
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse


def export_to_json(requests: list[dict], pretty: bool = True) -> str:
    """Export requests to JSON format."""
    cleaned = []
    for req in requests:
        entry = {
            "id": req.get("id"),
            "timestamp": req.get("timestamp"),
            "method": req.get("method"),
            "url": req.get("url"),
            "domain": req.get("domain"),
            "status_code": req.get("status_code"),
            "duration_ms": req.get("duration_ms"),
            "request": {
                "headers": req.get("request_headers", {}),
                "body": req.get("request_body"),
                "content_type": req.get("request_content_type"),
            },
            "response": {
                "headers": req.get("response_headers", {}),
                "body": req.get("response_body"),
                "content_type": req.get("response_content_type"),
                "size": req.get("response_size"),
            },
        }
        if req.get("is_graphql"):
            entry["graphql"] = {
                "operation": req.get("graphql_operation"),
                "doc_id": req.get("graphql_doc_id"),
                "variables": _safe_json_parse(req.get("graphql_variables")),
            }
        cleaned.append(entry)

    indent = 2 if pretty else None
    return json.dumps(cleaned, indent=indent, ensure_ascii=False, default=str)


def export_to_har(requests: list[dict]) -> str:
    """Export requests to HAR 1.2 format (importable by Chrome DevTools)."""
    entries = []
    for req in requests:
        # Parse request headers into HAR format
        req_headers = _headers_to_har(req.get("request_headers", {}))
        resp_headers = _headers_to_har(req.get("response_headers", {}))

        # Parse query string
        parsed = urlparse(req.get("url", ""))
        query_params = []
        if parsed.query:
            for k, v_list in parse_qs(parsed.query, keep_blank_values=True).items():
                for v in v_list:
                    query_params.append({"name": k, "value": v})

        # Build post data
        post_data = None
        if req.get("request_body"):
            mime_type = req.get("request_content_type", "")
            post_data = {
                "mimeType": mime_type,
                "text": req["request_body"],
            }
            # Parse form data params
            if "x-www-form-urlencoded" in mime_type:
                params = []
                for k, v_list in parse_qs(
                    req["request_body"], keep_blank_values=True
                ).items():
                    for v in v_list:
                        params.append({"name": k, "value": v})
                post_data["params"] = params

        entry = {
            "startedDateTime": req.get("timestamp", datetime.now().isoformat()),
            "time": req.get("duration_ms", 0) or 0,
            "request": {
                "method": req.get("method", "GET"),
                "url": req.get("url", ""),
                "httpVersion": "HTTP/2.0",
                "headers": req_headers,
                "queryString": query_params,
                "cookies": [],
                "headersSize": -1,
                "bodySize": len(req.get("request_body", "") or ""),
            },
            "response": {
                "status": req.get("status_code", 0),
                "statusText": "",
                "httpVersion": "HTTP/2.0",
                "headers": resp_headers,
                "cookies": [],
                "content": {
                    "size": req.get("response_size", 0),
                    "mimeType": req.get("response_content_type", ""),
                    "text": req.get("response_body", ""),
                },
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": req.get("response_size", 0),
            },
            "cache": {},
            "timings": {
                "send": 0,
                "wait": req.get("duration_ms", 0) or 0,
                "receive": 0,
            },
        }

        if post_data:
            entry["request"]["postData"] = post_data

        entries.append(entry)

    har = {
        "log": {
            "version": "1.2",
            "creator": {"name": "RequestCapture", "version": "0.1.0"},
            "entries": entries,
        }
    }
    return json.dumps(har, indent=2, ensure_ascii=False, default=str)


def export_to_python(requests: list[dict]) -> str:
    """Export requests as Python `requests` library code."""
    lines = ["import requests", ""]

    for i, req in enumerate(requests):
        method = req.get("method", "GET").lower()
        url = req.get("url", "")
        headers = req.get("request_headers", {})
        body = req.get("request_body")

        # Remove internal/automatic headers
        skip_headers = {
            "content-length", "host", "connection", "accept-encoding",
            "transfer-encoding",
        }
        filtered_headers = {
            k: v for k, v in (headers if isinstance(headers, dict) else {}).items()
            if k.lower() not in skip_headers
        }

        lines.append(f"# Request #{req.get('id', i + 1)}: {method.upper()} {req.get('domain', '')}{req.get('path', '')}")

        # Build cookies dict from cookie header
        cookies_dict = {}
        cookie_header = None
        for k, v in filtered_headers.items():
            if k.lower() == "cookie":
                cookie_header = k
                for pair in v.split("; "):
                    if "=" in pair:
                        ck, cv = pair.split("=", 1)
                        cookies_dict[ck.strip()] = cv.strip()

        if cookie_header:
            del filtered_headers[cookie_header]

        if cookies_dict:
            lines.append(f"cookies_{i} = {_format_dict(cookies_dict)}")
            lines.append("")

        if filtered_headers:
            lines.append(f"headers_{i} = {_format_dict(filtered_headers)}")
            lines.append("")

        # Build data/params
        data_var = None
        if body and req.get("request_content_type", "").startswith(
            "application/x-www-form-urlencoded"
        ):
            try:
                parsed_body = {}
                for k, v_list in parse_qs(body, keep_blank_values=True).items():
                    parsed_body[k] = v_list[0] if len(v_list) == 1 else v_list
                lines.append(f"data_{i} = {_format_dict(parsed_body)}")
                lines.append("")
                data_var = f"data_{i}"
            except Exception:
                lines.append(f"data_{i} = {repr(body)}")
                lines.append("")
                data_var = f"data_{i}"
        elif body:
            try:
                json_body = json.loads(body)
                lines.append(f"json_{i} = {_format_dict(json_body)}")
                lines.append("")
                data_var = f"json_{i}"
            except (json.JSONDecodeError, TypeError):
                lines.append(f"data_{i} = {repr(body)}")
                lines.append("")
                data_var = f"data_{i}"

        # Build the request call
        args = [repr(url)]
        if cookies_dict:
            args.append(f"cookies=cookies_{i}")
        if filtered_headers:
            args.append(f"headers=headers_{i}")
        if data_var:
            if data_var.startswith("json_"):
                args.append(f"json={data_var}")
            else:
                args.append(f"data={data_var}")

        call_args = ", ".join(args)
        lines.append(f"response_{i} = requests.{method}({call_args})")
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def export_to_curl(requests: list[dict]) -> str:
    """Export requests as cURL commands."""
    commands = []

    for req in requests:
        method = req.get("method", "GET")
        url = req.get("url", "")
        headers = req.get("request_headers", {})
        body = req.get("request_body")

        parts = ["curl"]

        if method != "GET":
            parts.append(f"-X {method}")

        parts.append(f"'{url}'")

        # Headers
        skip_headers = {"content-length", "host", "connection"}
        for k, v in (headers if isinstance(headers, dict) else {}).items():
            if k.lower() not in skip_headers:
                escaped_v = v.replace("'", "'\\''")
                parts.append(f"-H '{k}: {escaped_v}'")

        # Body
        if body:
            escaped_body = body.replace("'", "'\\''")
            if len(escaped_body) > 2000:
                escaped_body = escaped_body[:2000] + "... [truncated]"
            parts.append(f"--data-raw '{escaped_body}'")

        commands.append(
            f"# Request #{req.get('id', '?')}: {method} {req.get('domain', '')}{req.get('path', '')}\n"
            + " \\\n  ".join(parts)
        )

    return "\n\n".join(commands)


def _headers_to_har(headers: Any) -> list[dict]:
    """Convert headers dict to HAR format."""
    if isinstance(headers, dict):
        return [{"name": k, "value": v} for k, v in headers.items()]
    return []


def _safe_json_parse(s: Optional[str]) -> Any:
    """Parse JSON string, returning the string itself on failure."""
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def _format_dict(d: dict) -> str:
    """Format a dict as a readable Python literal."""
    if not d:
        return "{}"
    lines = ["{"]
    for k, v in d.items():
        lines.append(f"    {repr(k)}: {repr(v)},")
    lines.append("}")
    return "\n".join(lines)
