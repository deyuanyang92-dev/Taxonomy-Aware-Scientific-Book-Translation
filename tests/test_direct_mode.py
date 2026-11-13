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
        return "NO_ISSUES"

    n, skipped, fails = dm.run_review(ch, ids, "deepseek-flash", "SYS", Fake(review_reply))
    assert n == len(ids) and fails == []
    assert (ch.dir / "review" / "c01.jsonl").read_text() == ""  # 空文件也表示已核过
    assert dm.run_review(ch, ids, "deepseek-flash", "SYS", Fake("NO_ISSUES")) == (0, len(ids), [])
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


# ---------- 核译输出的严格解析 ----------

def test_parse_review_accepts_jsonl_fenced_jsonl_and_no_issues():
    one = '{"old":"甲","new":"乙","type":"误译"}'
    assert dm.parse_review(one + "\n\n" + '{"old":"丙","new":"丁"}') == [
        {"old": "甲", "new": "乙", "type": "误译"}, {"old": "丙", "new": "丁"}]
    assert dm.parse_review(f"```jsonl\n{one}\n```") == [{"old": "甲", "new": "乙", "type": "误译"}]  # 围栏里的内容照常解析
    assert dm.parse_review("NO_ISSUES") == [] and dm.parse_review("  NO_ISSUES \n") == []
    assert dm.parse_review("```\nNO_ISSUES\n```") == []
    assert dm.parse_review('{"old":"甲","new":""}') == [{"old": "甲", "new": ""}]  # 删去某字：new 可为空串


@pytest.mark.parametrize("bad, why", [
    ("", "输出为空"), ("   \n\n", "输出为空"), ("```\n```", "输出为空"),
    ("没有发现问题。", "不是合法 JSON"),
    ('{"old":"甲","new":"乙"}\n以上是全部问题。', "第 2 行不是合法 JSON"),
    ('{"old":"甲","new":"乙"}\n{坏json', "第 2 行不是合法 JSON"),
    ('{"old":"甲"}', "缺 old/new"),
    ('{"new":"乙"}', "缺 old/new"),
    ('{"old":"","new":"乙"}', "缺 old/new"),
    ('{"old":1,"new":"乙"}', "缺 old/new"),
    ('[{"old":"甲","new":"乙"}]', "不是 JSON 对象"),
    ('{"old":"甲","new":"乙"}\nNO_ISSUES', "混写"),
])
def test_parse_review_rejects_everything_else(bad, why):
    with pytest.raises(dm.ReviewParseError, match=why):
        dm.parse_review(bad)


def test_review_failure_writes_no_file_and_is_retried(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_for))
    for reply in ("", "我没发现问题", '{"old":"甲"}', "```json\n[{\"old\":\"甲\",\"new\":\"乙\"}]\n```"):
        n, skipped, fails = dm.run_review(ch, ids, "deepseek-flash", "SYS", Fake(reply))
        assert n == 0 and len(fails) == len(ids), reply
        assert not list((ch.dir / "review").glob("*.jsonl"))  # 失败不写完成文件
    # 修好之后同一批块会被重核，而不是被当成已完成跳过
    f = Fake("NO_ISSUES")
    n, skipped, fails = dm.run_review(ch, ids, "deepseek-flash", "SYS", f)
    assert (n, skipped, fails) == (len(ids), 0, []) and len(f.calls) == len(ids)
    assert all(p.read_text() == "" for p in (ch.dir / "review").glob("*.jsonl"))  # NO_ISSUES -> 空文件，表示已核无问题


def test_review_prompt_tells_model_to_write_no_issues():
    s = dm.build_system("review", "分类学")
    assert "NO_ISSUES" in s and "空输出会被当作失败" in s


# ---------- 续跑一致性（.meta.json） ----------

def translated(book, limit=1000, system="SYS", engine="claude-sonnet"):
    ch = dm.Chapter(book, "ch05", limit)
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, engine, system, Fake(zh_for))
    return ch, ids


