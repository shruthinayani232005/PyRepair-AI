"""Verification and confidence scoring."""
import ast


def verify(code, result):
    """A repair is verified only if it parses, exits cleanly and does not time out."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error remains: {e.msg}"
    if result["timed_out"]:
        return False, "Execution timed out"
    if result["returncode"] != 0:
        return False, f'{result["error_type"]}: {result["error_message"]}'
    return True, "Code ran successfully with exit code 0"


def confidence(diagnosis, success, attempts):
    """Heuristic score (never 100%): error identified, line identified, repair works, few attempts."""
    if not diagnosis:
        return 0.95 if success else 0.0
    got_type = bool(diagnosis.get("error_type"))
    got_line = bool(str(diagnosis.get("problem_line", "")).strip())
    if not success:
        return round(min(0.25, 0.1 * got_type + 0.1 * got_line), 2)
    score = 0.45 + 0.2 * got_type + 0.15 * got_line
    score += 0.15 * max(0.0, min(1.0, float(diagnosis.get("confidence", 0) or 0)))
    score -= 0.1 * (attempts - 1)
    return round(max(0.05, min(0.95, score)), 2)
