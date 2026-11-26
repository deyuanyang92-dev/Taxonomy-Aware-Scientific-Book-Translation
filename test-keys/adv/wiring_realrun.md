# key-model wiring real run

- source: /mnt/p/翻译-译作/Marinov1977_Polychaeta/md_en/b07.md
- cmd: python3 -m booklayout key-model --source <src> --out <scratch>/b07.json
- exit: 1; stdout: keys=0 branches=0 problems=53 graph_keys=4 graph_errors=53 graph_warn=0
- keymodel keys (old): 0; graph keys: 4; expect_keys: true
- graph errors: 53; warnings: 0
- first 5 errors (raw, not triaged):
  - {"code":"single_branch","severity":"error","lead":"1a","detail":"couplet 1 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"2a","detail":"couplet 2 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"3a","detail":"couplet 3 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"4a","detail":"couplet 4 has one branch","key":1}
  - {"code":"single_branch","severity":"error","lead":"5a","detail":"couplet 5 has one branch","key":1}
