"""scripts/bench/qc_baseline.py：静默漏检率三指标。"""
import qc_baseline as qb

TXT = "多毛類の分類は、体節数 25 対、全長 12 mm の標本に基づく。" * 6 + "\n第二行 Nereis diversicolor 30 mm\n" * 3


def test_seed_is_deterministic_and_changes_text():
    for kind in qb.KINDS:
        a = qb.seed_error(TXT, kind, 1)
        assert a == qb.seed_error(TXT, kind, 1) and a != TXT


def test_clean_page_passes_with_empty_yiku(tmp_path):
    y = qb.empty_yiku(tmp_path)
    assert qb.qc_action(TXT, yiku=y) == "pass"


def test_baseline_reports_three_rates(tmp_path):
    y = qb.empty_yiku(tmp_path)
    r = qb.baseline({"p1": TXT, "p2": TXT + "追加"}, real=[(TXT, TXT.replace("の", "ロ").replace("体", "休").replace("標", "槇"))], yiku=y)
    assert set(r) >= {"seeded_detect", "clean_false_alarm", "real_silent_miss", "n_clean", "n_seeded", "n_real"}
    # 现有质控不看内容：高置信页植入错误一律放行 → 检出率 0（这就是要量化的缺口）
    assert r["seeded_detect"] == 0.0 and r["clean_false_alarm"] == 0.0
    assert r["real_silent_miss"] == 1.0


def test_no_real_pages_gives_none(tmp_path):
    r = qb.baseline({"p1": TXT}, real=[], yiku=qb.empty_yiku(tmp_path))
    assert r["real_silent_miss"] is None
