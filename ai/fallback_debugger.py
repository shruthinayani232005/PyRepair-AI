"""Rule-based debugger used when no API key is set (or the AI fails).
Each handler makes a minimal edit to the failing line and returns an explanation."""
import ast
import difflib
import re
import sys

TYPES = {"list": list, "str": str, "dict": dict, "int": int, "float": float, "tuple": tuple, "set": set}
ALIASES = {("list", "push"): "append", ("list", "add"): "append", ("list", "length"): "__len__",
           ("dict", "has_key"): "get", ("str", "push"): "join"}
BLOCK_START = re.compile(r"^\s*(def|class|if|elif|else|for|while|try|except|finally|with)\b")


def _indent(line):
    return line[:len(line) - len(line.lstrip())]


def _split_comment(line):
    i = line.find(" #")
    return (line[:i], line[i:]) if i != -1 else (line, "")


def _result(lines, rc, ex, strat, conf):
    return {"lines": lines, "root_cause": rc, "explanation": ex, "strategy": strat, "conf": conf}


def index_error(lines, i, msg, code):
    m = re.search(r"\b([A-Za-z_]\w*)\[\s*(-?\d+)\s*\]", lines[i])
    if m:
        lines[i] = lines[i][:m.start()] + f"{m.group(1)}[-1]" + lines[i][m.end():]
        return _result(lines, f"Index {m.group(2)} is outside the bounds of '{m.group(1)}'.",
                       "You asked for a position that does not exist in the list.",
                       "Use the last valid element ([-1]) instead of the out-of-range index.", 0.7)
    m = re.search(r"\b([A-Za-z_]\w*)\[\s*([A-Za-z_]\w*)\s*\]", lines[i])
    if m:
        new = f"{m.group(1)}[min({m.group(2)}, len({m.group(1)}) - 1)]"
        lines[i] = lines[i][:m.start()] + new + lines[i][m.end():]
        return _result(lines, f"Variable index '{m.group(2)}' can exceed the length of '{m.group(1)}'.",
                       "The index grew larger than the list.", "Clamp the index to the last valid position.", 0.55)
    return None


def zero_division(lines, i, msg, code):
    m = re.search(r"(//|/|%)\s*([A-Za-z_][\w.]*(?:\([^()]*\))?|\d+(?:\.\d+)?)", lines[i])
    if not m:
        return None
    den = m.group(2)
    new = "1" if re.fullmatch(r"0+(\.0+)?", den) else f"({den} or 1)"
    lines[i] = lines[i][:m.start(2)] + new + lines[i][m.end(2):]
    return _result(lines, f"The divisor '{den}' is zero.", "Dividing by zero is undefined in Python.",
                   "Replace a zero divisor with 1 so the division is safe.", 0.65)


def name_error(lines, i, msg, code):
    m = re.search(r"name '(\w+)' is not defined", msg)
    if not m:
        return None
    name = m.group(1)
    known = set()
    try:
        for n in ast.walk(ast.parse(code)):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                known.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                known.add(n.name)
            elif isinstance(n, ast.arg):
                known.add(n.arg)
    except SyntaxError:
        pass
    close = difflib.get_close_matches(name, known, 1, 0.7)
    if close:
        lines[i] = re.sub(rf"\b{name}\b", close[0], lines[i])
        return _result(lines, f"'{name}' looks like a typo of '{close[0]}'.", "The name was never defined.",
                       f"Rename '{name}' to '{close[0]}'.", 0.85)
    if name in getattr(sys, "stdlib_module_names", ()):
        lines.insert(0, f"import {name}")
        return _result(lines, f"Module '{name}' was used without importing it.", "Modules must be imported first.",
                       f"Add 'import {name}' at the top.", 0.8)
    lines.insert(i, f"{_indent(lines[i])}{name} = 0")
    return _result(lines, f"Variable '{name}' is used before it is defined.", "Python needs a value assigned first.",
                   f"Define '{name} = 0' before its first use.", 0.4)


def type_error(lines, i, msg, code):
    if not ("concatenate" in msg or ("unsupported operand type(s) for +" in msg and "str" in msg)):
        return None
    line = lines[i]
    body = line.strip()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    off = len(line) - len(line.lstrip())
    leaves = []

    def flat(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            flat(n.left), flat(n.right)
        else:
            leaves.append(n)
    chains = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)]
    if not chains:
        return None
    flat(max(chains, key=lambda n: n.end_col_offset - n.col_offset))
    is_str = lambda n: isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str)) \
        or (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "str")
    if any(is_str(n) for n in leaves):
        targets = [n for n in leaves if not is_str(n)]
    elif "concatenate" in msg:
        targets = leaves[-1:]
    else:
        targets = leaves[:1]
    for n in sorted(targets, key=lambda n: -n.col_offset):
        seg = body[n.col_offset:n.end_col_offset]
        body = body[:n.col_offset] + f"str({seg})" + body[n.end_col_offset:]
    lines[i] = line[:off] + body
    return _result(lines, "A string was combined with a non-string value using '+'.",
                   "Python cannot add text and numbers directly.", "Wrap the non-string operand in str().", 0.8)