def test_meta_records_engine_and_hashes(book):
    ch, ids = translated(book)
    meta = json.loads((ch.dir / "out" / "c00.meta.json").read_text(encoding="utf8"))
    assert meta["engine"] == "claude-sonnet"
    assert meta["system_sha256"] == dm._digest("SYS")
    assert meta["terms_sha256"] == dm._digest((ch.dir / "terms" / "c00.md").read_text(encoding="utf8"))
    assert meta["sha256"] == dm._digest("SYS", (ch.dir / "terms" / "c00.md").read_text(encoding="utf8"), "")
    assert len(meta["sha256"]) == 64


def test_resume_refuses_changed_system_prompt_and_force_redoes(book):
    ch, ids = translated(book)
    f = Fake(zh_for)
    with pytest.raises(dm.StaleOutputError, match="系统提示词变了.*--force"):
        dm.run_translate(ch, ids, "claude-sonnet", "SYS 改过了", f)
    assert f.calls == []  # 报错在调用模型之前，不花钱
    n, skipped, fails = dm.run_translate(ch, ids, "claude-sonnet", "SYS 改过了", f, force=True)
    assert (n, skipped, fails) == (len(ids), 0, [])
    assert json.loads((ch.dir / "out" / "c00.meta.json").read_text(encoding="utf8"))["system_sha256"] == dm._digest("SYS 改过了")
    assert dm.run_translate(ch, ids, "claude-sonnet", "SYS 改过了", Fake(zh_for)) == (0, len(ids), [])  # 重做后再续跑一致


def test_resume_refuses_other_engine(book):
    ch, ids = translated(book)
    with pytest.raises(dm.StaleOutputError, match="引擎 claude-sonnet -> claude-opus"):
        dm.run_translate(ch, ids, "claude-opus", "SYS", Fake(zh_for))


def test_resume_only_redoes_chunk_whose_terms_changed(book):
    ch, ids = translated(book)
    (ch.dir / "terms" / "c01.md").write_text("| 英文 | 译名 |\n新增术语\n", encoding="utf8")
    with pytest.raises(dm.StaleOutputError, match=r"c01：术语表变了"):
        dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_for))
    f = Fake(zh_for)
    n, skipped, fails = dm.run_translate(ch, ids, "claude-sonnet", "SYS", f, force=True)
    assert (n, skipped) == (1, len(ids) - 1) and len(f.calls) == 1 and "新增术语" in f.calls[0][1]


def test_legacy_output_without_meta_is_not_trusted(book):
    ch, ids = translated(book)
    (ch.dir / "out" / "c00.meta.json").unlink()
    with pytest.raises(dm.StaleOutputError, match="缺 meta.json"):
        dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_for))


def test_review_resume_checks_engine_system_and_translation(book):
    ch, ids = translated(book)
    dm.run_review(ch, ids, "deepseek-flash", "RSYS", Fake("NO_ISSUES"))
    assert dm.run_review(ch, ids, "deepseek-flash", "RSYS", Fake("NO_ISSUES")) == (0, len(ids), [])
    with pytest.raises(dm.StaleOutputError, match="系统提示词变了"):
        dm.run_review(ch, ids, "deepseek-flash", "RSYS2", Fake("NO_ISSUES"))
    with pytest.raises(dm.StaleOutputError, match="引擎"):
        dm.run_review(ch, ids, "deepseek-v4-pro", "RSYS", Fake("NO_ISSUES"))
    # 译文被改动（例如重译）后，旧核译作废
    out = ch.dir / "out" / "c00.md"
    out.write_text(out.read_text(encoding="utf8").replace("沙蚕", "蚯蚓", 3), encoding="utf8")
    with pytest.raises(dm.StaleOutputError, match="c00：所核译文变了"):
        dm.run_review(ch, ids, "deepseek-flash", "RSYS", Fake("NO_ISSUES"))
    f = Fake("NO_ISSUES")
    assert dm.run_review(ch, ids, "deepseek-flash", "RSYS", f, force=True) == (1, len(ids) - 1, []) and len(f.calls) == 1


