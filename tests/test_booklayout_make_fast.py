"""make --fast (T5, design 2026-11-26 D): one test per D.2 row, per-module fingerprints, per-page cache."""
from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from booklayout import buildcache, make as mk, sourcecheck


def _state(**kw):
    s = {"src": "S1" * 8, "tr": "T1", "profile": "P1", "sc_key": "K", "source_fp": "F"}
    s.update(kw)
    return s


def _prev(**kw):
    return _state(**{"sc_done": True, "sc_src": "S1" * 8, **kw})


# ---- D.2 rows -------------------------------------------------------------------------------

def test_row_style_only_skips_source_check():
    d = mk.classify_change(_prev(), _state(profile="P2"), "auto", translated=False)
    assert d["mode"] == "style" and d["skip_source_check"]
    assert d["reason"].startswith("src unchanged, hash=")


def test_row_translation_only_translated_edition_skips():
    d = mk.classify_change(_prev(), _state(tr="T2"), "auto", translated=True)
    assert d["mode"] == "translation" and d["skip_source_check"]


def test_row_translation_only_same_language_runs():
    d = mk.classify_change(_prev(), _state(tr="T2"), "auto", translated=False)
    assert d["mode"] == "full" and not d["skip_source_check"]
    assert "same-language" in d["reason"]


def test_row_source_changed_is_full():
    d = mk.classify_change(_prev(), _state(src="S2" * 8), "auto", translated=True)
    assert d["mode"] == "full" and not d["skip_source_check"]


def test_row_code_changed_is_full():
    d = mk.classify_change(_prev(), _state(source_fp="F2"), "auto")
    assert not d["skip_source_check"] and "code" in d["reason"]


def test_row_source_check_inputs_changed_is_full():
    d = mk.classify_change(_prev(), _state(sc_key="K2"), "auto")
    assert not d["skip_source_check"]


def test_row_release_never_skips():
    d = mk.classify_change(_prev(), _state(), "auto", release=True)
    assert not d["skip_source_check"] and "release" in d["reason"]


def test_no_fast_flag_never_skips():
    assert not mk.classify_change(_prev(), _state(), None)["skip_source_check"]


def test_no_previous_state_or_unfinished_source_check_runs():
    assert not mk.classify_change({}, _state(), "auto")["skip_source_check"]
    assert not mk.classify_change(_state(), _state(), "auto")["skip_source_check"]  # sc_done missing


def test_nothing_changed_skips():
    assert mk.classify_change(_prev(), _state(), "auto")["mode"] == "none"


def test_fast_style_refuses_translation_change():
    d = mk.classify_change(_prev(), _state(tr="T2"), "style", translated=True)
    assert not d["skip_source_check"]


def test_sc_src_drift_is_full():
    # skipped twice while the source text moved in between must not look unchanged
    d = mk.classify_change(_prev(sc_src="OLD"), _state(), "auto")
    assert d["mode"] == "full"


# ---- digests --------------------------------------------------------------------------------

def _aligned(tmp_path, text="uno", tr="one", style=None, role="body"):
    p = tmp_path / "a.json"
    blk = {"block_id": "b1", "role": role, "text": text, "translation": tr}
    if style:
        blk["style"] = style
    p.write_text(json.dumps({"pages": [{"page": 1, "blocks": [blk]}]}), encoding="utf-8")
    return p


def test_digest_translation_edit_keeps_src(tmp_path):
    a = mk.aligned_digests(_aligned(tmp_path))
    b = mk.aligned_digests(_aligned(tmp_path, tr="ONE"))
    assert a["src"] == b["src"] and a["tr"] != b["tr"]


def test_digest_source_edit_changes_src(tmp_path):
    assert mk.aligned_digests(_aligned(tmp_path))["src"] != mk.aligned_digests(_aligned(tmp_path, text="dos"))["src"]
    assert mk.aligned_digests(_aligned(tmp_path))["src"] != mk.aligned_digests(_aligned(tmp_path, role="note"))["src"]


def test_digest_style_name_is_not_source(tmp_path):
    assert mk.aligned_digests(_aligned(tmp_path))["src"] == mk.aligned_digests(_aligned(tmp_path, style="Body"))["src"]


# ---- per-module fingerprints ----------------------------------------------------------------

def _pkg(tmp_path, monkeypatch):
    pkg = tmp_path / "booklayout"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text("")
    (pkg / "cli.py").write_text("from . import normalize\n")
    (pkg / "normalize.py").write_text("X = 1\n")
    (pkg / "builder.py").write_text("from booklayout.english import f\ndef g():\n    from .profile import P\n")
    (pkg / "english.py").write_text("f = 1\n")
    (pkg / "profile.py").write_text("P = 1\n")
    (pkg / "keymodel.py").write_text("")
    (pkg / "qa.py").write_text("Q = 1\n")
    (pkg / "sourcecheck.py").write_text("from .scanfigures import find\n")
    (pkg / "scanfigures.py").write_text("find = 1\n")
    monkeypatch.setattr(buildcache, "_PKG", pkg)
    return pkg


def test_gate_edit_does_not_change_builder_fingerprint(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch)
    before = buildcache.fingerprints()
    (pkg / "qa.py").write_text("Q = 2\n")
    after = buildcache.fingerprints()
    assert before["builder"] == after["builder"] and before["source"] == after["source"]
    assert before["all"] != after["all"]


