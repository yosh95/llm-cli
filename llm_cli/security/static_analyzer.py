import ast
import logging

logger = logging.getLogger(__name__)


class PythonSecurityScanner(ast.NodeVisitor):
    """
    AST-based static analyzer to detect potentially dangerous Python code.
    This acts as a fast, deterministic layer of defense before execution.
    """

    # Modules that are strictly forbidden to import entirely
    DANGEROUS_MODULES = {
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

    # Modules that are allowed but have restricted members (granular check)
    RESTRICTED_MODULES = {
        "os": {
            "system",
            "popen",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "execl",
            "execle",
            "execlp",
            "execlpe",
            "execv",
            "execve",
            "execvp",
            "execvpe",
            "fork",
            "forkpty",
            "kill",
            "killpg",
            "plock",
            "chmod",
            "chown",
            "lchmod",
            "lchown",
            "fchmod",
            "fchown",
            "chroot",
            "putenv",
            "unsetenv",
        },
        "shutil": {
            "rmtree",
            "move",
            "make_archive",
            "unpack_archive",
        },
    }

    # Specific functions that are high-risk
    DANGEROUS_FUNCTIONS = {
        "eval",
        "exec",
        "getattr",
        "setattr",
        "delattr",
        "__import__",
        "breakpoint",
        "input",
        "globals",
        "locals",
        "vars",
        "compile",
    }

    # High-risk attributes (Reflection)
    DANGEROUS_ATTRIBUTES = {
        "__subclasses__",
        "__bases__",
        "__class__",
        "__mro__",
        "__dict__",
        "__builtins__",
        "__globals__",
    }

    # High-risk commands that shouldn't touch sensitive system paths
    SENSITIVE_TARGET_COMMANDS = {"rm", "shred", "dd", "mkfs", "chown", "chmod"}

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.found_modules: set[str] = set()
        self.aliases: dict[str, str] = {}  # Track aliases of dangerous functions

        # Load blocked paths from config to check against subprocess targets
        from llm_cli.clients.config import config_manager

        self.blocked_paths = config_manager.get("security", "blocked_paths") or []

    def _check_subprocess_node(self, node: ast.Call) -> None:
        """
        Checks for shell=True and dangerous command combinations in subprocess calls.
        """
        is_subprocess_call = False
        cmd_args: list[str] = []

        # 1. Detect if this is a subprocess call and extract literal arguments
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
            is_subprocess_call = True

        if not is_subprocess_call:
            return

        # 2. Extract arguments (best effort for literal strings)
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.List):
                for elt in first_arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        cmd_args.append(elt.value)
            elif isinstance(first_arg, ast.Constant) and isinstance(
                first_arg.value, str
            ):
                cmd_args.append(first_arg.value)

        # 3. Check for shell=True
        for kw in node.keywords:
            if kw.arg == "shell":
                val = None
                if isinstance(kw.value, ast.Constant):
                    val = kw.value.value
                elif isinstance(kw.value, ast.Name):
                    val = kw.value.id == "True"

                if val is True:
                    self.issues.append(
                        "Security Violation: 'shell=True' is strictly forbidden."
                    )

        # 4. Smart Guardrail: Command + Path combination
        if cmd_args:
            cmd = cmd_args[0].split("/")[-1]  # Handle /bin/rm as rm
            if cmd in self.SENSITIVE_TARGET_COMMANDS:
                for arg in cmd_args[1:]:
                    # Check if any argument targets a blocked path
                    for blocked in self.blocked_paths:
                        # Simple prefix match (e.g. /etc/shadow matches /etc)
                        if arg == blocked or arg.startswith(blocked + "/"):
                            self.issues.append(
                                f"Security Violation: Command '{cmd}' targeting "
                                f"sensitive path '{arg}' is forbidden."
                            )

    def visit_Assign(self, node: ast.Assign) -> None:
        """
        Detect assignments like 'f = eval'.
        """
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.DANGEROUS_FUNCTIONS
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.aliases[target.id] = node.value.id
                    self.issues.append(
                        f"Security Violation: Aliasing dangerous function "
                        f"'{node.value.id}' to '{target.id}' is forbidden."
                    )
        self.generic_visit(node)

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

            # Granular check for restricted modules
            if base_module in self.RESTRICTED_MODULES:
                restricted_members = self.RESTRICTED_MODULES[base_module]
                for alias in node.names:
                    if alias.name == "*":
                        self.issues.append(
                            f"Security Violation: Wildcard import from restricted "
                            f"module '{node.module}' is forbidden."
                        )
                    elif alias.name in restricted_members:
                        self.issues.append(
                            f"High-risk member import detected: "
                            f"{node.module}.{alias.name}"
                        )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.DANGEROUS_ATTRIBUTES:
            self.issues.append(f"Reflection attack vector detected: {node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for direct calls to dangerous functions or their aliases
        if isinstance(node.func, ast.Name):
            func_id = node.func.id
            actual_func = self.aliases.get(func_id, func_id)
            if actual_func in self.DANGEROUS_FUNCTIONS:
                self.issues.append(f"High-risk function call detected: {func_id}")

            # Check for sensitive path access in open()
            if func_id == "open":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        val = arg.value.lower()
                        if "/etc/" in val or "~/.ssh" in val or ".." in val:
                            self.issues.append(
                                f"Security Violation: Access to sensitive path "
                                f"'{arg.value}' in open() is forbidden."
                            )

        # Check for attribute calls like os.system() or getattr(os, "system")
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module_id = node.func.value.id
                if module_id in self.DANGEROUS_MODULES:
                    self.issues.append(
                        f"High-risk method call: {module_id}.{attr_name}"
                    )

                # Granular check for restricted modules
                if module_id in self.RESTRICTED_MODULES:
                    if attr_name in self.RESTRICTED_MODULES[module_id]:
                        self.issues.append(
                            f"Security Violation: {module_id}.{attr_name} is forbidden."
                        )

        # Special handling for getattr/setattr to prevent dynamic bypass
        if isinstance(node.func, ast.Name) and node.func.id in ("getattr", "setattr"):
            if len(node.args) >= 2:
                attr_arg = node.args[1]
                # If the attribute name is not a literal string, it's a bypass risk
                if not isinstance(attr_arg, ast.Constant):
                    self.issues.append(
                        f"Security Violation: Dynamic attribute access in "
                        f"{node.func.id}() is forbidden."
                    )
                else:
                    attr_val = attr_arg.value
                    if (
                        attr_val in self.DANGEROUS_FUNCTIONS
                        or attr_val in self.DANGEROUS_ATTRIBUTES
                    ):
                        self.issues.append(
                            f"Security Violation: Accessing {attr_val!r} via "
                            f"{node.func.id}() is forbidden."
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
