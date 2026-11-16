import json
import subprocess
import sys
from pathlib import Path

import pytest

from workcell_agent.environment import check_environment


def test_environment_separates_installed_usd_from_isaac_runtime():
    result = check_environment("core")
    assert result["python"]
    assert result["packages"]["usd-core"]
    assert result["isaac_running"] is False
    assert result["runtime"] is None
    assert result["status"] == "ready"
    assert result["required_missing"] == []


def test_core_check_fails_in_python_without_installed_packages():
    script = Path(__file__).parents[1] / "src" / "workcell_agent" / "environment.py"
    process = subprocess.run([sys.executable, "-I", "-S", str(script), "--target", "core"],
                             capture_output=True, text=True, check=False)
    assert process.returncode == 1
    result = json.loads(process.stdout)
    assert {"mcp", "usd-core", "cadquery-ocp", "pydantic"} <= set(result["required_missing"])
    assert result["status"] == "unavailable"


def test_isaac_check_requires_running_kit():
    script = Path(__file__).parents[1] / "src" / "workcell_agent" / "environment.py"
    process = subprocess.run([sys.executable, str(script), "--target", "isaac"],
                             capture_output=True, text=True, check=False)
    assert process.returncode == 1
    result = json.loads(process.stdout)
    assert "isaac_runtime" in result["required_missing"]
    assert result["isaac_running"] is False


def test_environment_rejects_unknown_target():
    with pytest.raises(ValueError):
        check_environment("unknown")
