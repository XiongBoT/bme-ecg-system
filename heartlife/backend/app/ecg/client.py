from __future__ import annotations

import httpx
from fastapi import Depends
from pydantic import ValidationError

from app.core.config import Settings
from app.core.deps import get_settings
from app.core.errors import AppError
from app.ecg.schemas import ExchangeResult, SummaryResult


class EcgClient:
    """Fixed server-to-server origin, no redirects/proxy-env or browser credentials."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def _request(self, method: str, path: str, *, subject: str | None = None,
                 token: str | None = None, operation: str | None = None, **kwargs) -> httpx.Response:
        if not self.settings.is_ecg_integration_enabled:
            raise AppError(503, "ECG_DISABLED", "心电数据连接尚未启用")
        headers = {"X-HeartLife-Key": self.settings.ecg_client_secret}
        if subject:
            headers["X-HeartLife-Subject"] = subject
        if token:
            headers["Authorization"] = "Bearer " + token
        if operation:
            headers["X-HeartLife-Operation"] = operation
        try:
            with httpx.Client(base_url=self.settings.ecg_api_base_url, headers=headers,
                              timeout=5.0, follow_redirects=False, trust_env=False,
                              transport=self.transport) as client:
                # Bound response size; neither notes nor raw waveforms belong in this API.
                with client.stream(method, path, **kwargs) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 128 * 1024:
                            raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回内容异常")
                    return httpx.Response(response.status_code, content=bytes(body))
        except httpx.HTTPError as exc:
            raise AppError(503, "ECG_UNAVAILABLE", "心电服务暂时无法连接，请稍后重试") from exc

    @staticmethod
    def _data(response: httpx.Response, model):
        try:
            return model.model_validate_json(response.content)
        except (ValueError, ValidationError) as exc:
            raise AppError(502, "ECG_INVALID_RESPONSE", "心电服务返回内容异常") from exc

    def exchange(self, code: str, subject: str, operation: str) -> ExchangeResult:
        response = self._request("POST", "/api/heartlife/exchange", json={
            "code": code, "subject_id": subject, "operation_id": operation,
        })
        if response.status_code in (400, 401, 403, 404, 422):
            raise AppError(422, "ECG_CODE_INVALID", "绑定码无效或已过期，请在心电平台重新生成")
        if response.status_code == 409:
            raise AppError(409, "ECG_ALREADY_LINKED", "账号已存在关联，请先在心电平台撤销关联后重试")
        if response.status_code == 429:
            raise AppError(429, "ECG_RATE_LIMITED", "绑定尝试较多，请稍后再试")
        if response.status_code != 200:
            raise AppError(503, "ECG_UNAVAILABLE", "心电服务暂时无法连接，请稍后重试")
        return self._data(response, ExchangeResult)

    def summary(self, subject: str, token: str, params: dict) -> SummaryResult:
        response = self._request("GET", "/api/heartlife/summary", subject=subject, token=token, params=params)
        if response.status_code in (401, 403, 404):
            raise AppError(409, "ECG_LINK_EXPIRED", "心电授权已失效，请解除关联后重新绑定")
        if response.status_code == 422:
            raise AppError(422, "ECG_INVALID_PERIOD", "心电统计日期不合法")
        if response.status_code != 200:
            raise AppError(503, "ECG_UNAVAILABLE", "心电服务暂时无法连接，请稍后重试")
        return self._data(response, SummaryResult)

    def revoke_subject(self, subject: str, operation: str) -> bool:
        response = self._request("DELETE", "/api/heartlife/subject-grant", subject=subject, operation=operation)
        # Even a 401 is not success: the deployment key could have changed.
        if response.status_code != 200:
            return False
        try:
            return response.json().get("revoked") is True
        except (ValueError, AttributeError):
            return False

    def revoke_token(self, subject: str, token: str) -> bool:
        response = self._request("DELETE", "/api/heartlife/grant", subject=subject, token=token)
        if response.status_code != 200:
            return False
        try:
            return response.json().get("revoked") is True
        except (ValueError, AttributeError):
            return False


def get_ecg_client(settings: Settings = Depends(get_settings)) -> EcgClient:
    return EcgClient(settings)
