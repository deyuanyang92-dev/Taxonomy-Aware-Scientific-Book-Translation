import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vl_translate as T  # noqa: E402


def test_parse_reply_accepts_strings_and_objects():
    assert T.parse_reply('["甲","乙"]', 2) == ["甲", "乙"]
    assert T.parse_reply('```json\n[{"original":"a","translation":"甲"},"乙"]\n```', 2) == ["甲", "乙"]


def test_parse_reply_rejects_bad():
    assert T.parse_reply('["甲"]', 2) is None
    assert T.parse_reply("not json", 1) is None
    assert T.parse_reply('[{"x":1}]', 1) is None
