"""docstore.langid：纯脚本语言识别（零 token）。"""
from docstore.langid import _despace, detect_text

DE = ("Oberer Dorsallappen beim neutralen Vorderende und beim Männchen noch im 25. Notopod so lang wie unterer, "
      "nur beim Weibchen hier etwas kürzer; im 40. Notopod jedoch noch fast so lang wie unterer; danach langsam "
      "kürzer werdend, aber im 62. Notopod noch mehr als halb so lang wie der untere.")
EN = ("The prostomium is wider than long, with four eyes; the anterior pair is larger than the posterior pair. "
      "Dorsal cirri are present on all segments and the chaetae are compound falcigers with short blades.")
RU = "Простомиум шире длины, с четырьмя глазами, которые расположены по углам трапеции; щупальца не длиннее пальп."
BG = "Простомиумът е по-широк, отколкото дълъг, с четири очи, които са разположени в трапец; пипалата са къси."


def test_german():
    assert detect_text(DE)[0] == "de"


def test_english():
    assert detect_text(EN)[0] == "en"


def test_russian_vs_bulgarian():
    assert detect_text(RU)[0] == "ru"
    assert detect_text(BG)[0] == "bg"


def test_cjk():
    assert detect_text("口前叶宽大于长，具眼两对，触手短于触角。" * 3)[0] == "zh"
    assert detect_text("口前葉は幅が長さより広く、眼は二対ある。" * 3)[0] == "ja"


def test_ocr_fragments_not_portuguese():
    # ABBYY 老文本层：字母被隔开、变音丢失；单字母碎片（o, e）不得把德文页判成葡萄牙文
    garbled = ("B o rsten seg m en t, fast bis zum K o rp e rh in te re n d e vo rh an d en ; d ie v o rd ere n lang "
               "und d u n n , die h in te re n k iirz er u n d d ick er; o e o e da da no no und der die mit von")
    assert detect_text(garbled)[0] == "de"


def test_despace():
    assert _despace("G e s a H a r t m a n n") == "GesaHartmann"


def test_empty_and_figures():
    assert detect_text("") == ("und", 0.0)
    assert detect_text("Tafel 1 8A 8B 10 11")[0] == "und"


def test_tess_lang_for(monkeypatch):
    import docstore.textify as t
    monkeypatch.setattr(t, "_USER_TESS_LANG", None)
    assert t.tess_lang_for("de") == "deu"
    assert t.tess_lang_for("") == "chi_sim+eng"
    monkeypatch.setattr(t, "_USER_TESS_LANG", "eng")
    assert t.tess_lang_for("de") == "eng"
