"""Tests for the IIIF Image API server."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from iiif.main import app, get_service
from iiif.image_service import IIIFImageService

client = TestClient(app)


def make_image(path, width=200, height=100, color=(200, 30, 30)):
    img = Image.new("RGB", (width, height), color)
    img.save(path, format="JPEG")


@pytest.fixture()
def c(tmp_path):
    svc = IIIFImageService([str(tmp_path)])
    app.dependency_overrides[get_service] = lambda: svc
    yield TestClient(app)
    app.dependency_overrides.pop(get_service, None)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_info_json(c, tmp_path):
    make_image(tmp_path / "basic.jpg")
    response = c.get("/basic.jpg/info.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/ld+json")
    body = response.json()
    assert body["@context"] == "http://iiif.io/api/image/3/context.json"
    assert body["type"] == "ImageService3"
    assert body["protocol"] == "http://iiif.io/api/image"
    assert body["profile"] == "level2"
    assert body["width"] == 200
    assert body["height"] == 100
    assert body["maxWidth"] == 4000


def test_info_json_v2_negotiation(c, tmp_path):
    make_image(tmp_path / "basic2.jpg")
    response = c.get(
        "/basic2.jpg/info.json",
        headers={"Accept": 'application/ld+json;profile="http://iiif.io/api/image/2/context.json"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["@context"] == "http://iiif.io/api/image/2/context.json"
    assert body["protocol"] == "http://iiif.io/api/image"


def test_full_image(c, tmp_path):
    make_image(tmp_path / "basic3.jpg")
    response = c.get("/basic3.jpg/full/max/0/default.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (200, 100)


def test_region_and_size(c, tmp_path):
    make_image(tmp_path / "basic4.jpg")
    response = c.get("/basic4.jpg/50,25,100,50/max/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_size_exact(c, tmp_path):
    make_image(tmp_path / "basic5.jpg")
    response = c.get("/basic5.jpg/full/50,25/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (50, 25)


def test_size_width_only(c, tmp_path):
    make_image(tmp_path / "basic6.jpg")
    response = c.get("/basic6.jpg/full/150,/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (150, 75)


def test_size_pct(c, tmp_path):
    make_image(tmp_path / "basic7.jpg")
    response = c.get("/basic7.jpg/full/pct:50/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_rotation(c, tmp_path):
    make_image(tmp_path / "basic8.jpg")
    response = c.get("/basic8.jpg/full/max/90/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 200)


def test_rotation_mirror(c, tmp_path):
    make_image(tmp_path / "basic13.jpg")
    response = c.get("/basic13.jpg/full/max/!90/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    # mirrored + rotated 90 degrees swaps dimensions as well
    assert img.size == (100, 200)


def test_format_png(c, tmp_path):
    make_image(tmp_path / "basic9.jpg")
    response = c.get("/basic9.jpg/full/max/0/default.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_unknown_format(c, tmp_path):
    make_image(tmp_path / "basic10.jpg")
    response = c.get("/basic10.jpg/full/max/0/default.xyz")
    assert response.status_code == 400


def test_unknown_image(c, tmp_path):
    response = c.get("/doesnotexist.jpg/full/max/0/default.jpg")
    assert response.status_code == 404


def test_tiles(c, tmp_path):
    make_image(tmp_path / "basic11.jpg")
    response = c.get("/basic11.jpg/tiles/100/2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_quality_gray(c, tmp_path):
    make_image(tmp_path / "basic12.jpg")
    response = c.get("/basic12.jpg/full/max/0/gray.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_directory_search_first_match(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    make_image(one / "shared.jpg")
    make_image(two / "shared.jpg", color=(0, 0, 255))
    svc = IIIFImageService([str(one), str(two)])
    data, mime = svc.image_bytes("shared.jpg", "full", "max", "0", "default", "jpg")
    img = Image.open(io.BytesIO(data))
    assert img.size == (200, 100)


def test_directory_search_fallback(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    make_image(two / "onlyhere.jpg")
    svc = IIIFImageService([str(one), str(two)])
    data, mime = svc.image_bytes("onlyhere", "full", "max", "0", "default", "jpg")
    img = Image.open(io.BytesIO(data))
    assert img.size == (200, 100)


def test_tile_writes_atomically_to_cache(tmp_path):
    make_image(tmp_path / "cached.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService([str(tmp_path)], cache_dir=str(cache_dir))
    data, mime = svc.tile_bytes("cached.jpg", 100, 2)
    assert mime == "image/jpeg"
    cached_files = list(cache_dir.glob("*")) if cache_dir.is_dir() else []
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == data