def test_force_retranslate_also_drops_downstream_review_files(book):
    ch, ids = translated(book)
    dm.run_review(ch, ids, "deepseek-flash", "RSYS", Fake("NO_ISSUES"))
    assert (ch.dir / "review" / "c00.jsonl").exists()
    dm.run_translate(ch, ids, "claude-opus", "SYS", Fake(zh_for), force=True)
    assert not list((ch.dir / "review").glob("c0*"))  # 初译重做，对应的核译产物与 meta 一并删除


def test_run_direct_exits_with_hint_on_stale_output(book, monkeypatch):
    import types

    import llm_engines
    ch, ids = translated(book, system="旧提示词")
    monkeypatch.setattr(llm_engines, "call", lambda *a, **k: pytest.fail("不一致时不应调用模型"))
    a = types.SimpleNamespace(chapters="ch05", mode="translate", domain="分类学", book_desc="", scope="Nereididae",
                              chunk_chars=1000, dry=False, engine="claude-sonnet", same_engine_ok=False, j=1, force=False)
    with pytest.raises(SystemExit) as e:
        run_batches.run_direct(a, book, "")
    assert "--force" in str(e.value) and "不一致" in str(e.value)


def test_cli_help_mentions_force():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), "--help"], capture_output=True, text=True)
    assert "--force" in r.stdout


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


# ---------- 术语决策（term_decisions.jsonl） ----------

DEC1 = '{"en":"cirrus","zh":"须","sense":"沙蚕背须","reason":"本块指背须","source":"杨德渐2006 p.0168","chunk":"乱填"}'
DEC2 = '{"en":"palp","zh":"触须","sense":"口器","reason":"无","source":""}'


def zh_with_decisions(user):
    return ("沙蚕" * 400 + "\n\n### 待定术语\nnuchal organ｜项器｜暂定\n\n### 术语决策\n```\n"
            + DEC1 + "\n" + DEC2 + "\n这行不是JSON\n{\"en\":\"x\"}\n```\n")


def test_build_system_translate_asks_for_decision_block_with_schema():
    s = dm.build_system("translate", "分类学")
    assert "### 术语决策" in s and "HARD" in s and "SOFT" in s
    for k in ('"en"', '"zh"', '"sense"', '"reason"', '"source"', '"chunk"'):
        assert k in s
    assert "没有依据就写空串" in s


def test_user_translate_carries_chunk_tag_and_keeps_prefix():
    u = dm.user_translate("TBL", "text", "ch05/c03")
    assert u.startswith("本块术语表（来自 yiku）：\nTBL") and "本块编号：ch05/c03" in u and u.endswith("text")
    assert "本块编号" not in dm.user_translate("TBL", "text")


def test_split_sections_any_order_and_strip_pending_ignores_decisions():
    body, pend, dec = dm.split_sections("译文\n\n### 待定术语\n- a｜甲｜暂定\n\n### 术语决策\n{\"en\":\"a\"}\n")
    assert (body, pend, dec) == ("译文", ["a｜甲｜暂定"], ['{"en":"a"}'])
    body2, pend2, dec2 = dm.split_sections("译文\n### 术语决策\n{\"en\":\"a\"}\n### 待定术语\nb｜乙｜暂定\n")
    assert (body2, pend2, dec2) == ("译文", ["b｜乙｜暂定"], ['{"en":"a"}'])
    assert dm.strip_pending("译文\n### 术语决策\n{\"en\":\"a\"}\n") == ("译文", [])
    assert dm.split_sections("只有译文") == ("只有译文", [], [])


