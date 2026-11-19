"""fidelity_check：拉丁名、人名、数字、术语首现的确定性核对与修正；heading_bilingual：标题加英文。合成短句，不联网、不调模型。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import direct_mode as dm
import fidelity_check as fc
import heading_bilingual as hb
import run_batches

REPO = Path(__file__).resolve().parent.parent
PERSONS = {"Darwin": "达尔文", "Wallace": "华莱士", "Bateson": "贝特森", "Ray": "雷", "De Vries": "德弗里斯",
           "Mayr": "迈尔"}


@pytest.fixture
def yk(tmp_path):
    from yiku import db as D
    con = D.connect(tmp_path / "t.db")
    D.add_source(con, "dzz", "动物志", "authority", domain="分类学", year=2004)
    for en, zh in [("Sabella crassicornis", "厚角缨鳃虫"), ("Nereis", "沙蚕属"), ("Drosophila", "果蝇"),
                   ("Nereididae", "沙蚕科"), ("Mendelian", "孟德尔式的"),
                   ("integument", "体被"), ("cuticle", "角质层"), ("chaeta", "刚毛"), ("seta", "刚毛"),
                   ("hair chaeta", "毛状刚毛")]:
        D.add_term(con, en, zh, "dzz", domain="分类学", status="已核")
    D.add_term(con, "gill", "鳃", "dzz", domain="分类学", status="已核")           # 单字：不加英文
    D.add_term(con, "papilla", "乳突", "dzz", domain="分类学", status="候选")      # 候选：不加英文
    con.commit()
    return fc.Yiku(con, "分类学")


def run(en, zh, **kw):
    kw.setdefault("persons", PERSONS)
    return fc.check_texts(en, zh, **kw)


def kinds(res, kind):
    return [i for i in res.issues if i.kind == kind]


# ---------- 1. 拉丁名 ----------

def test_binomial_missing_reported_with_english_sentence():
    res = run("Intro here. The worm Nereis diversicolor was common in the bay. Last one.", "沙蚕很常见。")
    (i,) = kinds(res, "拉丁名")
    assert i.item == "Nereis diversicolor" and "was common in the bay" in i.sentence and "Intro here" not in i.sentence
    assert not i.fixed and res.unfixed


def test_binomial_present_in_any_form_passes():
    en = "We studied Nereis diversicolor and Sabella pavonina."
    assert not kinds(run(en, "我们研究了*Nereis diversicolor*和 *Sabella pavonina*。"), "拉丁名")
    assert not kinds(run(en, "研究了 Nereis diversicolor，另有 S. pavonina。"), "拉丁名")


def test_sentence_initial_english_words_are_not_latin():
    en = "Species evidently had descended. The area was large. Among the taxa, Whenever variation was found."
    assert not kinds(run(en, "译文。"), "拉丁名")


def test_hyphenated_fragments_and_versus_not_latin():
    en = "separated by septa (\u2018\u2018Dis-\nsepimente\u201d) in Owenia versus Nereis diversicolor."
    assert [i.item for i in kinds(run(en, "译文。"), "拉丁名")] == ["Owenia", "Nereis diversicolor"]


def test_persons_not_latin():
    en = "Darwin claimed that Sonneborn refused this. Ray Lankester and A. R. Wallace agreed (Cock, 1977)."
    assert not kinds(run(en, "译文。"), "拉丁名")


def test_standalone_genus_by_latin_ending_midsentence():
    res = run("species of Oenothera were based on varieties of Paramecium and the Origin in Africa.", "月见草，草履虫。")
    assert sorted(i.item for i in kinds(res, "拉丁名")) == ["Oenothera", "Paramecium"]   # Origin、Africa 不算


def test_genus_present_as_part_of_binomial_in_chinese():
    assert not kinds(run("on Oenothera lamarckiana plants", "在*Oenothera lamarckiana*上"), "拉丁名")
    assert not kinds(run("the genus Oenothera", "*Oenothera* 属"), "拉丁名")


def test_italic_english_names_are_trusted_and_yiku_known_genus_found(yk):
    res = run("*Hyalinoecia tubicola* lives with Drosophila. Nereis is common.", "无。", yiku=yk)
    assert sorted(i.item for i in kinds(res, "拉丁名")) == ["Drosophila", "Hyalinoecia tubicola", "Nereis"]


def test_yiku_non_genus_words_ignored(yk):
    res = run("The Mendelian ratios and Nereididae are described.", "无。", yiku=yk)
    assert not kinds(res, "拉丁名")                      # 科名、-ian 形容词不算属名


def test_fix_inserts_latin_after_first_yiku_chinese_name(yk):
    en = "Sabella crassicornis and Nereis and Drosophila are listed."
    zh = "厚角缨鳃虫、沙蚕属和果蝇属都列出。厚角缨鳃虫又出现。"
    res = run(en, zh, yiku=yk, fix=True)
    assert res.zh == "厚角缨鳃虫（*Sabella crassicornis*）、沙蚕属（*Nereis*）和果蝇属（*Drosophila*）都列出。厚角缨鳃虫又出现。"
    assert all(i.fixed for i in kinds(res, "拉丁名")) and not res.unfixed


def test_fix_never_invents_chinese(yk):
    res = run("Studies of Oenothera and Nereis here.", "月见草和某种虫。", yiku=yk, fix=True)
    assert res.zh == "月见草和某种虫。"
    assert sorted(i.item for i in res.unfixed) == ["Nereis", "Oenothera"]


def test_fix_skips_headings(yk):
    zh = "### 沙蚕属\n\n正文里提到沙蚕属。\n"
    res = run("Nereis here.", zh, yiku=yk, fix=True)
    assert res.zh == "### 沙蚕属\n\n正文里提到沙蚕属（*Nereis*）。\n"


# ---------- 2. 人名 ----------

def test_person_names_replaced_in_running_text():
    res = run("x", "正如Darwin所说，Wallace的观点；De Vries的月见草。", fix=True)
    assert res.zh == "正如达尔文所说，华莱士的观点；德弗里斯的月见草。"


def test_person_report_mode_does_not_modify():
    zh = "Wallace说。"
    res = run("x", zh)
    assert res.zh == zh and [i.item for i in kinds(res, "人名")] == ["Wallace"] and res.unfixed


def test_person_names_not_touched_in_citations():
    zh = "见（Darwin, 1859; Mayr et al., 1990）与 Wallace (1870) 和 Mayr et al. (1990)，以及 Bateson 等（1902）。"
    assert run("x", zh, fix=True).zh == zh


def test_person_names_not_touched_in_reference_list():
    zh = ("Wallace提出。\n\n## 参考文献\n\nDarwin, C. 1859. On the origin. London.\nWallace A. R. 1870. Contributions.\n"
          "\n## 附录\n\nWallace又提到。\n")
    out = run("x", zh, fix=True).zh
    assert out.startswith("华莱士提出。") and "Darwin, C. 1859" in out and "Wallace A. R. 1870" in out
    assert out.endswith("华莱士又提到。\n")
    line = "Darwin, C. 1859. On the origin."
    assert run("x", line, fix=True).zh == line          # 没有标题也能认出文献条目行


def test_given_names_and_initials_dropped_before_table_name():
    zh = "和A. R. Wallace，William Bateson与A.R. Wallace；Alfred Russel Wallace。"
    assert run("x", zh, fix=True).zh == "和华莱士，贝特森与华莱士；华莱士。"


def test_ray_lankester_and_other_given_context_untouched():
    zh = "包括Ray Lankester、Erasmus Darwin，以及Ray的处方。"
    assert run("x", zh, fix=True).zh == "包括Ray Lankester、Erasmus Darwin，以及雷的处方。"


def test_possessive_gloss_hyphen_and_substrings():
    assert run("x", "Ray's处方和Wallace's观点", fix=True).zh == "雷的处方和华莱士的观点"
    zh = "达尔文（Charles Darwin）；Rayleigh、X-Ray、Ray-finned、Mendelian、Darwinism。"
    assert run("x", zh, fix=True).zh == zh


def test_person_replacement_leaves_trailer_alone():
    zh = "Wallace说。\n\n### 术语决策\n{\"en\":\"Wallace\",\"zh\":\"W\"}\n"
    out = run("x", zh, fix=True).zh
    assert out.startswith("华莱士说。") and out.endswith('{"en":"Wallace","zh":"W"}\n')


def test_load_persons_tsv(tmp_path):
    f = tmp_path / "p.tsv"
    f.write_text("# 注释\nDarwin\t达尔文\n\nHuxley\t赫胥黎\nbad line\n", encoding="utf8")
    assert fc.load_persons(f) == {"Darwin": "达尔文", "Huxley": "赫胥黎"}
    seed = fc.load_persons()
    assert seed["Wallace"] == "华莱士" and seed["Aristotle"] == "亚里士多德" and len(seed) >= 15


# ---------- 3. 数字 ----------

def test_numbers_with_unit_and_years_must_appear():
    en = "Worms 12 mm long, 600,000 eggs, 5-8 cm, 30%, by 1900 and (Mayr, 1963a). Fig. 3 shows 7 specimens."
    zh = "虫长12毫米，有600000枚卵，5至8厘米，30%，1900年。"
    got = sorted(i.item for i in kinds(run(en, zh), "数字"))
    assert got == ["1963"]                                # 3、7 没有单位，不查；1963 缺失


def test_numbers_missing_listed_with_sentence():
    res = run("Bodies reach 45 mm. They live to 2 m in depth.", "体长可达45毫米。")
    (i,) = kinds(res, "数字")
    assert i.item == "2 m" and "live to 2 m" in i.sentence and res.unfixed


def test_numbers_fullwidth_digits_and_thousand_separators_in_chinese():
    assert not kinds(run("up to 1,500 m and 20 °C", "达１５００米，20°C"), "数字")


# ---------- 4. 术语首现 ----------

def test_term_first_occurrence_gets_english_then_only_chinese(yk):
    en = "The integument bears chaetae; the cuticle is thin."
    zh = "体被具刚毛；角质层很薄。体被又厚。"
    res = run(en, zh, yiku=yk, fix=True)
    assert res.zh == "体被（integument）具刚毛（chaeta）；角质层（cuticle）很薄。体被又厚。"
    assert {i.item for i in kinds(res, "术语首现")} == {"integument", "chaeta", "cuticle"} and not res.unfixed


def test_term_report_mode_and_already_bracketed_or_seen(yk):
    en = "The integument is thin."
    assert [i.item for i in kinds(run(en, "体被很薄。", yiku=yk), "术语首现")] == ["integument"]
    assert not kinds(run(en, "体被（integument）很薄。", yiku=yk), "术语首现")
    assert not kinds(run(en, "体被（Integument; 又称外皮）很薄。", yiku=yk), "术语首现")
    seen = {"integument"}
    res = run(en, "体被很薄。", yiku=yk, fix=True, seen=seen)
    assert res.zh == "体被很薄。" and not res.issues


def test_term_seen_state_shared_across_chunks(yk):
    seen = set()
    a = run("The cuticle.", "角质层。", yiku=yk, fix=True, seen=seen)
    b = run("The cuticle again.", "角质层又出现。", yiku=yk, fix=True, seen=seen)
    assert a.zh == "角质层（cuticle）。" and b.zh == "角质层又出现。" and seen == {"cuticle"}


def test_term_skips_headings_citations_short_unverified_and_absent(yk):
    zh = "### 角质层\n\n（Mayr, 1990）之后体被，鳃与乳突很多。\n"
    res = run("The cuticle, integument, gill and papilla; Nereis.", zh, yiku=yk, fix=True)
    assert "角质层（cuticle）" not in res.zh and "### 角质层\n" in res.zh and "体被（integument）" in res.zh
    assert "鳃（" not in res.zh and "乳突（" not in res.zh          # 单字、候选都不加
    assert not [i for i in kinds(res, "术语首现") if i.item in ("cuticle", "gill", "papilla")]


def test_term_longest_match_not_inside_longer_yiku_term(yk):
    res = run("The chaeta and hair chaeta.", "毛状刚毛很长。", yiku=yk, fix=True)
    assert res.zh == "毛状刚毛（hair chaeta）很长。"       # 「刚毛」落在更长的已知名里，不单独加


def test_term_without_english_in_chunk_not_touched(yk):
    assert run("Nothing here.", "体被很薄。", yiku=yk, fix=True).zh == "体被很薄。"


# ---------- 5. 命令行 ----------

def cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "fidelity_check.py"), *args],
                          capture_output=True, text=True, cwd=cwd)


def test_cli_report_fix_and_exit_codes(tmp_path):
    en = tmp_path / "chunk.txt"
    zh = tmp_path / "chunk.md"
    en.write_text("The theory of Wallace on Oenothera, 12 mm.\n", encoding="utf8")
    zh.write_text("Wallace的理论，12毫米。\n\n### 待定术语\nWallace｜华莱士\n", encoding="utf8")
    r = cli("--en", str(en), "--zh", str(zh), "--no-yiku")
    assert r.returncode == 1 and "Oenothera" in r.stdout and "Wallace" in r.stdout
    assert zh.read_text(encoding="utf8").startswith("Wallace")             # 只报告不改
    r = cli("--en", str(en), "--zh", str(zh), "--fix", "--no-yiku")
    assert r.returncode == 1 and "Oenothera" in r.stdout                   # 拉丁名补不了：仍有未修复
    text = zh.read_text(encoding="utf8")
    assert text.startswith("华莱士的理论") and text.endswith("Wallace｜华莱士\n")   # 尾节原样
    assert (tmp_path / "chunk.md.bak-fidelity").read_text(encoding="utf8").startswith("Wallace")
    out = tmp_path / "o.md"
    zh2 = tmp_path / "z2.md"
    zh2.write_text("Wallace说。\n", encoding="utf8")
    en.write_text("Wallace said.\n", encoding="utf8")
    r = cli("--en", str(en), "--zh", str(zh2), "--fix", "-o", str(out), "--no-yiku")
    assert r.returncode == 0 and out.read_text(encoding="utf8") == "华莱士说。\n" and zh2.read_text(encoding="utf8") == "Wallace说。\n"


def test_cli_seen_file_shared_between_chunks(tmp_path, yk):
    db = yk.con.execute("PRAGMA database_list").fetchone()[2]
    seen = tmp_path / "seen.json"
    for n, (en, zh) in enumerate([("The cuticle.", "角质层。"), ("The cuticle.", "角质层又。")]):
        (tmp_path / f"e{n}.txt").write_text(en, encoding="utf8")
        (tmp_path / f"z{n}.md").write_text(zh, encoding="utf8")
        r = cli("--en", str(tmp_path / f"e{n}.txt"), "--zh", str(tmp_path / f"z{n}.md"), "--fix", "--db", db,
                "--seen", str(seen))
        assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "z0.md").read_text(encoding="utf8") == "角质层（cuticle）。"
    assert (tmp_path / "z1.md").read_text(encoding="utf8") == "角质层又。"
    assert json.loads(seen.read_text(encoding="utf8")) == ["cuticle"]


# ---------- 6. 接入 run_batches 直调翻译 ----------

class Fake:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, engine, system, user, **kw):
        self.calls.append(user)
        return self.reply(user), {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture
def book(tmp_path, monkeypatch):
    (tmp_path / "src_en").mkdir()
    (tmp_path / "译文").mkdir()
    para = "Wallace studied Oenothera and the integument. " * 8
    (tmp_path / "src_en" / "ch05.txt").write_text((para + "\n\n") * 14, encoding="utf8")
    monkeypatch.setattr(dm, "yiku_table", lambda f, d, s: "| 英文 | 译名 |\n")
    return tmp_path


def zh_reply(user):
    return "Wallace研究了月见草和体被。" * 40 + "\n\n### 待定术语\nfoo｜富｜暂定\n"


def args(**kw):
    import types
    base = dict(chapters="ch05", mode="translate", domain="分类学", book_desc="", scope="Nereididae", chunk_chars=1000,
                dry=False, engine="claude-sonnet", same_engine_ok=False, j=1, force=False, no_yiku=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_run_direct_translate_runs_fidelity_and_logs(book, monkeypatch):
    import llm_engines
    f = Fake(zh_reply)
    monkeypatch.setattr(llm_engines, "call", f)
    assert run_batches.run_direct(args(), book, "") in (0, 1)
    d = book / "核译" / "direct" / "ch05"
    out = (d / "out" / "c00.md").read_text(encoding="utf8")
    assert out.startswith("华莱士研究了月见草") and "### 待定术语\nfoo｜富｜暂定\n" in out
    assert (d / "out" / "c00.md.bak-fidelity").read_text(encoding="utf8").startswith("Wallace研究")
    log = (d / "fidelity" / "c00.txt").read_text(encoding="utf8")
    assert "Oenothera" in log and "Wallace" in log
    merged = (book / "译文" / "ch05_直译初译.md").read_text(encoding="utf8")
    assert "Wallace研究" not in merged and "华莱士研究" in merged                    # 合并用的是修正后的块
    calls = len(f.calls)
    run_batches.run_direct(args(), book, "")                                          # 再跑：不重复处理已记录的块
    assert len(f.calls) == calls and "Oenothera" in (d / "fidelity" / "c00.txt").read_text(encoding="utf8")


def test_run_direct_no_fidelity_flag_skips(book, monkeypatch):
    import llm_engines
    monkeypatch.setattr(llm_engines, "call", Fake(zh_reply))
    run_batches.run_direct(args(no_fidelity=True), book, "")
    d = book / "核译" / "direct" / "ch05"
    assert (d / "out" / "c00.md").read_text(encoding="utf8").startswith("Wallace研究") and not (d / "fidelity").exists()


def test_cli_help_mentions_no_fidelity():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "run_batches.py"), "--help"], capture_output=True, text=True)
    assert "--no-fidelity" in r.stdout


def test_chapter_pass_shares_seen_in_chunk_order_and_stops_at_gap(book, yk):
    ch = dm.Chapter(book, "ch05", 1000)
    ids = ch.prepare("分类学", "Nereididae")
    assert len(ids) >= 4
    for c in ids[:3]:
        (ch.dir / "chunks" / f"{c}.txt").write_text("The cuticle.\n", encoding="utf8")
    for c in (ids[0], ids[1], ids[3]):                   # ids[2] 缺：只处理到它之前
        (ch.dir / "out").mkdir(exist_ok=True)
        (ch.dir / "out" / f"{c}.md").write_text("角质层。\n", encoding="utf8")
    lines = fc.run_chapter(ch.dir, ids, yiku=yk, persons=PERSONS)
    assert (ch.dir / "out" / f"{ids[0]}.md").read_text(encoding="utf8") == "角质层（cuticle）。\n"
    assert (ch.dir / "out" / f"{ids[1]}.md").read_text(encoding="utf8") == "角质层。\n"
    assert (ch.dir / "out" / f"{ids[3]}.md").read_text(encoding="utf8") == "角质层。\n"   # 未处理
    assert any(ids[2] in ln for ln in lines)


# ---------- 7. 标题加英文 ----------

EN_HEADS = """<!-- p.19 -->

