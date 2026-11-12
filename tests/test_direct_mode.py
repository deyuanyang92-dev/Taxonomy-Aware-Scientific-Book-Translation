"""run_batches 直调模式：切块、系统提示词、断点续跑、疑似拒译、核译问题单合并。全部用假调用，不联网。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import direct_mode as dm
import run_batches

REPO = Path(__file__).resolve().parent.parent
PARA = "Nereis has parapodia with notopodial ligules. Sp. and Fig. 3 are listed (O.F. Müller, 1776). "


def make_text(n_chars):
    out, total = [], 0
    while total < n_chars:
        out.append(PARA * 3)
        total += len(out[-1])
    return "\n".join(out)


# ---------- 切块 ----------

def test_split_prefers_paragraph_break():
    para = ("A" * 40 + ". " + "word " * 100).strip() + "."  # ~540 字符
    text = "\n\n".join([para] * 6)
    chunks = dm.split_chunks(text, 1300)
    assert len(chunks) >= 3
    assert all(len(c) <= 1300 + 1000 for c in chunks)
    # 在空行处断开：每块都是完整段落的整数倍
    assert all(c.count(para) >= 1 and c.replace(para, "").strip() == "" for c in chunks)


def test_split_ignores_blank_line_inside_sentence():
    """PDF 抽取在图注、换页处插空行，句子没完的空行不是段落边界。"""
    body = "word " * 150  # 750 字符，不含句末标点
    text = body + "and the sentence\n\ncontinues here. " + "more " * 150 + "end."
    first = dm.split_chunks(text, 1000)[0]
    assert first.endswith("continues here.") and "and the sentence\n\ncontinues" in first


def test_split_at_sentence_end_not_abbreviation():
    text = ("This is one sentence about Platynereis dumerilii (O.F. Müller, 1776) and Fig. 3 and sp. nov. " * 30)
    chunks = dm.split_chunks(text, 1000)
    assert len(chunks) > 1
    for c in chunks[:-1]:
        assert c.endswith("nov.") or c.endswith("sentence about Platynereis dumerilii (O.F. Müller, 1776) and Fig. 3 and sp. nov.")
        assert not c.endswith(("O.F.", "Fig.", "sp."))
    assert "".join("".join(chunks).split()) == "".join(text.split())  # 不丢字


def test_split_without_blank_lines_hard_wrapped():
    text = "\n".join(["line of hard wrapped text number %d without period" % i for i in range(300)])
    chunks = dm.split_chunks(text, 2000)
    assert len(chunks) > 1 and all(len(c) < 3000 for c in chunks)
    assert "".join("".join(chunks).split()) == "".join(text.split())


def test_split_short_text_single_and_tiny_tail_merged():
    assert dm.split_chunks("short.", 9000) == ["short."]
    chunks = dm.split_chunks(("word. " * 300) + "tail end.", 1000)
    assert chunks[-1].endswith("tail end.") and len(chunks[-1]) > 20


# ---------- 系统提示词 ----------

def test_build_system_translate_has_purpose_rules_style_output(tmp_path):
    s = dm.build_system("translate", "分类学", "（一章）", "本书补充：科名以杨德渐为准")
    assert s.startswith("用途说明：用户是分类学研究者，拥有本书")
    assert "请完整逐句翻译" in s
    assert "通用翻译规范" in s  # RULES.md
    assert "领域包：分类学" in s
    assert "译风指南" in s  # STYLE.md
    assert "### 待定术语" in s and "本次输出要求" in s
    assert "本书补充说明" in s and "杨德渐" in s


def test_build_system_review_has_jsonl_requirements():
    s = dm.build_system("review", "分类学")
    assert "独立核译员" in s and "核译输出要求" in s
    assert '"old"' in s and "JSONL" in s
    assert "## C. 术语查证" not in s
    with pytest.raises(ValueError):
        dm.build_system("other", "分类学")


def test_skill_dir_resolves_in_repo():
    assert (dm.skill_dir() / "RULES.md").exists()


# ---------- 输出整理 ----------

def test_strip_pending_and_parse_jsonl():
    body, pend = dm.strip_pending("译文一\n\n### 待定术语\nnuchal organ｜项器｜依据\n- foo｜富｜暂定\n")
    assert body == "译文一" and pend == ["nuchal organ｜项器｜依据", "foo｜富｜暂定"]
    assert dm.strip_pending("只有译文") == ("只有译文", [])
    text = '```jsonl\n{"old":"甲","new":"乙","type":"误译"}\n说明文字\n{坏json\n{"x":1}\n```'
    assert dm.parse_jsonl(text) == [{"old": "甲", "new": "乙", "type": "误译"}]


# ---------- 整章流程（假调用） ----------

@pytest.fixture
def book(tmp_path, monkeypatch):
    (tmp_path / "src_en").mkdir()
    (tmp_path / "译文").mkdir()
    (tmp_path / "src_en" / "ch05.txt").write_text("Nereididae Blainville, 1818\n" + make_text(2500), encoding="utf8")
    monkeypatch.setattr(dm, "yiku_table", lambda f, d, s: f"| 英文 | 译名 |\n术语表 scope={s}\n")
    return tmp_path


class Fake:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, engine, system, user, **kw):
        self.calls.append((engine, user, kw))
        r = self.reply(user) if callable(self.reply) else self.reply
        return r, {"input_tokens": 1, "output_tokens": 1}


def zh_for(user):
    n = user.split("请翻译以下英文原文：")[1].count("Nereis")
    return "沙蚕" * 400 + f"（{n}）\n\n### 待定术语\nnuchal organ｜项器｜暂定\n"


def test_prepare_writes_chunks_and_terms_and_scope(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", None)
    assert len(ids) >= 3
    assert (ch.dir / "chunks" / "c00.txt").exists()
    assert "scope=Nereididae" in (ch.dir / "terms" / "c00.md").read_text(encoding="utf8")
    # 原文变了要报错，不混用新旧块
    (book / "src_en" / "ch05.txt").write_text("changed text. " * 500, encoding="utf8")
    with pytest.raises(RuntimeError, match="原文或块长已变"):
        dm.Chapter(book, "ch05", 1000).prepare("分类学", None)


def test_translate_resume_and_merge_strips_pending(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    f = Fake(zh_for)
    n, skipped, fails = dm.run_translate(ch, ids, "claude-sonnet", "SYS", f)
    assert (n, skipped, fails) == (len(ids), 0, [])
    first_user = f.calls[0][1]
    assert first_user.startswith("本块术语表（来自 yiku）：") and "术语表 scope=Nereididae" in first_user
    assert f.calls[0][2]["tag"].startswith("ch05/c")
    # 再跑一次：全部跳过，不再调用
    f2 = Fake(zh_for)
    assert dm.run_translate(ch, ids, "claude-sonnet", "SYS", f2) == (0, len(ids), [])
    assert f2.calls == []
    msg = dm.merge_translation(ch, ids)
    assert "已合并" in msg
    merged = ch.merged.read_text(encoding="utf8")
    assert "### 待定术语" not in merged and merged.count("沙蚕") >= 400 * len(ids)
    pend = (ch.dir / "pending_terms.tsv").read_text(encoding="utf8")
    assert pend.count("nuchal organ") == 1  # 跨块去重
    # 已存在不覆盖
    ch.merged.write_text("用户改过", encoding="utf8")
    assert "不覆盖" in dm.merge_translation(ch, ids) and ch.merged.read_text(encoding="utf8") == "用户改过"


def test_refusal_goes_to_suspect_and_is_not_done(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    f = Fake("抱歉，出于版权原因我无法翻译这段内容。")
    n, skipped, fails = dm.run_translate(ch, ids, "claude-sonnet", "SYS", f)
    assert n == 0 and len(fails) == len(ids) and "疑似拒译" in fails[0]
    assert not (ch.dir / "out" / "c00.md").exists() and (ch.dir / "out" / "c00.suspect.md").exists()
    assert "未合并" in dm.merge_translation(ch, ids)


def test_engine_error_does_not_stop_other_chunks(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")

    def reply(user):
        if "Nereididae Blainville" in user:  # 第一块
            raise RuntimeError("推理耗尽")
        return zh_for(user)

    n, _, fails = dm.run_translate(ch, ids, "deepseek-v4-pro", "SYS", Fake(reply), jobs=2)
    assert n == len(ids) - 1 and len(fails) == 1 and "推理耗尽" in fails[0]


def test_review_and_merge_issues(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_for))
    dm.merge_translation(ch, ids)
    merged = ch.merged.read_text(encoding="utf8")

    def review_reply(user):
        assert user.startswith("file: ch05_直译初译.md") and "=== 英文原文 ===" in user and "=== 中文译文 ===" in user
        assert "### 待定术语" not in user.split("=== 中文译文 ===")[1]
        cid_has_first = "Nereididae Blainville" in user
        if cid_has_first:
            return '```\n{"file":"c00.md","old":"沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕","new":"X","type":"术语"}\n{"old":"不存在的句子","new":"Y","type":"误译"}\n```'
        return ""

    n, skipped, fails = dm.run_review(ch, ids, "deepseek-flash", "SYS", Fake(review_reply))
    assert n == len(ids) and fails == []
    assert (ch.dir / "review" / "c01.jsonl").read_text() == ""  # 空文件也表示已核过
    assert dm.run_review(ch, ids, "deepseek-flash", "SYS", Fake("")) == (0, len(ids), [])
    ok, bad = dm.merge_review(ch, ids)
    # 「沙蚕」重复多次：old 在合并译文中不是恰好 1 次，进拒绝；不存在的句子同理
    assert merged.count("沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕沙蚕") > 1
    assert (ok, bad) == (0, 2)
    rej = [json.loads(ln) for ln in (ch.dir / "rejected.jsonl").read_text(encoding="utf8").splitlines()]
    assert {r["file"] for r in rej} == {"ch05_直译初译.md"} and all("reject" in r for r in rej)


def test_merge_review_accepts_unique_old(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(lambda u: f"独一无二的句子{len(u)}。" + "沙蚕" * 300))
    dm.merge_translation(ch, ids)
    merged = ch.merged.read_text(encoding="utf8")
    old = merged.splitlines()[0][:12]
    assert merged.count(old) == 1
    (ch.dir / "review").mkdir(exist_ok=True)
    (ch.dir / "review" / "c00.jsonl").write_text(json.dumps({"old": old, "new": "改后", "type": "误译"}, ensure_ascii=False) + "\n", encoding="utf8")
    ok, bad = dm.merge_review(ch, ids)
    assert (ok, bad) == (1, 0)
    it = json.loads(ch.issues.read_text(encoding="utf8"))
    assert it["file"] == "ch05_直译初译.md" and it["chunk"] == "c00"


# ---------- 命令行 ----------

def run_cli(book, *args, env=None):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), str(book), *args],
                          capture_output=True, text=True, env=env)


def test_cli_agent_mode_choices_unchanged_and_help_mentions_default_allocation():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "claude-sonnet" in r.stdout and "deepseek-flash" in r.stdout and "codex" in r.stdout
    assert "初译 claude-sonnet" in r.stdout.replace("\n", "").replace("  ", "")


def test_cli_direct_dry_writes_system_without_calling_models(book, tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "yiku").write_text("#!/bin/sh\necho '| 英文 | 译名 |'\n")
    (fake_bin / "yiku").chmod(0o755)
    import os
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    r = run_cli(book, "--mode", "translate", "--chapters", "ch05", "--engine", "claude-sonnet", "--dry",
                "--chunk-chars", "1000", env=env)
    assert r.returncode == 0, r.stderr
    d = book / "核译" / "direct" / "ch05"
    assert (d / "system_translate.md").read_text(encoding="utf8").startswith("用途说明")
    assert len(list((d / "chunks").glob("c*.txt"))) >= 3
    assert not (d / "out").exists()


def test_cli_direct_requires_chapters_and_refuses_same_engine(book):
    r = run_cli(book, "--mode", "translate", "--engine", "deepseek-flash")
    assert r.returncode != 0 and "--chapters" in (r.stdout + r.stderr)


def test_run_direct_same_engine_refused(book, monkeypatch):
    import types
    a = types.SimpleNamespace(chapters="ch05", mode="review", domain="分类学", book_desc="", scope="Nereididae",
                              chunk_chars=1000, dry=False, engine="claude-sonnet", same_engine_ok=False, j=1)
    ch = dm.Chapter(book, "ch05", 1000)
    ch.prepare("分类学", "Nereididae")
    (ch.dir / "engines.json").write_text(json.dumps({"translate": "claude-sonnet"}))
    with pytest.raises(SystemExit) as e:
        run_batches.run_direct(a, book, "")
    assert "不能用同一个模型" in str(e.value)
