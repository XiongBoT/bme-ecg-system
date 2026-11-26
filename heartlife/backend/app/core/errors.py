from __future__ import annotations

import logging
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("heartlife")


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def get_request_id(request: Request) -> str:
    req_id = getattr(request.state, "request_id", None)
    if not req_id:
        req_id = uuid.uuid4().hex[:16]
        request.state.request_id = req_id
    return req_id


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    req_id = get_request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": req_id,
            }
        },
        headers={"X-Request-Id": req_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first_msg = "请求参数不合法"
        errors = exc.errors()
        if errors:
            loc = ".".join(str(part) for part in errors[0].get("loc", []) if part != "body")
            msg = errors[0].get("msg", "参数校验失败")
            first_msg = f"{loc}: {msg}" if loc else msg
        return error_response(request, 422, "VALIDATION_ERROR", first_msg)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        code_map = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "SERVICE_UNAVAILABLE",
        }
        detail = exc.detail if isinstance(exc.detail, str) else "请求被拒绝"
        return error_response(request, exc.status_code, code_map.get(exc.status_code, "HTTP_ERROR"), detail)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        req_id = get_request_id(request)
        logger.error("Unhandled server error request_id=%s type=%s", req_id, type(exc).__name__)
        return error_response(request, 500, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试")
