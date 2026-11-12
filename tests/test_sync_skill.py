"""scripts/sync_skill.sh：复制前比对、--dry 不复制、不删技能目录里多出的文件。"""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SYNC = REPO / "scripts" / "sync_skill.sh"


def run(dest, *args):
    env = {"SKILL_DIR": str(dest), "PATH": "/usr/bin:/bin", "HOME": str(dest)}
    return subprocess.run(["bash", str(SYNC), *args], capture_output=True, text=True, env=env)


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "skill"


def test_dry_prints_diff_without_copy(dest):
    r = run(dest, "--dry")
    assert r.returncode == 0, r.stderr
    assert "新增  RULES.md" in r.stdout
    assert "未复制" in r.stdout
    assert not (dest / "RULES.md").exists()


def test_sync_copies_skill_md_domains_and_scripts(dest):
    r = run(dest)
    assert r.returncode == 0, r.stderr
    assert (dest / "RULES.md").read_text() == (REPO / "skill" / "RULES.md").read_text()
    assert (dest / "domains" / "分类学.md").exists()
    assert (dest / "scripts" / "deepseek_offpeak.py").exists()
    assert not list(dest.rglob("__pycache__"))
    # 再跑一次：已一致
    assert "已与仓库一致" in run(dest).stdout


def test_changed_file_shows_diff_and_extra_files_kept(dest):
    run(dest)
    (dest / "RULES.md").write_text("旧版\n", encoding="utf8")
    (dest / "terms").mkdir()
    (dest / "terms" / "x.tsv").write_text("keep\n")
    (dest / "额外.md").write_text("only in skill\n", encoding="utf8")
    r = run(dest)
    assert "更新  RULES.md" in r.stdout
    assert "-旧版" in r.stdout
    assert "额外.md" in r.stdout  # 仅技能目录有：提示但不删
    assert (dest / "额外.md").exists()
    assert (dest / "terms" / "x.tsv").exists()
    assert (dest / "RULES.md").read_text() == (REPO / "skill" / "RULES.md").read_text()
