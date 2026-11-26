"""预案：连续 10 页空返回即停止提交；本地空白页不提交；垃圾文本层/边缘阴影不影响空白判定。"""
import fitz
import pytest

from docstore.engines import paddle_vl as pv

EMPTY = "empty_suspect: 云端返回空文本但页面非空白（疑似漏识）"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PADDLEOCR_TOKEN", "tok")
    monkeypatch.setattr(pv, "_new_session", lambda: None)


def inked_pdf(path, n):
    doc = fitz.open()
    for _ in range(n):
        pg = doc.new_page(width=200, height=280)
        pg.draw_rect(fitz.Rect(30, 30, 170, 250), color=None, fill=(0, 0, 0))
    doc.save(str(path))
    return str(path)


def test_empty_streak_counts_consecutive_only():
    f = {p: EMPTY for p in [1, 2, 3, 5, 6]}
    assert pv.empty_streak([1, 2, 3, 4, 5, 6], f) == 3
    assert pv.empty_streak([1, 2, 3, 5, 6], f) == 5  # 4 未提交，不打断
    assert pv.empty_streak([], {}) == 0


def test_probe_all_empty_stops_before_rest(monkeypatch, tmp_path):
    pdf = inked_pdf(tmp_path / "a.pdf", 40)
    posted: list[list[int]] = []

    def fake(pdf_path, ps, **kw):
        posted.append(list(ps))
        kw["out"][1].update({p: EMPTY for p in ps})

    monkeypatch.setattr(pv, "run_chunk", fake)
    res = pv.run_pages(pdf, list(range(1, 41)), log=lambda s: None)
    assert posted == [list(range(1, 11))]  # 只提交 10 页探针，剩余 30 页没花额度
    assert res["empty_storm"] is True
    assert all(str(res["failed"][p]).startswith("empty_storm") for p in range(11, 41))


def test_probe_ok_continues_with_rest(monkeypatch, tmp_path):
    pdf = inked_pdf(tmp_path / "a.pdf", 25)
    posted: list[list[int]] = []

    def fake(pdf_path, ps, **kw):
        posted.append(list(ps))
        kw["out"][0].update({p: ("txt", {}) for p in ps})

    monkeypatch.setattr(pv, "run_chunk", fake)
    res = pv.run_pages(pdf, list(range(1, 26)), log=lambda s: None)
    assert posted[0] == list(range(1, 11)) and sum(len(x) for x in posted) == 25
    assert not res["empty_storm"] and len(res["ok"]) == 25


def test_nine_empty_in_probe_is_not_storm(monkeypatch, tmp_path):
    pdf = inked_pdf(tmp_path / "a.pdf", 20)

    def fake(pdf_path, ps, **kw):
        for p in ps:
            if p == 5 or p > 10:
                kw["out"][0][p] = ("txt", {})
            else:
                kw["out"][1][p] = EMPTY

    monkeypatch.setattr(pv, "run_chunk", fake)
    res = pv.run_pages(pdf, list(range(1, 21)), log=lambda s: None)
    assert not res["empty_storm"]


def test_local_blank_pages_not_submitted(monkeypatch, tmp_path):
    doc = fitz.open()
    for i in range(4):
        pg = doc.new_page(width=200, height=280)
        pg.draw_rect(pg.rect, color=None, fill=(0.96, 0.92, 0.82))
        if i % 2:
            pg.draw_rect(fitz.Rect(30, 30, 170, 250), color=None, fill=(0, 0, 0))
    p = str(tmp_path / "b.pdf")
    doc.save(p)
    posted: list[list[int]] = []

    def fake(pdf_path, ps, **kw):
        posted.append(list(ps))
        kw["out"][0].update({q: ("t", {}) for q in ps})

    monkeypatch.setattr(pv, "run_chunk", fake)
    res = pv.run_pages(p, [1, 2, 3, 4], log=lambda s: None)
    assert posted == [[2, 4]]
    assert res["ok"][1][1]["empty_reason"] == "blank" and res["ok"][3][1]["job_id"] == "local-blank"


def test_is_blank_junk_text_layer_and_edge_shadow(tmp_path):
    doc = fitz.open()
    pg = doc.new_page(width=200, height=280)
    pg.draw_rect(pg.rect, color=None, fill=(0.96, 0.92, 0.82))
    pg.draw_rect(fitz.Rect(0, 0, 8, 280), color=None, fill=(0.2, 0.2, 0.2))  # 书脊阴影
    pg.insert_text((100, 140), "I", fontsize=8)  # 垃圾文本层
    pg2 = doc.new_page(width=200, height=280)
    pg2.draw_rect(pg2.rect, color=None, fill=(0.96, 0.92, 0.82))
    pg2.insert_text((20, 50), "Real text content on this page", fontsize=10)
    p = str(tmp_path / "j.pdf")
    doc.save(p)
    assert pv._is_blank(p, 1) is True
    assert pv._is_blank(p, 2) is False
