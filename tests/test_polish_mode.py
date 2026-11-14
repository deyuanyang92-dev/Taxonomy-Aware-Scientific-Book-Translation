"""run_batches --mode polish：中文通读。假引擎，不联网；合成书目录。
闸口：引证、年份、图号、斜体拉丁名、数字与单位、〔译注〕、页码标记、HARD 术语任一被改动的问题单条目一律拒绝，不进问题单。"""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import apply_issues
import direct_mode as dm
import polish_guard as pg
import run_batches

REPO = Path(__file__).resolve().parent.parent

SRC = ("Nereididae Blainville, 1818\n\n<!-- p.13 -->\nSmith (1978) described Nereis virens (Fig. 2).\n\n"
       "<!-- p.14 -->\nJones et al. (1980) sampled 12 sites.\n")
ZH = ("<!-- p.13 -->\n沙蚕科的 Smith（1978）描述了 *Nereis virens*（图 2），因为该种体长可达 30 mm，所以很常见，"
      "然而这种情况不一定普遍〔译注：原书如此〕。沙蚕的鳃很小。\n\n"
      "<!-- p.14 -->\nJones 等（1980）在 12 个站点采到标本，背须被认为是感觉器官。\n")
SENT = "沙蚕科的 Smith（1978）描述了 *Nereis virens*（图 2），因为该种体长可达 30 mm，所以很常见"
GOOD = "该种体长可达 30 mm，所以很常见。沙蚕科的 Smith（1978）描述了 *Nereis virens*（图 2）"
TABLE = "领域：分类学\n\n## HARD（必用）\n| 英文 | 译名 | 依据 | 状态 | 其他译名（不用） |\n|---|---|---|---|---|\n| gill | 鳃 | yzz | 已核 |  |\n\n## SOFT\n| 英文 | 译名 |\n"


class Fake:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, engine, system, user, **kw):
        self.calls.append((engine, system, user))
        return (self.reply(user) if callable(self.reply) else self.reply), {"input_tokens": 1, "output_tokens": 1}


def issue(old, new, **kw):
    return json.dumps({"old": old, "new": new, "type": "润色", "reason": "先结论后条件", **kw}, ensure_ascii=False) + "\n"


@pytest.fixture
def book(tmp_path, monkeypatch):
    """已合并、已过闸口的终稿：src_en/译文 都放好，只差润色。"""
    (tmp_path / "src_en").mkdir()
    (tmp_path / "译文").mkdir()
    (tmp_path / "src_en" / "ch05.txt").write_text(SRC, encoding="utf8")
    monkeypatch.setattr(dm, "yiku_table", lambda f, d, s: TABLE)
    ch = dm.Chapter(tmp_path, "ch05")
    ids = ch.prepare("分类学", "Nereididae")
    dm.run_translate(ch, ids, "claude-sonnet", "SYS", Fake(ZH), 1)
    dm.merge_translation(ch, ids)
    assert ch.merged.read_text(encoding="utf8").strip() == ZH.strip()
    return tmp_path


def polish(book, monkeypatch, reply, engine="deepseek-flash"):
    import llm_engines
    fake = Fake(reply)
    monkeypatch.setattr(llm_engines, "call", fake)
    args = types.SimpleNamespace(chapters="ch05", mode="polish", domain="分类学", book_desc="", scope="Nereididae",
                                 chunk_chars=9000, dry=False, engine=engine, same_engine_ok=False, j=1, force=False,
                                 fallback=None)
    code = run_batches.run_direct(args, book, "")
    return code, fake


def issues_of(book):
    p = book / "核译" / "issues" / "ch05_polish.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf8").splitlines() if ln.strip()]


def rejected_of(book):
    p = book / "核译" / "direct" / "ch05" / "rejected_polish.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf8").splitlines() if ln.strip()]


def merged(book):
    return (book / "译文" / "ch05_直译初译.md").read_text(encoding="utf8")


# ---------- (1) 合法润色改动被采纳并经 apply_issues 应用 ----------

