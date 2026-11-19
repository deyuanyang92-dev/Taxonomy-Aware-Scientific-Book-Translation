# yiku · agent instructions
- Run `python3 -m pytest -q`, `ruff check .`, `mypy yiku` before committing.
- Keep the core domain-free: no discipline-specific term lists in code; those live in the user's database.
- Everything extracted is status 候选 until a human or the lead session marks it 已核.
- Reply to the user in Chinese or English only.
