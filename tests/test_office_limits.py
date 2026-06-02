"""Resource-cap guards for parsing untrusted office/PDF files (F2).

.docx/.xlsx are zip+XML containers; a few-KB zip-bomb can decompress to
gigabytes and OOM-kill the process during a corpus scan. These tests verify the
pre-parse screen rejects bombs before openpyxl/python-docx ever decompress them.
"""
import zipfile

from graphify import detect


def _write_zip(path, name, payload):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)


def test_file_within_size_cap(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 1024)
    assert detect._file_within_size_cap(f) is True          # within default cap
    assert detect._file_within_size_cap(f, cap=512) is False  # over an explicit small cap
    assert detect._file_within_size_cap(tmp_path / "missing") is False


def test_zip_ratio_bomb_rejected(tmp_path):
    """A tiny file that expands far past the ratio threshold is rejected."""
    bomb = tmp_path / "bomb.xlsx"
    _write_zip(bomb, "xl/worksheets/sheet1.xml", b"0" * (5 * 1024 * 1024))  # 5 MiB of zeros -> tiny zip
    assert bomb.stat().st_size < 100 * 1024  # compressed to well under 100 KiB
    assert detect._zip_within_caps(bomb) is False


def test_legit_zip_passes(tmp_path):
    ok = tmp_path / "ok.docx"
    _write_zip(ok, "word/document.xml", b"<xml>hello world</xml>" * 20)
    assert detect._zip_within_caps(ok) is True


def test_non_zip_rejected(tmp_path):
    notzip = tmp_path / "fake.xlsx"
    notzip.write_bytes(b"this is not a zip file")
    assert detect._zip_within_caps(notzip) is False


def test_converters_return_empty_for_bomb(tmp_path):
    """The live converters bail out (return "") on a bomb before parsing."""
    for ext in (".docx", ".xlsx"):
        bomb = tmp_path / f"bomb{ext}"
        _write_zip(bomb, "x.xml", b"0" * (5 * 1024 * 1024))
        assert detect.docx_to_markdown(bomb) == ""
        assert detect.xlsx_to_markdown(bomb) == ""


def test_pdf_over_cap_returns_empty(tmp_path, monkeypatch):
    """A PDF larger than the raw cap is skipped before pypdf opens it."""
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"x" * 4096)
    # shrink the cap via the helper's default by patching the module constant and
    # calling through a wrapper that reads it fresh
    monkeypatch.setattr(detect, "_OFFICE_MAX_RAW_BYTES", 100)
    monkeypatch.setattr(detect, "_file_within_size_cap",
                        lambda p, cap=100: p.stat().st_size <= cap if p.exists() else False)
    assert detect.extract_pdf_text(big) == ""
