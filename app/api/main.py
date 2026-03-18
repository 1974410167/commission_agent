"""Commission Agent 的 FastAPI 入口。

这个文件尽量保持“薄”：
- `GET /` 只负责渲染演示页面；
- `POST /api/chat` 只负责把请求交给 Agent workflow；
- `POST /api/chat/reset` 只负责清理会话上下文。

真正的意图识别、参数归一化、权限校验、ES 查询、RAG 解释，
都放在 application 层，不在这里堆业务逻辑。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.schemas import ChatAPIResponse, ChatRequest, HealthResponse, ResetChatRequest, ResetChatResponse
from app.application.agent.checkpointer import dump_conversation_state, get_thread_config, reset_conversation_state
from app.application.agent.graph import get_agent_workflow
from app.application.agent.state import build_turn_input
from app.common.exceptions import LLMServiceError
from app.common.logging_utils import configure_project_logging, get_api_logger
from app.config.settings import get_settings
from app.domain.agent_models import UserContext
from app.web.demo_data import load_sample_conversations, resolve_demo_context


configure_project_logging()
app = FastAPI(title="Commission Agent", version="0.2.0")
settings = get_settings()
api_logger = get_api_logger()
templates = Jinja2Templates(directory=str(settings.project_root / "app" / "web" / "templates"))
app.mount(
    "/static",
    StaticFiles(directory=str(settings.project_root / "app" / "web" / "static")),
    name="static",
)


@app.get("/")
def index(request: Request):
    """渲染演示首页，并把可直接命中的样例 id 注入前端。"""
    default_conversation_id = f"demo-{int(time.time())}"
    api_logger.info("page_view | path=/ | conversation_id=%s", default_conversation_id)
    page_payload = {
        "defaultConversationId": default_conversation_id,
        "sampleContext": resolve_demo_context(),
        "sampleConversations": load_sample_conversations(),
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_conversation_id": default_conversation_id,
            "page_payload": page_payload,
        },
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """返回最小健康状态，供本地调试和脚本探活使用。"""
    api_logger.info("health_check | status=ok")
    return HealthResponse(status="ok")


@app.post("/api/chat", response_model=ChatAPIResponse)
def chat(request: ChatRequest) -> ChatAPIResponse:
    """执行一轮 Agent，并补充调试面板所需的 debug 字段。"""
    started_at = time.perf_counter()
    api_logger.info(
        "chat_request | conversation_id=%s | user_role=%s | bound_creator_id=%s | message=%s",
        request.conversation_id,
        request.user_role,
        request.bound_creator_id,
        request.message,
    )
    workflow = get_agent_workflow()
    try:
        result = workflow.invoke(
            build_turn_input(
                conversation_id=request.conversation_id,
                message=request.message,
                user_context=UserContext(
                    user_role=request.user_role,
                    bound_creator_id=request.bound_creator_id,
                ),
            ),
            config=get_thread_config(request.conversation_id),
        )
    except LLMServiceError as exc:
        api_logger.exception(
            "chat_failed | conversation_id=%s | reason=%s",
            request.conversation_id,
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response_payload = result["response"].model_dump()
    debug = response_payload.get("debug") or {}
    # 这里的 timing 是整次 HTTP 请求耗时，不是单独某个 ES 或 LLM 子步骤耗时。
    debug["timing"] = {
        "request_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "workflow_ms": round(sum(item.get("duration_ms", 0) for item in result.get("node_logs", [])), 2),
    }
    # 把当前会话快照一并返回给前端，便于右侧调试面板直观看到上下文继承效果。
    debug["conversation_snapshot"] = dump_conversation_state(workflow, request.conversation_id)
    debug["workflow_trace"] = result.get("node_logs", [])
    response_payload["debug"] = debug
    api_logger.info(
        "chat_response | conversation_id=%s | action=%s | intent=%s | selected_tool=%s | nlu_mode=%s | llm_provider=%s | chat_model=%s | request_ms=%s",
        request.conversation_id,
        response_payload.get("action"),
        response_payload.get("intent"),
        debug.get("selected_tool"),
        debug.get("nlu_mode"),
        debug.get("llm_provider"),
        debug.get("chat_model"),
        debug["timing"]["request_ms"],
    )
    return ChatAPIResponse(**response_payload)


@app.post("/api/chat/reset", response_model=ResetChatResponse)
def reset_chat(request: ResetChatRequest) -> ResetChatResponse:
    """清理指定 conversation_id 的内存会话状态。"""
    reset_conversation_state(request.conversation_id, settings)
    api_logger.info("chat_reset | conversation_id=%s", request.conversation_id)
    return ResetChatResponse(status="ok")
