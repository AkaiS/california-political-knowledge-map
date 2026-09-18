"""Local browser entry point for retrieval chat."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI
from pydantic import ValidationError
from pydantic_ai.ui.vercel_ai.request_types import (
    SubmitMessage,
    TextUIPart,
    ToolApprovalResponded,
    ToolApprovalRespondedPart,
)
from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    DoneChunk,
    FinishChunk,
    StartChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolApprovalRequestChunk,
    ToolInputAvailableChunk,
    ToolOutputAvailableChunk,
    ToolOutputDeniedChunk,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from knowledge_map.chat_presentation import render_answer, search_details
from knowledge_map.chat_startup import (
    ChatDependencies,
    chat_dependencies,
    new_chat_session,
)
from knowledge_map.schemas.query_preparation import (
    QuestionPreparationResult,
    RewriteRejection,
)
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.utils.agents import create_agent


class ChatSessionProtocol(Protocol):
    async def prepare(self) -> QuestionPreparationResult: ...

    def reject(self, correction: str | None = None) -> RewriteRejection: ...

    async def approve(self) -> RetrievalAnswer | EvidenceAssemblyFailure: ...


@dataclass
class BrowserSession:
    session: ChatSessionProtocol
    message_id: str | None = None
    approval_id: str | None = None
    awaiting_correction: bool = False


def create_app(
    *,
    startup: Callable[
        [], AbstractAsyncContextManager[ChatDependencies | None]
    ] = chat_dependencies,
    session_factory: Callable[
        [str, ChatDependencies | None], ChatSessionProtocol
    ] = new_chat_session,
) -> FastAPI:
    """Serve the stock frontend and adapt its messages to one Chat Session."""
    sessions: dict[str, BrowserSession] = {}
    dependencies: ChatDependencies | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal dependencies
        async with startup() as dependencies:
            yield
        sessions.clear()

    async def post_chat(request: Request) -> Response:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(
                {"error": "Expected Content-Type: application/json"}, status_code=415
            )
        try:
            submission = SubmitMessage.model_validate_json(await request.body())
        except ValidationError:
            return JSONResponse({"error": "Invalid chat message"}, status_code=422)
        options = submission.__pydantic_extra__ or {}
        if options.get("model") or options.get("builtinTools"):
            return JSONResponse(
                {"error": "Models and tools are fixed at application startup."},
                status_code=400,
            )
        if entry := sessions.get(submission.id):
            message = submission.messages[-1] if submission.messages else None
            if entry.awaiting_correction and message and message.role == "user":
                if not message.parts or any(
                    not isinstance(part, TextUIPart) for part in message.parts
                ):
                    return JSONResponse(
                        {"error": "Enter a text correction."}, status_code=422
                    )
                correction = "\n".join(
                    part.text for part in message.parts if isinstance(part, TextUIPart)
                ).strip()
                if not correction:
                    return JSONResponse(
                        {"error": "Enter a text correction."}, status_code=422
                    )
                entry.awaiting_correction = False
                entry.session.reject(correction)
                return prepare_response(entry)
            approvals = (
                [
                    part
                    for part in message.parts
                    if isinstance(part, ToolApprovalRespondedPart)
                    and part.type == "tool-Query approval"
                    and part.tool_call_id == entry.approval_id
                    and isinstance(part.approval, ToolApprovalResponded)
                    and part.approval.id == entry.approval_id
                ]
                if message
                and message.role == "assistant"
                and message.id == entry.message_id
                else []
            )
            if entry.approval_id is None or len(approvals) != 1:
                return JSONResponse(
                    {"error": "This question has no matching pending approval."},
                    status_code=409,
                )
            approval_id = entry.approval_id
            entry.approval_id = None
            decision = approvals[0].approval
            assert isinstance(decision, ToolApprovalResponded)
            if not decision.approved:
                entry.awaiting_correction = True

                async def rejection_stream() -> AsyncIterator[str]:
                    text_id = str(uuid4())
                    chunks: list[BaseChunk] = [
                        StartChunk(message_id=entry.message_id),
                        ToolOutputDeniedChunk(tool_call_id=approval_id),
                        TextStartChunk(id=text_id),
                        TextDeltaChunk(
                            id=text_id,
                            delta="Describe the change you want in your next message.",
                        ),
                        TextEndChunk(id=text_id),
                        FinishChunk(finish_reason="stop"),
                        DoneChunk(),
                    ]
                    for chunk in chunks:
                        yield f"data: {chunk.encode(sdk_version=7)}\n\n"

                return StreamingResponse(
                    rejection_stream(),
                    media_type="text/event-stream",
                    headers={
                        "x-vercel-ai-ui-message-stream": "v1",
                        "Cache-Control": "no-cache",
                    },
                )

            async def answer_stream() -> AsyncIterator[str]:
                operation_id = str(uuid4())
                starting: list[BaseChunk] = [
                    StartChunk(message_id=entry.message_id),
                    ToolOutputAvailableChunk(
                        tool_call_id=approval_id, output={"approved": True}
                    ),
                    ToolInputAvailableChunk(
                        tool_call_id=operation_id, tool_name="Search details", input={}
                    ),
                ]
                for chunk in starting:
                    yield f"data: {chunk.encode(sdk_version=7)}\n\n"
                result = await entry.session.approve()
                text = render_answer(result)
                text_id = str(uuid4())
                chunks: list[BaseChunk] = [
                    ToolOutputAvailableChunk(
                        tool_call_id=operation_id, output=search_details(result)
                    ),
                    TextStartChunk(id=text_id),
                    TextDeltaChunk(id=text_id, delta=text),
                    TextEndChunk(id=text_id),
                    FinishChunk(finish_reason="stop"),
                    DoneChunk(),
                ]
                for chunk in chunks:
                    yield f"data: {chunk.encode(sdk_version=7)}\n\n"

            return StreamingResponse(
                answer_stream(),
                media_type="text/event-stream",
                headers={
                    "x-vercel-ai-ui-message-stream": "v1",
                    "Cache-Control": "no-cache",
                },
            )
        if len(submission.messages) != 1 or submission.messages[0].role != "user":
            return JSONResponse(
                {"error": "Start a new chat to ask a question."}, status_code=409
            )
        message = submission.messages[0]
        if not message.parts or any(
            not isinstance(part, TextUIPart) for part in message.parts
        ):
            return JSONResponse({"error": "Enter a text question."}, status_code=422)
        question = "\n".join(
            part.text for part in message.parts if isinstance(part, TextUIPart)
        ).strip()
        if not question:
            return JSONResponse({"error": "Enter a text question."}, status_code=422)
        session = session_factory(question, dependencies)
        entry = BrowserSession(session)
        sessions[submission.id] = entry
        return prepare_response(entry)

    def prepare_response(entry: BrowserSession) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            result = await entry.session.prepare()
            message_id, call_id = str(uuid4()), str(uuid4())
            text = (
                result.message
                if result.status != "awaiting_approval"
                else "\n\n".join(
                    value
                    for value in (
                        result.approval.question,
                        result.approval.explanation,
                        result.approval.recoverable_portion,
                    )
                    if value
                )
            )
            chunks: list[BaseChunk] = [
                StartChunk(message_id=message_id),
                TextStartChunk(id=message_id),
                TextDeltaChunk(id=message_id, delta=text),
                TextEndChunk(id=message_id),
            ]
            if result.status == "awaiting_approval":
                entry.message_id = message_id
                entry.approval_id = call_id
                chunks.extend(
                    [
                        ToolInputAvailableChunk(
                            tool_call_id=call_id,
                            tool_name="Query approval",
                            input=result.approval.model_dump(exclude_none=True),
                        ),
                        ToolApprovalRequestChunk(
                            approval_id=call_id, tool_call_id=call_id
                        ),
                    ]
                )
            chunks.extend(
                [
                    FinishChunk(
                        finish_reason="tool-calls"
                        if result.status == "awaiting_approval"
                        else "stop"
                    ),
                    DoneChunk(),
                ]
            )
            for chunk in chunks:
                yield f"data: {chunk.encode(sdk_version=7)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "x-vercel-ai-ui-message-stream": "v1",
                "Cache-Control": "no-cache",
            },
        )

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    frontend = create_agent(name="local_chat_shell").to_web()
    frontend.router.routes.insert(0, Route("/api/chat", post_chat, methods=["POST"]))
    app.mount("/", frontend)
    return app
