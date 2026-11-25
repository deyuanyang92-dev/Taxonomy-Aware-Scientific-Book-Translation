import json
import subprocess
import threading
from pathlib import Path

import fitz
import pytest

from docstore import cli, open_store, proofread
from docstore.store import make_version

# Synthetic text: one deliberate recognition error, stable line/word counts.
TEXT = "\n".join(["Die Borsten sind lang und besitzen feine Zahne am oberen Rand."] * 10)
FLAGGED_TEXT = TEXT.replace("sind lang und besitzen feine Zahne am oberen Rand.",
                            "Alpha Bravo Charlie Delta Echo Foxtrot 101 202 303 404", 1)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSTORE_AGENT", "pytest")
    pdf_path = tmp_path / "synthetic.pdf"
    with fitz.open() as pdf:
        for _ in range(5):
            pdf.new_page(width=120, height=160).insert_text((10, 20), "Die Borsten")
        pdf.save(pdf_path)
    store = open_store(tmp_path / "lib")
    key, _ = store.register(pdf_path, key="HartmannSchroder_test", by="pytest")
    store.put_version(key, 1, make_version(TEXT, "ocr", producer="tesseract", engine="tesseract deu",
                                         dpi=200, level="ocr_sampled", conf=0.81))
    return store, key


def read_audit(store, key, rejects=False):
    prefix = "proofread_rejects" if rejects else "proofread"
    return [json.loads(line) for line in (store.root / "_audit" / f"{prefix}_{key}.jsonl").read_text().splitlines()]


def fix_word(prompt, image):
    assert prompt.startswith(proofread.PROMPT)
    assert image.read_bytes().startswith(b"\x89PNG")
    return prompt[len(proofread.PROMPT):].replace("Zahne", "Zähne", 1)


def test_accepts_promotes_preserves_confidence_and_audits(lib, capsys):
    store, key = lib
    stats = proofread.proofread_doc(store, key, runner=fix_word, by="codex")
    assert stats == {"candidates": 1, "done": 1, "accepted": 1, "rejected": 0, "failed": 0, "flagged": 0}
    page = store.read_page(key, 1)
    assert page["text"] == TEXT.replace("Zahne", "Zähne", 1)
    assert page["producer"] == "proofread:codex-sol"
    assert page["engine"] == "tesseract deu + proofread:codex-sol"
    assert page["method"] == "ocr" and page["dpi"] == 200 and page["verify_level"] == "ocr_sampled"
    assert page["quality"]["ocr_conf"] == 0.81
    assert page["alternates"][0]["text"] == TEXT
    assert "by codex" in page["source"]
    assert page["extra"]["proofread"] == {"changed_words": 1, "base_producer": "tesseract"}
    assert page["extra"]["run_by"] == "codex"
    record, = read_audit(store, key)
    assert record["accepted"] is True and record["reasons"] == [] and record["by"] == "codex"
    assert record["flags"] == []
    assert record["conf"] == 0.81 and record["word_diff"] == [[["Zahne"], ["Zähne"]]]
    assert record["proofread"] == {"changed_words": 1, "base_producer": "tesseract"}
    output = capsys.readouterr().out
    assert "accepted" in output and "flags=" not in output


def test_hallucination_is_stored_without_promotion_and_resume_skips(lib):
    store, key = lib
    hallucination = "An entirely invented description. " * 500
    stats = proofread.proofread_doc(store, key, runner=lambda *_: hallucination)
    assert stats["rejected"] == 1 and stats["accepted"] == stats["failed"] == 0
    page = store.read_page(key, 1)
    assert page["text"] == TEXT and page["producer"] == "tesseract"
    rejected, = page["alternates"]
    assert rejected["text"] == hallucination and rejected["producer"] == "proofread:codex-sol"
    assert rejected["proofread"]["base_producer"] == "tesseract"
    assert read_audit(store, key) == read_audit(store, key, rejects=True)
    assert any("word count ratio" in r for r in read_audit(store, key)[0]["reasons"])
    assert proofread.candidates(store, key) == []
    stats = proofread.proofread_doc(store, key, runner=lambda *_: pytest.fail("resume called model"))
    assert stats["done"] == 0 and stats["candidates"] == 0


