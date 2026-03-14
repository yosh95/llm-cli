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
        "subprocess",
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
            self.found_modules.add(alias.name.split(".")[0])
            if alias.name.split(".")[0] in self.DANGEROUS_MODULES:
                self.issues.append(f"High-risk module import detected: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_module = node.module.split(".")[0]
            self.found_modules.add(base_module)
            if base_module in self.DANGEROUS_MODULES:
                self.issues.append(f"High-risk module import detected: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for direct calls to dangerous functions
        if isinstance(node.func, ast.Name):
            if node.func.id in self.DANGEROUS_FUNCTIONS:
                self.issues.append(f"High-risk function call detected: {node.func.id}")

        # Check for attribute calls like os.system()
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in self.DANGEROUS_MODULES:
                    self.issues.append(
                        f"High-risk method call: {node.func.value.id}.{node.func.attr}"
                    )

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
