import json

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

class ResponseWrapperMiddleware(BaseHTTPMiddleware):
    """把非流式 JSON 响应包成统一信封 {code,data,message}。

    跳过包装的条件（满足任一即可，优先级从高到低）：
      1. 请求路径是 OpenAPI 文档相关路径（/openapi.json、/docs、/redoc 等）
      2. request.state.is_stream = True（SSE/WS/文件流，endpoint 手动设置）
      3. request.state.is_exception_handled = True（异常处理器已经构造好信封）
      4. response.headers["X-Error-Handled"] = "1"（header 级兜底标记）
      5. body 已经是 {code,data,message} 三字段齐全的信封（success_response / 旧版接口兼容）
      6. content-type 不是 application/json（重定向/纯文本/文件下载等）
    """

    @staticmethod
    def _is_docs_request(request: Request) -> bool:
        """判断是否 OpenAPI 文档相关请求，这类响应必须原样返回。

        Swagger UI / ReDoc 会直接解析 /openapi.json 根级的 openapi、info、paths 字段。
        一旦被包成 {code,data,message}，openapi 版本号就沉到了 data 里，
        Swagger UI 会报：
            The provided definition does not specify a valid version field.

        这里从 app 上读取实际配置的路径，而不是写死字符串，
        这样 docs_url / openapi_url / redoc_url 被改成别的值时依然生效，
        关闭文档（值为 None）时也不会误伤同名的业务路由。
        """
        app = request.app
        docs_paths = (
            getattr(app, "openapi_url", None),
            getattr(app, "docs_url", None),
            getattr(app, "redoc_url", None),
            getattr(app, "swagger_ui_oauth2_redirect_url", None),
        )
        path = request.url.path
        return any(
            p and (path == p or path.startswith(f"{p}/")) for p in docs_paths
        )

    @staticmethod
    def _is_already_envelope(payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and "code" in payload
            and "data" in payload
            and "message" in payload
        )

    @staticmethod
    def _filtered_headers(response: Response, drop: tuple[str, ...] = ()) -> dict[str, str]:
        """拷贝响应头，去掉指定的 key（大小写不敏感）。"""
        drop_set = {"content-length", *drop}
        return {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in drop_set
        }

    @classmethod
    def _rebuild(cls, response: Response, body: bytes) -> Response:
        """用已读出的字节原样重建响应。

        response.body_iterator 是一次性异步生成器（starlette/middleware/base.py 的
        body_stream），读过之后再返回原 response 只会发出空 body。
        同时必须丢掉旧的 content-length，否则长度与实际 body 不符会被截断。
        """
        return Response(
            content=body,
            status_code=response.status_code,
            headers=cls._filtered_headers(response),
            media_type=response.headers.get("content-type"),
        )

    @classmethod
    def _envelope_response(cls, wrapped: dict, response: Response) -> JSONResponse:
        """构造统一信封响应。

        丢掉旧 content-length / content-type，交给 JSONResponse 按新 body 重算，
        否则 starlette 的 init_headers 会沿用旧长度导致响应被截断。
        """
        return JSONResponse(
            content=wrapped,
            status_code=response.status_code,
            headers=cls._filtered_headers(response, drop=("content-type",)),
            media_type="application/json; charset=utf-8",
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # --- 快速判定：状态 & header 级标记，不必读 body ---
        if self._is_docs_request(request):
            return response
        if getattr(request.state, "is_stream", False):
            return response
        if getattr(request.state, "is_exception_handled", False):
            return response
        # header级标记，证明已经处理这个错误了。一般是公司内部是自定义的
        if response.headers.get("X-Error-Handled") == "1":
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # --- 必须读 body 的场景：需要判断内容是否已是信封 ---
        # ⚠️ 这里的 response 并不是 endpoint 当初返回的那个对象。
        # BaseHTTPMiddleware.call_next 先用 anyio 内存流截获 ASGI 消息，再统一重新包成
        # starlette.middleware.base._StreamingResponse 返回（base.py:190-192），
        # 而该类的 __init__ 里就赋值了 body_iterator（base.py:218）。
        # 也就是说：JSONResponse / RedirectResponse / FileResponse / 真 StreamingResponse
        # 到了这里都已经被换成同一种 _StreamingResponse，全都带 body_iterator。
        # 因此下面这个保护目前是**不可达**的，普通 JSON 响应一定会继续往下走包装逻辑；
        # 保留它只是为了防 call_next 行为变更，不要指望它能过滤掉某类响应。
        if not hasattr(response, "body_iterator"):
            return response

        try:
            body_chunks = [chunk async for chunk in response.body_iterator]
            raw_body = b"".join(body_chunks)
        except Exception:  # noqa: BLE001 - 任何读取失败都直接原封不动返回，宁可漏包也不能打断用户
            return response

        if not raw_body:
            # 空 body（比如 204 No Content），包一层空 data
            return self._envelope_response(
                {"code": 0, "data": None, "message": "ok"}, response
            )

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return self._rebuild(response, raw_body)  # 非法 JSON，原样回吐

        if self._is_already_envelope(payload):
            return self._rebuild(response, raw_body)  # 已是信封，原样回吐

        return self._envelope_response(
            {"code": 0, "data": payload, "message": "ok"}, response
        )