@pytest.mark.parametrize("rejected", [False, True])
def test_flagged_pages_are_counted_and_audited_without_rejecting_for_flags(lib, capsys, rejected):
    store, key = lib
    new = FLAGGED_TEXT + ("\n" * 10 if rejected else "")
    stats = proofread.proofread_doc(store, key, runner=lambda *_: new)
    assert stats["flagged"] == 1 and stats["failed"] == 0
    assert stats["accepted"] == int(not rejected) and stats["rejected"] == int(rejected)
    record, = read_audit(store, key)
    assert record["flags"] == ["new_capitalised:6", "digits_changed:4"]
    assert record["accepted"] is not rejected
    assert "flags=new_capitalised:6,digits_changed:4" in capsys.readouterr().out
    if rejected:
        assert read_audit(store, key, rejects=True) == [record]


def test_resume_skips_promoted_page(lib):
    store, key = lib
    proofread.proofread_doc(store, key, runner=fix_word)
    assert proofread.candidates(store, key) == []
    proofread.proofread_doc(store, key, runner=lambda *_: pytest.fail("resume called model"))
    assert len(read_audit(store, key)) == 1


def test_metadata_retained_if_another_writer_demotes_page(lib, monkeypatch):
    store, key = lib
    put = store.put_version

    def put_then_demote(*args, **kwargs):
        result = put(*args, **kwargs)
        put(key, 1, make_version(TEXT, "verified", producer="other-agent", source="other"), promote=True)
        return result

    monkeypatch.setattr(store, "put_version", put_then_demote)
    assert proofread.proofread_doc(store, key, runner=fix_word)["accepted"] == 1
    page = store.read_page(key, 1)
    assert page["producer"] == "other-agent"
    version = next(v for v in page["alternates"] if v["producer"] == "proofread:codex-sol")
    assert version["proofread"] == {"changed_words": 1, "base_producer": "tesseract"}
    assert version["run_by"] == "pytest"


@pytest.mark.parametrize(("page", "expected"), [
    ({"quality": {"ocr_conf": 0.72}, "alternates": [{"method": "ocr", "quality": {"ocr_conf": 0.5}}]}, 0.72),
    ({"quality": {"ocr_conf": None}, "alternates": [
        {"method": "text_layer", "quality": {"ocr_conf": 0.4}},
        {"method": "ocr", "quality": {}},
        {"method": "ocr", "quality": {"ocr_conf": 0.0}},
        {"method": "ocr", "quality": {"ocr_conf": 0.9}}]}, 0.0),
    ({"quality": None, "alternates": [{"method": "ocr", "quality": {"ocr_conf": 0.8}}]}, 0.8),
    ({}, None),
    ({"alternates": [{"method": "text_layer", "quality": {"ocr_conf": 0.4}}]}, None),
])
def test_page_conf(page, expected):
    assert proofread.page_conf(page) == expected


def test_candidates_filters_sorts_and_recovers_old_confidence(lib):
    store, key = lib
    # Simulate a historical latinfix version with missing confidence.
    store.put_version(key, 1, make_version(TEXT, "ocr", producer="latinfix", source="latinfix"), promote=True)
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tess", conf=0.7))
    store.put_version(key, 3, make_version(TEXT, "ocr", producer="tess", conf=0.92))
    store.put_version(key, 4, make_version("short", "ocr", producer="tess", conf=0.2))
    store.put_version(key, 5, make_version(TEXT, "ocr", producer="tess"))
    assert proofread.candidates(store, key) == [(2, 0.7), (1, 0.81)]
    assert proofread.candidates(store, key, pages=[1, 3, 5], include_unknown=True) == [(1, 0.81), (5, None)]
    assert proofread.candidates(store, key, below=0.7) == []
    assert proofread.candidates(store, key, min_chars=5, pages=[4]) == [(4, 0.2)]
    proofread.proofread_doc(store, key, pages=[1], runner=fix_word)
    assert store.read_page(key, 1)["quality"]["ocr_conf"] == 0.81


@pytest.mark.parametrize(("new", "reason"), [
    ("", "empty text"),
    ("  \n", "empty text"),
    ("wort " * 108, "word count ratio"),
    ("wort " * 92, "word count ratio"),
    ("\n".join(["wort"] * 100), "line count"),
    ("Here " + "wort " * 99, "non-text chatter"),
    (" Sure " + "wort " * 99, "non-text chatter"),
    ("``` " + "wort " * 99, "non-text chatter"),
    ("wort " * 98 + "OCR TEXT", "non-text chatter"),
])
def test_sanity_rejects(new, reason):
    assert any(reason in item for item in proofread.sanity("wort " * 100, new))


