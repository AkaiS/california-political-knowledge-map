"""Local FastAPI entry point for Source Guides."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal, Protocol

import logfire
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from knowledge_map.adapters.source_guides import GuideAlreadyRunning, SQLiteGuideStore
from knowledge_map.chat_presentation import (
    assessment_guide,
    render_answer,
    source_guide,
)
from knowledge_map.chat_startup import (
    ChatDependencies,
    chat_dependencies,
    new_chat_session,
)
from knowledge_map.schemas.query_preparation import QuestionAssessment, QuestionText
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.schemas.source_guides import SavedSourceGuide, SourceGuide
from knowledge_map.utils.agents import create_agent

logger = logging.getLogger(__name__)


class QuestionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: QuestionText


class GuideUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    guide_db_path: str | Path | None = None,
) -> FastAPI:
    dependencies: ChatDependencies | None = None
    guide_store = SQLiteGuideStore(guide_db_path)
    running: set[asyncio.Task[None]] = set()
    accepting = False

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal dependencies, accepting
        try:
            async with startup() as dependencies:
                if browser_url is not None:
                    print(f"Open {browser_url} in your browser.", flush=True)
                accepting = True
                try:
                    yield
                finally:
                    accepting = False
                    for task in running:
                        task.cancel()
                    await asyncio.gather(*running, return_exceptions=True)
        finally:
            dependencies = None

    def json_content_type_error(request: Request) -> Response | None:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse(
                {"error": "Expected Content-Type: application/json"}, status_code=415
            )
        return None

    def stopping_service_error() -> Response | None:
        if not accepting:
            return JSONResponse(
                {"error": "The local service is stopping."}, status_code=503
            )
        return None

    async def submit_question(request: Request) -> Response:
        if error := json_content_type_error(request):
            return error
        try:
            submission = QuestionSubmission.model_validate_json(await request.body())
        except ValidationError:
            return JSONResponse(
                {"error": "Enter a complete text question."}, status_code=422
            )
        if error := stopping_service_error():
            return error
        saved = guide_store.create(submission.question)
        return start_execution(saved)

    async def update_guide(request: Request) -> Response:
        if error := json_content_type_error(request):
            return error
        try:
            GuideUpdate.model_validate_json(await request.body())
        except ValidationError:
            return JSONResponse(
                {"error": "Update guide uses its saved question and settings."},
                status_code=422,
            )
        if error := stopping_service_error():
            return error
        try:
            saved = guide_store.start_update(request.path_params["guide_id"])
        except KeyError:
            return JSONResponse({"error": "Source Guide not found."}, status_code=404)
        except GuideAlreadyRunning:
            return JSONResponse(
                {
                    "error": "This guide is already being searched. Wait for it to finish before updating."
                },
                status_code=409,
            )
        return start_execution(saved)

    def start_execution(saved: SavedSourceGuide) -> Response:
        task = asyncio.create_task(execute(saved))
        running.add(task)
        task.add_done_callback(running.discard)
        return JSONResponse(
            saved.model_dump(mode="json", exclude_none=True),
            status_code=202,
            headers={"Location": f"/api/guides/{saved.guide_id}"},
        )

    async def execute(saved: SavedSourceGuide) -> None:
        session = None
        try:
            session = session_factory(saved.question, dependencies)
            result = await session.run()
        except asyncio.CancelledError:
            guide_store.finish(
                saved.guide_id,
                saved.latest_attempt.attempt_id,
                SourceGuide(
                    question=saved.question,
                    status="interrupted",
                    message="This search was interrupted before it finished.",
                ),
            )
            raise
        except Exception:
            stage = session.stage if session is not None else "assessment"
            logger.exception("Source Guide %s failed", stage)
            status = {
                "assessment": "assessment_failed",
                "retrieval": "retrieval_failed",
                "guidance": "guidance_failed",
            }[stage]
            guide = SourceGuide.model_validate(
                {
                    "question": saved.question,
                    "status": status,
                    "assessment": session.assessment if session is not None else None,
                    "message": {
                        "assessment": "The question could not be assessed. Try submitting it again.",
                        "retrieval": "The search could not be completed. Try submitting the question again.",
                        "guidance": "Reading directions could not be prepared. The retrieved articles have not passed the relevance check. Try submitting the question again.",
                    }[stage],
                }
            )
        else:
            if isinstance(result, QuestionAssessment):
                guide = assessment_guide(saved.question, result)
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
        guide_store.finish(saved.guide_id, saved.latest_attempt.attempt_id, guide)

    async def list_guides(request: Request) -> Response:
        return JSONResponse(
            {
                "guides": [
                    guide.model_dump(
                        mode="json", exclude_none=True, exclude={"articles", "message"}
                    )
                    for guide in guide_store.list()
                ]
            }
        )

    async def read_guide(request: Request) -> Response:
        try:
            guide = guide_store.get(request.path_params["guide_id"])
        except KeyError:
            return JSONResponse({"error": "Source Guide not found."}, status_code=404)
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
        Route("/api/guides", list_guides, methods=["GET"]),
        Route("/api/guides/{guide_id}", read_guide, methods=["GET"]),
        Route("/api/guides/{guide_id}/update", update_guide, methods=["POST"]),
        Route("/api/coverage", coverage, methods=["GET"]),
        *(
            Route(path, asset, methods=["GET"])
            for path in ("/", "/guide.js", "/guide.css")
        ),
    ]
    app.mount("/", frontend)
    return app
