# IIIF Image API Server

A [Python](https://www.python.org) / [FastAPI](https://fastapi.tiangolo.com) based
web service implementing the
[IIIF Image API](https://iiif.io/api/image/3.0/) (and version 2.1).

Images are manipulated and resized with
[libvips](https://www.libvips.org/) (the `libvips` C library, accessed through its
Python bindings via the [`pyvips`](https://pypi.org/project/pyvips/) package).

## Running

```bash
uv sync --extra dev
uv run uvicorn iiif.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t iiif-image-api .
docker run -p 8000:8000 iiif-image-api
```

The image installs dependencies with [uv](https://docs.astral.sh/uv/) from the
lockfile and runs the server with `uvicorn` (it includes the `libvips` system
library required by the `pyvips` bindings).

## Endpoints

### Image information

```
GET /{image_id}/info.json
```

Returns a JSON-LD document describing the technical properties of the image
(`@context`, id, type, protocol, profile, width, height, ...).

* Version 3 documents use `"type": "ImageService3"`, `"@context":
  "http://iiif.io/api/image/3/context.json"` and `"profile": "level2"`, served as
  `application/ld+json;profile="http://iiif.io/api/image/3/context.json"`.
* Version 2 documents use the JSON-LD style (`"@id"`, `"@type": "iiif:Image"`,
  `"profile": ["http://iiif.io/api/image/2/level2.json"]`) and are served as
  `application/ld+json;profile="http://iiif.io/api/image/2/context.json"`.

The served version is selected through the `Accept` header (falling back to
`IIIF_IMAGE_API_VERSION`).

Informational requests can be issued as `HEAD` as well as `GET`: a `HEAD`
request to `/{image_id}/info.json` returns the same status code and metadata
(media type, content length) as the corresponding `GET`, without a response
body, so clients can probe an image's information before fetching it.

### Image requests

```
GET /{image_id}/{region}/{size}/{rotation}/{quality}.{format}
```

Conforms to the IIIF Image API image request URI syntax:

```
{identifier}/{region}/{size}/{rotation}/{quality}.{format}
```

Examples:

* `/myimage/full/max/0/default.jpg`
* `/myimage/125,15,120,140/max/0/default.jpg`
* `/myimage/pct:41.6,7.5,40,70/max/0/default.jpg`
* `/myimage/full/150,/0/default.jpg`
* `/myimage/full/225,100/!90/gray.png`

Supported values:

* **region**: `full`, `square`, `x,y,w,h`, `pct:x,y,w,h`
* **size**: `max`, `full`, `w,`, `^,h`, `pct:n`, `pct:^n`, `w,h`, `^w,h`, `!w,h`, `^!w,h`
* **rotation**: `n` or `!n` (clockwise degrees, mirroring applied before rotation
  when prefixed with `!`)
* **quality**: `default`, `color`, `gray`, `bitonal`
* **format**: `jpg`, `tif`, `tiff`, `png`, `gif`, `jp2`, `j2k`, `webp`, `pdf`

### Tiles

```
GET /{image_id}/tiles/{tile_size}/{scale}
```

Returns a tile of the image, e.g. `/myimage/tiles/256/2`.

## Configuration

Settings can be provided through environment variables, optionally via a `.env`
file placed in the project root (loaded automatically via `python-dotenv`):

```bash
IIIF_IMAGE_DB=/data/images.db
IIIF_MAX_WIDTH=4000
IIIF_MAX_HEIGHT=4000
IIIF_MAX_AREA=
IIIF_IMAGE_API_VERSION=3
IIIF_CACHE_DIR=/var/www/iiif-cache
IIIF_PLAUSIBLE_API_URL=https://plausible.io/api/event
IIIF_PLAUSIBLE_DOMAIN=
```

* `IIIF_IMAGE_DB` — path to the SQLite image lookup database used to resolve
  image identifiers to files. Defaults to `/data/images.db`.
* `IIIF_MAX_WIDTH`, `IIIF_MAX_HEIGHT`, `IIIF_MAX_AREA` — server imposed maximum
  image dimensions / area.
* `IIIF_IMAGE_API_VERSION` — default version of the image information document
  served (`3` or `2`).
* `IIIF_CACHE_DIR` — directory used to cache generated tiles.
* `IIIF_PLAUSIBLE_API_URL` — Plausible Events API endpoint used for usage
  tracking (defaults to `https://plausible.io/api/event`).
* `IIIF_PLAUSIBLE_DOMAIN` — Plausible site domain the usage events are
  attributed to; when set, usage tracking is enabled (no events are sent
  otherwise).
* `IIIF_PLAUSIBLE_ENABLED` — optional explicit on/off switch for usage
  tracking; when unset, tracking follows the presence of `IIIF_PLAUSIBLE_DOMAIN`.

## Usage tracking

Image API usage can be reported to a
[Plausible](https://plausible.io) analytics instance through its
[Events API](https://plausible.io/docs/events-api) by adding API calls that use
the service.

When a Plausible site domain is configured through `IIIF_PLAUSIBLE_DOMAIN`, the
server sends an event to the Plausible Events API for every image API request
that is actually served (`GET` only; `HEAD` probes are not counted as usage):

* `image_info` — `GET /{image_id}/info.json`
* `image_request` — `GET /{image_id}/{region}/{size}/{rotation}/{quality}.{format}`
* `image_tile` — `GET /{image_id}/tiles/{tile_size}/{scale}`

Each event carries the requested image identifier as a custom property and is
sent as a JSON `POST` to the configured events endpoint, forwarding the
`User-Agent` and `X-Forwarded-For` headers of the originating request for
Plausible's unique visitor counting.

Tracking is best effort: it is disabled unless a Plausible domain is configured
and never fails an image request, should the Plausible instance be unreachable.

## Populating the image lookup database

Image identifiers are resolved through a SQLite database with an `identifier`
and a `path` column (a lookup table). The database is populated by scanning
image directories recursively for image files:

```bash
uv run python -m iiif.populate --dirs /data/images --db /data/images.db
```

The command indexes every supported image file found (including files in
subdirectories) into the lookup database, using the filename as identifier and
the full file path as location. Afterwards the server looks images up in this
database instead of scanning directories at request time:

```bash
uv run uvicorn iiif.main:app --host 0.0.0.0 --port 8000
```

The directories to scan (`--dirs`, one or more paths) and the lookup database
to populate (`--db`) are both passed on the command line and are required.

## Tests

```bash
uv run python -m pytest tests/ -q
```

## Notes

* Image identifiers are looked up in the SQLite lookup database populated by
  the `iiif.populate` command; since the combination of identifier and path is
  unique, the same image identifier may be registered with several paths (e.g.
  when the same file name occurs in multiple scanned directories).
* All image manipulation (region extraction, resizing, rotation, quality,
  format conversion) is performed by libvips.
* Generated tiles are written atomically (write to temporary file, then `os.replace`)
  into the configured tile cache directory.
* Requests for the full size of an image that need no manipulation (full region,
  no resizing, no rotation, default quality, format matching the source file) are
  served directly from the original file: the original image is linked into the
  cache directory under the cached filename instead of generating (and caching) a
  rendered copy through libvips.
