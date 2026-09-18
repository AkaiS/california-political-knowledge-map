"""Local browser entry point for retrieval chat."""

import logging
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
    UIMessage,
)
from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    DoneChunk,
    ErrorChunk,
    FinishChunk,
    StartChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
    ToolApprovalRequestChunk,
    ToolInputAvailableChunk,
    ToolOutputAvailableChunk,
    ToolOutputDeniedChunk,
    ToolOutputErrorChunk,
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

logger = logging.getLogger(__name__)

NEW_CHAT_GUIDANCE = "Start a new chat to ask a question."
TERMINAL_FAILURE = f"This question could not be completed. {NEW_CHAT_GUIDANCE}"


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


def _composer_text(message: UIMessage) -> str | None:
    text_parts = [part for part in message.parts if isinstance(part, TextUIPart)]
    if not text_parts or len(text_parts) != len(message.parts):
        return None
    return "\n".join(part.text for part in text_parts).strip() or None


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
    terminal_conversations: set[str] = set()
    dependencies: ChatDependencies | None = None

    def finish_session(conversation_id: str) -> None:
        sessions.pop(conversation_id, None)
        terminal_conversations.add(conversation_id)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal dependencies
        try:
            async with startup() as dependencies:
                yield
        finally:
            sessions.clear()
            terminal_conversations.clear()
            dependencies = None

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
                rejected_proposal = (
                    submission.messages[-2] if len(submission.messages) >= 2 else None
                )
                if (
                    rejected_proposal is None
                    or rejected_proposal.role != "assistant"
                    or rejected_proposal.id != entry.message_id
                ):
                    return JSONResponse(
                        {"error": "This question has no matching rejected proposal."},
                        status_code=409,
                    )
                correction = _composer_text(message)
                if correction is None:
                    return JSONResponse(
                        {"error": "Enter a text correction."}, status_code=422
                    )
                entry.awaiting_correction = False
                return prepare_response(submission.id, entry, correction=correction)
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

            # The response owns the consumed session until its answer finishes.
            finish_session(submission.id)

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
                try:
                    for chunk in starting:
                        yield f"data: {chunk.encode(sdk_version=7)}\n\n"
                    result = await entry.session.approve()
                except Exception:
                    logger.exception("Chat Session approval failed")
                    failure_chunks: list[BaseChunk] = [
                        ToolOutputErrorChunk(
                            tool_call_id=operation_id, error_text=TERMINAL_FAILURE
                        ),
                        ErrorChunk(error_text=TERMINAL_FAILURE),
                        FinishChunk(finish_reason="stop"),
                        DoneChunk(),
                    ]
                    for chunk in failure_chunks:
                        yield f"data: {chunk.encode(sdk_version=7)}\n\n"
                    return
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
        if (
            submission.id in terminal_conversations
            or len(submission.messages) != 1
            or submission.messages[0].role != "user"
        ):
            return JSONResponse({"error": NEW_CHAT_GUIDANCE}, status_code=409)
        message = submission.messages[0]
        question = _composer_text(message)
        if question is None:
            return JSONResponse({"error": "Enter a text question."}, status_code=422)
        session = session_factory(question, dependencies)
        entry = BrowserSession(session)
        sessions[submission.id] = entry
        return prepare_response(submission.id, entry)

    def prepare_response(
        conversation_id: str, entry: BrowserSession, *, correction: str | None = None
    ) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            try:
                if correction is not None:
                    entry.session.reject(correction)
                result = await entry.session.prepare()
            except Exception:
                logger.exception("Chat Session preparation failed")
                finish_session(conversation_id)
                failure_chunks: list[BaseChunk] = [
                    StartChunk(message_id=str(uuid4())),
                    ErrorChunk(error_text=TERMINAL_FAILURE),
                    FinishChunk(finish_reason="stop"),
                    DoneChunk(),
                ]
                for chunk in failure_chunks:
                    yield f"data: {chunk.encode(sdk_version=7)}\n\n"
                return
            except BaseException:
                finish_session(conversation_id)
                raise
            if result.status != "awaiting_approval":
                finish_session(conversation_id)
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