def test_valid_polish_edit_is_kept_and_applies(book, monkeypatch):
    code, fake = polish(book, monkeypatch, issue(SENT, GOOD))
    assert code == 0
    (it,) = issues_of(book)
    assert it["type"] == "润色" and it["file"] == "ch05_直译初译.md" and it["old"] == SENT
    assert rejected_of(book) == []
    res = apply_issues.apply(book, book / "核译" / "issues" / "ch05_polish.jsonl")
    assert (res.ok, res.bad) == (1, [])
    assert GOOD in merged(book) and SENT not in merged(book)
    assert pg.signature(merged(book)) == pg.signature(ZH)             # 事实指纹前后一致
    assert dm.page_labels(merged(book)) == ["13", "14"]
    # 模型只看到中文：用户消息里没有英文原文，系统提示词带 STYLE 第 6 节
    _engine, system, user = fake.calls[0]
    assert "=== 英文原文 ===" not in user and "Nereis virens (Fig. 2)" not in user and "=== 中文译文 ===" in user
    assert "先结论后条件" in system and "名家逻辑" in system and "NO_ISSUES" in system


# ---------- (2) 丢引证的改动被拒绝 ----------

def test_edit_dropping_a_citation_is_rejected(book, monkeypatch):
    bad_new = "该种体长可达 30 mm，所以很常见。沙蚕科的学者描述了 *Nereis virens*（图 2）"
    polish(book, monkeypatch, issue(SENT, bad_new))
    assert issues_of(book) == []
    (rej,) = rejected_of(book)
    assert "引证" in rej["reject"] and "smith" in rej["reject"].lower()
    res = apply_issues.apply(book, book / "核译" / "issues" / "ch05_polish.jsonl")
    assert res.ok == 0 and merged(book).strip() == ZH.strip()          # 译文原样不动


def test_edit_changing_a_year_or_figure_or_number_is_rejected(book, monkeypatch):
    rows = [issue("Jones 等（1980）在 12 个站点", "Jones 等（1981）在 12 个站点"),
            issue("（图 2），因为", "（图 3），因为"),
            issue("体长可达 30 mm", "体长可达 30 毫米"),
            issue("采到标本，背须", "采到标本，背须约 3 对，")]
    polish(book, monkeypatch, "".join(rows))
    assert issues_of(book) == []
    why = " ".join(r["reject"] for r in rejected_of(book))
    assert len(rejected_of(book)) == 4 and "年份" in why and "图号" in why and "数字" in why


# ---------- (3) 改拉丁名的改动被拒绝 ----------

def test_edit_changing_a_latin_name_is_rejected(book, monkeypatch):
    polish(book, monkeypatch, issue(SENT, GOOD.replace("Nereis virens", "Nereis diversicolor")))
    assert issues_of(book) == []
    (rej,) = rejected_of(book)
    assert "斜体/拉丁名" in rej["reject"] and "Nereis virens" in rej["reject"]


def test_edit_dropping_translator_note_or_hard_term_is_rejected(book, monkeypatch):
    rows = [issue("然而这种情况不一定普遍〔译注：原书如此〕。", "然而这种情况不一定普遍。"),
            issue("沙蚕的鳃很小。", "沙蚕的呼吸器官很小。")]            # 「鳃」是术语表 HARD 译名
    polish(book, monkeypatch, "".join(rows))
    assert issues_of(book) == []
    why = [r["reject"] for r in rejected_of(book)]
    assert "译注" in why[0] and "HARD 术语「鳃」" in why[1]


# ---------- (4) 页码标记保持 ----------

def test_page_markers_are_preserved(book, monkeypatch):
    moved = ("<!-- p.13 -->\n沙蚕科的 Smith（1978）描述了", "<!-- p.14 -->\n沙蚕科的 Smith（1978）描述了")
    dropped = ("<!-- p.14 -->\nJones 等（1980）在 12 个站点采到标本", "Jones 等（1980）在 12 个站点采到标本")
    ok = ("背须被认为是感觉器官", "一般认为背须是感觉器官")
    polish(book, monkeypatch, "".join(issue(o, n) for o, n in (moved, dropped, ok)))
    (kept,) = issues_of(book)
    assert kept["old"] == ok[0]
    why = " ".join(r["reject"] for r in rejected_of(book))
    assert len(rejected_of(book)) == 2 and "页码标记" in why
    apply_issues.apply(book, book / "核译" / "issues" / "ch05_polish.jsonl")
    assert dm.page_labels(merged(book)) == ["13", "14"] and "一般认为背须是感觉器官" in merged(book)


def test_edit_that_changes_line_structure_is_rejected(book, monkeypatch):
    polish(book, monkeypatch, issue("采到标本，背须", "采到标本。\n\n背须"))
    assert issues_of(book) == [] and "换行" in rejected_of(book)[0]["reject"]


