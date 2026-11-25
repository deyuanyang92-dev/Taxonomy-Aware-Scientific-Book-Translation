from __future__ import annotations

import argparse
import json
from pathlib import Path

from booklayout import cli
from booklayout import sourcecheck as sc


def toks_line(words: list[str], page: int = 1, line: int = 0, conf: float = 95.0,
              toks: list[sc.SrcTok] | None = None, lines: list[sc.SrcLine] | None = None):
    toks = [] if toks is None else toks
    lines = [] if lines is None else lines
    start = len(toks)
    for w in words:
        toks.append(sc.SrcTok(w, page, line, conf, (0, 0, 10, 10)))
    lines.append(sc.SrcLine(page, line, " ".join(words), conf, (0, 0, 10, 10), list(range(start, len(toks)))))
    return toks, lines


LEX = sc.Lexicon(words=frozenset({"la", "especie", "superficie", "casi", "todos", "de", "el", "parápodo",
                                  "san", "martín", "un", "ejemplar", "con", "cuerpo", "largo"}),
                 names=frozenset({"syllis", "krohnii", "trypanosyllis", "aeolis"}))


def types(report):
    return sorted(it["type"] for it in report["items"])


def test_fold_strips_accents_and_case():
    assert sc.fold("Martín") == "martin"
    assert sc.fold("ÑANDÚ") == "nandu"


def test_classify_decides_which_side_is_a_word():
    assert sc.classify("todos", "todavos", LEX) == "output_error"
    assert sc.classify("tadavos", "todos", LEX) == "tess_noise"
    assert sc.classify("especie", "superficie", LEX) == "conflict"
    assert sc.classify("xqz", "zzq", LEX) == "review"


def test_classify_uses_tesseract_frequency_for_domain_words():
    lex = sc.Lexicon(words=LEX.words, names=LEX.names, seen={"proventrículo": 3})
    assert sc.classify("proventrículo", "proventriculo", lex) == "output_error"


def test_compare_reports_rewrite_and_accent_loss():
    toks, lines = toks_line("la especie de San Martín con un ejemplar largo".split())
    out = "la superficie de San Martin con un ejemplar largo".split()
    rep = sc.compare(toks, lines, out, [1] * len(out), LEX)
    got = {(it["source"], it["output"]): it["type"] for it in rep["items"]}
    assert got[("especie", "superficie")] == "conflict"
    assert ("Martín", "Martin") in got


def test_compare_flags_missing_line_and_not_present_text():
    toks, lines = toks_line("la especie de un ejemplar largo".split())
    toks, lines = toks_line("Trypanosyllis aeolis Langerhans 1879".split(), line=1, toks=toks, lines=lines)
    toks, lines = toks_line("con el cuerpo largo de casi todos".split(), line=2, toks=toks, lines=lines)
    out = "la especie de un ejemplar largo con el cuerpo largo de casi todos".split()
    rep = sc.compare(toks, lines, out, [1] * len(out), LEX)
    missing = [it for it in rep["items"] if it["type"] == "missing"]
    assert [it["source"] for it in missing] == ["Trypanosyllis aeolis Langerhans 1879"]


def test_compare_calls_line_moved_when_text_is_on_a_nearby_page():
    toks, lines = toks_line("Trypanosyllis aeolis Langerhans 1879".split())
    toks, lines = toks_line("la especie de un ejemplar largo con el cuerpo".split(), page=1, line=1,
                            toks=toks, lines=lines)
    out = "la especie de un ejemplar largo con el cuerpo".split() + "Trypanosyllis aeolis Langerhans 1879".split()
    pages = [1] * 9 + [2] * 4
    rep = sc.compare(toks, lines, out, pages, LEX)
    assert "missing" not in types(rep)
    assert "moved" in types(rep)


def test_compare_ignores_pure_word_split_differences():
    toks, lines = toks_line("con el cuerpo tapa dos largo".split())
    out = "con el cuerpo tapados largo".split()
    rep = sc.compare(toks, lines, out, [1] * len(out), LEX)
    assert rep["items"] == []


def test_name_suspect_when_both_ocrs_agree_on_a_misread_epithet():
    toks, lines = toks_line("Syllis krobnii de un ejemplar largo".split())
    out = "Syllis krobnii de un ejemplar largo".split()
    rep = sc.compare(toks, lines, out, [1] * len(out), LEX)
    sus = [it for it in rep["items"] if it["type"] == "name_suspect"]
    assert [(it["output"], it["suggest"]) for it in sus] == [("krobnii", "krohnii")]


def test_low_confidence_real_word_still_beats_non_word_output():
    toks, lines = toks_line("el cuerpo de casi todos".split())
    toks[-1].conf = 40.0
    out = "el cuerpo de casi todavos".split()
    rep = sc.compare(toks, lines, out, [1] * len(out), LEX)
    assert [(it["source"], it["type"]) for it in rep["items"]] == [("todos", "output_error")]


def test_verdict_skips_noise_and_accepted():
    rep = {"items": [{"id": "a", "type": "tess_noise"}, {"id": "b", "type": "conflict"},
                     {"id": "c", "type": "review"}]}
    ok, open_ = sc.verdict(rep, {"b"})
    assert not ok and open_ == {"review": 1}
    assert sc.verdict(rep, {"b", "c"}) == (True, {})


def test_split_columns_cuts_wide_gaps():
    def w(x, text):  # Tesseract TSV 行：left=6, top=7, width=8, height=9, conf=10, text=11
        return ["5", "1", "1", "1", "1", "1", str(x), "100", "40", "30", "95", text]
    segs = sc.split_columns([w(0, "parte"), w(50, "anterior"), w(900, "nucales"), w(950, "bandas")])
    assert [[t[11] for t in s] for s in segs] == [["parte", "anterior"], ["nucales", "bandas"]]


def test_gate_blocks_on_failed_source_check(tmp_path: Path):
    ok = {"ok": True, "problems": []}
    for name in ("qa", "check"):
        (tmp_path / f"{name}.json").write_text(json.dumps(ok))
    (tmp_path / "key.json").write_text(json.dumps({}))
    (tmp_path / "sc.json").write_text(json.dumps({"ok": False, "open": {"missing": 2}}))
    parser = cli.build_parser()
    args = parser.parse_args(["gate", "--qa", str(tmp_path / "qa.json"), "--check", str(tmp_path / "check.json"),
                              "--key-report", str(tmp_path / "key.json"),
                              "--source-check", str(tmp_path / "sc.json"),
                              "--out", str(tmp_path / "gate.json")])
    assert args.func(args) != 0
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert any("source-check" in p for p in gate["problems"])
    assert gate["coverage"]["source_check"] is True
    assert isinstance(args, argparse.Namespace)


def test_classify_dropped_ordinal_is_tesseract_noise():
    # Vol25 p4: Tesseract reads "M" for the printed "Mª"; the output is right
    assert sc.classify("M", "Mª", LEX) == "tess_noise"
    assert sc.classify("N", "Nº", LEX) == "tess_noise"
    assert sc.classify("Mª", "M", LEX) != "tess_noise"
