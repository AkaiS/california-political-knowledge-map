"""The one event loop a thread's blocking model calls share.

The Story Pipeline is synchronous, but every model client underneath it is
async and caches an httpx connection pool.  A pool's synchronisation
primitives bind to whichever loop first drove them, so a client that outlives
a single call has to be reached on that same loop every time.

``asyncio.run`` cannot provide it.  It closes the loop it created and then
clears the thread's current loop, so the next blocking call finds none
installed, builds a fresh one, and reaches a pool still bound to the loop
that has gone -- surfacing as ``RuntimeError: ... is bound to a different
event loop``, which the OpenAI SDK reports as the bare string
``Connection error.``
"""

import asyncio
import warnings
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def thread_event_loop() -> asyncio.AbstractEventLoop:
    """This thread's usable loop, installing one when there is none.

    Installed with ``set_event_loop`` so that Pydantic AI's ``run_sync``
    resolves the same loop, putting the agents and the embedder on one loop
    rather than each on one of its own.  A loop someone else already closed
    is replaced rather than handed back, since a closed loop runs nothing.
    """

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    with warnings.catch_warnings():
        # Reading the installed loop is how this thread finds the loop its
        # clients are bound to.  Python deprecates the read for the case this
        # function exists to handle -- there is no loop yet -- and answers it
        # below by installing one.
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
