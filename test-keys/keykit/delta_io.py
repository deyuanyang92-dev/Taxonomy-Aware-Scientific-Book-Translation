"""读 DELTA Intkey 编译数据集（ichars / iitems）为 keykit Matrix。

二进制布局的格式知识来自 open-delta（MPL）的 IntkeyDatasetFileReader.java 等，
此处为独立重写；偏移与依据行号见 survey/checks/delta_travisia/FORMAT_NOTES.md。

约定：
- 文件由 128 字节（32 个小端 int32）的记录组成，记录号从 1 起。
- Matrix 的状态下标为 0 起（DELTA 状态 1 对应下标 0），与 Character.states 对齐。
- 多状态性状完全解码。整数/实数/文本性状的取值解码为 DeltaDataset.numeric / .text，
  Matrix 中这些性状只记 INAPPLICABLE 或 UNKNOWN 占位（不放状态集合）。
- 未解码：分类单元丰度、图像、字符/分类单元链接文件、关键状态边界以外的显示格式字段。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .matrix import INAPPLICABLE, UNKNOWN, Character, Matrix, Taxon, Value
except ImportError:  # 直接以脚本方式导入
    from matrix import INAPPLICABLE, UNKNOWN, Character, Matrix, Taxon, Value  # type: ignore[no-redef]

RECORD_INTS = 32
RECORD_BYTES = 128
MAJOR_VERSION = 5
MINOR_VERSION = 2
ENCODING = "cp1252"

CHAR_TYPES = {1: "unordered", 2: "ordered", 3: "integer", 4: "real", 5: "text"}


class DeltaFormatError(ValueError):
    pass


def clean_name(raw: str) -> str:
    """去掉 DELTA 格式标记：斜体开 `\\i{}`/`i{}`、斜体关 `\\i0{}`、末尾的 `\\`、记录填充的 NUL。"""
    s = raw.replace("\x00", "").replace("\\i0{}", "").replace("\\i{}", "").replace("i{}", "")
    s = s.replace(".-", ". ")
    return s.rstrip("\\").strip()


_RTF_MAP = {"\\endash{}": "-", "\\emdash{}": "-", "\\i0{}": "", "\\i{}": "", "\\b0{}": "", "\\b{}": ""}


def plain_text(s: str) -> str:
    """DELTA 文本值里的 RTF 记号转成纯文本（只处理已见到的 endash/emdash/斜体粗体开关）。"""
    for k, v in _RTF_MAP.items():
        s = s.replace(k, v)
    return s


@dataclass
class DeltaDataset:
    heading: str
    matrix: Matrix
    raw_names: list[str]  # 含 DELTA 标记的原始分类单元名
    char_types: list[str]  # 每性状：unordered/ordered/integer/real/text
    notes: list[str | None]  # 性状备注（ichars rpChlp）
    units: dict[int, str]  # 数值性状单位
    # 依赖：控制性状 -> 状态下标 -> 使其不适用的性状下标集合
    dependencies: dict[int, dict[int, set[int]]]
    integer_range: dict[int, tuple[int, int]]  # 整数性状 (min, max)
    numeric: dict[tuple[int, int], tuple[float, float] | set[int]] = field(default_factory=dict)
    text: dict[tuple[int, int], str] = field(default_factory=dict)  # (taxon, char) -> 文本
    # 同时有状态位与不适用位的 (taxon, char)：Matrix 里取状态集合，不适用位记在这里
    partly_inapplicable: set[tuple[int, int]] = field(default_factory=set)
    undecoded: list[str] = field(default_factory=list)


def _ints(buf: bytes, off: int, n: int) -> list[int]:
    if off < 0 or off + 4 * n > len(buf):
        raise DeltaFormatError(f"read of {n} ints at byte {off} outside file ({len(buf)} bytes)")
    return list(struct.unpack_from(f"<{n}i", buf, off))


def _floats(buf: bytes, off: int, n: int) -> list[float]:
    if off < 0 or off + 4 * n > len(buf):
        raise DeltaFormatError(f"read of {n} floats at byte {off} outside file ({len(buf)} bytes)")
    return list(struct.unpack_from(f"<{n}f", buf, off))


def _rec(n: int) -> int:
    """记录号（1 起）-> 字节偏移。"""
    return (n - 1) * RECORD_BYTES


def _recs_for(nbytes: int) -> int:
    return math.ceil(nbytes / RECORD_BYTES)


def _str_at(buf: bytes, off: int, n: int) -> str:
    return buf[off : off + n].decode(ENCODING)


def _ref_string(buf: bytes, recno: int) -> str:
    """记录 recno 存长度，下一记录存正文。"""
    n = _ints(buf, _rec(recno), 1)[0]
    return _str_at(buf, _rec(recno + 1), n)


def _bits(buf: bytes, off: int, nbits: int) -> list[bool]:
    """低位在前的位数组。"""
    nbytes = math.ceil(nbits / 8)
    raw = buf[off : off + nbytes]
    if len(raw) < nbytes:
        raise DeltaFormatError("bit array outside file")
    return [bool(raw[i >> 3] >> (i & 7) & 1) for i in range(nbits)]


def read_intkey(src: str | Path) -> DeltaDataset:
    """读目录 src 下的 ichars 与 iitems。"""
    d = Path(src)
    ch = (d / "ichars").read_bytes()
    it = (d / "iitems").read_bytes()

    # ichars 头记录（Reader.java:164-205）
    h = _ints(ch, 0, RECORD_INTS)
    nc, rp_cdes, rp_stat, rp_chlp, rp_heading = h[0], h[2], h[3], h[4], h[12]
    # iitems 头记录（Reader.java:221-305）
    g = _ints(it, 0, RECORD_INTS)
    nitem, nchar, lrec = g[0], g[1], g[4]
    rp_tnam, rp_spec, rp_mini, ldep, rp_cdep, rp_cdat = g[5], g[6], g[7], g[8], g[9], g[12]
    major = g[15]  # g[20] 为次版本号，Java 仅在 rpOmitOr 非 0 时才校验，这里不校验
    if nc != nchar:
        raise DeltaFormatError(f"ichars has {nc} characters, iitems has {nchar}")
    if lrec != RECORD_INTS:
        raise DeltaFormatError(f"record length {lrec} != {RECORD_INTS}")
    if major != MAJOR_VERSION:
        raise DeltaFormatError(f"major version {major} != {MAJOR_VERSION}")

    heading = _ref_string(ch, rp_heading) if rp_heading > 0 else _ref_string(it, 2)

    # 分类单元名（Reader.java:891-920）：nitem+1 个累计偏移，其后记录起存名字字节
    offs = _ints(it, _rec(rp_tnam), nitem + 1)
    name_base = _rec(rp_tnam + _recs_for(4 * (nitem + 1)))
    names = [_str_at(it, name_base + offs[i], offs[i + 1] - offs[i]) for i in range(nitem)]

    # 性状类型 / 状态数 / 可靠度（Reader.java:430-480）
    types = _ints(it, _rec(rp_spec), nc)
    span = _recs_for(4 * nc)
    nstates_it = _ints(it, _rec(rp_spec + span), nc)
    reliab = _floats(it, _rec(rp_spec + 2 * span), nc)
    nstates = _ints(ch, _rec(rp_stat), nc)
    kinds: list[str] = []
    for t in types:
        if abs(t) not in CHAR_TYPES:
            raise DeltaFormatError(f"unknown character type {t}")
        kinds.append(CHAR_TYPES[abs(t)])
    for i, k in enumerate(kinds):
        if k in ("unordered", "ordered") and nstates[i] != nstates_it[i]:
            raise DeltaFormatError(f"state count differs for character {i + 1}")

    # 性状描述与状态名（Reader.java:601-660）：记录 = (nstates+1) 个长度，后接文本
    desc_recs = _ints(ch, _rec(rp_cdes), nc)
    characters: list[Character] = []
    units: dict[int, str] = {}
    for i in range(nc):
        base = desc_recs[i]
        lens = _ints(ch, _rec(base), nstates[i] + 1)
        pos = _rec(base + _recs_for(4 * (nstates[i] + 1)))
        texts = []
        for n in lens:
            texts.append(_str_at(ch, pos, n))
            pos += n
        if kinds[i] in ("unordered", "ordered"):
            states = texts[1:]
        else:
            states = []
            if len(texts) > 1:
                units[i] = texts[1]
        characters.append(Character(name=texts[0], states=states, reliability=float(reliab[i])))

    # 备注（Reader.java:689-720）
    notes: list[str | None] = [None] * nc
    if rp_chlp > 0:
        refs = _ints(ch, _rec(rp_chlp), nc)
        notes = [_ref_string(ch, r) if r else None for r in refs]

    # 整数性状 min/max（Reader.java:730-760）
    int_range: dict[int, tuple[int, int]] = {}
    if rp_mini:
        mins = _ints(it, _rec(rp_mini), nc)
        maxs = _ints(it, _rec(rp_mini + span), nc)
        for i, k in enumerate(kinds):
            if k == "integer":
                int_range[i] = (mins[i], maxs[i])

    # 依赖（Reader.java:772-880）；数组内部指针为 1 起的 int 下标
    deps: dict[int, dict[int, set[int]]] = {}
    if ldep >= nc and rp_cdep > 0:
        dd = _ints(it, _rec(rp_cdep), ldep)
        for i in range(nc):
            p = dd[i]
            if p <= 0:
                continue
            ns = len(characters[i].states)
            per_state: dict[int, set[int]] = {}
            for j in range(ns):
                q = dd[p - 1 + j]
                if q <= 0:
                    continue
                nr = dd[q - 1]
                deps_set: set[int] = set()
                for r in range(nr):
                    lo, hi = dd[q + 2 * r], dd[q + 2 * r + 1]
                    deps_set.update(c - 1 for c in range(lo, hi + 1))
                per_state[j] = deps_set
            deps[i] = per_state

    # 取值（Reader.java:1415-1620）
    cdat = _ints(it, _rec(rp_cdat), nc)
    taxa = [Taxon(name=clean_name(n)) for n in names]
    numeric: dict[tuple[int, int], tuple[float, float] | set[int]] = {}
    text: dict[tuple[int, int], str] = {}
    partly: set[tuple[int, int]] = set()
    for c in range(nc):
        base = _rec(cdat[c])
        k = kinds[c]
        if k in ("unordered", "ordered"):
            bpt = nstates[c] + 1
            bits = _bits(it, base, bpt * nitem)
            for t in range(nitem):
                chunk = bits[t * bpt : (t + 1) * bpt]
                present = frozenset(s for s in range(nstates[c]) if chunk[s])
                if chunk[-1] and present:
                    partly.add((t, c))
                if present:
                    taxa[t].values[c] = present
                else:
                    taxa[t].values[c] = INAPPLICABLE if chunk[-1] else UNKNOWN
        elif k == "integer":
            lo, hi = int_range.get(c, (0, 0))
            bpt = hi - lo + 4
            bits = _bits(it, base, bpt * nitem)
            for t in range(nitem):
                chunk = bits[t * bpt : (t + 1) * bpt]
                if chunk[-1]:
                    taxa[t].values[c] = INAPPLICABLE
                    continue
                vals = {q + lo - 1 for q in range(bpt - 1) if chunk[q]}
                taxa[t].values[c] = UNKNOWN
                if vals:
                    numeric[(t, c)] = vals
        else:
            inap = _bits(it, base, nitem)
            after = base + _rec(1 + _recs_for(math.ceil(nitem / 8)))
            if k == "real":
                fl = _floats(it, after, 2 * nitem)
                for t in range(nitem):
                    lo_f, hi_f = fl[2 * t], fl[2 * t + 1]
                    if inap[t]:
                        taxa[t].values[c] = INAPPLICABLE
                    else:
                        taxa[t].values[c] = UNKNOWN
                        if lo_f <= hi_f:
                            numeric[(t, c)] = (lo_f, hi_f)
            else:  # text：nitem+1 个偏移（1 起），其后记录起存文本字节
                toffs = _ints(it, after, nitem + 1)
                tbase = after + _rec(1 + _recs_for(4 * (nitem + 1)))
                for t in range(nitem):
                    a, b = toffs[t], toffs[t + 1]
                    taxa[t].values[c] = INAPPLICABLE if inap[t] else UNKNOWN
                    if b > a and not inap[t]:
                        text[(t, c)] = _str_at(it, tbase + a - 1, b - a)

    undecoded = [
        "分类单元丰度（Taxon.abundance 保持默认 5.0）",
        "字符/分类单元图像、链接文件、overlay 字体、or 词、字符分组小标题",
        "实数性状的 key state boundaries（rpNkbd）",
        "Intkey 内部 b-tree 与图像掩码（iitems 尾部）",
    ]
    return DeltaDataset(
        heading=heading,
        matrix=Matrix(characters=characters, taxa=taxa),
        raw_names=names,
        char_types=kinds,
        notes=notes,
        units=units,
        dependencies=deps,
        integer_range=int_range,
        numeric=numeric,
        text=text,
        partly_inapplicable=partly,
        undecoded=undecoded,
    )


def read_matrix(src: str | Path) -> Matrix:
    return read_intkey(src).matrix


def value_text(m: Matrix, t: int, c: int) -> str:
    """调试/核对用：值转成可读串。"""
    v: Value = m.value(t, c)
    if isinstance(v, str):
        return v
    return "/".join(m.characters[c].states[i] for i in sorted(v))


# ---------------------------------------------------------------------------
# 写文本 DELTA（specs / chars / items / toint / tokey / key）
# ---------------------------------------------------------------------------

_TYPE_CODE = {"unordered": "UM", "ordered": "OM", "integer": "IN", "real": "RN", "text": "TE"}


def _f32(x: float) -> str:
    """float32 的最短往返十进制串。"""
    want = struct.pack("<f", x)
    for p in range(1, 10):
        s = f"{x:.{p}g}"
        if struct.pack("<f", float(s)) == want:
            return s
    return f"{x:.9g}"


def _ranges(nums: list[int]) -> str:
    """升序整数 -> '1-3/5/7-8'（用于取值，/ 表示 or）。"""
    out: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return "/".join(out)


def _wrap(tokens: list[str], width: int = 78) -> str:
    lines: list[str] = []
    cur = ""
    for tk in tokens:
        if cur and len(cur) + 1 + len(tk) > width:
            lines.append(cur)
            cur = tk
        else:
            cur = f"{cur} {tk}" if cur else tk
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _restore_name(raw: str) -> str:
    """iitems 里的名字首个 '\\' 被吃掉、末尾多一个 '\\'（整体错位 1 字符）；还原为输入写法。"""
    if raw.endswith(("\\", "\x00")) and not raw.startswith("\\"):
        return "\\" + raw[:-1]
    return raw


def write_delta(ds: DeltaDataset, outdir: str | Path) -> list[Path]:
    """把 DeltaDataset 写成文本 DELTA：specs、chars、items、toint、tokey、key。

    返回写出的文件。未解码、因此未写入的内容见各文件头的 *COMMENT。
    """
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    m = ds.matrix
    nc, nt = len(m.characters), len(m.taxa)
    skipped = (
        "Written by keykit.delta_io.write_delta. NOT written (not decoded from the compiled files): "
        "taxon abundance, images, character notes (cnotes), IMPLICIT VALUES, MANDATORY CHARACTERS, "
        "key state boundaries, or-words, character headings. Values of a multistate character that is "
        "both scored and inapplicable for one taxon are written as scored states only."
    )

    # specs
    types = [f"{i + 1},{_TYPE_CODE[k]}" for i, k in enumerate(ds.char_types)]
    nst = [f"{i + 1},{len(ch.states)}" for i, ch in enumerate(m.characters) if ds.char_types[i] in ("unordered", "ordered")]
    maxs = max([len(ch.states) for ch in m.characters] + [2])
    dep_parts: list[str] = []
    for c in sorted(ds.dependencies):
        groups: dict[frozenset[int], list[int]] = {}
        for s, dset in sorted(ds.dependencies[c].items()):
            groups.setdefault(frozenset(dset), []).append(s)
        for gdeps, sts in groups.items():
            if not gdeps:
                continue
            rng = _ranges([d + 1 for d in sorted(gdeps)]).replace("/", ":")  # 依赖语法用 : 分隔范围
            dep_parts.append(f"{c + 1},{_ranges([s + 1 for s in sts])}:{rng}")
    specs = [
        f"*COMMENT {skipped}",
        "",
        f"*NUMBER OF CHARACTERS {nc}",
        f"*MAXIMUM NUMBER OF STATES {maxs}",
        f"*MAXIMUM NUMBER OF ITEMS {nt}",
        "",
        "*CHARACTER TYPES " + _wrap(types),
        "",
        "*NUMBERS OF STATES " + _wrap(nst),
    ]
    if dep_parts:
        specs += ["", "*DEPENDENT CHARACTERS " + _wrap(dep_parts)]
    (out / "specs").write_text("\n".join(specs) + "\n", encoding=ENCODING)

    # chars
    cl = [f"*COMMENT {skipped}", "", "*CHARACTER LIST"]
    for i, ch in enumerate(m.characters):
        k = ds.char_types[i]
        cl.append(f"#{i + 1}. {ch.name}/")
        if k in ("unordered", "ordered"):
            for j, sname in enumerate(ch.states):
                cl.append(f"   {j + 1}. {sname}/")
        elif i in ds.units:
            cl.append(f"   {ds.units[i]}/")
        cl.append("")
    (out / "chars").write_text("\n".join(cl), encoding=ENCODING)

    # items
    il = [f"*COMMENT {skipped}", "", "*ITEM DESCRIPTIONS"]
    for t, tx in enumerate(m.taxa):
        il.append(f"# {_restore_name(ds.raw_names[t])}/")
        toks: list[str] = []
        for c in range(nc):
            v = tx.values.get(c, UNKNOWN)
            k = ds.char_types[c]
            if k == "text":
                if (t, c) in ds.text:
                    toks.append(f"{c + 1},{ds.text[(t, c)]}")
                elif v == INAPPLICABLE:
                    toks.append(f"{c + 1},-")
            elif k == "integer":
                nums = ds.numeric.get((t, c))
                if isinstance(nums, set) and nums:
                    toks.append(f"{c + 1},{_ranges(sorted(nums))}")
                elif v == INAPPLICABLE:
                    toks.append(f"{c + 1},-")
            elif k == "real":
                rv = ds.numeric.get((t, c))
                if isinstance(rv, tuple):
                    lo, hi = rv
                    toks.append(f"{c + 1},{_f32(lo)}" if lo == hi else f"{c + 1},{_f32(lo)}-{_f32(hi)}")
                elif v == INAPPLICABLE:
                    toks.append(f"{c + 1},-")
            elif isinstance(v, frozenset) and v:
                toks.append(f"{c + 1},{_ranges([s + 1 for s in sorted(v)])}")
            elif v == INAPPLICABLE:
                toks.append(f"{c + 1},-")
        il.append(_wrap(toks))
        il.append("")
    (out / "items").write_text("\n".join(il), encoding=ENCODING)

    rel = _wrap([f"{i + 1},{_f32(ch.reliability)}" for i, ch in enumerate(m.characters)])
    head = ds.heading
    toint = [
        f"*COMMENT {skipped}", "", f"*HEADING {head}", "", "*INPUT FILE specs", "", "*TRANSLATE INTO INTKEY FORMAT", "",
        "*CHARACTER RELIABILITIES " + rel, "", "*INTKEY OUTPUT FILE ichars", "", "*INPUT FILE chars", "",
        "*INTKEY OUTPUT FILE iitems", "", "*INPUT FILE items", "",
    ]
    (out / "toint").write_text("\n".join(toint), encoding=ENCODING)
    tokey = [
        f"*COMMENT {skipped}", "", f"*HEADING {head}", "", "*INPUT FILE specs", "", "*TRANSLATE INTO KEY FORMAT", "",
        "*CHARACTER RELIABILITIES " + rel, "", "*KEY OUTPUT FILE kchars", "", "*INPUT FILE chars", "",
        "*KEY OUTPUT FILE kitems", "", "*INPUT FILE items", "",
    ]
    (out / "tokey").write_text("\n".join(tokey), encoding=ENCODING)
    key = [
        "*COMMENT Open-delta KEY run; default parameter values set explicitly.", "",
        "*RBASE 1.4", "", "*ABASE 2.0", "", "*REUSE 1.01", "", "*VARYWT 0.8", "",
        "*CHARACTERS FILE kchars", "", "*ITEMS FILE kitems", "",
    ]
    (out / "key").write_text("\n".join(key), encoding=ENCODING)
    return [out / n for n in ("specs", "chars", "items", "toint", "tokey", "key")]


def binned_matrix(ds: DeltaDataset, nbins: int = 3) -> Matrix:
    """把整数/实数性状按数据空隙分箱成状态，其余性状原样；文本性状保持占位（不可用）。

    分箱用 tabkey.choose_cuts（与文献表同一套）；区间跨切点的分类单元进入多个箱（多态）。
    """
    from .tabkey import bin_labels, choose_cuts

    m = ds.matrix
    chars = [Character(c.name, list(c.states), c.reliability) for c in m.characters]
    taxa = [Taxon(t.name, dict(t.values), t.abundance) for t in m.taxa]
    for c in range(len(chars)):
        ivs: dict[int, tuple[float, float]] = {}
        for (t, cc), v in ds.numeric.items():
            if cc != c:
                continue
            if isinstance(v, tuple):
                ivs[t] = v
            elif v:
                ivs[t] = (float(min(v)), float(max(v)))
        if len(ivs) < 3:
            continue
        cuts = choose_cuts(list(ivs.values()), nbins)
        labs = bin_labels(cuts)
        chars[c] = Character(m.characters[c].name, labs, m.characters[c].reliability)
        for t, (lo, hi) in ivs.items():
            a = sum(1 for x in cuts if x <= lo)
            b = sum(1 for x in cuts if x <= hi)
            taxa[t].values[c] = frozenset(range(a, b + 1))
        for t in range(len(taxa)):
            if t not in ivs:
                taxa[t].values[c] = m.value(t, c) if isinstance(m.value(t, c), str) else UNKNOWN
    return Matrix(chars, taxa)
