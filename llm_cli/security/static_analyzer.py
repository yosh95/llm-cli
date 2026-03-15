import ast
import logging

logger = logging.getLogger(__name__)


class PythonSecurityScanner(ast.NodeVisitor):
    """
    AST-based static analyzer to detect potentially dangerous Python code.
    This acts as a fast, deterministic layer of defense before execution.
    """

    # Modules that are generally considered dangerous in an AI agent context
    DANGEROUS_MODULES = {
        "os",
        "shutil",
        "socket",
        "requests",
        "urllib",
        "builtins",
        "importlib",
        "pickle",
        "marshal",
        "shelve",
        "ctypes",
        "pty",
        "platform",
    }

    # Specific functions that are high-risk
    DANGEROUS_FUNCTIONS = {
        "eval",
        "exec",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "__import__",
        "breakpoint",
        "input",
    }

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.found_modules: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module_name = alias.name.split(".")[0]
            self.found_modules.add(module_name)
            if module_name in self.DANGEROUS_MODULES:
                self.issues.append(f"High-risk module import detected: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_module = node.module.split(".")[0]
            self.found_modules.add(base_module)
            if base_module in self.DANGEROUS_MODULES:
                self.issues.append(f"High-risk module import detected: {node.module}")
        self.generic_visit(node)

    def _check_subprocess_node(self, node: ast.Call) -> None:
        """Helper to check for shell=True in subprocess calls."""
        # Detect: subprocess.run, subprocess.Popen, subprocess.call, etc.
        is_subprocess_call = False
        if isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                is_subprocess_call = True
        elif isinstance(node.func, ast.Name) and node.func.id in [
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
        ]:
            # This handles 'from subprocess import run'
            is_subprocess_call = True

        if is_subprocess_call:
            for kw in node.keywords:
                if kw.arg == "shell":
                    # Check if value is True (Constant in Python 3.8+)
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.issues.append(
                            "Security Violation: 'shell=True' is strictly forbidden "
                            "in subprocess calls."
                        )
                    # Also check for non-literal True if possible,
                    # but literals are the main risk
                    elif isinstance(kw.value, ast.Name) and kw.value.id == "True":
                        self.issues.append(
                            "Security Violation: 'shell=True' is strictly forbidden "
                            "in subprocess calls."
                        )

    def visit_Call(self, node: ast.Call) -> None:
        # Check for direct calls to dangerous functions
        if isinstance(node.func, ast.Name):
            if node.func.id in self.DANGEROUS_FUNCTIONS:
                self.issues.append(f"High-risk function call detected: {node.func.id}")

        # Check for attribute calls like os.system()
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                module_id = node.func.value.id
                if module_id in self.DANGEROUS_MODULES:
                    self.issues.append(
                        f"High-risk method call: {module_id}.{node.func.attr}"
                    )
                # Specific check for os.system and os.popen which are shell-like
                # even without shell=True arg
                if module_id == "os" and node.func.attr in ["system", "popen"]:
                    self.issues.append(
                        f"Security Violation: os.{node.func.attr} is forbidden. "
                        "Use subprocess.run(shell=False)."
                    )

        # Context-aware check for subprocess
        self._check_subprocess_node(node)

        self.generic_visit(node)


def analyze_python_safety(code: str) -> tuple[bool, list[str]]:
    """
    Analyzes Python code for security issues using AST.
    Returns (is_safe, issues_list).
    """
    try:
        tree = ast.parse(code)
        scanner = PythonSecurityScanner()
        scanner.visit(tree)
        return len(scanner.issues) == 0, scanner.issues
    except SyntaxError as e:
        return False, [f"Syntax Error: {e}"]
    except Exception as e:
        return False, [f"Analysis Error: {e}"]
