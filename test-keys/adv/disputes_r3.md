# Round 3 disputes (keygraph, executor A)

Keeping a heading-only key (ruling item 8, SPEC line 41) conflicts with three existing samples. I did not edit samples. Please re-expect them or reverse item 8.

- ja_image_only: heading + image placeholder. Now 1 empty key, finding empty_key. Sample wants keys 0 + no_keys.
- ru_lost_glyphs: heading + box glyphs. Now 1 empty key with empty_key. Sample wants keys 0 + no_keys.
- r3_second_title_empty: second heading with only a placeholder. Now 2 keys, second reports empty_key. Sample wants keys 1, no findings.

Runner conflict (translation now also gets check()):
- r3_ja_omission: translation lacks branch 1b, so check() adds single_branch next to missing_branch. Sample comment says translation side counts only align codes.
- r3_zh_jump: translation 1(4) ... 1 is a real self-loop, so check() adds cycle and unreachable next to target_changed. Same convention question.
