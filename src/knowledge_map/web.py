"""Local browser entry point for retrieval chat."""

from fastapi import FastAPI

from knowledge_map.utils.agents import create_agent


def create_app() -> FastAPI:
    """Serve Pydantic AI's stock frontend with its default local protections."""
    app = FastAPI()
    app.mount("/", create_agent(name="local_chat_shell").to_web())
    return app
