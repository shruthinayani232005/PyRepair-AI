"""Static analysis with Python's ast module (no code is executed)."""
import ast
import builtins

SUSPICIOUS_IMPORTS = {"pickle", "marshal", "ctypes", "socket", "subprocess", "shutil",
                      "telnetlib", "ftplib", "urllib", "requests"}
DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_ATTRS = {"os.system", "os.remove", "os.rmdir", "os.unlink", "shutil.rmtree",
                   "subprocess.run", "subprocess.Popen", "subprocess.call"}


def _dotted(node):
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return node.id if isinstance(node, ast.Name) else None


def _is_str(n):
    return isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str))


def _is_num(n):
    return isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)


def analyze(code):
    issues = []
    add = lambda t, n, m, s="warning": issues.append(
        {"type": t, "line": getattr(n, "lineno", None), "message": m, "severity": s})
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        issues.append({"type": "syntax", "line": e.lineno, "message": e.msg, "severity": "error"})
        return {"syntax_ok": False, "issues": issues, "summary": _summary(False, issues)}

    defined = set(dir(builtins)) | {"__file__", "__name__"}
    stored, loaded, list_lens = {}, set(), {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, ast.Name):
            (defined.add(n.id), stored.setdefault(n.id, n)) if isinstance(n.ctx, ast.Store) else loaded.add(n.id)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined.update(n.names)
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.List) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            list_lens[n.targets[0].id] = len(n.value.elts)

    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined:
            add("undefined_variable", n, f"'{n.id}' is used but never defined", "error")
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for m in mods:
                if m.split(".")[0] in SUSPICIOUS_IMPORTS:
                    add("suspicious_import", n, f"Import of '{m}' may allow system/network access")
        elif isinstance(n, ast.Call):
            name = _dotted(n.func)
            if name in DANGEROUS_CALLS or name in DANGEROUS_ATTRS:
                add("dangerous_operation", n, f"Call to '{name}' is potentially dangerous")
        elif isinstance(n, ast.BinOp):
            if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and _is_num(n.right) and n.right.value == 0:
                add("zero_division", n, "Division by constant zero", "error")
            if isinstance(n.op, ast.Add) and ((_is_str(n.left) and _is_num(n.right)) or
                                              (_is_num(n.left) and _is_str(n.right))):
                add("type_problem", n, "Adding a string and a number", "error")
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in list_lens:
            idx = n.slice
            if _is_num(idx) and isinstance(idx.value, int) and not -list_lens[n.value.id] <= idx.value < list_lens[n.value.id]:
                add("index_out_of_range", n, f"Index {idx.value} is outside list '{n.value.id}' "
                    f"(length {list_lens[n.value.id]})", "error")
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(n, field, None)
            if isinstance(stmts, list):
                for prev, nxt in zip(stmts, stmts[1:]):
                    if isinstance(prev, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                        add("unreachable_code", nxt, "Code after return/raise/break/continue never runs")

    for name, node in stored.items():
        if name not in loaded and not name.startswith("_"):
            add("unused_variable", node, f"Variable '{name}' is assigned but never used", "info")
    issues.sort(key=lambda i: i["line"] or 0)
    return {"syntax_ok": True, "issues": issues, "summary": _summary(True, issues)}


def _summary(ok, issues):
    if not issues:
        return "Syntax OK. No static issues found."
    lines = [f"Line {i['line']}: [{i['type']}] {i['message']}" for i in issues]
    return ("Syntax OK. " if ok else "Syntax error. ") + f"{len(issues)} finding(s):\n" + "\n".join(lines)
