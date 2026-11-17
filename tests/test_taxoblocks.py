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


def test_junk_keeps_japanese_text_and_taxon_heading():
    # 2026-11-17：日文正文按拉丁字母比例判 junk，整段留原文，英/中稿出现日文。
    from transqa.taxoblocks import kind

    assert kind("形態―前口葉は二葉に分かれ，各葉の先端が明瞭な頭頂になっている", "ja") != "junk"
    assert kind("ウロコムシ科", "ja") != "junk"
    assert kind("Polynoidae", "ja") != "junk"
    assert kind("bt If) 7 bad m CO LIU SA", "ja") == "junk"
