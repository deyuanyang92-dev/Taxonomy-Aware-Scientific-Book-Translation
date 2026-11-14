"""语言表：文字系统、否定/缺失词、1–20 的数词。新语言加一项即可，未列出的语言相关检查报 capability_missing。"""
from __future__ import annotations

import re

CYR = 'Ѐ-ӿ'
HAN = '一-鿿'
KANA = '぀-ヿ'
LAT = 'A-Za-zÀ-ɏ'

# script: 该语言用的全部字符；own: 只有该语言（或同文字语言）才有、可用来判断“残留原文”的字符
LANG: dict[str, dict[str, str]] = {
    'bg': {'script': CYR, 'own': CYR, 'neg': r'\b(?:не|без|липсва|липсват|няма|отсъства|отсъстват|нито)\b'},
    'ru': {'script': CYR, 'own': CYR, 'neg': r'\b(?:не|нет|без|отсутству\w*|ни)\b'},
    'uk': {'script': CYR, 'own': CYR, 'neg': r'\b(?:не|немає|без|відсутн\w*|ні)\b'},
    'sr': {'script': CYR, 'own': CYR, 'neg': r'\b(?:не|нема|без)\b'},
    'el': {'script': 'Ͱ-Ͽ', 'own': 'Ͱ-Ͽ', 'neg': r'\b(?:δεν|μη|χωρίς)\b'},
    'de': {'script': LAT, 'own': '', 'neg': r'\b(?:nicht|kein\w*|ohne|fehl\w*)\b'},
    'fr': {'script': LAT, 'own': '', 'neg': r'\b(?:ne|pas|sans|aucun\w*|absent\w*|manqu\w*)\b'},
    'es': {'script': LAT, 'own': '', 'neg': r'\b(?:no|sin|ningún|ninguna|ausente\w*|carece\w*)\b'},
    'it': {'script': LAT, 'own': '', 'neg': r'\b(?:non|senza|nessun\w*|assent\w*|manca\w*)\b'},
    'pt': {'script': LAT, 'own': '', 'neg': r'\b(?:não|sem|nenhum\w*|ausente\w*)\b'},
    'nl': {'script': LAT, 'own': '', 'neg': r'\b(?:niet|geen|zonder|ontbre\w*)\b'},
    'la': {'script': LAT, 'own': '', 'neg': r'\b(?:non|nec|neque|sine|nullus|nulla|desunt|deest|absent)\b'},
    'en': {'script': LAT, 'own': '', 'neg': r'\b(?:no|not|without|absent|lacking|lacks?|none|never|nor|devoid)\b|\bnon-'},
    'ja': {'script': KANA + HAN, 'own': KANA, 'neg': r'(?:ない|無い|なし|無し|欠く|欠如|ず[、。]|ません)'},
    'zh': {'script': HAN, 'own': '', 'neg': r'(?:没有|無|无|不|缺|未|非)'},
    'ko': {'script': '가-힯', 'own': '가-힯', 'neg': r'(?:없|않|아니|무)'},
}

# 1–20 的数词（小写；原文写成数词、译文写成阿拉伯数字不算“新增数字”）
_W = {
    'bg': 'един една едно два две три четири пет шест седем осем девет десет единадесет дванадесет тринадесет '
          'четиринадесет петнадесет шестнадесет седемнадесет осемнадесет деветнадесет двадесет',
    'ru': 'один одна одно два две три четыре пять шесть семь восемь девять десять одиннадцать двенадцать '
          'тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать',
    'uk': 'один одна два дві три чотири пять шість сім вісім девять десять одинадцять дванадцять тринадцять '
          'чотирнадцять пятнадцять шістнадцять сімнадцять вісімнадцять девятнадцять двадцять',
    'de': 'eins ein zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn fünfzehn sechzehn '
          'siebzehn achtzehn neunzehn zwanzig',
    'fr': 'un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize dix-sept '
          'dix-huit dix-neuf vingt',
    'es': 'uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete '
          'dieciocho diecinueve veinte',
    'it': 'uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici quindici sedici '
          'diciassette diciotto diciannove venti',
    'pt': 'um dois três quatro cinco seis sete oito nove dez onze doze treze catorze quinze dezesseis dezessete '
          'dezoito dezenove vinte',
    'nl': 'een twee drie vier vijf zes zeven acht negen tien elf twaalf dertien veertien vijftien zestien zeventien '
          'achttien negentien twintig',
    'la': 'unus duo tres quattuor quinque sex septem octo novem decem undecim duodecim tredecim quattuordecim '
          'quindecim sedecim septendecim duodeviginti undeviginti viginti',
    'en': 'one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
          'seventeen eighteen nineteen twenty',
    'ja': '一 二 三 四 五 六 七 八 九 十',
    'zh': '一 二 三 四 五 六 七 八 九 十',
}
# 一词多值的语言（один/одна/одно = 1）：按顺序展开到 1–20
_MULTI = {'bg': [1, 1, 1, 2, 2], 'ru': [1, 1, 1, 2, 2], 'uk': [1, 1, 2, 2], 'de': [1, 1], 'en': []}


def numerals(lang: str) -> dict[str, int]:
    words = _W.get(base(lang), '').split()
    if not words:
        return {}
    lead = _MULTI.get(base(lang), [])
    vals = lead + list(range((lead[-1] + 1) if lead else 1, 21))
    return {w: v for w, v in zip(words, vals)}


def base(lang: str) -> str:
    return lang.split('-')[0].lower()


def info(lang: str) -> dict[str, str] | None:
    return LANG.get(base(lang))


def count_neg(text: str, lang: str) -> int | None:
    i = info(lang)
    return len(re.findall(i['neg'], text, re.I)) if i else None


def numeral_values(text: str, lang: str) -> list[int]:
    """文本里以数词出现的 1–20（按出现次数）。"""
    table = numerals(lang)
    if not table:
        return []
    if base(lang) in ('ja', 'zh'):
        return [table[c] for c in text if c in table]
    return [table[w] for w in re.findall(r'[^\W\d_]+', text.lower()) if w in table]
