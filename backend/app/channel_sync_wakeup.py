"""Wake the existing sync worker after a successful inventory transaction."""


def request_shopify_sync(request) -> bool:
    event = getattr(request.app.state, "shopify_sync_wakeup", None)
    if event is None:
        return False
    # No IDs, authorization, or publication decisions come from this signal.
    # The worker re-reads committed rows through its existing eligibility gates.
    event.set()
    return True