def test_parse_decisions_overrides_chunk_and_collects_invalid():
    ok, bad = dm.parse_decisions(["```", DEC1, DEC2, "这行不是JSON", '{"en":"x"}', "```"], "ch05/c02")
    assert [d["en"] for d in ok] == ["cirrus", "palp"] and all(d["chunk"] == "ch05/c02" for d in ok)
    assert bad == ["这行不是JSON", '{"en":"x"}']


def test_translate_saves_decisions_per_chunk_and_merges_chapter_and_book(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    f = Fake(zh_with_decisions)
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", f)
    assert "本块编号：ch05/c00" in f.calls[0][1]
    per = (ch.dir / "decisions" / "c00.jsonl").read_text(encoding="utf8").splitlines()
    assert [json.loads(x)["chunk"] for x in per] == ["ch05/c00", "ch05/c00"]
    assert (ch.dir / "decisions" / "c00.invalid.txt").read_text(encoding="utf8").splitlines() == ["这行不是JSON", '{"en":"x"}']
    msg = dm.merge_translation(ch, ids)
    assert f"术语决策 {2 * len(ids)} 条" in msg
    chap = [json.loads(x) for x in (ch.dir / "term_decisions.jsonl").read_text(encoding="utf8").splitlines()]
    assert len(chap) == 2 * len(ids) and {d["chunk"] for d in chap} == {f"ch05/{i}" for i in ids}
    book_file = book / "核译" / "term_decisions.jsonl"
    assert len(book_file.read_text(encoding="utf8").splitlines()) == 2 * len(ids)
    merged = ch.merged.read_text(encoding="utf8")
    assert "术语决策" not in merged and "cirrus" not in merged and "待定术语" not in merged


def test_merge_decisions_falls_back_to_out_files_and_is_idempotent(book):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_with_decisions))
    for p in (ch.dir / "decisions").glob("*"):  # 旧产物没有 decisions/：从 out/cNN.md 现解析
        p.unlink()
    assert dm.merge_decisions(ch, ids) == 2 * len(ids)
    assert dm.merge_decisions(ch, ids) == 2 * len(ids)
    assert len((book / "核译" / "term_decisions.jsonl").read_text(encoding="utf8").splitlines()) == 2 * len(ids)


def test_force_retranslate_drops_old_decisions(book):
    ch, ids = translated(book)
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(zh_with_decisions), force=True)  # zh_for 无决策 -> 先造有的
    assert (ch.dir / "decisions" / "c00.jsonl").exists()
    dm.run_translate(ch, ids, "claude-opus", "SYS", Fake(zh_for), force=True)
    assert (ch.dir / "decisions" / "c00.jsonl").read_text(encoding="utf8") == ""  # 重做后是新输出的（空）决策，不留旧的
    assert not (ch.dir / "decisions" / "c00.invalid.txt").exists()


def test_yiku_table_passes_fallback(monkeypatch, tmp_path):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "TABLE", "")

    monkeypatch.setattr(dm.subprocess, "run", fake_run)
    assert dm.yiku_table(tmp_path / "c.txt", "分类学", "Nereididae", "进化生物学") == "TABLE"
    assert seen[-1][-2:] == ["--fallback", "进化生物学"]
    dm.yiku_table(tmp_path / "c.txt", "分类学")
    assert "--fallback" not in seen[-1]


def test_agent_mode_prompts_describe_hard_soft_and_decisions(book, monkeypatch):
    monkeypatch.setattr(run_batches, "term_table", lambda src: "TABLE")
    p = run_batches.translate_prompt(book, "ch05", "")
    assert "HARD" in p and "SOFT" in p and "term_decisions.jsonl" in p and '"sense"' in p
    r = run_batches.review_prompt(book, "b01", [{"src": "src_en/ch05.txt"}], "")
    assert "--decisions" in r and "HARD" in r


def test_cli_help_mentions_fallback():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), "--help"], capture_output=True, text=True)
    assert "--fallback" in r.stdout
