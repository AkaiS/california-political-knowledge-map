"""Local FastAPI entry point for Source Guides."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

import logfire
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from knowledge_map.adapters.source_guides import GuideAlreadyRunning, SQLiteGuideStore
from knowledge_map.chat_presentation import (
    assessment_guide,
    deferred_disclosures,
    guide_collections,
    guide_publication_orders,
    render_answer,
    source_guide,
)
from knowledge_map.chat_startup import (
    ChatDependencies,
    chat_dependencies,
    new_chat_session,
)
from knowledge_map.public_access import (
    PublicAccessMiddleware,
    PublicSettings,
    VisitorAdmission,
    source_ip,
    visitor_id,
)
from knowledge_map.schemas.query_preparation import QuestionAssessment, QuestionText
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.schemas.source_guides import (
    GuideDisclosure,
    GuideSearchDetails,
    SavedSourceGuide,
    SourceGuide,
)
from knowledge_map.utils.agents import create_agent

logger = logging.getLogger(__name__)


class QuestionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: QuestionText


class GuideUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionDeadlineExceeded(Exception):
    """The admitted question exhausted its total public execution time."""


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
    public_settings: PublicSettings | None = None,
    readiness: Callable[[], bool] | None = None,
) -> FastAPI:
    public = public_settings or PublicSettings()
    dependencies: ChatDependencies | None = None
    guide_store: SQLiteGuideStore
    running: dict[str, asyncio.Task[None]] = {}
    accepting = False
    admission = VisitorAdmission(public) if public.enabled else None
    execution_slots = asyncio.Semaphore(public.active_questions)

    def owner(request: Request) -> str | None:
        return visitor_id(request) if public.enabled else None

    async def ready() -> bool:
        if not accepting:
            return False
        try:
            healthy = readiness is None or await run_in_threadpool(readiness)
            return accepting and healthy
        except Exception:
            logger.exception("Source Guide readiness check failed")
            return False

    def admission_error(request: Request) -> Response | None:
        if admission is None:
            return None
        if len(running) >= public.active_questions + public.queued_questions:
            return JSONResponse(
                {
                    "error": "All search places are occupied. Try again after a search finishes."
                },
                status_code=429,
                headers={"Retry-After": "30"},
            )
        visitor, ip = visitor_id(request), source_ip(request, public)
        if not admission.available(visitor, ip):
            return JSONResponse(
                {
                    "error": "The hourly question limit has been reached. Try again later."
                },
                status_code=429,
                headers={"Retry-After": "3600"},
            )
        if not guide_store.admit_public_question(public.daily_submissions):
            return JSONResponse(
                {
                    "error": "Today's question limit has been reached. Please return tomorrow."
                },
                status_code=429,
            )
        admission.consume(visitor, ip)
        return None

    def guide_response(
        guide: SavedSourceGuide,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        return JSONResponse(
            {
                **guide.model_dump(mode="json", exclude_none=True),
                "publication_orders": guide_publication_orders(guide),
            },
            status_code=status_code,
            headers=headers,
        )

    def search_details() -> GuideSearchDetails:
        return GuideSearchDetails(
            collections=guide_collections(dependencies.coverage) if dependencies else ()
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal dependencies, accepting, guide_store
        try:
            async with startup() as dependencies:
                guide_store = SQLiteGuideStore(guide_db_path)
                guide_store.interrupt_unfinished(public_only=public.enabled)
                if public.enabled:
                    guide_store.prune_public_guides(public.retention_days)
                if browser_url is not None:
                    print(f"Open {browser_url} in your browser.", flush=True)
                accepting = True
                try:
                    yield
                finally:
                    accepting = False
                    tasks = tuple(running.values())
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    if public.enabled:
                        guide_store.interrupt_unfinished(public_only=True)
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

    async def stopping_service_error(
        *, check_dependencies: bool = True
    ) -> Response | None:
        if not accepting or check_dependencies and not await ready():
            return JSONResponse(
                {
                    "error": "The service is unavailable. Try again later."
                    if public.enabled
                    else "The local service is stopping."
                },
                status_code=503,
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
        if public.enabled and len(submission.question) > public.max_question_characters:
            return JSONResponse(
                {
                    "error": f"Questions may contain at most {public.max_question_characters:,} characters."
                },
                status_code=422,
            )
        if error := await stopping_service_error():
            return error
        if error := admission_error(request):
            return error
        saved = guide_store.create(
            submission.question, search_details(), owner_id=owner(request)
        )
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
        if error := await stopping_service_error():
            return error
        try:
            current = guide_store.get(
                request.path_params["guide_id"], owner_id=owner(request)
            )
            if current.latest_attempt.status == "running":
                raise GuideAlreadyRunning(current.guide_id)
            if (
                public.enabled
                and len(current.question) > public.max_question_characters
            ):
                return JSONResponse(
                    {"error": "The saved question exceeds the question length limit."},
                    status_code=422,
                )
            if error := admission_error(request):
                return error
            saved = guide_store.start_update(
                request.path_params["guide_id"],
                search_details(),
                owner_id=owner(request),
            )
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

    async def cancel_attempt(request: Request) -> Response:
        if error := json_content_type_error(request):
            return error
        try:
            GuideUpdate.model_validate_json(await request.body())
        except ValidationError:
            return JSONResponse(
                {"error": "Cancel uses the selected search attempt."}, status_code=422
            )
        if error := await stopping_service_error(check_dependencies=False):
            return error
        guide_id = request.path_params["guide_id"]
        attempt_id = request.path_params["attempt_id"]
        try:
            saved = guide_store.get(guide_id, owner_id=owner(request))
        except KeyError:
            return JSONResponse({"error": "Source Guide not found."}, status_code=404)
        cancelled = guide_store.finish(
            guide_id,
            attempt_id,
            SourceGuide(
                question=saved.question,
                status="cancelled",
                message="This search was cancelled.",
            ),
            owner_id=owner(request),
        )
        if (
            cancelled.latest_attempt.attempt_id == attempt_id
            and cancelled.latest_attempt.status == "cancelled"
            and (task := running.get(attempt_id)) is not None
        ):
            task.cancel()
        return guide_response(cancelled)

    def start_execution(saved: SavedSourceGuide) -> Response:
        if public.enabled:
            guide_store.prune_public_guides(public.retention_days)
        attempt_id = saved.latest_attempt.attempt_id
        task = asyncio.create_task(execute(saved))
        running[attempt_id] = task
        task.add_done_callback(lambda _: running.pop(attempt_id, None))
        return guide_response(
            saved,
            status_code=202,
            headers={"Location": f"/api/guides/{saved.guide_id}"},
        )

    async def execute(saved: SavedSourceGuide) -> None:
        session = None

        async def run_question():
            nonlocal session
            session = session_factory(saved.question, dependencies)
            return await session.run()

        try:
            if public.enabled:
                deadline = asyncio.timeout(public.deadline_seconds)
                try:
                    async with deadline, execution_slots:
                        result = await run_question()
                    if deadline.expired():
                        raise QuestionDeadlineExceeded
                except TimeoutError as error:
                    if deadline.expired():
                        raise QuestionDeadlineExceeded from error
                    raise
            else:
                result = await run_question()
        except QuestionDeadlineExceeded:
            guide_store.finish(
                saved.guide_id,
                saved.latest_attempt.attempt_id,
                SourceGuide(
                    question=saved.question,
                    status="interrupted",
                    message="This search exceeded its time limit. Choose Retry to search again.",
                ),
            )
            return
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
                        "assessment": "The question could not be assessed. Choose Retry to search again.",
                        "retrieval": "The search could not be completed. Choose Retry to search again.",
                        "guidance": "Reading directions could not be prepared. The retrieved articles have not passed the relevance check. Choose Retry to search again.",
                    }[stage],
                }
            )
            guide = guide.model_copy(
                update={
                    "disclosures": (
                        GuideDisclosure.model_validate(
                            {"kind": status, "message": guide.message}
                        ),
                        *deferred_disclosures(guide.assessment),
                    )
                }
            )
            guide = guide.model_copy(
                update={
                    "message": "\n\n".join(
                        disclosure.message for disclosure in guide.disclosures
                    )
                }
            )
        else:
            if isinstance(result, QuestionAssessment):
                guide = assessment_guide(saved.question, result)
            else:
                guide = source_guide(result, story_db_path=guide_store.db_path)
                if isinstance(result, RetrievalAnswer):
                    logfire.info(
                        "chat_session.answer_prepared",
                        chat_session_id=session.chat_session_id,
                        audit_schema_version=2,
                        rendered_text=render_answer(result, guide=guide),
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
                    guide.model_dump(mode="json", exclude_none=True)
                    for guide in guide_store.list(owner_id=owner(request))
                ]
            }
        )

    async def read_guide(request: Request) -> Response:
        try:
            guide = guide_store.get(
                request.path_params["guide_id"], owner_id=owner(request)
            )
        except KeyError:
            return JSONResponse({"error": "Source Guide not found."}, status_code=404)
        return guide_response(guide)

    async def coverage(request: Request) -> Response:
        return JSONResponse(
            {
                "entries": [
                    entry.model_dump(mode="json", exclude_none=True)
                    for entry in search_details().collections
                ]
            }
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
    if public.enabled:
        app.add_middleware(PublicAccessMiddleware, settings=public)

    @app.get("/health/live")
    async def live() -> Response:
        return JSONResponse({"status": "alive"})

    @app.get("/health/ready")
    async def ready_response() -> Response:
        healthy = await ready()
        return JSONResponse(
            {"status": "ready" if healthy else "unavailable"},
            status_code=200 if healthy else 503,
        )

    frontend = create_agent(name="local_guide_shell").to_web(
        allowed_hosts=[urlsplit(public.public_origin).hostname]
        if public.enabled and public.public_origin
        else None,
    )
    frontend.router.routes[:] = [
        Route("/api/questions", submit_question, methods=["POST"]),
        Route("/api/guides", list_guides, methods=["GET"]),
        Route("/api/guides/{guide_id}", read_guide, methods=["GET"]),
        Route("/api/guides/{guide_id}/update", update_guide, methods=["POST"]),
        Route(
            "/api/guides/{guide_id}/attempts/{attempt_id}/cancel",
            cancel_attempt,
            methods=["POST"],
        ),
        Route("/api/coverage", coverage, methods=["GET"]),
        *(
            Route(path, asset, methods=["GET"])
            for path in ("/", "/guide.js", "/guide.css")
        ),
    ]
    app.mount("/", frontend)
    return app
