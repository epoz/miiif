"""Usage tracking through the Plausible.io Events API.

Sends usage events for image API requests to a Plausible analytics instance via
its Events API:

https://plausible.io/docs/events-api

The Events API accepts `POST /api/event` requests with a JSON body holding the
event `name`, the target page `url` and the site `domain`, plus optional custom
`props`, `referrer`, `revenue` and `interactive` values.

Server-side events require the `User-Agent` and `X-Forwarded-For` headers of the
original client to be forwarded for Plausible's unique visitor counting to work
as intended.

Tracking is opt-in: it is only enabled when a Plausible site `domain` is
configured through the `IIIF_PLAUSIBLE_DOMAIN` environment variable (and not
explicitly disabled through `IIIF_PLAUSIBLE_ENABLED`).
"""

import json
import os
import urllib.request

from .config import settings

# Fallback User-Agent used when the original request carries none, so that
# Plausible can still attribute the event to a visitor.
DEFAULT_TRACKING_USER_AGENT = "iiif-image-api"


def tracking_enabled() -> bool:
    """Return True when Plausible usage tracking is enabled and configured."""
    flag = (os.environ.get("IIIF_PLAUSIBLE_ENABLED") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool((settings.plausible_domain or "").strip())


def send_event(
    name: str,
    url: str,
    props: dict[str, str] | None = None,
    user_agent: str | None = None,
    forwarded_for: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """Send a single event to the Plausible Events API.

    The event is sent as a JSON POST to the configured Plausible events endpoint
    (``IIIF_PLAUSIBLE_API_URL``, defaulting to the Plausible cloud endpoint).
    The `User-Agent` of the originating request is forwarded (falling back to a
    server default) and the optional `X-Forwarded-For` header overrides the IP
    address used for visitor attribution.

    Returns:
        True when the event was accepted by the Plausible instance, False when
        tracking is disabled or the event could not be delivered. Never raises:
        usage tracking must not interfere with the image API itself.

    Args:
        name: Name of the event; ``pageview`` is a reserved event name in
            Plausible, any other name is treated as a custom event.
        url: URL of the page (or resource) the event is attached to; hostnames
            derived from it take part in unique visitor recognition.
        props: Optional custom properties attached to the event (max 30).
        user_agent: User-Agent of the originating request, forwarded for
            unique visitor counting and device reporting.
        forwarded_for: Optional ``X-Forwarded-For`` value overriding the client
            IP address used for visitor attribution.
        timeout: Timeout in seconds for the tracking request.
    """
    if not tracking_enabled():
        return False
    domain = (settings.plausible_domain or "").strip()
    if not domain:
        # No Plausible site configured: nothing to attribute the event to.
        return False
    payload = {"name": name, "url": url, "domain": domain}
    if props:
        payload["props"] = props
    request = urllib.request.Request(
        settings.plausible_api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": user_agent or DEFAULT_TRACKING_USER_AGENT,
        },
        method="POST",
    )
    if forwarded_for:
        request.add_header("X-Forwarded-For", forwarded_for)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status in (200, 202)
    except Exception:
        # Plausible is an external analytics sink: drop the event instead of
        # failing the image request that triggered it.
        return False
