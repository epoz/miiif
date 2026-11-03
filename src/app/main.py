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
    settings.search_dirs,
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/{image_id}/info.json")
def image_info(image_id: str, request: Request, svc: IIIFImageService = Depends(get_service)):
    version = negotiate_version(request)
    base_uri = _base_uri(request)
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


@app.get("/{image_id}/{region}/{size}/{rotation}/{quality_format}")
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
    try:
        data, mime = svc.image_bytes(image_id, region, size, rotation, quality, fmt)
    except IIIFError as exc:
        return _error_response(exc)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


@app.get("/{image_id}/tiles/{tile_size}/{scale}")
def image_tiles(image_id: str, tile_size: str, scale: int, svc: IIIFImageService = Depends(get_service)):
    try:
        data, mime = svc.tile_bytes(image_id, tile_size, scale)
    except IIIFError as exc:
        return _error_response(exc)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


app.add_exception_handler(IIIFError, iiif_error_handler)


__all__ = ["app"]
