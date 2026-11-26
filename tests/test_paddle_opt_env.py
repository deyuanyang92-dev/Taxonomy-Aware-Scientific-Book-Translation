import json
import os
import subprocess
import sys

import pytest

BASE = {"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False}


def _opt_in_fresh_process(env_value):
    # 子进程里导入，避免 importlib.reload 替换模块级异常类，影响其他测试
    env = {k: v for k, v in os.environ.items() if k != "DOCSTORE_PADDLE_OPT"}
    if env_value is not None:
        env["DOCSTORE_PADDLE_OPT"] = env_value
    code = "import json; from docstore.engines import paddle_vl; print(json.dumps(paddle_vl.OPT))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("env_value, expected", [
    (None, BASE),
    (json.dumps({"useLayoutDetection": False, "promptLabel": "ocr"}),
     {**BASE, "useLayoutDetection": False, "promptLabel": "ocr"}),
])
def test_opt_env_override_merges_and_defaults(env_value, expected):
    assert _opt_in_fresh_process(env_value) == expected