# ---------- 续跑、NO_ISSUES、引擎 ----------

def test_no_issues_and_resume_skips_done_chunks(book, monkeypatch):
    code, fake = polish(book, monkeypatch, "NO_ISSUES")
    assert code == 0 and issues_of(book) == [] and len(fake.calls) == 1
    code, fake = polish(book, monkeypatch, "NO_ISSUES")
    assert code == 0 and fake.calls == []                              # 已有产物，跳过


def test_polish_may_reuse_the_translator_engine_and_records_it(book, monkeypatch):
    (book / "核译" / "direct" / "ch05" / "engines.json").write_text(json.dumps({"translate": "deepseek-flash"}))
    code, _ = polish(book, monkeypatch, "NO_ISSUES")                   # 通读不看原文，不受初译/核译异模型限制
    assert code == 0
    assert json.loads((book / "核译" / "direct" / "ch05" / "engines.json").read_text())["polish"] == "deepseek-flash"


def test_unparsable_model_output_fails_chunk_without_issues_file(book, monkeypatch):
    code, _ = polish(book, monkeypatch, "好的，已润色完毕。")
    assert code == 1 and issues_of(book) == []
    assert not (book / "核译" / "direct" / "ch05" / "polish" / "c00.jsonl").exists()   # 不写完成文件，下次续跑重做


# ---------- 提示词：规则运行时从 STYLE.md 读 ----------

def test_system_prompt_reads_style_section_at_runtime(tmp_path):
    (tmp_path / "RULES.md").write_text("RULES\n", encoding="utf8")
    (tmp_path / "domains").mkdir()
    (tmp_path / "domains" / "分类学.md").write_text("DOMAIN\n", encoding="utf8")
    (tmp_path / "STYLE.md").write_text("## 5. 别的\n不要这个\n\n## 6. 名家逻辑：测试\n- 规则甲XYZ\n- 规则乙\n\n## 7. 之后\n也不要\n",
                                       encoding="utf8")
    s = dm.build_system("polish", "分类学", skill=tmp_path)
    assert "规则甲XYZ" in s and "规则乙" in s and "不要这个" not in s and "也不要" not in s
    assert "只看到中文译文" in s and "术语表" in s and "润色" in s
    (tmp_path / "STYLE.md").write_text("## 5. 别的\n", encoding="utf8")
    with pytest.raises(ValueError, match="名家逻辑"):
        dm.build_system("polish", "分类学", skill=tmp_path)


def test_real_style_md_has_the_section():
    assert "先结论后条件" in dm.build_system("polish", "分类学")


# ---------- 闸口函数本身 ----------

def test_guard_signature_equal_for_pure_reordering_and_differs_otherwise():
    a = "Smith（1978）见图 2，体长 30 mm，*Nereis virens*。"
    assert pg.violations(a, "体长 30 mm，*Nereis virens*，见图 2（Smith（1978））。") == []
    assert pg.violations(a, a.replace("30 mm", "30 μm"))
    assert pg.violations(a, a.replace("*Nereis virens*", "Nereis virens"))
    assert pg.violations(a, a.replace("图 2", "图 2、3"))


def test_hard_terms_parsed_from_table_hard_section_only():
    assert pg.hard_terms(TABLE) == ["鳃"]


# ---------- 命令行 ----------

def test_cli_lists_polish_defaults_to_deepseek_flash_and_refuses_agent_engines(book, monkeypatch):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), "--help"], capture_output=True, text=True)
    assert "polish" in r.stdout
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), str(book), "--mode", "polish",
                        "--engine", "codex", "--chapters", "ch05"], capture_output=True, text=True)
    assert r.returncode != 0 and "直调" in (r.stdout + r.stderr)
    seen = {}
    monkeypatch.setattr(run_batches, "run_direct", lambda a, B, notes: seen.update(engine=a.engine, mode=a.mode) or 0)
    monkeypatch.setattr(sys, "argv", ["run_batches.py", str(book), "--mode", "polish", "--chapters", "ch05"])
    with pytest.raises(SystemExit) as e:
        run_batches.main()
    assert e.value.code == 0 and seen == {"engine": "deepseek-flash", "mode": "polish"}
    monkeypatch.setattr(sys, "argv", ["run_batches.py", str(book), "--mode", "polish", "--chapters", "ch05",
                                      "--engine", "claude-sonnet"])
    with pytest.raises(SystemExit):
        run_batches.main()
    assert seen["engine"] == "claude-sonnet"
