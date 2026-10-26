"""统一异常与错误码。

错误码格式 `DATADICT-<四位>`，按域分段：
    1xxx 通用    2xxx 数据源与采集    3xxx 标注    4xxx 检索    5xxx 权限
错误码一旦对外发布就不再变更含义——它会被 API 消费方写进重试/告警逻辑。
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger


class ErrorCode(StrEnum):
    # 1xxx 通用
    INTERNAL_ERROR = "DATADICT-1000"
    INVALID_PARAM = "DATADICT-1001"
    NOT_FOUND = "DATADICT-1002"
    CONFLICT = "DATADICT-1003"
    INVALID_URN = "DATADICT-1004"

    # 2xxx 数据源与采集
    DATASOURCE_NOT_FOUND = "DATADICT-2000"
    UNSUPPORTED_DATASOURCE = "DATADICT-2001"
    DATASOURCE_CONNECT_FAILED = "DATADICT-2002"
    DATASOURCE_PERMISSION_DENIED = "DATADICT-2003"
    SYNC_ALREADY_RUNNING = "DATADICT-2004"
    COLLECT_TIMEOUT = "DATADICT-2005"

    # 3xxx 标注
    ANNOTATION_NOT_FOUND = "DATADICT-3000"
    # 试图通过标注接口写入采集层字段（raw_type / column_name 等）。
    # 见 DEV-TASKS T5.1 验收标准。
    ANNOTATION_READONLY_FIELD = "DATADICT-3001"
    ANNOTATION_MERGE_CONFLICT = "DATADICT-3002"
    ANNOTATION_BATCH_FAILED = "DATADICT-3003"

    # 4xxx 检索
    QUERY_TOO_SHORT = "DATADICT-4000"

    # 5xxx 权限
    UNAUTHENTICATED = "DATADICT-5000"
    FORBIDDEN = "DATADICT-5001"


class DataDictError(Exception):
    """所有业务异常的基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: ErrorCode = ErrorCode.INVALID_PARAM

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(DataDictError):
    status_code = status.HTTP_404_NOT_FOUND
    code = ErrorCode.NOT_FOUND


class ConflictError(DataDictError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.CONFLICT


class ForbiddenError(DataDictError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.FORBIDDEN


class UnauthenticatedError(DataDictError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = ErrorCode.UNAUTHENTICATED


# Starlette 把 HTTP_422_UNPROCESSABLE_ENTITY 改名为 ..._CONTENT 并弃用了旧名，
# 直接用字面量避免跟着上游改名走。
HTTP_422 = 422


class InvalidUrnError(DataDictError):
    status_code = HTTP_422
    code = ErrorCode.INVALID_URN


class UnsupportedDataSourceError(DataDictError):
    code = ErrorCode.UNSUPPORTED_DATASOURCE


class SyncAlreadyRunningError(ConflictError):
    code = ErrorCode.SYNC_ALREADY_RUNNING


class AnnotationReadonlyFieldError(DataDictError):
    """标注接口收到了采集层字段。

    采集层与知识层的隔离有三道防线：数据库角色权限（最硬）、写入路径分离、
    以及这里的接口层校验。三道都要有——数据库那道拦不住"web 角色误改采集表"。
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = ErrorCode.ANNOTATION_READONLY_FIELD


class AnnotationBatchError(DataDictError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = ErrorCode.ANNOTATION_BATCH_FAILED


def _error_body(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if detail:
        body["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DataDictError)
    async def _handle_datadict_error(_: Request, exc: DataDictError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_422,
            content=_error_body(
                ErrorCode.INVALID_PARAM, "请求参数校验失败", {"errors": exc.errors()}
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 未预期异常一律记完整堆栈，但不把内部信息返回给调用方
        logger.opt(exception=exc).error(
            "未处理异常 method={} path={}", request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(ErrorCode.INTERNAL_ERROR, "服务内部错误"),
        )
