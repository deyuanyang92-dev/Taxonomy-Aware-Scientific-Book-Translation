import re


def clean_md(t: str) -> str:
    t = re.sub(r"!\[.*?\]\(.*?\)", "", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"</?[a-z][^>]*>", "", t)
    return re.sub(r"[*_]{1,3}", "", t)
