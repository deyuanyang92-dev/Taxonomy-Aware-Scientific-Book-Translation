import numpy as np

from booklayout import typo_features as tf


def _bars(slant_deg: float, h: int = 40, n: int = 6) -> np.ndarray:
    """n vertical strokes (x-height h), sheared by slant_deg like italic type."""
    img = np.zeros((h + 10, 200), bool)
    t = np.tan(np.radians(slant_deg))
    for k in range(n):
        x0 = 20 + 25 * k
        for y in range(5, h + 5):
            x = int(round(x0 + t * (h + 5 - y)))
            img[y, x:x + 5] = True
    return img


def test_slant_roman_and_italic():
    assert abs(tf.slant_angle(_bars(0), 45)) <= 1
    assert 12 <= tf.slant_angle(_bars(15), 45) <= 18


def test_split_mixed_cuts_italic_roman_run():
    ink = np.concatenate([_bars(15), _bars(0)], axis=1)  # no blank gap guaranteed
    spans = tf.split_mixed(ink, (0, ink.shape[1]), 40, 45)
    assert len(spans) >= 2


def test_italic_words_diagonal_letters_unknown():
    w = [tf.Word("vez", (0, 0, 200, 40), 25.0)]
    ln = tf.Line("vez", 1.0, (0, 0, 200, 40), 5, 7, 0.1, 0.7, w)
    assert tf.italic_words(ln, 20) == [None]
