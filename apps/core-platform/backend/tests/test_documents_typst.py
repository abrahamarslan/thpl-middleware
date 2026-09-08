"""Typst PDF service — hermetic unit tests (no DB, no Redis).

typst-py is a hard import in service.py, so skip cleanly when the wheel
is not installed (bare checkout / CI without deps).
"""

import pytest

typst = pytest.importorskip("typst")

from app.common.exception.errors import UpstreamError  # noqa: E402
from app.core.conf import settings  # noqa: E402
from app.modules.documents import service  # noqa: E402


def test_compile_minimal_markup_to_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TYPST_FONT_PATHS", [])
    monkeypatch.setattr(settings, "TYPST_PDF_STANDARDS", [])

    path = service.render_typst_to_pdf("= Hello\n\nWorld.", "hello.pdf")

    data = tmp_path.joinpath("pdf", path.rsplit("/", 1)[-1]).read_bytes()
    assert data[:4] == b"%PDF"


def test_compile_with_sys_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TYPST_FONT_PATHS", [])
    monkeypatch.setattr(settings, "TYPST_PDF_STANDARDS", [])

    source = '#let inv = json(bytes(sys.inputs.invoice))\nInvoice #inv.number'
    path = service.render_typst_to_pdf(
        source, "inv.pdf", sys_inputs={"invoice": '{"number": "INV-1"}'}
    )

    data = tmp_path.joinpath("pdf", path.rsplit("/", 1)[-1]).read_bytes()
    assert data[:4] == b"%PDF"


def test_invalid_markup_raises_upstream(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TYPST_FONT_PATHS", [])
    monkeypatch.setattr(settings, "TYPST_PDF_STANDARDS", [])

    with pytest.raises(UpstreamError):
        service.render_typst_to_pdf("#nonexistent-fn()[", "bad.pdf")
