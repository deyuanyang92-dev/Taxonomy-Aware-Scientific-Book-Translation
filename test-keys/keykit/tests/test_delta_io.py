"""delta_io：DELTA Intkey 二进制读入。真数据测试在数据目录缺失时跳过。"""
from __future__ import annotations

import collections
from pathlib import Path

import pytest

from keykit.delta_io import (
    DeltaDataset,
    DeltaFormatError,
    _bits,
    _ints,
    _rec,
    _f32,
    _ranges,
    _restore_name,
    _wrap,
    clean_name,
    plain_text,
    read_intkey,
    write_delta,
)
from keykit.matrix import INAPPLICABLE, UNKNOWN

DATA = Path("/mnt/p/Travisia/02_原始数据/DELTA_Wilson_Avery_2023/Travisia_2023_v1-01")
needs_data = pytest.mark.skipif(not (DATA / "ichars").exists(), reason="Travisia DELTA 数据不在本机")


def test_rec_offsets_are_one_based_128_bytes() -> None:
    assert _rec(1) == 0
    assert _rec(3) == 256


def test_bits_low_bit_first() -> None:
    assert _bits(bytes([0b00000101, 0b00000001]), 0, 10) == [
        True, False, True, False, False, False, False, False, True, False,
    ]


def test_ints_bounds_checked() -> None:
    with pytest.raises(DeltaFormatError):
        _ints(b"\x00" * 8, 4, 2)


def test_clean_name_and_plain_text() -> None:
    assert clean_name("i{}Travisia amadoi\\i0{} Elias, 2003\\") == "Travisia amadoi Elias, 2003"
    assert clean_name("Travisia zieglerae Wiklund, 2019\x00") == "Travisia zieglerae Wiklund, 2019"  # 末尾 NUL 填充
    assert clean_name("i{}Travisia \\i{}una\\i0{} Avery, 2023") == "Travisia una Avery, 2023"
    assert clean_name("i{}Travisia olens\\i0{}.-Hartmann-Schröder, 1980") == "Travisia olens. Hartmann-Schröder, 1980"
    assert plain_text("1\\endash{}15 \\i{}T.\\i0{}") == "1-15 T."


@pytest.fixture(scope="module")
def ds() -> DeltaDataset:
    return read_intkey(DATA)


@needs_data
def test_counts(ds: DeltaDataset) -> None:
    m = ds.matrix
    assert len(m.taxa) == 45  # 40 个种 + 亚种/cf./sensu/sp. 条目
    assert len(m.characters) == 48
    assert collections.Counter(ds.char_types) == {"unordered": 24, "integer": 16, "text": 8}
    assert ds.heading.startswith("Travisia (Annelida, Travisiidae)")


@needs_data
def test_names_and_states(ds: DeltaDataset) -> None:
    m = ds.matrix
    assert m.taxa[0].name == "Travisia amadoi Elias, Bremec, Lana & Orensanz, 2003"
    assert m.characters[0].name == "prostomium <form>"
    assert m.characters[0].states == ["pointed, more or less conical", "truncate", "rounded"]
    assert ds.units[18] == "chaetigers"


@needs_data
def test_values_match_species_rtf(ds: DeltaDataset) -> None:
    """Travisia amadoi 的描述（species.rtf）：prostomium longer than maximum width；
    chaetiger 1 uniannulate；posterior chaetigers uniannulate, or triannulate；
    annulation pattern changes at chaetigers 11-12；pygidial lobes 7。"""
    m = ds.matrix
    assert m.value(0, 1) == frozenset({2})
    assert m.value(0, 6) == frozenset({0})
    assert m.value(0, 10) == frozenset({0, 2})
    assert ds.numeric[(0, 9)] == {11, 12}
    assert ds.numeric[(0, 38)] == {7}
    assert m.value(0, 13) == UNKNOWN  # branchiae length 未描述
    assert m.value(0, 15) == INAPPLICABLE  # 分枝鳃形态：鳃为 cirriform 时不适用


