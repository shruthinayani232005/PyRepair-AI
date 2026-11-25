"""Side-by-side HTML diff built on difflib."""
import difflib
import html


def _row(ln, left, lcls, rn, right, rcls):
    esc = lambda t: html.escape(t) if t is not None else ""
    return (f'<tr><td class="ln">{ln or ""}</td><td class="{lcls}">{esc(left)}</td>'
            f'<td class="ln">{rn or ""}</td><td class="{rcls}">{esc(right)}</td></tr>')


def html_diff(old, new):
    a, b = old.splitlines(), new.splitlines()
    rows, stats = [], {"removed": 0, "added": 0, "modified": 0}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append(_row(i1 + k + 1, a[i1 + k], "same", j1 + k + 1, b[j1 + k], "same"))
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            l = a[i1 + k] if i1 + k < i2 else None
            r = b[j1 + k] if j1 + k < j2 else None
            if l is not None and r is not None:
                stats["modified"] += 1
                rows.append(_row(i1 + k + 1, l, "mod", j1 + k + 1, r, "mod"))
            elif l is not None:
                stats["removed"] += 1
                rows.append(_row(i1 + k + 1, l, "del", None, None, "empty"))
            else:
                stats["added"] += 1
                rows.append(_row(None, None, "empty", j1 + k + 1, r, "add"))
    table = ('<table class="diff"><tr><th></th><th>Original</th><th></th><th>Repaired</th></tr>'
             + "".join(rows) + "</table>")
    return table, stats


def unified(old, new):
    return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                          "original.py", "repaired.py", lineterm=""))
