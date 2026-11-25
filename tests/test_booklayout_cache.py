"""Task 6: input-hash cache for `booklayout build`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from booklayout import cli


@pytest.fixture
def env(tmp_path, monkeypatch):
    fig = tmp_path / "figs"
    fig.mkdir()
    (fig / "source_figure_audit.json").write_text("[]", encoding="utf-8")
    (fig / "f1.png").write_bytes(b"png1")
    aligned = tmp_path / "aligned.json"
    aligned.write_text(json.dumps({"pages": []}), encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text("{}", encoding="utf-8")
    calls = {"build": 0, "pdf": 0}

    def fake_build(out, page_map, paths, meta_, key_breaks):
        calls["build"] += 1
        Path(out).write_bytes(b"docx-%d" % calls["build"])
        return {"pages": []}

    def fake_convert(docx, pdf_out):
        calls["pdf"] += 1
        p = pdf_out or Path(docx).with_suffix(".pdf")
        p.write_bytes(b"pdf-%d" % calls["pdf"])
        return p

    monkeypatch.setattr(cli, "build", fake_build)
    monkeypatch.setattr(cli, "_convert_pdf", fake_convert)
    monkeypatch.setattr(cli, "_report", lambda data, figs, meta=None: {
        "source_pages": 0, "blocks": 0, "untranslated_blocks": 0,
        "untranslated_content_blocks": 0, "figures": 0})
    out = tmp_path / "o" / "book.docx"
    out.parent.mkdir()

    def run(*extra):
        argv = ["build", "--aligned", str(aligned), "--figures", str(fig), "--metadata", str(meta),
                "--out", str(out), "--pdf", "--report", str(tmp_path / "rep.json"), *extra]
        args = cli.build_parser().parse_args(argv)
        return args.func(args)

    return {"run": run, "calls": calls, "aligned": aligned, "fig": fig, "meta": meta, "out": out.with_name("book.DRAFT.docx"),
            "report": tmp_path / "rep.json"}


def test_unchanged_inputs_skip_docx_and_pdf(env):
    assert env["run"]() == 0
    assert env["run"]() == 0
    assert env["calls"] == {"build": 1, "pdf": 1}
    assert json.loads(env["report"].read_text(encoding="utf-8"))["out_pdf"].endswith("book.DRAFT.pdf")


@pytest.mark.parametrize("what", ["aligned", "meta", "figure_new", "figure_edit"])
def test_any_input_change_rebuilds(env, what):
    env["run"]()
    if what == "aligned":
        env["aligned"].write_text(json.dumps({"pages": [], "x": 1}), encoding="utf-8")
    elif what == "meta":
        env["meta"].write_text('{"title": "x"}', encoding="utf-8")
    elif what == "figure_new":
        (env["fig"] / "f2.png").write_bytes(b"png2")
    else:
        (env["fig"] / "f1.png").write_bytes(b"png1-changed")
    env["run"]()
    assert env["calls"] == {"build": 2, "pdf": 2}


def test_no_cache_flag_forces_rebuild(env):
    env["run"]()
    env["run"]("--no-cache")
    assert env["calls"] == {"build": 2, "pdf": 2}


def test_edited_docx_or_deleted_pdf_not_reused(env):
    env["run"]()
    env["out"].write_bytes(b"tampered")
    env["run"]()
    assert env["calls"]["build"] == 2
    env["out"].with_suffix(".pdf").unlink()
    env["run"]()
    assert env["calls"]["build"] == 2 and env["calls"]["pdf"] == 3
