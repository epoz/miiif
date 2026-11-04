"""Tests for the IIIF Image API server."""

import io
import json
import sqlite3
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from iiif import tracking
from iiif.main import app, get_service
from iiif.image_service import BadRequest, ImageNotFound, IIIFImageService
from iiif.populate import populate
from iiif.tracking import send_event

client = TestClient(app)


def make_image(path, width=200, height=100, color=(200, 30, 30)):
    img = Image.new("RGB", (width, height), color)
    img.save(path, format="JPEG")


@pytest.fixture()
def lookup_db(tmp_path):
    db = tmp_path / "images.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE image_map (identifier TEXT PRIMARY KEY, path TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    return db


def register_image(db, identifier: str, path) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR REPLACE INTO image_map (identifier, path) VALUES (?, ?)",
        (identifier, str(path)),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def c(tmp_path, lookup_db):
    svc = IIIFImageService(str(lookup_db))
    app.dependency_overrides[get_service] = lambda: svc
    yield TestClient(app)
    app.dependency_overrides.pop(get_service, None)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_head_health():
    response = client.head("/health")
    assert response.status_code == 200
    assert response.content == b""


def test_info_json(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic.jpg")
    register_image(lookup_db, "basic.jpg", tmp_path / "basic.jpg")
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


def test_head_info_json(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic14.jpg")
    register_image(lookup_db, "basic14.jpg", tmp_path / "basic14.jpg")
    response = c.head("/basic14.jpg/info.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/ld+json")
    assert response.headers["content-length"]
    assert response.content == b""


def test_head_info_json_missing_image(c, tmp_path, lookup_db):
    response = c.head("/doesnotexist.jpg/info.json")
    assert response.status_code == 404
    assert response.content == b""


def test_info_json_v2_negotiation(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic2.jpg")
    register_image(lookup_db, "basic2.jpg", tmp_path / "basic2.jpg")
    response = c.get(
        "/basic2.jpg/info.json",
        headers={"Accept": 'application/ld+json;profile="http://iiif.io/api/image/2/context.json"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["@context"] == "http://iiif.io/api/image/2/context.json"
    assert body["protocol"] == "http://iiif.io/api/image"


def test_full_image(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic3.jpg")
    register_image(lookup_db, "basic3.jpg", tmp_path / "basic3.jpg")
    response = c.get("/basic3.jpg/full/max/0/default.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (200, 100)


def test_head_image(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic15.jpg")
    register_image(lookup_db, "basic15.jpg", tmp_path / "basic15.jpg")
    response = c.head("/basic15.jpg/full/max/0/default.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b""


def test_region_and_size(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic4.jpg")
    register_image(lookup_db, "basic4.jpg", tmp_path / "basic4.jpg")
    response = c.get("/basic4.jpg/50,25,100,50/max/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_size_exact(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic5.jpg")
    register_image(lookup_db, "basic5.jpg", tmp_path / "basic5.jpg")
    response = c.get("/basic5.jpg/full/50,25/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (50, 25)


def test_size_width_only(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic6.jpg")
    register_image(lookup_db, "basic6.jpg", tmp_path / "basic6.jpg")
    response = c.get("/basic6.jpg/full/150,/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (150, 75)


def test_size_pct(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic7.jpg")
    register_image(lookup_db, "basic7.jpg", tmp_path / "basic7.jpg")
    response = c.get("/basic7.jpg/full/pct:50/0/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_rotation(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic8.jpg")
    register_image(lookup_db, "basic8.jpg", tmp_path / "basic8.jpg")
    response = c.get("/basic8.jpg/full/max/90/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 200)


def test_rotation_mirror(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic13.jpg")
    register_image(lookup_db, "basic13.jpg", tmp_path / "basic13.jpg")
    response = c.get("/basic13.jpg/full/max/!90/default.jpg")
    assert response.status_code == 200
    img = Image.open(io.BytesIO(response.content))
    # mirrored + rotated 90 degrees swaps dimensions as well
    assert img.size == (100, 200)


def test_format_png(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic9.jpg")
    register_image(lookup_db, "basic9.jpg", tmp_path / "basic9.jpg")
    response = c.get("/basic9.jpg/full/max/0/default.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_unknown_format(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic10.jpg")
    register_image(lookup_db, "basic10.jpg", tmp_path / "basic10.jpg")
    response = c.get("/basic10.jpg/full/max/0/default.xyz")
    assert response.status_code == 400


def test_unknown_image(c, tmp_path, lookup_db):
    response = c.get("/doesnotexist.jpg/full/max/0/default.jpg")
    assert response.status_code == 404


def test_head_unknown_image(c, tmp_path, lookup_db):
    response = c.head("/doesnotexist.jpg/full/max/0/default.jpg")
    assert response.status_code == 404
    assert response.content == b""


def test_tiles(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic11.jpg")
    register_image(lookup_db, "basic11.jpg", tmp_path / "basic11.jpg")
    response = c.get("/basic11.jpg/tiles/100/2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (100, 50)


def test_head_tiles(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic16.jpg")
    register_image(lookup_db, "basic16.jpg", tmp_path / "basic16.jpg")
    response = c.head("/basic16.jpg/tiles/100/2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b""


def test_quality_gray(c, tmp_path, lookup_db):
    make_image(tmp_path / "basic12.jpg")
    register_image(lookup_db, "basic12.jpg", tmp_path / "basic12.jpg")
    response = c.get("/basic12.jpg/full/max/0/gray.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_lookup_by_identifier_with_extension(c, tmp_path, lookup_db):
    make_image(tmp_path / "by_ext.jpg")
    register_image(lookup_db, "by_ext.jpg", tmp_path / "by_ext.jpg")
    svc = IIIFImageService(str(lookup_db))
    path = svc.find_image("by_ext.jpg")
    assert path == tmp_path / "by_ext.jpg"


def test_lookup_fallback_to_extension(tmp_path, lookup_db):
    make_image(tmp_path / "onlyhere.jpg")
    register_image(lookup_db, "onlyhere", tmp_path / "onlyhere.jpg")
    svc = IIIFImageService(str(lookup_db))
    path = svc.find_image("onlyhere")
    assert path == tmp_path / "onlyhere.jpg"


def test_lookup_rejects_paths(c, tmp_path, lookup_db):
    svc = IIIFImageService(str(lookup_db))
    with pytest.raises(BadRequest):
        svc.find_image("sub/dir/basic.jpg")
    with pytest.raises(ImageNotFound):
        svc.find_image("missing.jpg")


def test_populate_indexes_directories_recursively(tmp_path):
    images = tmp_path / "images"
    deep = images / "sub" / "deep"
    deep.mkdir(parents=True)
    make_image(deep / "nested.jpg")
    make_image(images / "flat.jpg")
    db = tmp_path / "images.db"
    count = populate([images], db)
    assert count == 2
    svc = IIIFImageService(str(db))
    assert svc.find_image("nested.jpg") == deep / "nested.jpg"
    assert svc.find_image("flat") == images / "flat.jpg"
    with pytest.raises(ImageNotFound):
        svc.find_image("missing.jpg")


def test_tile_writes_atomically_to_cache(tmp_path, lookup_db):
    make_image(tmp_path / "cached.jpg")
    register_image(lookup_db, "cached.jpg", tmp_path / "cached.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService(str(lookup_db), cache_dir=str(cache_dir))
    data, mime = svc.tile_bytes("cached.jpg", 100, 2)
    assert mime == "image/jpeg"
    cached_files = list(cache_dir.glob("*")) if cache_dir.is_dir() else []
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == data


def test_image_writes_atomically_to_cache(tmp_path, lookup_db):
    make_image(tmp_path / "cached2.jpg")
    register_image(lookup_db, "cached2.jpg", tmp_path / "cached2.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService(str(lookup_db), cache_dir=str(cache_dir))
    data, mime = svc.image_bytes("cached2.jpg", "full", "max", "0", "default", "jpg")
    assert mime == "image/jpeg"
    cached_files = list(cache_dir.glob("*")) if cache_dir.is_dir() else []
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == data


def test_full_size_request_does_not_render(tmp_path, lookup_db):
    make_image(tmp_path / "fullsize.jpg", width=200, height=100)
    register_image(lookup_db, "fullsize.jpg", tmp_path / "fullsize.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService(str(lookup_db), cache_dir=str(cache_dir))
    original = (tmp_path / "fullsize.jpg").read_bytes()
    with mock.patch.object(IIIFImageService, "_render") as render:
        data, mime = svc.image_bytes("fullsize.jpg", "full", "max", "0", "default", "jpg")
    render.assert_not_called()
    assert mime == "image/jpeg"
    # The original file is served through a link in the cache directory.
    assert data == original
    cached_files = list(cache_dir.glob("*")) if cache_dir.is_dir() else []
    assert len(cached_files) == 1
    assert cached_files[0].is_symlink()


def test_full_size_request_format_mismatch_renders(tmp_path, lookup_db):
    make_image(tmp_path / "fullsize2.jpg", width=200, height=100)
    register_image(lookup_db, "fullsize2.jpg", tmp_path / "fullsize2.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService(str(lookup_db), cache_dir=str(cache_dir))
    with mock.patch.object(IIIFImageService, "_render", wraps=svc._render) as render:
        data, mime = svc.image_bytes("fullsize2.jpg", "full", "max", "0", "default", "png")
    render.assert_called_once()
    assert mime == "image/png"


def test_full_size_request_rotation_renders(tmp_path, lookup_db):
    make_image(tmp_path / "fullsize3.jpg", width=200, height=100)
    register_image(lookup_db, "fullsize3.jpg", tmp_path / "fullsize3.jpg")
    cache_dir = tmp_path / "cache"
    svc = IIIFImageService(str(lookup_db), cache_dir=str(cache_dir))
    with mock.patch.object(IIIFImageService, "_render", wraps=svc._render) as render:
        data, mime = svc.image_bytes("fullsize3.jpg", "full", "max", "90", "default", "jpg")
    render.assert_called_once()
    assert mime == "image/jpeg"


class _FakePlausibleResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_send_event_disabled_without_domain(monkeypatch):
    monkeypatch.delenv("IIIF_PLAUSIBLE_DOMAIN", raising=False)
    monkeypatch.delenv("IIIF_PLAUSIBLE_ENABLED", raising=False)
    with mock.patch.object(tracking.urllib.request, "urlopen") as urlopen:
        assert send_event("image_info", "http://example.org/img/info.json") is False
        urlopen.assert_not_called()


def test_send_event_respects_enabled_flag(monkeypatch):
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    monkeypatch.setenv("IIIF_PLAUSIBLE_ENABLED", "0")
    with mock.patch.object(tracking.urllib.request, "urlopen") as urlopen:
        assert send_event("image_info", "http://example.org/img/info.json") is False
        urlopen.assert_not_called()


def test_send_event_posts_payload_to_plausible(monkeypatch):
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakePlausibleResponse()

    monkeypatch.setattr(tracking.urllib.request, "urlopen", fake_urlopen)
    ok = send_event(
        "image_request",
        "http://example.org/img/full/max/0/default.jpg",
        props={"image_id": "img.jpg"},
        user_agent="Mozilla/5.0 (TestClient)",
        forwarded_for="127.0.0.1",
    )
    assert ok is True
    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.full_url == "https://plausible.io/api/event"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["name"] == "image_request"
    assert payload["url"] == "http://example.org/img/full/max/0/default.jpg"
    assert payload["domain"] == "example.org"
    assert payload["props"] == {"image_id": "img.jpg"}
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["User-agent"] == "Mozilla/5.0 (TestClient)"
    assert request.headers["X-forwarded-for"] == "127.0.0.1"
    assert captured["timeout"] == 5.0


def test_send_event_swallows_errors(monkeypatch):
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")

    def failing_urlopen(request, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(tracking.urllib.request, "urlopen", failing_urlopen)
    assert send_event("image_info", "http://example.org/img/info.json") is False


def test_image_info_request_tracked(c, tmp_path, lookup_db, monkeypatch):
    make_image(tmp_path / "tracked.jpg")
    register_image(lookup_db, "tracked.jpg", tmp_path / "tracked.jpg")
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    send_event_mock = mock.Mock(return_value=True)
    monkeypatch.setattr("iiif.main.send_event", send_event_mock)
    response = c.get("/tracked.jpg/info.json")
    assert response.status_code == 200
    send_event_mock.assert_called_once()
    kwargs = send_event_mock.call_args.kwargs
    assert kwargs["name"] == "image_info"
    assert kwargs["url"] == "http://testserver/tracked.jpg/info.json"
    assert kwargs["props"]["image_id"] == "tracked.jpg"


def test_image_request_tracked(c, tmp_path, lookup_db, monkeypatch):
    make_image(tmp_path / "tracked2.jpg")
    register_image(lookup_db, "tracked2.jpg", tmp_path / "tracked2.jpg")
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    send_event_mock = mock.Mock(return_value=True)
    monkeypatch.setattr("iiif.main.send_event", send_event_mock)
    response = c.get("/tracked2.jpg/full/max/0/default.jpg")
    assert response.status_code == 200
    send_event_mock.assert_called_once()
    kwargs = send_event_mock.call_args.kwargs
    assert kwargs["name"] == "image_request"
    assert kwargs["url"] == "http://testserver/tracked2.jpg/full/max/0/default.jpg"
    assert kwargs["props"]["image_id"] == "tracked2.jpg"


def test_tiles_request_tracked(c, tmp_path, lookup_db, monkeypatch):
    make_image(tmp_path / "tracked3.jpg")
    register_image(lookup_db, "tracked3.jpg", tmp_path / "tracked3.jpg")
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    send_event_mock = mock.Mock(return_value=True)
    monkeypatch.setattr("iiif.main.send_event", send_event_mock)
    response = c.get("/tracked3.jpg/tiles/100/2")
    assert response.status_code == 200
    send_event_mock.assert_called_once()
    kwargs = send_event_mock.call_args.kwargs
    assert kwargs["name"] == "image_tile"
    assert kwargs["url"] == "http://testserver/tracked3.jpg/tiles/100/2"
    assert kwargs["props"]["image_id"] == "tracked3.jpg"


@pytest.mark.parametrize(
    "method,url",
    [
        ("HEAD", "/tracked4.jpg/info.json"),
        ("HEAD", "/tracked4.jpg/full/max/0/default.jpg"),
        ("HEAD", "/tracked4.jpg/tiles/100/2"),
    ],
)
def test_head_requests_not_tracked(c, tmp_path, lookup_db, monkeypatch, method, url):
    make_image(tmp_path / "tracked4.jpg")
    register_image(lookup_db, "tracked4.jpg", tmp_path / "tracked4.jpg")
    monkeypatch.setenv("IIIF_PLAUSIBLE_DOMAIN", "example.org")
    send_event_mock = mock.Mock(return_value=True)
    monkeypatch.setattr("iiif.main.send_event", send_event_mock)
    response = getattr(c, method.lower())(url)
    assert response.status_code == 200
    send_event_mock.assert_not_called()
