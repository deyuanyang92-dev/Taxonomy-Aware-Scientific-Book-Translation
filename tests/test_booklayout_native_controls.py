"""Native ingest drops C0 control characters that private-encoded fonts emit (Handbook: U+0007/U+0008)."""
from booklayout import ingest_native


def _sp(t):
    return {"text": t, "font": "F", "size": 9.0, "flags": 0}


class _Page:
    def get_text(self, _mode):
        return {"blocks": [
            {"lines": [{"spans": [_sp("1.4 \x07Linnaeus and the genera")], "bbox": (0, 0, 100, 10)}]},
            {"lines": [{"spans": [_sp("\x08")], "bbox": (0, 12, 10, 22)}]},
            {"lines": [{"spans": [_sp("tab\tstays")], "bbox": (0, 24, 50, 34)}]},
        ]}


def test_controls_removed_and_ornament_only_line_dropped():
    lines = ingest_native._page_lines(_Page())
    texts = [ln["text"] for ln in lines]
    assert texts[0].startswith("1.4") and "\x07" not in texts[0] and "Linnaeus" in texts[0]
    assert len(lines) == 2
    assert all("\x08" not in t for t in texts)


def test_strip_controls_keeps_newline_tab():
    assert ingest_native.strip_controls("a\x07b\nc\td\x1f") == "ab\nc\td"