def test_builder_closure_edits_change_builder_fingerprint(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch)
    base = buildcache.fingerprints()["builder"]
    for name in ("english.py", "profile.py", "normalize.py", "cli.py"):   # absolute, lazy, cli-top-level, cli
        old = (pkg / name).read_text()
        (pkg / name).write_text(old + "# edit\n")
        assert buildcache.fingerprints()["builder"] != base, name
        (pkg / name).write_text(old)


def test_source_edit_changes_only_source_fingerprint(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch)
    before = buildcache.fingerprints()
    (pkg / "scanfigures.py").write_text("find = 2\n")
    after = buildcache.fingerprints()
    assert before["source"] != after["source"] and before["builder"] == after["builder"]


def test_real_package_builder_fp_ignores_qa_and_sourcecheck():
    closure = buildcache.module_closure(buildcache.BUILD_ROOTS)
    assert "builder" in closure and "profile" in closure
    assert not {"qa", "stylecheck", "sourcecheck"} & closure


# ---- per-page figure-region cache -----------------------------------------------------------

def test_figure_boxes_cached_per_page(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    from booklayout import scanfigures
    png = tmp_path / "p0001.png"
    cv2.imwrite(str(png), np.full((40, 40), 255, np.uint8))
    calls = []

    class B:
        x0, y0, x1, y1 = 1, 2, 3, 4

    monkeypatch.setattr(scanfigures, "find_figures", lambda g, dpi: calls.append(1) or [B()])
    assert sourcecheck.figure_boxes(png, 300) == [(1, 2, 3, 4)]
    assert sourcecheck.figure_boxes(png, 300) == [(1, 2, 3, 4)]
    assert len(calls) == 1                                  # second call from cache
    sourcecheck.figure_boxes(png, 150)                      # other dpi: recomputed
    assert len(calls) == 2
    cv2.imwrite(str(png), np.zeros((40, 40), np.uint8))     # scan changed: recomputed
    sourcecheck.figure_boxes(png, 150)
    assert len(calls) == 3
    assert len(list(tmp_path.glob("p0001.figs.*.json"))) == 1   # stale entries removed


# ---- make() end to end with stubbed subprocesses --------------------------------------------

@pytest.fixture
def fake(tmp_path, monkeypatch):
    called: list[str] = []

    def bl(*a):
        called.append(str(a[0]))
        a = [str(x) for x in a]
        if a[0] == "build":
            out = Path(a[a.index("--out") + 1])
            out.write_bytes(b"docx")
            out.with_suffix(".pdf").write_bytes(b"pdf")
        elif a[0] == "key-report":
            Path(a[a.index("--out") + 1]).write_text("{}")
        elif a[0] == "gate":
            Path(a[a.index("--out") + 1]).write_text(json.dumps({"problems": []}))
        elif a[0] == "source-check":
            Path(a[a.index("--out") + 1]).write_text(json.dumps({"ok": True}))
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(mk, "_bl", bl)
    monkeypatch.setattr(mk, "_bl_mod", lambda *a: bl("stylecheck"))
    src = tmp_path / "src.pdf"
    src.write_bytes(b"%PDF")
    (tmp_path / "meta.json").write_text("{}")

    def run(aligned, fast=None, translated=True, profile=None, release=None):
        args = Namespace(aligned=aligned, figures=tmp_path, metadata=tmp_path / "meta.json", profile=profile,
                         out_dir=tmp_path / "out", name="b", release_acceptance=release, source_pdf=src,
                         translated=translated, pages="1-2", accepted=None, lang="spa", dict_lang="es", jobs=1,
                         html=False, edit_html=False, fast=fast)
        called.clear()
        rc = mk.make(args)
        summ = json.loads((tmp_path / "out" / "b.make.json").read_text())
        return rc, list(called), summ

    return run, tmp_path


def test_make_fast_end_to_end(fake):
    run, tmp = fake
    al = _aligned(tmp)
    rc, c, s = run(al, fast="auto")
    assert rc == 0 and "source-check" in c and not s["skipped"]       # first run: no state, full
    al = _aligned(tmp, tr="ONE")                                       # only translation changed
    rc, c, s = run(al, fast="auto")
    assert rc == 0 and "source-check" not in c
    assert s["skipped"][0]["gate"] == "source-check" and "src unchanged" in s["skipped"][0]["reason"]
    gj = json.loads((tmp / "out" / "b.work" / "gate.json").read_text())
    assert gj["skipped"][0]["gate"] == "source-check"                  # visible in the gate report, not a pass
    rc, c, s = run(al, fast=None)                                      # no --fast: everything
    assert "source-check" in c
    al = _aligned(tmp, text="dos", tr="ONE")                           # source changed
    rc, c, s = run(al, fast="auto")
    assert "source-check" in c and s["fast"]["mode"] == "full"
    rc, c, s = run(al, fast="auto", release=tmp / "acc.json")          # release ignores --fast
    assert "source-check" in c


def test_make_records_per_gate_seconds(fake):
    run, tmp = fake
    _rc, _c, s = run(_aligned(tmp))
    assert set(s["gate_seconds"]) >= {"qa", "check", "stylecheck", "source-check"}