def test_sanity_allows_small_corrections_and_threshold_boundaries():
    assert proofread.sanity(TEXT, TEXT.replace("Zahne", "Zähne", 1)) == []
    words = [f"word{i}" for i in range(107)]
    assert proofread.sanity(" ".join(words[:100]), " ".join(words[:93])) == []
    assert proofread.sanity(" ".join(words[:100]), " ".join(words)) == []
    assert proofread.sanity("\n".join(["wort"] * 10), "\n".join(["wort"] * 7 + ["wort wort wort"])) == []
    assert proofread.sanity("", "invention")


def test_flags_count_numeric_replacements_deletions_and_insertions():
    old = "wort " * 100 + "1 2 3 4"
    for new in ("wort " * 100 + "5 6 7 8", "wort " * 100, old + " 5 6 7 8"):
        assert proofread.flags(old, new) == ["digits_changed:4"]
        assert proofread.sanity(old, new) == []


def test_flags_percentage_thresholds():
    old = " ".join(["Bekannt"] * 200)
    assert proofread.flags(old, old.replace("Bekannt", "Neuwort", 6)) == []
    assert proofread.flags(old, old.replace("Bekannt", "Neuwort", 7)) == ["new_capitalised:7"]
    old = " ".join(str(n) for n in range(200))
    assert proofread.flags(old, " ".join(["999"] * 6 + old.split()[6:])) == []
    assert proofread.flags(old, " ".join(["999"] * 7 + old.split()[7:])) == ["digits_changed:7"]


@pytest.mark.parametrize(("replacement", "expected"), [
    ("Alpha Bravo Charlie Delta Echo", []),
    ("Alpha Bravo Charlie Delta Echo Foxtrot", ["new_capitalised:6"]),
    ("1 2 3", []),
    ("1 2 3 4", ["digits_changed:4"]),
    ("Alpha Bravo Charlie Delta Echo Foxtrot 1 2 3 4", ["new_capitalised:6", "digits_changed:4"]),
])
def test_flags_fixed_thresholds_do_not_reject(replacement, expected):
    old = "wort " * 100
    new = replacement + " " + "wort " * (100 - len(replacement.split()))
    assert proofread.flags(old, new) == expected
    assert proofread.sanity(old, new) == []


def test_flags_ignore_known_and_short_capitalised_words():
    old = "Alpha wort " * 50
    new = "Alpha Beta Ab " * 6 + "wort " * 82
    assert proofread.flags(old, new) == ["new_capitalised:6"]


@pytest.mark.parametrize(("changed", "expected"), [(50, []), (51, ["rewrite: changed 51% of words"])])
def test_sanity_rewrite_fraction_boundary(changed, expected):
    old = [f"word{i}" for i in range(100)]
    new = [f"fix{i}" if i < changed else w for i, w in enumerate(old)]
    assert proofread.sanity(" ".join(old), " ".join(new)) == expected


def test_sanity_rewrite_counts_insertions_and_deletions():
    old = [f"word{i}" for i in range(100)]
    new = old[26:] + [f"added{i}" for i in range(26)]
    assert proofread.sanity(" ".join(old), " ".join(new)) == ["rewrite: changed 52% of words"]


def test_sanity_repetition_loop_is_contiguous_and_relative_to_original():
    words = [f"word{i}" for i in range(300)]
    phrase = ["one", "two", "three", "four", "five", "six"]
    base = " ".join(words)
    assert proofread.sanity(base, " ".join(phrase * 2 + words[12:])) == []
    assert proofread.sanity(base, " ".join(phrase * 3 + words[18:])) == ["repetition loop"]
    # 文献条目式的非连续重复（×20）是合法的
    spread = []
    for i in range(20):
        spread += phrase + words[i * 10:i * 10 + 4]
    assert proofread.sanity(" ".join(spread), " ".join(spread)) == []
    assert "repetition loop" not in proofread.sanity(" ".join(spread), " ".join(spread).replace("word0", "Word0"))
    # 原文已有同样的连续重复：不算模型造成
    looped = " ".join(phrase * 3 + words[18:])
    assert proofread.sanity(looped, looped.replace("word20", "Word20")) == []


