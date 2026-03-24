from llm_cli.security.static_analyzer import analyze_python_safety


def test_analyze_python_safety_clean_code():
    """Verify that safe Python code passes analysis."""
    code = """
import math
import json
from pathlib import Path

def calculate_circle_area(radius):
    return math.pi * radius ** 2

data = {"radius": 5, "area": calculate_circle_area(5)}
print(json.dumps(data))
"""
    is_safe, issues = analyze_python_safety(code)
    assert is_safe is True
    assert len(issues) == 0


def test_analyze_python_safety_blocked_imports():
    """Verify that dangerous imports are detected."""
    # os is usually blocked by policy, let's see what static_analyzer blocks
    # Looking at static_analyzer.py (implied from evaluation)
    code = "import os; os.system('rm -rf /')"
    is_safe, issues = analyze_python_safety(code)
    assert is_safe is False
    assert any(
        "os.system" in issue.lower()
        or "shell=True" in issue
        or "dangerous" in issue.lower()
        for issue in issues
    )


def test_analyze_python_safety_subprocess_shell_true():
    """Verify that subprocess.run(..., shell=True) is blocked."""
    code = "import subprocess; subprocess.run('ls -la', shell=True)"
    is_safe, issues = analyze_python_safety(code)
    assert is_safe is False
    assert any("shell=True" in issue for issue in issues)


def test_analyze_python_safety_dynamic_execution():
    """Verify that eval and exec are blocked."""
    is_safe, issues = analyze_python_safety("eval('1+1')")
    assert is_safe is False
    assert any("eval" in issue for issue in issues)

    is_safe, issues = analyze_python_safety("exec('print(1)')")
    assert is_safe is False
    assert any("exec" in issue for issue in issues)


def test_analyze_python_safety_path_traversal_in_code():
    """Verify detection of suspicious path access."""
    code = "open('/etc/passwd', 'r')"
    is_safe, issues = analyze_python_safety(code)
    # The analyzer might flag this as sensitive
    assert is_safe is False or any("sensitive" in issue.lower() for issue in issues)


def test_analyze_python_safety_attribute_access():
    """Verify that accessing dangerous attributes via getattr or similar is flagged."""
    code = "getattr(os, 'system')('ls')"
    is_safe, issues = analyze_python_safety(code)
    assert is_safe is False


def test_analyze_python_safety_smart_guardrail():
    """Verify that rm is allowed generally but blocked for sensitive paths."""
    # 1. Safe rm (relative path or file)
    code_safe = "import subprocess; subprocess.run(['rm', 'temp.txt'])"
    is_safe, issues = analyze_python_safety(code_safe)
    assert is_safe is True
    assert len(issues) == 0

    # 2. Blocked rm (targets /etc)
    code_blocked = "import subprocess; subprocess.run(['rm', '-rf', '/etc/shadow'])"
    is_safe, issues = analyze_python_safety(code_blocked)
    assert is_safe is False
    assert any(
        "sensitive path" in issue.lower() and "rm" in issue.lower() for issue in issues
    )
