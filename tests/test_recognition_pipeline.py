import asyncio

import pytest

from app.recognition_pipeline import complete_visual_evidence


def test_catalogue_checks_overlap_provider_and_both_finish_before_return():
    async def run():
        catalogue_started = asyncio.Event()
        provider_finished = False
        rows = [{"catalogue_id": "same-printing"}]

        async def load():
            return rows

        async def enrich(value):
            assert value is rows
            assert not provider_finished
            catalogue_started.set()
            value[0]["visual_similarity"] = 0.95

        async def provider():
            nonlocal provider_finished
            # Deadlocks under the previous schedule: catalogue enrichment waited
            # for provider completion. No wall-clock speed assertion is needed.
            await catalogue_started.wait()
            provider_finished = True

        result = await asyncio.wait_for(complete_visual_evidence(load, enrich, provider), 1)
        assert result is rows
        assert result[0]["visual_similarity"] == 0.95
        assert provider_finished

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["load", "enrich", "provider", "cancel"])
def test_failure_or_cancellation_cleans_up_all_branches(failure):
    async def run():
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def load():
            await entered.wait()
            if failure == "load":
                raise ValueError("lookup failed")
            return []

        async def enrich(_):
            if failure == "enrich":
                raise ValueError("image failed")
            await asyncio.Event().wait()

        async def provider():
            try:
                entered.set()
                if failure == "provider":
                    raise ValueError("provider failed")
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        task = asyncio.create_task(complete_visual_evidence(load, enrich, provider))
        if failure == "cancel":
            await entered.wait()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
            await asyncio.wait_for(task, 1)
        assert cleaned.is_set()

    asyncio.run(run())
