"""End-to-end API tests using the demo TTS engine."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from paperparser.config import Settings
from paperparser.server import create_app
from tests.conftest import make_pdf


@pytest.fixture()
def client(tmp_path):
    """A TestClient over an app with a fake TTS engine and a seeded library."""
    lib = tmp_path / "lib"
    (lib / "P1").mkdir(parents=True)
    make_pdf(lib / "P1" / "paper.pdf")
    app = create_app(Settings(library_dir=lib, fake_tts=True, lead_seconds=2.0))
    with TestClient(app) as c:
        yield c


def test_rest_flow(client):
    assert client.get("/").status_code == 200
    for js in ("/static/app.js", "/static/vendor/pdfjs/pdf.min.mjs", "/static/vendor/pdfjs/pdf.worker.min.mjs"):
        assert client.get(js).headers["content-type"].startswith("text/javascript"), js
    assert client.get("/api/status").json()["state"] == "ready"
    assert client.get("/api/projects").json()[0]["name"] == "P1"
    assert client.post("/api/projects", json={"name": "P2"}).status_code == 201
    assert client.post("/api/projects", json={"name": "../x"}).status_code == 400
    pdf = client.get("/api/projects/P1/papers/paper.pdf/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    up = client.post("/api/projects/P2/papers", files=[("files", ("n.pdf", pdf.content, "application/pdf")), ("files", ("bad.pdf", b"x", "application/pdf"))])
    assert len(up.json()["added"]) == 1 and len(up.json()["errors"]) == 1
    r = client.patch("/api/projects/P1/papers/paper.pdf", json={"notes": "hi", "status": "reading", "reading_pos": 5})
    assert r.json()["notes"] == "hi" and r.json()["reading_pos"] == 5
    assert client.patch("/api/projects/P1/papers/paper.pdf", json={"status": "bogus"}).status_code == 422
    words = client.get("/api/projects/P1/papers/paper.pdf/words").json()
    assert len(words["words"]) > 100 and words["references_start"] is not None
    assert client.get("/api/projects/P1/papers/missing.pdf/pdf").status_code == 404


def _collect(ws, until_end=True, limit=200):
    """Read (header, pcm) pairs from the websocket until an ``end`` message."""
    chunks = []
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == "chunk":
            chunks.append((msg, ws.receive_bytes()))
        elif msg["type"] in ("end", "error"):
            return chunks, msg
    return chunks, None


def test_websocket_streams_audio_with_word_timings(client):
    n_words = len(client.get("/api/projects/P1/papers/paper.pdf/words").json()["words"])
    with client.websocket_connect("/ws/read") as ws:
        ws.send_json({"type": "start", "project": "P1", "file": "paper.pdf", "start_word": 0, "voice": "af_heart", "speed": 1.0})
        # flow control: lead is 2s, so tell the server we've "played" a lot as we go
        chunks, last = [], None
        for _ in range(500):
            msg = ws.receive_json()
            if msg["type"] == "chunk":
                pcm = ws.receive_bytes()
                chunks.append((msg, pcm))
                assert len(pcm) == round(msg["duration"] * msg["sample_rate"]) * 2
                ws.send_json({"type": "pos", "t": sum(m["duration"] for m, _ in chunks)})
            else:
                last = msg
                break
    assert last == {"type": "end"}
    spoken = [w[0] for m, _ in chunks for w in m["words"]]
    assert spoken == sorted(spoken) and len(set(spoken)) == len(spoken)
    assert max(spoken) < n_words


def test_websocket_restart_and_stop(client):
    with client.websocket_connect("/ws/read") as ws:
        start = {"type": "start", "project": "P1", "file": "paper.pdf", "voice": "af_heart", "speed": 1.0}
        ws.send_json({**start, "start_word": 0})
        first = ws.receive_json()
        assert first["type"] == "chunk"
        ws.receive_bytes()
        ws.send_json({"type": "stop"})
        time.sleep(0.3)
        ws.send_json({**start, "start_word": 60})
        for _ in range(20):  # drain leftovers from the first run until the restarted stream shows up
            msg = ws.receive_json()
            if msg["type"] == "chunk":
                ws.receive_bytes()
                if msg["words"][0][0] >= 60:
                    break
        else:
            pytest.fail("restart did not start from the requested word")


def test_websocket_reports_errors(client):
    with client.websocket_connect("/ws/read") as ws:
        ws.send_json({"type": "start", "project": "Nope", "file": "x.pdf"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
