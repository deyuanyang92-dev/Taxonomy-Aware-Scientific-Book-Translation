"""transqa.taxoblocks：样例取自 Hartmann-Schröder 1971/1979 实际段落。"""
from transqa.taxoblocks import kind


def test_labels_de():
    assert kind("Fundort: Pt. Hedland: Abrasionsterrasse vor dem Highway Motel: Sand mit Detritus; 27. 9. 75: 1 Exemplar.") == "locality"
    assert kind("Locus typicus:Broome: Gantheaume Point: Kliff mit Felsterrasse am Leuchtturm") == "locality"
    assert kind("Ökologie: Substrat: alle Sedimente, Phytal, unter Steinen; Tiefe: Eulitoral bis etwa 620 m.") == "ecology"
    assert kind("Verbreitung: Außer in der Arktis und Antarktis weltweit verbreitet.") == "distribution"
    assert kind("Taxonomische Bemerkung: E. microphylloides n. sp. steht der E. microphylla SCHMARDA am nächsten.") == "remarks"


def test_headings_and_citations():
    assert kind("Gattung Eumida MALMGREN, 1865 Eumida (Eumida) sanguinea (OERSTED, 1843)") == "heading"
    assert kind("Opisthodonta morena Langerhans, 1879") == "heading"
    assert kind("DAY & HUTCHINGS (1978).") == "citation"
    assert kind("LANGERHANS, P., 1879. Die Wurmfauna von Madeira. — Zeits. wiss. Zool., 32: 513-592, Taf. 31-33.") == "reference"


def test_junk_caption():
    assert kind("bt If) 7 bad m CO LIU SA") == "junk"
    assert kind(">>>") == "junk"
    assert kind("Fig. 4-6. Opisthodonta pterochaeta Southern. 4, Vorderende von dorsal") == "caption"


def test_description_vs_narrative():
    d = ("Körper klein. Prostomium mit vier Augen, oft mit zusätzlichen Stirnaugen. Palpen nur an der Basis "
         "miteinander verwachsen. Zwei Paar Tentakelcirren.")
    n = ("Das einzige von Peres 1954 gesammelte Tier ist inzwischen wieder verloren gegangen; das Material von "
         "Laubier und Storch lag mir zur Untersuchung vor. An dieser Stelle möchte ich den Herren nochmals danken.")
    assert kind(d) == "description"
    assert kind(n) == "narrative"


def test_reference_entries():
    assert kind("——, 1970. Contribution à la faunistique du coralligène. — Ann. Inst. Océanogr., 46: 79-107.") == "reference"
    assert kind("FAUVEL, P., 1923. Polychètes errantes. — Faune de France, 5: 1-494.") == "reference"


def test_risk_signals():
    from transqa.taxoblocks import risk
    gl = [("Tentakelcirren", "tentacular cirri")]
    assert risk("Zwei Paar Tentakelcirren.", "Two pairs of tentacle cirrus.", terms=gl) == ["term"]
    assert risk("Zwei Paar Tentakelcirren.", "Two pairs of tentacular cirri.", terms=gl) == []
    assert "number" in risk("mit 48 Borstensegmenten 6 mm lang", "6 mm long with 46 setigers")
    assert "negation" in risk("Augen fehlen.", "Eyes present.")
    assert "residue" in risk("aus Ghardaqa", "aus Ghardaqa")
    assert "name" in risk("wie bei Eulalia microphylla", "as in E. microphylla")
    assert risk("x", "y", rewritten=True) == ["rewritten"]


def test_risk_term_whole_word():
    from transqa.taxoblocks import risk
    gl = [("Borsten", "setae"), ("von hinten", "in posterior view")]
    assert risk("mit 32 Borstensegmenten", "with 32 setigers", terms=gl) == []
    assert risk("die hinteren Parapodien", "the posterior parapodia", terms=gl) == []
    assert risk("13. von hinten", "13th from behind", terms=gl) == ["term"]


# ---- risk() 误报修复（2026-11-19）：数字写法、CJK 长度比、解剖词不是学名 ----

def test_risk_number_notation_is_not_a_difference():
    # 小数逗号 = 小数点；千分位写法不同不算数字不一致（德→英常见）
    from transqa.taxoblocks import risk
    assert "number" not in risk("Länge 1,5 mm, Tiefe 2,5 m", "Length 1.5 mm, depth 2.5 m")
    assert "number" not in risk("bis 1.200 m Tiefe", "to 1,200 m depth")
    assert "number" not in risk("136 000 Exemplare", "136,000 specimens")
    # 真数字差异仍须报
    assert "number" in risk("Länge 1,5 mm", "Length 1.6 mm")
    assert "number" in risk("mit 48 Borstensegmenten", "with 46 setigers")


def test_risk_length_is_language_aware():
    from transqa.taxoblocks import risk
    en = "The dorsal cirri are slender and about twice as long as the parapodial lobes in most segments."
    zh = "背须细长，在大多数体节中约为足叶长度的两倍。"
    assert "length" not in risk(en, zh, "en", "zh")          # 中文字数约为英文的 0.47（实测 Rouse 2022 ch05-09）
    assert "length" not in risk(en, zh, "en", "zh-CN")
    assert "length" in risk(en, "背须细长。", "en", "zh")     # 明显漏译
    assert "length" in risk(en, en * 3, "en", "zh")          # 明显重复
    assert "length" in risk(zh * 2, "Dorsal cirri slender.", "zh", "en")      # zh→en 漏译
    assert "length" not in risk(zh * 2, en, "zh", "en")                          # zh→en 正常（比值≈2.2）
    # 同文字体系的旧阈值不变
    assert "length" in risk("Zwei Paar Tentakelcirren am Prostomium.", "Two.", "de", "en")


def test_risk_length_empty_target_and_short_labels():
    from transqa.taxoblocks import risk
    assert "length" in risk("Fig. 4. Vorderende von dorsal.", "", "de", "en")   # 空译文必报
    assert "length" not in risk("Dorsal cirrus", "背须", "en", "zh")             # 极短标签不按比例判


def test_risk_anatomical_adjective_is_not_a_taxon():
    from transqa.taxoblocks import risk
    assert "name" not in risk("Dorsal cirrus long.", "背须长。", "en", "zh")
    assert "name" not in risk("Ventral cirri short.", "腹须短。", "en", "zh")
    # 真学名丢失仍须报
    assert "name" in risk("as in Eulalia microphylla", "如同该属", "en", "zh")
    assert "name" in risk("wie bei Eulalia microphylla", "as in E. microphylla")


def test_junk_keeps_japanese_text_and_taxon_heading():
    # 2026-11-17：日文正文按拉丁字母比例判 junk，整段留原文，英/中稿出现日文。
    from transqa.taxoblocks import kind

    assert kind("形態―前口葉は二葉に分かれ，各葉の先端が明瞭な頭頂になっている", "ja") != "junk"
    assert kind("ウロコムシ科", "ja") != "junk"
    assert kind("Polynoidae", "ja") != "junk"
    assert kind("bt If) 7 bad m CO LIU SA", "ja") == "junk"


# ---- risk() 误报修复（2026-11-19）：数字写法、CJK 长度比、解剖词不是学名 ----