"""Core IIIF Image API logic: image lookup, manipulation and encoding.

All image manipulation is delegated to libvips (https://www.libvips.org) via
the python bindings (``pyvips``).

The manipulation sequence implemented here follows the IIIF Image API
specification order:

    Region -> Size -> Rotation -> Quality -> Format
"""

import math
import os
import re
from pathlib import Path

import pyvips

from .config import settings


class IIIFError(Exception):
    """Base class for errors that map onto IIIF Image API responses."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ImageNotFound(IIIFError):
    status_code = 404


class BadRequest(IIIFError):
    status_code = 400


class NotImplemented(IIIFError):
    status_code = 501


# MIME type and libvips file suffix for every supported format value.
IMAGE_FORMATS = {
    "jpg": ("image/jpeg", ".jpg"),
    "jpeg": ("image/jpeg", ".jpg"),
    "tif": ("image/tiff", ".tif"),
    "tiff": ("image/tiff", ".tif"),
    "png": ("image/png", ".png"),
    "gif": ("image/gif", ".gif"),
    "jp2": ("image/jp2", ".jp2"),
    "j2k": ("image/jp2", ".jp2"),
    "webp": ("image/webp", ".webp"),
    "pdf": ("application/pdf", ".pdf"),
}

QUALITY_VALUES = ("default", "color", "gray", "bitonal")


class IIIFImageService:
    """Serve IIIF image requests for images found in configured directories."""

    def __init__(
        self,
        directories,
        max_width: int | None = None,
        max_height: int | None = None,
        max_area: int | None = None,
        cache_dir: str | None = None,
    ):
        self.directories = [Path(d) for d in directories]
        self.max_width = max_width if max_width is not None else settings.max_width
        self.max_height = max_height if max_height is not None else settings.max_height
        self.max_area = max_area if max_area is not None else settings.max_area
        self.cache_dir = Path(cache_dir) if cache_dir else None

    # ------------------------------------------------------------------
    # Image lookup
    # ------------------------------------------------------------------
    def find_image(self, identifier: str) -> Path:
        """Find the file for an image identifier in the configured directories.

        The directories are searched in the order in which they are
        configured; the first directory containing a file whose filename
        matches the image identifier wins. Identifiers without a file extension
        are looked up with a set of common image file extensions appended.
        """
        if not identifier or "/" in identifier or "\\" in identifier:
            raise BadRequest("Image identifier must be a filename, not a path")
        candidates = [identifier]
        if "." not in identifier:
            candidates += [
                f"{identifier}{ext}"
                for ext in (
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".tif",
                    ".tiff",
                    ".gif",
                    ".webp",
                    ".jp2",
                )
            ]
        for directory in self.directories:
            for name in candidates:
                candidate = directory / name
                try:
                    if candidate.is_file():
                        return candidate
                except OSError:
                    continue
        raise ImageNotFound(f"Image not found: {identifier}")

    def _load(self, identifier: str):
        path = self.find_image(identifier)
        image = pyvips.Image.new_from_file(str(path))
        return path, image

    def image_size(self, identifier: str):
        """Return (path, width, height) for an identifier."""
        path, image = self._load(identifier)
        return path, image.width, image.height

    # ------------------------------------------------------------------
    # Image information
    # ------------------------------------------------------------------
    def info_document(self, identifier: str, version: str, base_uri: str) -> dict:
        _path, width, height = self.image_size(identifier)
        if version == "2":
            doc = {
                "@context": "http://iiif.io/api/image/2/context.json",
                "@id": f"{base_uri}/{identifier}",
                "@type": "iiif:Image",
                "protocol": "http://iiif.io/api/image",
                "profile": [f"http://iiif.io/api/image/2/level2.json"],
                "width": width,
                "height": height,
            }
        else:
            doc = {
                "@context": "http://iiif.io/api/image/3/context.json",
                "id": f"{base_uri}/{identifier}",
                "type": "ImageService3",
                "protocol": "http://iiif.io/api/image",
                "profile": "level2",
                "width": width,
                "height": height,
            }
            doc["maxWidth"] = self.max_width
            doc["maxHeight"] = self.max_height
            if self.max_area is not None:
                doc["maxArea"] = self.max_area
            doc["extraFormats"] = ["webp"]
            doc["extraQualities"] = ["gray", "bitonal"]
            doc["extraFeatures"] = [
                "regionByPx",
                "regionByPct",
                "regionSquare",
                "sizeByW",
                "sizeByH",
                "sizeByPct",
                "sizeByWh",
                "sizeByConfinedWh",
                "rotationArbitrary",
                "mirroring",
                "sizeUpscaling",
                "canonicalLinkHeader",
                "profileLinkHeader",
                "cors",
                "jsonldMediaType",
            ]
        return doc

    # ------------------------------------------------------------------
    # Region / size / rotation / quality / format handling
    # ------------------------------------------------------------------
    def _parse_region(self, region: str, width: int, height: int):
        region = (region or "full").strip()
        if region == "full":
            return 0, 0, width, height
        if region == "square":
            side = min(width, height)
            if side <= 0:
                raise BadRequest("Image has no pixels to extract a square region from")
            return (width - side) // 2, (height - side) // 2, side, side
        values = region.split(",")
        if region.startswith("pct:") and len(values) == 4:
            try:
                px, py, pw, ph = (float(v) for v in values)
            except ValueError:
                raise BadRequest(f"Invalid percentage region: {region}") from None
            if pw <= 0 or ph <= 0:
                raise BadRequest("Region width and height must be positive")
            x = int(round(px / 100.0 * width))
            y = int(round(py / 100.0 * height))
            rw = max(1, int(round(pw / 100.0 * width)))
            rh = max(1, int(round(ph / 100.0 * height)))
        else:
            if len(values) != 4:
                raise BadRequest(f"Invalid region: {region}")
            try:
                x, y, rw, rh = (int(v) for v in values)
            except ValueError:
                raise BadRequest(f"Invalid region: {region}") from None
            if rw <= 0 or rh <= 0:
                raise BadRequest("Region width and height must be positive")
            if x < 0 or y < 0:
                raise BadRequest("Region coordinates must be non-negative")
            if x >= width or y >= height:
                raise BadRequest("Region is outside the bounds of the image")
            rw = min(rw, width - x)
            rh = min(rh, height - y)
        return x, y, rw, rh

    def _resolve_size(self, size, region_width: int, region_height: int):
        """Resolve the size parameter into (width, height, is_exact)."""
        size = (size or "max").strip()
        allow_upscale = size.startswith("^")
        if allow_upscale:
            size = size[1:]
        best_fit = False
        if size.startswith("!"):
            best_fit = True
            size = size[1:]

        if size in ("", "max", "full"):
            return region_width, region_height, False

        if size.startswith("pct:"):
            try:
                percent = float(size[len("pct:"):])
            except ValueError:
                raise BadRequest(f"Invalid size: {size}") from None
            if percent < 0 or (percent > 100 and not allow_upscale):
                raise BadRequest(f"Size percentage out of range: {size}")
            factor = percent / 100.0
            return (
                max(1, int(round(region_width * factor))),
                max(1, int(round(region_height * factor))),
                False,
            )

        if best_fit:
            parts = size.split(",")
            if len(parts) != 2:
                raise BadRequest(f"Invalid size: {size}")
            width, height = (int(v) for v in parts)
            if width <= 0 or height <= 0:
                raise BadRequest(f"Invalid size: {size}")
            scale = min(width / region_width, height / region_height)
            return max(1, int(round(region_width * scale))), max(1, int(round(region_height * scale))), False

        if "," in size:
            parts = [p.strip() for p in size.split(",")]
            if len(parts) == 2 and parts[0] == "":
                # ",h" -> height only
                height = int(parts[1])
                if height <= 0:
                    raise BadRequest(f"Invalid size: {size}")
                if not allow_upscale and height > region_height:
                    raise BadRequest(f"Requested size exceeds image bounds: {size}")
                return max(1, int(round(region_width * height / region_height))), height, False
            if len(parts) == 2 and parts[1] == "":
                # "w," -> width only
                width = int(parts[0])
                if width <= 0:
                    raise BadRequest(f"Invalid size: {size}")
                if not allow_upscale and width > region_width:
                    raise BadRequest(f"Requested size exceeds image bounds: {size}")
                return width, max(1, int(round(region_height * width / region_width))), False
            if len(parts) == 2:
                # "w,h" -> exact size
                width, height = int(parts[0]), int(parts[1])
                if width <= 0 or height <= 0:
                    raise BadRequest(f"Invalid size: {size}")
                if not allow_upscale and (width > region_width or height > region_height):
                    raise BadRequest(f"Requested size exceeds image bounds: {size}")
                return width, height, True
            raise BadRequest(f"Invalid size: {size}")

        raise BadRequest(f"Invalid size: {size}")

    def _apply_limits(self, tw: int, th: int, rw: int, rh: int):
        if self.max_width is None and self.max_height is None and self.max_area is None:
            return tw, th
        w, h = tw, th
        if self.max_area is not None and (w * h) > self.max_area and (w * h) > 0:
            scale = math.sqrt(self.max_area / (w * h))
            w = max(1, int(round(w * scale)))
            h = max(1, int(round(h * scale)))
        max_w = self.max_width if self.max_width is not None else self.max_height
        max_h = self.max_height if self.max_height is not None else self.max_width
        if max_w is not None and w > max_w:
            w = max_w
            h = int(round(rh * max_w / rw)) if rw else h
        if max_h is not None and h > max_h:
            h = max_h
            w = int(round(rw * max_h / rh)) if rh else w
        if w < 1 or h < 1:
            raise BadRequest("Requested image size is smaller than one pixel")
        if (
            (self.max_width is not None and w > self.max_width)
            or (self.max_height is not None and h > self.max_height)
            or (self.max_area is not None and (w * h) > self.max_area)
        ):
            raise ImageNotFound("Requested image size exceeds server limits")
        return w, h

    # ------------------------------------------------------------------
    # Core render pipeline: region -> size -> rotation -> quality -> format
    # ------------------------------------------------------------------
    def _render(
        self,
        identifier: str,
        region: str,
        size: str,
        rotation: str,
        quality: str,
        fmt: str,
    ) -> tuple:
        _path, image = self._load(identifier)
        width, height = image.width, image.height

        x, y, rw, rh = self._parse_region(region, width, height)
        image = image.crop(x, y, rw, rh)

        tw, th, is_exact = self._resolve_size(size, rw, rh)
        tw, th = self._apply_limits(tw, th, rw, rh)

        if is_exact:
            sx = tw / rw if rw else 1.0
            sy = th / rh if rh else 1.0
            image = image.affine([sx, 0, 0, sy])
        elif tw != rw or th != rh:
            image = image.resize(tw / rw if rw else 1.0)

        rotation = rotation or "0"
        mirror = rotation.startswith("!")
        number = rotation[1:].strip() if mirror else rotation.strip()
        angle = 0.0
        if number:
            try:
                angle = float(number)
            except ValueError:
                raise BadRequest(f"Invalid rotation: {rotation}") from None
        if mirror:
            image = image.flip(pyvips.enums.Direction.HORIZONTAL)
        angle = angle % 360.0
        if angle != 0:
            if angle % 90 == 0:
                steps = int(round(angle / 90.0))
                angle_deg = steps * 90
                name = {90: "D90", 180: "D180", 270: "D270"}.get(angle_deg, "D0")
                image = image.rot(getattr(pyvips.enums.Angle, name))
            else:
                rad = math.radians(angle)
                c = math.cos(rad)
                s = math.sin(rad)
                image = image.affine([c, -s, s, c])

        quality = (quality or "default").strip().lower()
        if quality not in QUALITY_VALUES:
            raise BadRequest(f"Unsupported quality: {quality}")
        if quality in ("gray", "bitonal"):
            image = image.colourspace("b-w")

        fmt_key = (fmt or "jpg").strip().lower().lstrip(".")
        if fmt_key not in IMAGE_FORMATS:
            raise BadRequest(f"Unsupported format: {fmt}")
        mime, suffix = IMAGE_FORMATS[fmt_key]

        try:
            data = image.write_to_buffer(suffix)
        except Exception as exc:  # noqa: BLE001
            raise NotImplemented(f"Format {fmt} could not be encoded: {exc}") from exc

        return data, mime

    def image_bytes(self, identifier: str, region: str, size: str, rotation: str, quality: str, fmt: str) -> tuple:
        return self._render(identifier, region, size, rotation, quality, fmt)

    # ------------------------------------------------------------------
    # Tiles
    # ------------------------------------------------------------------
    def tile_bytes(self, identifier: str, tile_size, scale) -> tuple:
        _path, image = self._load(identifier)
        width, height = image.width, image.height
        parts = [p.strip() for p in str(tile_size).split(",")]
        if len(parts) == 1 and parts[0].isdigit():
            tile_w = int(parts[0])
            tile_h = tile_w
        elif len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            tile_w, tile_h = int(parts[0]), int(parts[1])
        else:
            raise BadRequest(f"Invalid tile size: {tile_size}")
        if not isinstance(scale, int) or scale < 1:
            raise BadRequest(f"Invalid tile scale: {scale}")

        count_x = max(1, int(math.ceil(width / (tile_w * scale))))
        count_y = max(1, int(math.ceil(height / (tile_h * scale))))
        for n in range(count_x):
            for m in range(count_y):
                xr = n * tile_w * scale
                yr = m * tile_h * scale
                wr = tile_w * scale
                hr = tile_h * scale
                if xr + wr > width:
                    wr = width - xr
                if yr + hr > height:
                    hr = height - yr
                ws = tile_w
                if xr + tile_w * scale > width:
                    ws = int(math.ceil((width - xr) / scale))
                hs = tile_h
                if yr + tile_h * scale > height:
                    hs = int(math.ceil((height - yr) / scale))
                data, mime = self._render(
                    identifier, f"{xr},{yr},{wr},{hr}", f"{ws},{hs}", "0", "default", "jpg"
                )
                # Write the generated tile to the cache directory atomically so
                # that a caching reverse proxy (e.g. Caddy) can serve it directly
                # from disk before falling back to the FastAPI backend.
                if self.cache_dir is not None:
                    try:
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(identifier))
                        final_path = self.cache_dir / f"{safe}__tile_{n}_{m}_{scale}.jpg"
                        tmp_path = self.cache_dir / f".{final_path.name}.tmp.{os.getpid()}"
                        tmp_path.write_bytes(data)
                        os.replace(tmp_path, final_path)
                    except OSError:
                        pass
                return data, mime
        raise ImageNotFound("No tiles could be generated")
