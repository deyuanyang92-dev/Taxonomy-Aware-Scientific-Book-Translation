import docx

from booklayout import builder
from booklayout.profile import StyleProfile


def test_profile_accepts_couplet_key_style():
    StyleProfile(key_style="couplet").validate()


def test_key_couplet_keeps_name_and_page_together_flush_right():
    """Vol. 21 p. 47: "Neopetitia (p. 49)" must not split from its page."""
    d = docx.Document()
    text = ("3. Palpos con apariencia de ser biarticulados. Cirros ventrales insertos "
            "distalmente en los parápodos ..... Neopetitia (p. 49)")
    paras = builder.key_couplets(d, text, set())
    assert len(paras) == 1
    p = paras[0]
    xml = p._p.xml
    assert xml.count('w:val="right"') == 1, "one right tab: no separate name column"
    assert 'w:leader="dot"' in xml
    assert p.text.replace("\N{NARROW NO-BREAK SPACE}", " ").rstrip().endswith("\tNeopetitia (p. 49)")  # atomic glue
    assert p.text.startswith("3.\t")


def test_key_couplet_bullet_with_number_target():
    d = docx.Document()
    p = builder.key_couplets(d, "• Faringe inerme ..... 11", set())[0]
    assert p.text.startswith("•\t") and p.text.rstrip().endswith("11")
    assert "....." not in p.text
