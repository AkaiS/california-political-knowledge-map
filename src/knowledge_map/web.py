"""Local FastAPI entry point for Source Guides."""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from importlib.resources import files
from typing import Literal, Protocol

import logfire
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from knowledge_map.chat_presentation import render_answer, source_guide
from knowledge_map.chat_startup import (
    ChatDependencies,
    chat_dependencies,
    new_chat_session,
)
from knowledge_map.schemas.query_preparation import QuestionAssessment, QuestionText
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.schemas.source_guides import SourceGuide
from knowledge_map.utils.agents import create_agent

logger = logging.getLogger(__name__)


class QuestionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: QuestionText


class ChatSessionProtocol(Protocol):
    chat_session_id: str
    assessment: QuestionAssessment | None
    stage: Literal["assessment", "retrieval", "guidance"]

    async def run(
        self,
    ) -> RetrievalAnswer | EvidenceAssemblyFailure | QuestionAssessment: ...


def create_app(
    *,
    startup: Callable[
        [], AbstractAsyncContextManager[ChatDependencies | None]
    ] = chat_dependencies,
    session_factory: Callable[
        [str, ChatDependencies | None], ChatSessionProtocol
    ] = new_chat_session,
    browser_url: str | None = None,
) -> FastAPI:
    dependencies: ChatDependencies | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal dependencies
        try:
            async with startup() as dependencies:
                if browser_url is not None:
                    print(f"Open {browser_url} in your browser.", flush=True)
                yield
        finally:
            dependencies = None

    async def submit_question(request: Request) -> Response:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(
                {"error": "Expected Content-Type: application/json"}, status_code=415
            )
        try:
            submission = QuestionSubmission.model_validate_json(await request.body())
        except ValidationError:
            return JSONResponse(
                {"error": "Enter a complete text question."}, status_code=422
            )
        session = session_factory(submission.question, dependencies)
        try:
            result = await session.run()
        except Exception:
            logger.exception("Source Guide %s failed", session.stage)
            status = {
                "assessment": "assessment_failed",
                "retrieval": "retrieval_failed",
                "guidance": "guidance_failed",
            }[session.stage]
            guide = SourceGuide.model_validate(
                {
                    "question": submission.question,
                    "status": status,
                    "assessment": session.assessment,
                    "message": {
                        "assessment": "The question could not be assessed. Try submitting it again.",
                        "retrieval": "The search could not be completed. Try submitting the question again.",
                        "guidance": "Reading directions could not be prepared. The retrieved articles have not passed the relevance check. Try submitting the question again.",
                    }[session.stage],
                }
            )
            return JSONResponse(guide.model_dump(mode="json", exclude_none=True))
        if isinstance(result, QuestionAssessment):
            assert result.status in {"declined", "needs_edit"}
            guide = SourceGuide(
                question=submission.question,
                status=result.status,
                assessment=result,
                message=result.explanation,
            )
        else:
            guide = source_guide(result)
            if isinstance(result, RetrievalAnswer):
                logfire.info(
                    "chat_session.answer_prepared",
                    chat_session_id=session.chat_session_id,
                    audit_schema_version=2,
                    rendered_text=render_answer(result),
                    selected_sources=[
                        {
                            "citation": source.citation.model_dump(mode="json"),
                            "passages": [
                                {
                                    "chunk_id": passage.candidate.chunk_id,
                                    "text": passage.text,
                                    "provenance": passage.provenance,
                                }
                                for passage in source.passages
                            ],
                        }
                        for source in result.evidence.sources
                    ],
                )
        return JSONResponse(guide.model_dump(mode="json", exclude_none=True))

    async def coverage(request: Request) -> Response:
        return JSONResponse(
            dependencies.coverage.model_dump(mode="json", exclude_none=True)
            if dependencies
            else {"entries": []}
        )

    async def asset(request: Request) -> Response:
        filename, media_type = {
            "/": ("index.html", "text/html"),
            "/guide.js": ("guide.js", "text/javascript"),
            "/guide.css": ("guide.css", "text/css"),
        }[request.url.path]
        return Response(
            files("knowledge_map")
            .joinpath("resources/source-guides", filename)
            .read_text(),
            media_type=media_type,
            headers={
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            },
        )

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    frontend = create_agent(name="local_guide_shell").to_web()
    frontend.router.routes[:] = [
        Route("/api/questions", submit_question, methods=["POST"]),
        Route("/api/coverage", coverage, methods=["GET"]),
        *(
            Route(path, asset, methods=["GET"])
            for path in ("/", "/guide.js", "/guide.css")
        ),
    ]
    app.mount("/", frontend)
    return app
