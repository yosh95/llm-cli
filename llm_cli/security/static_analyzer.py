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

    # subprocess function names (used to detect bare calls like run(...) after
    # "from subprocess import run")
    SUBPROCESS_FUNC_NAMES = {"run", "Popen", "call", "check_call", "check_output"}

    def __init__(self) -> None:
        self.issues: list[str] = []
        self.found_modules: set[str] = set()

        # Tracks function-level aliases: alias_name -> canonical_function_name
        # e.g. "f = eval"  =>  {"f": "eval"}
        self.aliases: dict[str, str] = {}

        # Tracks module-level aliases: local_name -> canonical_module_name
        # e.g. "import subprocess as sp"  =>  {"sp": "subprocess"}
        # e.g. "import os as operating_system"  =>  {"operating_system": "os"}
        self.module_aliases: dict[str, str] = {}

        # Tracks imported function aliases from restricted/subprocess modules:
        # e.g. "from subprocess import run as r"  =>  {"r": "run"}
        # Used so bare calls like r([...]) are recognised as subprocess calls.
        self.func_aliases: dict[str, str] = {}

        # Load blocked paths from config to check against subprocess targets
        from llm_cli.clients.config import config_manager

        self.blocked_paths = config_manager.get("security", "blocked_paths") or []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_module(self, name: str) -> str:
        """Resolve a local variable name to its canonical module name."""
        return self.module_aliases.get(name, name)

    def _resolve_func(self, name: str) -> str:
        """Resolve a local function alias to its canonical function name."""
        # First check function-level aliases (f = eval), then func_aliases
        # (from subprocess import run as r).
        return self.aliases.get(name, self.func_aliases.get(name, name))

    # ------------------------------------------------------------------
    # subprocess detection helpers
    # ------------------------------------------------------------------

    def _is_subprocess_call(self, node: ast.Call) -> bool:
        """Return True if *node* is any form of subprocess invocation."""
        if isinstance(node.func, ast.Attribute):
            # sp.run(...) / subprocess.run(...)
            if isinstance(node.func.value, ast.Name):
                resolved = self._resolve_module(node.func.value.id)
                return resolved == "subprocess"
        elif isinstance(node.func, ast.Name):
            # Bare run(...) after "from subprocess import run [as r]"
            resolved_func = self._resolve_func(node.func.id)
            return resolved_func in self.SUBPROCESS_FUNC_NAMES
        return False

    def _check_subprocess_node(self, node: ast.Call) -> None:
        """
        Checks for shell=True and dangerous command combinations in subprocess calls.
        Now handles aliased module/function names.
        """
        if not self._is_subprocess_call(node):
            return

        cmd_args: list[str] = []

        # 1. Extract arguments (best effort for literal strings)
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

        # 2. Check for shell=True
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

        # 3. Smart Guardrail: Command + Path combination
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

    # ------------------------------------------------------------------
    # AST visitors
    # ------------------------------------------------------------------

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
        """
        Handle 'import X' and 'import X as Y'.
        Registers module aliases so that aliased usage (sp.run, etc.) is caught.
        """
        for alias in node.names:
            module_name = alias.name.split(".")[0]
            self.found_modules.add(module_name)

            # Register module alias: "import subprocess as sp" -> {"sp": "subprocess"}
            local_name = alias.asname if alias.asname else module_name
            if local_name != module_name:
                self.module_aliases[local_name] = module_name

            if module_name in self.DANGEROUS_MODULES:
                self.issues.append(f"High-risk module import detected: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """
        Handle 'from X import Y' and 'from X import Y as Z'.
        Registers function aliases from subprocess/restricted modules so that
        bare calls (r([...]) after 'from subprocess import run as r') are caught.
        """
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

            # Track subprocess function aliases:
            # "from subprocess import run as r" -> func_aliases["r"] = "run"
            if base_module == "subprocess":
                for alias in node.names:
                    canonical = alias.name
                    local = alias.asname if alias.asname else alias.name
                    if canonical in self.SUBPROCESS_FUNC_NAMES:
                        self.func_aliases[local] = canonical

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Dangerous reflection attributes
        if node.attr in self.DANGEROUS_ATTRIBUTES:
            self.issues.append(f"Reflection attack vector detected: {node.attr}")

        # Catch aliased dangerous module attribute access: sp.system(...) where sp=os
        if isinstance(node.func if isinstance(node, ast.Call) else node, ast.Attribute):
            pass  # handled in visit_Call

        # Standalone attribute read (not a call): e.g. "x = os.environ" via alias
        if isinstance(node.value, ast.Name):
            resolved = self._resolve_module(node.value.id)
            if resolved in self.DANGEROUS_MODULES and resolved != node.value.id:
                # Only flag if this attribute node is not part of a Call node
                # (visit_Call handles the call case to avoid double-reporting).
                # We cannot easily distinguish here, so we rely on visit_Call.
                pass

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # --- Direct calls: eval(...), exec(...), or their function-level aliases ---
        if isinstance(node.func, ast.Name):
            func_id = node.func.id
            actual_func = self._resolve_func(func_id)
            if actual_func in self.DANGEROUS_FUNCTIONS:
                self.issues.append(f"High-risk function call detected: {func_id}")

            # Sensitive path access in open()
            if func_id == "open":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        val = arg.value.lower()
                        if "/etc/" in val or "~/.ssh" in val or ".." in val:
                            self.issues.append(
                                f"Security Violation: Access to sensitive path "
                                f"'{arg.value}' in open() is forbidden."
                            )

        # --- Attribute calls: os.system(), sp.system(), operating_system.system() ---
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                raw_id = node.func.value.id
                # Resolve alias to canonical module name
                resolved_module = self._resolve_module(raw_id)

                if resolved_module in self.DANGEROUS_MODULES:
                    self.issues.append(f"High-risk method call: {raw_id}.{attr_name}")

                # Granular check for restricted modules (os, shutil)
                # Works for both "os.system()" and "o.system()" where o=os
                if resolved_module in self.RESTRICTED_MODULES:
                    if attr_name in self.RESTRICTED_MODULES[resolved_module]:
                        self.issues.append(
                            f"Security Violation: {raw_id}.{attr_name} is forbidden."
                        )

        # --- Special handling for getattr/setattr to prevent dynamic bypass ---
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

        # --- subprocess detection (handles aliases) ---
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
