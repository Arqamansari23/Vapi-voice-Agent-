"""Consistent JSON envelope: {"data": ..., "error": null} / {"data": null, "error": {...}}."""

from typing import Any

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise anywhere in a request to return an enveloped error response."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def success(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": data, "error": None})


def failure(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": message, "details": details}},
    )
