from llm_cli.security.static_analyzer import analyze_python_safety

# ============================================================
# Existing tests (unchanged)
# ============================================================


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
    is_safe, issues, _ = analyze_python_safety(code)
    assert is_safe is True
    assert len(issues) == 0


def test_analyze_python_safety_blocked_imports():
    """Verify that dangerous imports are detected."""
    code = "import os; os.system('rm -rf /')"
    is_safe, issues, _ = analyze_python_safety(code)
    assert is_safe is False
    assert any(
        "os.system" in issue.lower() or "shell=True" in issue or "dangerous" in issue.lower()
        for issue in issues
    )


def test_analyze_python_safety_subprocess_shell_true():
    """Verify that subprocess.run(..., shell=True) is blocked."""
    code = "import subprocess; subprocess.run('ls -la', shell=True)"
    is_safe, issues, _ = analyze_python_safety(code)
    assert is_safe is False
    assert any("shell=True" in issue for issue in issues)


def test_analyze_python_safety_dynamic_execution():
    """Verify that eval and exec are blocked."""
    is_safe, issues, _ = analyze_python_safety("eval('1+1')")
    assert is_safe is False
    assert any("eval" in issue for issue in issues)

    is_safe, issues, _ = analyze_python_safety("exec('print(1)')")
    assert is_safe is False
    assert any("exec" in issue for issue in issues)


def test_analyze_python_safety_path_traversal_in_code():
    """Verify detection of suspicious path access."""
    code = "open('/etc/passwd', 'r')"
    is_safe, issues, _ = analyze_python_safety(code)
    assert is_safe is False or any("sensitive" in issue.lower() for issue in issues)


def test_analyze_python_safety_attribute_access():
    """Verify that accessing dangerous attributes via getattr or similar is flagged."""
    code = "getattr(os, 'system')('ls')"
    is_safe, issues, _ = analyze_python_safety(code)
    assert is_safe is False


def test_analyze_python_safety_smart_guardrail():
    """Verify that rm is allowed generally but blocked for sensitive paths."""
    # Safe rm (relative path or file)
    code_safe = "import subprocess; subprocess.run(['rm', 'temp.txt'])"
    is_safe, issues, _ = analyze_python_safety(code_safe)
    assert is_safe is True
    assert len(issues) == 0

    # Blocked rm (targets /etc)
    code_blocked = "import subprocess; subprocess.run(['rm', '-rf', '/etc/shadow'])"
    is_safe, issues, _ = analyze_python_safety(code_blocked)
    assert is_safe is False
    assert any("sensitive path" in issue.lower() and "rm" in issue.lower() for issue in issues)


# ============================================================
# New tests: module alias tracking
# ============================================================


class TestModuleAliasTracking:
    """
    Regression tests for the module-alias bypass that existed before the fix.
    Each test verifies a concrete evasion pattern that was previously undetected.
    """

    # ----------------------------------------------------------
    # import X as Y  (dangerous module aliases)
    # ----------------------------------------------------------

    def test_dangerous_module_alias_shell_true(self):
        """'import subprocess as sp; sp.run(..., shell=True)' must be blocked."""
        code = "import subprocess as sp; sp.run('ls', shell=True)"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("shell=True" in i for i in issues)

    def test_dangerous_module_alias_sensitive_path(self):
        """Aliased subprocess targeting a blocked path must be blocked."""
        code = "import subprocess as sp; sp.run(['rm', '-rf', '/etc/shadow'])"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("sensitive path" in i.lower() for i in issues)

    def test_dangerous_module_alias_import_flagged(self):
        """'import socket as s' must still flag the dangerous import."""
        code = "import socket as s; s.connect(('evil.com', 80))"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("socket" in i.lower() for i in issues)

    # ----------------------------------------------------------
    # import X as Y  (restricted module aliases)
    # ----------------------------------------------------------

    def test_restricted_module_alias_os_system(self):
        """'import os as o; o.system(...)' must be blocked."""
        code = "import os as o; o.system('id')"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("system" in i.lower() for i in issues)

    def test_restricted_module_alias_os_fork(self):
        """'import os as operating_system; operating_system.fork()' must be blocked."""
        code = "import os as operating_system; operating_system.fork()"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("fork" in i.lower() for i in issues)

    def test_restricted_module_alias_shutil_rmtree(self):
        """'import shutil as sh; sh.rmtree(...)' must be blocked."""
        code = "import shutil as sh; sh.rmtree('/tmp/work')"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("rmtree" in i.lower() for i in issues)

    # ----------------------------------------------------------
    # from subprocess import run as r  (function aliases)
    # ----------------------------------------------------------

    def test_subprocess_func_alias_shell_true(self):
        """'from subprocess import run as r; r(..., shell=True)' must be blocked."""
        code = "from subprocess import run as r; r('ls', shell=True)"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("shell=True" in i for i in issues)

    def test_subprocess_func_alias_popen_shell_true(self):
        """'from subprocess import Popen as P; P(..., shell=True)' must be blocked."""
        code = "from subprocess import Popen as P; P('ls', shell=True)"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("shell=True" in i for i in issues)

    def test_subprocess_func_alias_sensitive_path(self):
        """Aliased subprocess function targeting a blocked path must be blocked."""
        code = "from subprocess import run as execute; execute(['rm', '/etc/passwd'])"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("sensitive path" in i.lower() for i in issues)

    def test_subprocess_func_no_alias_still_works(self):
        """Unaliased 'from subprocess import run' must still be detected."""
        code = "from subprocess import run; run('ls', shell=True)"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is False, f"Expected unsafe, issues={issues}"
        assert any("shell=True" in i for i in issues)

    # ----------------------------------------------------------
    # False-positive prevention: safe aliased usage must pass
    # ----------------------------------------------------------

    def test_alias_safe_module_no_false_positive(self):
        """Aliasing a safe module must NOT generate a false positive."""
        code = "import math as m; result = m.sqrt(16)"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is True, f"Expected safe, but got issues={issues}"

    def test_subprocess_alias_safe_use_no_false_positive(self):
        """Aliased subprocess.run with a safe command must NOT be flagged."""
        code = "import subprocess as sp; sp.run(['ls', '-la'])"
        is_safe, issues, _ = analyze_python_safety(code)
        assert is_safe is True, f"Expected safe, but got issues={issues}"
