"""Vapi integration: the transport layer between Vapi and our tool handlers.

Vapi POSTs here when the LLM calls one of our function tools:

    {"message": {"type": "tool-calls", "call": {...},
                 "toolCallList": [{"id": "...", "function": {"name": "...", "arguments": {...}}}]}}

and expects HTTP 200 with:

    {"results": [{"toolCallId": "...", "result": "<string the LLM reads>"}]}

Any non-200 status makes the assistant say "no result returned", so errors
are always returned *inside* the result string rather than as HTTP errors.
"""

import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.orm import Session

from app.agent_tools import SAVE_FAILED, TOOL_HANDLERS
from app.config import settings
from app.database import get_db
from app.responses import ApiError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


def _verify_secret(provided: str | None) -> None:
    # Vapi's custom credential may send "Bearer <secret>" if the prefix toggle is on.
    token = (provided or "").strip().removeprefix("Bearer ").strip()
    if settings.vapi_secret and not hmac.compare_digest(token, settings.vapi_secret):
        raise ApiError(401, "unauthorized", "Invalid or missing X-Vapi-Secret header")


def _parse_arguments(raw: Any) -> dict:
    """Arguments normally arrive as an object, but tolerate a JSON string too."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@router.post("/tools")
def handle_tool_calls(
    payload: dict = Body(...),
    x_vapi_secret: str | None = Header(None),
    db: Session = Depends(get_db),
) -> dict:
    _verify_secret(x_vapi_secret)
    message = payload.get("message") or {}
    call_id = (message.get("call") or {}).get("id")

    results = []
    for tool_call in message.get("toolCallList") or []:
        function = tool_call.get("function") or {}
        name = function.get("name")
        args = _parse_arguments(function.get("arguments"))
        logger.info("tool_call call_id=%s tool=%s args=%s", call_id, name, json.dumps(args))

        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            result = f"ERROR: Unknown tool '{name}'."
        else:
            try:
                result = handler(db, args)
            except Exception:  # never let an exception turn into silence on the phone
                logger.exception("Tool %s failed (call_id=%s)", name, call_id)
                db.rollback()
                result = SAVE_FAILED

        logger.info("tool_result call_id=%s tool=%s result=%s", call_id, name, result)
        results.append({"toolCallId": tool_call.get("id"), "result": result})

    return {"results": results}


@router.post("/webhook")
def handle_server_event(payload: dict = Body(...), x_vapi_secret: str | None = Header(None)) -> dict:
    """Assistant-level server messages: call status changes and the end-of-call report.

    This is how dropped calls are observable: the report includes `endedReason`
    (e.g. "customer-ended-call") and the transcript, even if nothing was saved.
    """
    _verify_secret(x_vapi_secret)
    message = payload.get("message") or {}
    event = message.get("type")
    call_id = (message.get("call") or {}).get("id")

    if event == "status-update":
        logger.info("call_status call_id=%s status=%s", call_id, message.get("status"))
    elif event == "end-of-call-report":
        artifact = message.get("artifact") or {}
        analysis = message.get("analysis") or {}
        logger.info(
            "call_ended call_id=%s reason=%s summary=%s\ntranscript:\n%s",
            call_id,
            message.get("endedReason"),
            analysis.get("summary") or message.get("summary"),
            artifact.get("transcript") or message.get("transcript"),
        )
    else:
        logger.debug("vapi_event type=%s call_id=%s", event, call_id)
    return {}
