"""apply_issues 闸口：问题单可重复应用，已应用的条目跳过，不再叠加（加性改动：补标题、补括注）。合成文本，不联网。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import apply_issues as ai

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def book(tmp_path):
    (tmp_path / "译文").mkdir()
    (tmp_path / "核译").mkdir()
    return tmp_path


def put(book, text, name="ch.md"):
    (book / "译文" / name).write_text(text, encoding="utf8")


def issues(book, rows, name="i.jsonl"):
    p = book / "核译" / name
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    return p


def read(book, name="ch.md"):
    return (book / "译文" / name).read_text(encoding="utf8")


def report(book):
    p = book / "核译" / "核译对照报告.md"
    return p.read_text(encoding="utf8") if p.exists() else ""


def row(old, new, typ="增译", f="ch.md"):
    return {"file": f, "old": old, "new": new, "type": typ, "reason": "测试", "en": ""}


def test_replacement_is_applied_once_and_reapplication_is_skipped_not_rejected(book):
    put(book, "前文。甲乙丙。后文。\n")
    p = issues(book, [row("甲乙丙", "甲丁丙", "误译")])
    r1 = ai.apply(book, p)
    assert (r1.ok, len(r1.bad), len(r1.skipped)) == (1, 0, 0) and read(book) == "前文。甲丁丙。后文。\n"
    rep = report(book)
    r2 = ai.apply(book, p)
    assert (r2.ok, len(r2.bad), len(r2.skipped)) == (0, 0, 1)
    assert read(book) == "前文。甲丁丙。后文。\n" and report(book) == rep          # 文本和对照报告都不变
    assert "已应用" in r2.skipped[0][1]


def test_additive_heading_not_duplicated_on_second_pass(book):
    put(book, "前一段。\n\n角质层及/或其特定层的厚度可有不同。\n")
    p = issues(book, [row("角质层及/或其特定层", "#### 角质层\n\n角质层及/或其特定层")])
    ai.apply(book, p)
    once = read(book)
    assert once == "前一段。\n\n#### 角质层\n\n角质层及/或其特定层的厚度可有不同。\n"
    r2 = ai.apply(book, p)
    assert read(book) == once and r2.ok == 0 and len(r2.skipped) == 1 and not r2.bad
    ai.apply(book, p)
    assert read(book).count("#### 角质层") == 1


def test_additive_bracket_note_not_duplicated(book):
    put(book, "燐虫具顶端微绒毛。\n")
    p = issues(book, [row("燐虫具", "燐虫（*Chaetopterus variopedatus*）具", "术语")])
    ai.apply(book, p)
    ai.apply(book, p)
    ai.apply(book, p)
    assert read(book) == "燐虫（*Chaetopterus variopedatus*）具顶端微绒毛。\n"


def test_trailing_additions_and_same_issue_listed_twice_in_one_file(book):
    put(book, "甲乙。\n")
    p = issues(book, [row("甲乙。", "甲乙。〔译注：丙〕"), row("甲乙。", "甲乙。〔译注：丙〕")])
    r = ai.apply(book, p)
    assert read(book) == "甲乙。〔译注：丙〕\n" and r.ok == 1 and len(r.skipped) == 1 and not r.bad


def test_idempotent_across_several_issues_and_files(book):
    put(book, "甲乙丙。丁戊己。\n", "a.md")
    put(book, "庚辛。\n", "b.md")
    p = issues(book, [row("乙", "乙（x）", "术语", "a.md"), row("丁戊", "#### 小标题\n\n丁戊", "增译", "a.md"),
                      row("庚", "辛", "误译", "b.md")])
    ai.apply(book, p)
    snap = (read(book, "a.md"), read(book, "b.md"), report(book))
    r = ai.apply(book, p)
    assert (read(book, "a.md"), read(book, "b.md"), report(book)) == snap
    assert r.ok == 0 and len(r.skipped) == 3 and not r.bad


def test_genuinely_missing_old_is_still_rejected(book):
    put(book, "甲乙。\n")
    r = ai.apply(book, issues(book, [row("不存在", "别的")]))
    assert r.ok == 0 and len(r.bad) == 1 and not r.skipped and "0 次" in r.bad[0][1]


def test_ambiguous_old_is_still_rejected_even_if_one_hit_is_already_covered(book):
    put(book, "甲乙。#### 角质层\n角质层与甲。\n")
    r = ai.apply(book, issues(book, [row("角质层", "#### 角质层")]))
    assert r.ok == 0 and len(r.bad) == 1 and not r.skipped and "2 次" in r.bad[0][1]
    assert read(book) == "甲乙。#### 角质层\n角质层与甲。\n"


def test_old_equal_new_rejected_and_lost_token_gate_unchanged(book):
    put(book, "Gardiner 说甲乙 12。\n")
    r = ai.apply(book, issues(book, [row("甲乙", "甲乙"), row("Gardiner 说", "他说", "语序"), row("12", "13", "语序")]))
    assert r.ok == 0 and len(r.bad) == 3 and not r.skipped
    assert any("新旧相同" in m for _, m in r.bad)
    assert sum(("丢失英文/数字" in m) or ("丢失数字/学名" in m) for _, m in r.bad) == 2  # 数字改动现由更严的数字规则拒


def test_dry_run_writes_nothing_and_counts_skips(book):
    put(book, "甲乙。\n")
    p = issues(book, [row("甲", "甲（x）")])
    r = ai.apply(book, p, dry=True)
    assert r.ok == 1 and read(book) == "甲乙。\n" and report(book) == ""
    ai.apply(book, p)
    r = ai.apply(book, p, dry=True)
    assert r.ok == 0 and len(r.skipped) == 1


def test_cli_twice_leaves_translation_unchanged(book):
    put(book, "前一段。\n\n角质层的厚度。\n")
    p = issues(book, [row("角质层的", "#### 角质层\n\n角质层的")])
    cmd = [sys.executable, str(REPO / "scripts" / "apply_issues.py"), str(book), str(p)]
    r1 = subprocess.run(cmd, capture_output=True, text=True)
    assert r1.returncode == 0 and "应用 1，拒绝 0" in r1.stdout, r1.stderr
    once = read(book)
    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert read(book) == once and "应用 0，拒绝 0" in r2.stdout and "已应用" in r2.stdout



def test_gated_type_cannot_drop_numbers_or_latin_names(book):
    put(book, "身体长 25 mm，见 *Nereis zonata*。\n")
    r1 = dict(row("长 25 mm", "很长", "误译"), en="Body 25 mm long")
    r2 = dict(row("见 *Nereis zonata*", "见该种", "漏译"), en="see *Nereis zonata*")
    r = ai.apply(book, issues(book, [r1, r2]))
    assert r.ok == 0 and len(r.bad) == 2 and all("丢失数字/学名" in m for _, m in r.bad)


def test_number_absent_from_source_may_be_removed(book):
    put(book, "身体长 25 mm。\n")
    r = ai.apply(book, issues(book, [dict(row("长 25 mm", "长", "增译"), en="Body long")]))
    assert r.ok == 1 and read(book) == "身体长。\n"


def test_cli_exit_code_nonzero_on_rejections(book):
    put(book, "甲乙丙\n")
    p = issues(book, [row("不存在", "x", "误译")])
    assert ai.main([str(book), str(p), "--dry"]) == 1


def test_decimal_comma_in_source_matches_point_in_translation(book):
    put(book, "长 33.6 mm。\n")
    r = ai.apply(book, issues(book, [dict(row("长 33.6 mm", "长 33.6 毫米", "术语"), en="дълъг 33,6 mm")]))
    assert r.ok == 1


def test_crlf_file_matches_with_lf_old_and_keeps_crlf(book):
    (book / "译文" / "ch.md").write_bytes("甲刚毛。\r\n乙疣足。\r\n".encode("utf8"))
    p = issues(book, [row("甲刚毛。\n乙疣足", "甲刚毛。\n乙疣足长", "误译")])
    assert ai.apply(book, p).ok == 1
    assert (book / "译文" / "ch.md").read_bytes() == "甲刚毛。\r\n乙疣足长。\r\n".encode("utf8")


def test_lf_file_stays_lf(book):
    put(book, "甲刚毛。\n乙疣足。\n")
    assert ai.apply(book, issues(book, [row("乙疣足", "乙疣足长", "误译")])).ok == 1
    assert (book / "译文" / "ch.md").read_bytes() == "甲刚毛。\n乙疣足长。\n".encode("utf8")
