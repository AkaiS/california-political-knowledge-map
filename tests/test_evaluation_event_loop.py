"""Consecutive cases share one model client without losing its connections.

A local Model Deployment's chat model is memoized, so its HTTP client and
keep-alive connection pool outlive any one case. A case run on its own event
loop closes that loop when it finishes, and the next case then reuses a pooled
connection bound to the closed loop: it fails with ``Event loop is closed``
before the server sees the request.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowledge_map.evaluation import run_data_set
from knowledge_map.evaluation.data_set import (
    EvaluationCase,
    EvaluationDataSet,
    EvaluationSplit,
)
from knowledge_map.evaluation.tasks import relevance
from knowledge_map.evaluation.tasks.relevance import (
    RelevanceExpectation,
    RelevanceInput,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment


class _KeepAliveChatCompletions(BaseHTTPRequestHandler):
    # HTTP/1.1 keeps the connection open, as llama-server does.
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 -- http.server's handler name
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "stub",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"classification": "RELEVANT"}),
                },
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def chat_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _KeepAliveChatCompletions)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _case(case_id: str) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        description="an article",
        task_input=RelevanceInput(url=f"https://example.com/{case_id}", headline="A bill"),
        expected_output=RelevanceExpectation(classification="RELEVANT"),
        split=EvaluationSplit.HELD_OUT,
    )


def test_a_case_after_a_successful_case_reuses_the_model_client(chat_server):
    data_set = EvaluationDataSet(
        task="relevance",
        description="consecutive cases",
        cases=(_case("first"), _case("second"), _case("third")),
    )
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL, model="stub", endpoint=chat_server
    )

    report = run_data_set(
        data_set,
        task=relevance.build_task(deployment, data_set),
        evaluators=(),
        max_concurrency=1,
    )

    assert [failure.error_message for failure in report.failures] == []
    assert len(report.cases) == 3
