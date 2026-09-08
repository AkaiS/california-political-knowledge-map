"""The one event loop a thread's blocking model calls share.

Model clients cache an httpx connection pool, and a pool's synchronisation
primitives bind to the loop that first drove them. A client outlives any one
call, so it has to be reached on that same loop every time.
"""

import asyncio
import warnings
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def thread_event_loop() -> asyncio.AbstractEventLoop:
    """This thread's usable loop, installing one when there is none.

    Left installed, so the clients bound to it can be reached again and so
    Pydantic AI's ``run_sync`` resolves the same one. A loop someone else
    already closed is replaced rather than handed back, since a closed loop
    runs nothing.
    """

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    with warnings.catch_warnings():
        # Python deprecates this read for the case this function exists to
        # handle -- there is no loop yet -- and answers it below.
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_on_thread_loop(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run one coroutine to completion, leaving the thread's loop installed."""

    return thread_event_loop().run_until_complete(coroutine)
