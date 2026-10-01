"""Schedule independent evidence branches without dropping required evidence."""
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def complete_visual_evidence(
    load: Callable[[], Awaitable[T]],
    enrich: Callable[[T], Awaitable[None]],
    provider: Callable[[], Awaitable[None]],
) -> T:
    async def catalogue() -> T:
        candidates = await load()
        await enrich(candidates)
        return candidates

    tasks = [asyncio.create_task(catalogue()), asyncio.create_task(provider())]
    try:
        candidates, _ = await asyncio.gather(*tasks)
        return candidates
    finally:
        # A failed/cancelled request must not leave provider work running detached.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