@needs_data
def test_polymorphic_with_inapplicable_bit(ds: DeltaDataset) -> None:
    """T. chinensis：branchiae cirriform, or branched; bifid or trifid。"""
    m = ds.matrix
    assert m.value(8, 14) == frozenset({0, 1})
    assert m.value(8, 15) == frozenset({1})
    assert ds.partly_inapplicable == {(8, 15)}


@needs_data
def test_text_value(ds: DeltaDataset) -> None:
    assert plain_text(ds.text[(8, 11)]).startswith("<Annulation pattern of segments: 1-15 triannulate")


@needs_data
def test_dependencies_agree_with_inapplicable_cells(ds: DeltaDataset) -> None:
    """控制性状的取值全落在“使依赖性状不适用”的状态里时，依赖性状必为 INAPPLICABLE。"""
    m = ds.matrix
    assert ds.dependencies[14] == {0: {15}}
    for ctrl, per_state in ds.dependencies.items():
        for t in range(len(m.taxa)):
            v = m.value(t, ctrl)
            if isinstance(v, str) or not v or not all(s in per_state for s in v):
                continue
            for dep in set.intersection(*(per_state[s] for s in v)):
                assert m.value(t, dep) in (INAPPLICABLE, UNKNOWN), (t, ctrl, dep)


def test_ranges_and_f32_and_wrap() -> None:
    assert _ranges([1, 2, 3, 5, 7, 8]) == "1-3/5/7-8"
    assert _f32(2.5) == "2.5"
    assert _f32(0.9797462224960327) == "0.9797462"
    lines = _wrap(["aaaa", "bbbb", "cccc"], width=9).split("\n")
    assert lines == ["aaaa bbbb", "cccc"]


def test_restore_name_undoes_one_char_shift() -> None:
    assert _restore_name("i{}Travisia\\i0{} x\\") == "\\i{}Travisia\\i0{} x"
    assert _restore_name("i{}Z\\i0{} y\x00") == "\\i{}Z\\i0{} y"
    assert _restore_name("\\i{}A\\i0{}") == "\\i{}A\\i0{}"


@needs_data
def test_write_delta_files(tmp_path: Path) -> None:
    ds = read_intkey(DATA)
    files = write_delta(ds, tmp_path)
    assert {f.name for f in files} == {"specs", "chars", "items", "toint", "tokey", "key"}
    specs = (tmp_path / "specs").read_text(encoding="cp1252")
    assert "*NUMBER OF CHARACTERS 48" in specs and "*MAXIMUM NUMBER OF ITEMS 45" in specs
    assert "*CHARACTER TYPES 1,UM 2,UM 3,TE" in specs
    assert "*DEPENDENT CHARACTERS 13,2:14-21" in specs
    assert "*COMMENT" in specs and "NOT written" in specs
    chars = (tmp_path / "chars").read_text(encoding="cp1252")
    assert chars.count("\n#") + 1 >= 48 and "*CHARACTER LIST" in chars
    items = (tmp_path / "items").read_text(encoding="cp1252")
    assert items.count("\n# ") == 45 - 1 + 1 and "*ITEM DESCRIPTIONS" in items


@needs_data
def test_write_delta_roundtrip_via_open_delta(tmp_path: Path) -> None:
    """OPEN_DELTA_CP=<classpath: common+commons-lang+io jars, confor classes>；缺 java 或变量则跳过。"""
    import os
    import shutil
    import subprocess

    cp = os.environ.get("OPEN_DELTA_CP")
    if not cp or not shutil.which("java"):
        pytest.skip("OPEN_DELTA_CP 未设或无 java")
    ds = read_intkey(DATA)
    write_delta(ds, tmp_path)
    subprocess.run(["java", "-cp", cp, "au.org.ala.delta.confor.CONFOR", "toint"], cwd=tmp_path, check=True,
                   capture_output=True, timeout=120)
    back = read_intkey(tmp_path)
    for t in range(len(ds.matrix.taxa)):
        for c in range(len(ds.matrix.characters)):
            assert back.matrix.taxa[t].values.get(c) == ds.matrix.taxa[t].values.get(c), (t, c)
    assert back.numeric == ds.numeric and back.text == ds.text and back.dependencies == ds.dependencies
    assert back.raw_names == ds.raw_names
