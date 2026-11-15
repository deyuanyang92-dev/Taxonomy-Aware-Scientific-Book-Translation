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