def test_word_diff():
    assert proofread.word_diff("a b c d", "a B c d extra") == [(["b"], ["B"]), ([], ["extra"])]
    assert proofread.word_diff("a b c", "a c") == [(["b"], [])]
    assert proofread.word_diff("a\nb c", "a b  c") == []


def test_empty_output_retried_once(lib):
    store, key = lib
    calls = []

    def runner(prompt, image):
        calls.append(image)
        return " \n" if len(calls) == 1 else fix_word(prompt, image)

    assert proofread.proofread_doc(store, key, runner=runner)["accepted"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["empty", "exception", "render"])
def test_failed_pages_audited_and_retryable(lib, monkeypatch, failure):
    store, key = lib
    calls = []

    def fail(*_):
        calls.append(1)
        if failure == "empty":
            return ""
        raise RuntimeError("synthetic failure")

    if failure == "render":
        monkeypatch.setattr(proofread, "page_png", fail)
    stats = proofread.proofread_doc(store, key, runner=fail)
    assert stats["done"] == stats["failed"] == 1 and stats["accepted"] == stats["rejected"] == 0
    assert len(calls) == (2 if failure == "empty" else 1)
    assert store.read_page(key, 1)["alternates"] == []
    record, = read_audit(store, key)
    assert record["accepted"] is False and record["reasons"] and record["word_diff"] == []
    assert record["flags"] == [] and stats["flagged"] == 0
    assert proofread.candidates(store, key) == [(1, 0.81)]


def test_dry_run_limit_and_cli(lib, monkeypatch, capsys):
    store, key = lib
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tess", conf=0.5))
    store.put_version(key, 3, make_version(TEXT, "ocr", producer="tess"))
    before = {n: store.page_path(key, n).read_bytes() for n in [1, 2, 3]}
    monkeypatch.setattr(proofread, "page_png", lambda *_: pytest.fail("dry run rendered"))
    monkeypatch.setattr(proofread, "_codex_runner", lambda *_: pytest.fail("dry run called codex"))
    assert cli.main(["--root", str(store.root), "proofread", key, "--pages", "1-3", "--limit", "1",
                     "--below", "0.9", "--workers", "2", "--engine", "codex-sol", "--include-unknown", "--dry"]) == 0
    output = capsys.readouterr().out
    assert "page=2" in output and "page=1" not in output and "projected_calls=1" in output
    assert json.loads(output.splitlines()[-1]) == {
        "candidates": 3, "done": 0, "accepted": 0, "rejected": 0, "failed": 0, "flagged": 0}
    assert not (store.root / "_audit").exists()
    assert before == {n: store.page_path(key, n).read_bytes() for n in [1, 2, 3]}


def test_cli_writer_convention(lib, monkeypatch, capsys):
    store, key = lib
    monkeypatch.delenv("DOCSTORE_AGENT")
    monkeypatch.setattr(proofread, "_codex_runner", fix_word)
    cli.main(["--root", str(store.root), "proofread", key])
    assert "unknown" in capsys.readouterr().err
    assert read_audit(store, key)[0]["by"] == "unknown"


def test_cli_explicit_by(lib, monkeypatch):
    store, key = lib
    monkeypatch.setattr(proofread, "_codex_runner", fix_word)
    cli.main(["--root", str(store.root), "--by", "explicit-agent", "proofread", key])
    assert read_audit(store, key)[0]["by"] == "explicit-agent"


def test_pool_runs_calls_in_parallel_but_renders_and_writes_on_main_thread(lib, monkeypatch):
    store, key = lib
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tess", conf=0.7))
    main_thread = threading.get_ident()
    render = proofread.page_png
    put = store.put_version
    barrier = threading.Barrier(2)

    def render_on_main(*args):
        assert threading.get_ident() == main_thread
        return render(*args)

    def write_on_main(*args, **kwargs):
        assert threading.get_ident() == main_thread
        return put(*args, **kwargs)

    def runner(prompt, image):
        assert threading.get_ident() != main_thread
        barrier.wait(timeout=10)
        return fix_word(prompt, image)

    monkeypatch.setattr(proofread, "page_png", render_on_main)
    monkeypatch.setattr(store, "put_version", write_on_main)
    stats = proofread.proofread_doc(store, key, runner=runner, workers=2)
    assert stats["accepted"] == stats["done"] == 2


