"""登录与会话接口（DEV-TASKS T8.4）。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import UnauthenticatedError
from app.db.session import get_web_session
from app.schemas.auth import CurrentUser, LoginRequest, TokenResponse
from app.services.auth import AuthService, AuthSession

router = APIRouter(prefix="/auth", tags=["auth"])

# auto_error=False：缺少 Authorization 头时返回 None，由下方统一抛我们的
# UnauthenticatedError（DATADICT-5000），避免 FastAPI 默认 403/直接 401 绕过错误码体系。
_bearer = HTTPBearer(auto_error=False)


def get_auth_service() -> AuthService:
    return AuthService()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="账号登录",
    description="校验用户名与密码，成功后签发 JWT。V0.1 简单登录，SSO/LDAP 接入见 PRD M10-1。",
)
async def login(
    payload: LoginRequest,
    session: Annotated[AuthSession, Depends(get_web_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await service.login(session, username=payload.username, password=payload.password)


async def get_current_user(
    session: Annotated[AuthSession, Depends(get_web_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise UnauthenticatedError("缺少 Bearer 令牌")
    return await service.current_user(session, token=credentials.credentials)


@router.get(
    "/me",
    response_model=CurrentUser,
    summary="当前登录用户",
    description="根据 Bearer 令牌返回当前用户资料，供前端会话保持与鉴权判断。",
)
async def me(current: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    return current