GENERAL ORGANIZATION

Polychaetes are metameric animals. The body is made of segments and is long enough to count as a paragraph.

INTEGUMENT

The integument of polychaetes is usually simple.

Extracellular Matrix

The matrix is thick and has fibres of many kinds in the layers.

Double-Obliquely Striated Fibers

vm VV

Some text ends here with a period.
"""


def test_english_headings_detected_in_order():
    got = [(h.text, h.rank) for h in hb.english_headings(EN_HEADS)]
    assert got == [("GENERAL ORGANIZATION", 1), ("INTEGUMENT", 1), ("Extracellular Matrix", 2),
                   ("Double-Obliquely Striated Fibers", 2)]


def test_title_case():
    assert hb.title_case("VASCULAR SYSTEM") == "Vascular System"
    assert hb.title_case("ORIGIN OF THE SPECIES") == "Origin of the Species"
    assert hb.title_case("Extracellular Matrix") == "Extracellular Matrix"


def test_align_and_append_english_titles():
    zh = ("# 试译\n\n## 一、正文\n\n### 一般体制\n\n正文。\n\n### 体被\n\n正文。\n\n#### 细胞外基质（Extracellular matrix）\n\n"
          "正文。\n\n#### 双斜纹肌纤维\n\n正文。\n\n## 二、图注\n")
    res = hb.align(EN_HEADS, zh)
    assert [(p.zh_line, p.new) for p in res.proposals] == [
        ("### 一般体制", "### 一般体制（General Organization）"), ("### 体被", "### 体被（Integument）"),
        ("#### 双斜纹肌纤维", "#### 双斜纹肌纤维（Double-Obliquely Striated Fibers）")]
    assert [u.text for u in res.unaligned_zh] == ["试译", "一、正文", "二、图注"] and not res.unaligned_en
    assert res.fixed_text.count("（General Organization）") == 1 and "（Extracellular matrix）" in res.fixed_text
    assert "# 试译\n" in res.fixed_text and res.fixed_text.endswith("## 二、图注\n")


def test_align_count_mismatch_reports_everything_unaligned():
    res = hb.align(EN_HEADS, "### 体被\n\n正文。\n")
    assert not res.proposals and len(res.unaligned_en) == 4 and res.mismatch and res.fixed_text == "### 体被\n\n正文。\n"


def test_heading_cli_dry_run_and_fix(tmp_path):
    en = tmp_path / "body.txt"
    zh = tmp_path / "t.md"
    en.write_text("INTEGUMENT\n\nThe integument of polychaetes is usually a simple layer of cells and more.\n", encoding="utf8")
    zh.write_text("### 体被\n\n正文。\n", encoding="utf8")
    exe = str(REPO / "scripts" / "heading_bilingual.py")
    r = subprocess.run([sys.executable, exe, "--en", str(en), "--zh", str(zh)], capture_output=True, text=True)
    assert r.returncode == 0 and "体被（Integument）" in r.stdout and zh.read_text(encoding="utf8") == "### 体被\n\n正文。\n"
    r = subprocess.run([sys.executable, exe, "--en", str(en), "--zh", str(zh), "--fix"], capture_output=True, text=True)
    assert r.returncode == 0 and zh.read_text(encoding="utf8") == "### 体被（Integument）\n\n正文。\n"
    assert (tmp_path / "t.md.bak-heading").exists()