def test_limit_selects_lowest_confidence_and_unknown_opt_in(lib):
    store, key = lib
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tess", conf=0.4))
    store.put_version(key, 3, make_version(TEXT, "ocr", producer="tess"))
    stats = proofread.proofread_doc(store, key, limit=1, runner=fix_word)
    assert stats["candidates"] == 2 and stats["done"] == 1
    assert store.read_page(key, 2)["producer"] == "proofread:codex-sol"
    assert store.read_page(key, 1)["producer"] == "tesseract"
    assert proofread.proofread_doc(store, key, pages=[3], runner=fix_word)["done"] == 0
    assert proofread.proofread_doc(store, key, pages=[3], include_unknown=True, runner=fix_word)["done"] == 1
    assert "ocr_conf" not in store.read_page(key, 3)["quality"]


def test_audit_diff_is_capped_without_losing_change_count(lib):
    store, key = lib
    old = " ".join(f"same{i} wrong" for i in range(250))
    store.put_version(key, 1, make_version(old, "ocr", producer="test", conf=0.5), promote=True)
    stats = proofread.proofread_doc(store, key, runner=lambda *_: old.replace("wrong", "right"))
    assert stats["accepted"] == 1
    record, = read_audit(store, key)
    assert len(record["word_diff"]) == 200 and record["proofread"]["changed_words"] == 250


