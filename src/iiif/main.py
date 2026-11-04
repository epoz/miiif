"""FastAPI based IIIF Image API server.

Implements the IIIF Image API (versions 2 and 3) as described at
https://iiif.io/api/image/3.0/ and https://iiif.io/api/image/2.1/

Image resizing is performed with libvips (https://www.libvips.org) through the
python bindings (``pyvips``).
"""

import json

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import settings
from .image_service import IIIFError, IIIFImageService
from .tracking import send_event

app = FastAPI(
    title="IIIF Image API Server",
    description=(
        "A FastAPI based server implementing the IIIF Image API, including "
        "region, size, rotation, quality and format handling, backed by libvips "
        "for image manipulation and resizing."
    ),
    version="1.0.0",
)

service = IIIFImageService(
    settings.image_db,
    max_width=settings.max_width,
    max_height=settings.max_height,
    max_area=settings.max_area,
    cache_dir=settings.tile_cache_dir,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


def get_service() -> IIIFImageService:
    return service


@app.exception_handler(IIIFError)
async def iiif_error_handler(request: Request, exc: IIIFError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "message": exc.message},
    )


def negotiate_version(request: Request) -> str:
    accept = request.headers.get("accept") or ""
    if "image/2" in accept or "iiif.io/api/image/2" in accept:
        return "2"
    if "image/3" in accept or "iiif.io/api/image/3" in accept:
        return "3"
    return settings.info_version


def _base_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _error_response(exc: IIIFError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "message": exc.message},
    )


def _track(
    name: str,
    url: str,
    image_id: str,
    request: Request,
) -> None:
    """Send a best effort usage event to the Plausible Events API.

    Image API usage is reported through Plausible (see
    https://plausible.io/docs/events-api); HEAD requests are ignored since they
    are only used as probes and do not constitute usage.
    """
    if request.method != "GET":
        return
    send_event(
        name=name,
        url=url,
        props={"image_id": image_id},
        user_agent=request.headers.get("user-agent"),
        forwarded_for=request.headers.get("x-forwarded-for"),
    )


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}


@app.api_route("/{image_id}/info.json", methods=["GET", "HEAD"])
def image_info(image_id: str, request: Request, svc: IIIFImageService = Depends(get_service)):
    version = negotiate_version(request)
    base_uri = _base_uri(request)
    _track("image_info", f"{base_uri}/{image_id}/info.json", image_id, request)
    try:
        document = svc.info_document(image_id, version, base_uri)
    except IIIFError as exc:
        return _error_response(exc)
    if version == "2":
        media_type = 'application/ld+json;profile="http://iiif.io/api/image/2/context.json"'
    else:
        media_type = 'application/ld+json;profile="http://iiif.io/api/image/3/context.json"'
    return Response(
        content=json.dumps(document),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


@app.api_route(
    "/{image_id}/{region}/{size}/{rotation}/{quality_format}",
    methods=["GET", "HEAD"],
)
def image_request(
    image_id: str,
    region: str,
    size: str,
    rotation: str,
    quality_format: str,
    request: Request,
    svc: IIIFImageService = Depends(get_service),
):
    version = negotiate_version(request)
    quality, _, fmt = quality_format.partition(".")
    quality = quality or "default"
    fmt = fmt or "jpg"
    image_url = (
        f"{_base_uri(request)}/{image_id}/{region}/{size}/{rotation}/{quality}.{fmt}"
    )
    _track("image_request", image_url, image_id, request)
    try:
        data, mime = svc.image_bytes(image_id, region, size, rotation, quality, fmt)
    except IIIFError as exc:
        return _error_response(exc)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


@app.api_route("/{image_id}/tiles/{tile_size}/{scale}", methods=["GET", "HEAD"])
def image_tiles(
    image_id: str,
    tile_size: str,
    scale: int,
    request: Request,
    svc: IIIFImageService = Depends(get_service),
):
    tiles_url = f"{_base_uri(request)}/{image_id}/tiles/{tile_size}/{scale}"
    _track("image_tile", tiles_url, image_id, request)
    try:
        data, mime = svc.tile_bytes(image_id, tile_size, scale)
    except IIIFError as exc:
        return _error_response(exc)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


app.add_exception_handler(IIIFError, iiif_error_handler)


__all__ = ["app"]
