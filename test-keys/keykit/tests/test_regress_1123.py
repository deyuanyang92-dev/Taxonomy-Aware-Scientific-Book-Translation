"""2026-11-23 主线程样张发现的问题的回归测试。"""
from keykit import fix, layout
from keykit.ir import Couplet, KeyIR, Lead
from keykit.profile import for_lang


def _ir(targets):
    leads = [Lead("正文", "taxon", t) for t in targets]
    cs = [Couplet(i + 1, None, leads[2 * i: 2 * i + 2]) for i in range(len(leads) // 2)]
    return KeyIR("t", cs)


def test_bare_rank_flagged_and_repaired():
    ir = _ir(["亚科 Harmothoinae", "亚科 Polynoinae"])
    assert [x["code"] for x in fix.check(ir)].count("D1") == 2
    ir, missing = fix.add_zh_names(ir, lambda lat: "哈鳞虫亚科" if lat == "Harmothoinae" else None)
    assert ir.couplets[0].leads[0].target == "Harmothoinae"
    assert ir.couplets[0].leads[0].name_zh == "哈鳞虫亚科"
    assert missing == ["Polynoinae"]  # 查不到不拟名
    assert "D1" not in [x["code"] for x in fix.check(ir)]


def test_channel_uses_percentile_not_max():
    prof = for_lang("zh", "dash")
    short = ["Aa"] * 9 + ["Opisthotrochopodus japonicus Imajima, 2001 extra long"]
    ch = layout.channel_mm([_ir(short)], prof)
    longest = layout.est_width_mm(short[-1], prof.font_size)
    assert ch < longest  # 一条特长去向不撑宽全表通道（L8）
    ld = Lead("x", "taxon", short[-1])
    assert layout.lead_right_mm(ld, prof, ch) >= longest  # 该条单独加宽，去向不折行（L3）


def test_fig_and_zh_name_glued():
    prof = for_lang("zh", "dash")
    ld = Lead("x", "taxon", "Iphione ovata", fig="（图38）", name_zh="某虫")
    s = layout.dest_text(ld, prof)
    wj = layout.WJOIN
    assert wj + "（" in s and "图" + wj + "3" in s
    assert "某虫 " + wj in s and chr(0xa0) + "Iphione" not in s