def key_error(lines, i, msg, code):
    key = msg.strip("'\"")
    pat = re.compile(rf"([A-Za-z_][\w.]*)\[\s*(['\"]){re.escape(key)}\2\s*\](?!\s*(=[^=]|\+=|-=))")
    m = pat.search(lines[i])
    if not m:
        return None
    lines[i] = lines[i][:m.start()] + f"{m.group(1)}.get({m.group(2)}{key}{m.group(2)})" + lines[i][m.end():]
    return _result(lines, f"The key '{key}' does not exist in the dictionary.", "Square brackets raise KeyError for missing keys.",
                   "Use dict.get(), which returns None instead of failing.", 0.75)


def attribute_error(lines, i, msg, code):
    m = re.search(r"'(\w+)' object has no attribute '(\w+)'", msg)
    if not m or m.group(1) not in TYPES:
        return None
    tname, attr = m.groups()
    new = ALIASES.get((tname, attr))
    if not new:
        names = dir(TYPES[tname])
        close = difflib.get_close_matches(attr, names, 1, 0.6) or \
            [n for n in names if n.lower() == attr.lower()]
        new = close[0] if close else None
    if not new or new.startswith("__"):
        return None
    lines[i] = re.sub(rf"\.{attr}\b", f".{new}", lines[i])
    return _result(lines, f"A {tname} has no method '{attr}'.", f"'{attr}' is not a {tname} method; '{new}' is.",
                   f"Replace .{attr} with .{new}.", 0.8)


def syntax_error(lines, i, msg, code):
    line = lines[i]
    code_part, comment = _split_comment(line)
    m = re.search(r"'(.)' was never closed", msg)
    if m:
        close = {"(": ")", "[": "]", "{": "}"}[m.group(1)]
        lines[i] = code_part.rstrip() + close + comment
        return _result(lines, f"Bracket '{m.group(1)}' is never closed.", "Every opening bracket needs a match.",
                       f"Append '{close}' to the line.", 0.6)
    if "unterminated string" in msg:
        q = re.search(r"(['\"])[^'\"]*$", code_part)
        if q:
            lines[i] = code_part.rstrip() + q.group(1) + comment
            return _result(lines, "A string literal is missing its closing quote.", "Strings must end with the same quote.",
                           "Add the missing quote.", 0.7)
    if "Missing parentheses in call to 'print'" in msg:
        p = re.match(r"^(\s*)print\s+(.+)$", code_part)
        if p:
            lines[i] = f"{p.group(1)}print({p.group(2).strip()})" + comment
            return _result(lines, "Python 2 style print statement.", "Python 3 print is a function.",
                           "Wrap the arguments in parentheses.", 0.9)
    if "expected an indented block" in msg:
        prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
        lines.insert(i, _indent(prev) + "    pass")
        return _result(lines, "A block header has no indented body.", "Python requires at least one indented statement.",
                       "Insert a 'pass' statement.", 0.6)
    if "unexpected indent" in msg or "unindent does not match" in msg:
        prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
        lines[i] = _indent(prev) + ("    " if prev.rstrip().endswith(":") else "") + line.lstrip()
        return _result(lines, "Inconsistent indentation.", "Indentation must follow the block structure.",
                       "Align the line with the previous statement.", 0.6)
    if re.match(r"^\s*(if|elif|while)\b", code_part) and re.search(r"(?<![=!<>])=(?!=)", code_part):
        lines[i] = re.sub(r"(?<![=!<>])=(?!=)", "==", code_part, count=1) + comment
        return _result(lines, "Assignment '=' used where comparison '==' is needed.", "Conditions compare values with '=='.",
                       "Replace '=' by '=='.", 0.7)
    if BLOCK_START.match(code_part) and not code_part.rstrip().endswith(":"):
        lines[i] = code_part.rstrip() + ":" + comment
        return _result(lines, "A block header is missing its trailing colon.", "if/for/while/def/class lines must end with ':'.",
                       "Append ':' to the line.", 0.85)
    return None


HANDLERS = {"IndexError": index_error, "ZeroDivisionError": zero_division, "NameError": name_error,
            "UnboundLocalError": name_error, "TypeError": type_error, "KeyError": key_error,
            "AttributeError": attribute_error, "SyntaxError": syntax_error,
            "IndentationError": syntax_error, "TabError": syntax_error}


def diagnose(info):
    code, etype = info["code"], info["error_type"]
    ln = int(info.get("line_number") or 0)
    lines = code.split("\n")
    out = {"error_type": etype, "problem_line": "", "repaired_code": "", "confidence": 0.0,
           "root_cause": "No built-in rule matches this error.",
           "explanation": "The fallback debugger covers common errors only. Configure an AI API key for deeper repairs.",
           "repair_strategy": "Manual review required."}
    if not 1 <= ln <= len(lines) or etype not in HANDLERS:
        return out
    out["problem_line"] = lines[ln - 1].strip()
    try:
        fix = HANDLERS[etype](list(lines), ln - 1, info.get("error_message", ""), code)
    except Exception:
        fix = None
    if fix:
        out.update(root_cause=fix["root_cause"], explanation=fix["explanation"],
                   repair_strategy=fix["strategy"], confidence=fix["conf"],
                   repaired_code="\n".join(fix["lines"]))
    return out