def test_codex_flags_and_fresh_empty_working_directory(tmp_path, monkeypatch):
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic image")
    directories = []

    def fake_run(args, **kwargs):
        assert args[:9] == ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m", "gpt-6.1-sol",
                            "-o", args[8]]
        wd = Path(args[args.index("-C") + 1])
        directories.append(wd)
        assert list(wd.iterdir()) == [] and kwargs["cwd"] == str(wd)
        assert args[-3:] == ["-i", str(image), "-"]
        assert kwargs == {"input": "prompt", "text": True, "capture_output": True,
                          "timeout": 900, "cwd": str(wd), "check": True}
        Path(args[8]).write_text("corrected text", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert proofread._codex_runner("prompt", image) == "corrected text"
    assert proofread._codex_runner("prompt", image) == "corrected text"
    assert directories[0] != directories[1] and all(not wd.exists() for wd in directories)


def test_codex_failure_does_not_use_partial_output(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        Path(args[8]).write_text("partial text")
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        proofread._codex_runner("prompt", tmp_path / "image.png")


@pytest.mark.parametrize("kwargs", [{"workers": 0}, {"limit": -1}, {"engine": "unknown"}])
def test_invalid_options(lib, kwargs):
    store, key = lib
    with pytest.raises(ValueError):
        proofread.proofread_doc(store, key, **kwargs)


def rejected_alternate(store, key, text=FLAGGED_TEXT, *, page=1, time="2026-01-02T00:00:00"):
    metadata = {"changed_words": sum(max(len(a), len(b)) for a, b in proofread.word_diff(TEXT, text)),
                "base_producer": "tesseract"}
    version = make_version(text, "ocr", producer="proofread:codex-sol", engine="tesseract deu + proofread:codex-sol",
                           dpi=200, level="ocr_sampled", conf=0.81, source="historical proofreading", time=time,
                           extra={"proofread": metadata, "run_by": "original-agent"})
    store.put_version(key, page, version, promote=False)
    return version


@pytest.fixture
def rejudge_lib(lib, monkeypatch):
    monkeypatch.setattr(proofread, "page_png", lambda *_: pytest.fail("rejudge rendered an image"))
    monkeypatch.setattr(proofread, "_codex_runner", lambda *_: pytest.fail("rejudge called codex"))
    return lib


def test_rejudge_promotes_stored_rejection_and_retains_metadata(rejudge_lib):
    store, key = rejudge_lib
    version = rejected_alternate(store, key)
    assert proofread.rejudge_doc(store, key, by="review-agent") == {
        "checked": 1, "promoted": 1, "still_rejected": 0}
    page = store.read_page(key, 1)
    for field in ("text", "producer", "engine", "dpi", "verify_level", "quality", "source", "time"):
        assert page[field] == version[field]
    assert page["extra"]["proofread"] == version["proofread"]
    assert page["extra"]["run_by"] == "original-agent"
    assert len(page["alternates"]) == 1 and page["alternates"][0]["text"] == TEXT
    assert store.page(key, 1)["text"] == FLAGGED_TEXT
    assert store.con.execute("SELECT text FROM pages WHERE key=? AND page=1", (key,)).fetchone()[0] == FLAGGED_TEXT
    record, = read_audit(store, key)
    assert record["rejudged"] is True and record["accepted"] is True and record["reasons"] == []
    assert record["by"] == "review-agent" and record["proofread"] == version["proofread"]
    assert record["flags"] == ["new_capitalised:6", "digits_changed:4"]
    assert not (store.root / "_audit" / f"proofread_rejects_{key}.jsonl").exists()


def test_rejudge_skips_primary_proofread_and_pages_without_alternates(rejudge_lib):
    store, key = rejudge_lib
    rejected_alternate(store, key)
    proofread.rejudge_doc(store, key)
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tesseract", conf=0.5))
    before = store.page_path(key, 1).read_bytes()
    assert proofread.rejudge_doc(store, key) == {"checked": 0, "promoted": 0, "still_rejected": 0}
    assert store.page_path(key, 1).read_bytes() == before
    assert len(read_audit(store, key)) == 1


@pytest.mark.parametrize("newest_rejected", [False, True])
def test_rejudge_selects_newest_alternate_and_audits_remaining_rejections(rejudge_lib, newest_rejected):
    store, key = rejudge_lib
    bad = "invented " * 500
    newest = bad if newest_rejected else FLAGGED_TEXT
    rejected_alternate(store, key, newest, time="2026-01-03T00:00:00")
    rejected_alternate(store, key, FLAGGED_TEXT if newest_rejected else bad, time="2026-01-01T00:00:00")
    before = store.page_path(key, 1).read_bytes()
    assert proofread.rejudge_doc(store, key) == {
        "checked": 1, "promoted": int(not newest_rejected), "still_rejected": int(newest_rejected)}
    record, = read_audit(store, key)
    assert record["rejudged"] is True and record["accepted"] is not newest_rejected
    assert "flags" in record
    if newest_rejected:
        assert record["reasons"] and read_audit(store, key, rejects=True) == [record]
        assert store.page_path(key, 1).read_bytes() == before
    else:
        assert store.read_page(key, 1)["text"] == newest


def test_rejudge_respects_page_filter(rejudge_lib):
    store, key = rejudge_lib
    rejected_alternate(store, key)
    store.put_version(key, 2, make_version(TEXT, "ocr", producer="tesseract"))
    rejected_alternate(store, key, page=2)
    assert proofread.rejudge_doc(store, key, pages=iter([2])) == {
        "checked": 1, "promoted": 1, "still_rejected": 0}
    assert store.read_page(key, 1)["text"] == TEXT
    assert store.read_page(key, 2)["text"] == FLAGGED_TEXT
    assert read_audit(store, key)[0]["page"] == 2


def test_rejudge_dry_run_changes_nothing(rejudge_lib, capsys):
    store, key = rejudge_lib
    rejected_alternate(store, key)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert proofread.rejudge_doc(store, key, dry=True) == {"checked": 1, "promoted": 0, "still_rejected": 0}
    assert "would promote" in capsys.readouterr().out
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("dry", [False, True])
def test_cli_rejudge_path(rejudge_lib, monkeypatch, capsys, dry):
    store, key = rejudge_lib
    rejected_alternate(store, key)
    monkeypatch.setattr(proofread, "proofread_doc", lambda *_a, **_kw: pytest.fail("called proofread_doc"))
    args = ["--root", str(store.root), "--by", "review-agent", "proofread", key, "--rejudge", "--pages", "1"]
    assert cli.main(args + (["--dry"] if dry else [])) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == {
        "checked": 1, "promoted": int(not dry), "still_rejected": 0}
    assert store.read_page(key, 1)["producer"] == ("tesseract" if dry else "proofread:codex-sol")
    if not dry:
        assert read_audit(store, key)[0]["by"] == "review-agent"
