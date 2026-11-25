"""PyRepair AI - Streamlit front end."""
import html
from pathlib import Path

import streamlit as st

from ai.ai_debugger import load_default_settings, resolve_provider
from core.agent_state import STAGES
from core.executor import run_code
from core.repair_agent import run_agent
from database import db
from utils.diff import html_diff

try:
    from streamlit_ace import st_ace
    HAS_ACE = True
except ImportError:
    HAS_ACE = False

st.set_page_config(page_title="PyRepair AI", page_icon="🛠️", layout="wide")
EXAMPLES_DIR = Path(__file__).parent / "examples"
EXAMPLES = {"IndexError": "index_error.py", "TypeError": "type_error.py", "NameError": "name_error.py",
            "ZeroDivisionError": "zero_division.py", "KeyError": "key_error.py",
            "AttributeError": "attribute_error.py", "SyntaxError": "syntax_error.py"}
THEMES = {"Midnight": ("#0b0f19", "#111827", "#6366f1"), "Slate": ("#14181f", "#1d232d", "#14b8a6")}
BADGE = {"Pending": ("○", "#6b7280"), "Running": ("◐", "#3b82f6"), "Completed": ("●", "#22c55e"),
         "Failed": ("●", "#ef4444"), "Skipped": ("○", "#4b5563")}

# ---------------- state ----------------
ss = st.session_state
ss.setdefault("page", "home")
ss.setdefault("code", "")
ss.setdefault("result", None)
ss.setdefault("ver", 0)
ss.setdefault("settings", load_default_settings())
ss.setdefault("rerun_out", None)
try:
    db.init_db()
except Exception as e:
    st.sidebar.error(f"Database unavailable: {e}")


def css():
    bg, card, accent = THEMES[ss.settings["theme"]]
    st.markdown(f"""<style>
    .stApp {{ background:{bg}; }}
    .hero h1 {{ font-size:2.4rem; margin:0; background:linear-gradient(90deg,{accent},#22d3ee);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
    .hero p {{ color:#9ca3af; margin:.2rem 0; }}
    .card {{ background:{card}; border:1px solid #1f2937; border-radius:14px; padding:14px 16px; }}
    .card .l {{ color:#9ca3af; font-size:.75rem; text-transform:uppercase; letter-spacing:.06em; }}
    .card .v {{ font-size:1.25rem; font-weight:600; margin-top:4px; }}
    .chip {{ display:inline-block; background:{card}; border:1px solid #1f2937; border-radius:999px;
        padding:5px 12px; margin:3px 4px 3px 0; font-size:.82rem; }}
    table.diff {{ width:100%; border-collapse:collapse; font-family:monospace; font-size:.85rem; background:{card}; }}
    table.diff td, table.diff th {{ padding:2px 8px; white-space:pre-wrap; vertical-align:top; }}
    table.diff th {{ color:#9ca3af; text-align:left; border-bottom:1px solid #1f2937; }}
    td.ln {{ color:#6b7280; width:36px; text-align:right; }}
    td.del {{ background:rgba(239,68,68,.22); }} td.add {{ background:rgba(34,197,94,.22); }}
    td.mod {{ background:rgba(234,179,8,.22); }} td.empty {{ background:#0000001a; }}
    .tl {{ border-left:2px solid #1f2937; margin-left:6px; padding-left:14px; }}
    .tl div {{ margin:7px 0; font-family:monospace; font-size:.85rem; }}
    .tl .t {{ color:#6b7280; margin-right:10px; }} .tl .error {{ color:#f87171; }} .tl .warning {{ color:#fbbf24; }}
    section[data-testid="stSidebar"] {{ background:{card}; }}
    </style>""", unsafe_allow_html=True)


def card(label, value):
    return f'<div class="card"><div class="l">{label}</div><div class="v">{html.escape(str(value))}</div></div>'


def stage_html(stages):
    return "".join(f'<span class="chip"><span style="color:{BADGE[stages[s]][1]}">{BADGE[stages[s]][0]}</span> '
                   f'{s} <span style="color:#6b7280">· {stages[s]}</span></span>' for s in STAGES)


def go(page):
    ss.page = page


def new_session():
    ss.update(page="home", code="", result=None, rerun_out=None, ver=ss.ver + 1)


def load_code(text):
    ss.update(code=text, result=None, ver=ss.ver + 1)


def context(code, ln, radius=3):
    lines = code.splitlines()
    if not ln:
        return ""
    return "\n".join(f"{'>>' if i == ln else '  '} {i:>3} | {lines[i - 1]}"
                     for i in range(max(1, ln - radius), min(len(lines), ln + radius) + 1))


# ---------------- sidebar ----------------
css()
with st.sidebar:
    st.markdown("## 🛠️ PyRepair AI")
    st.caption("Detect. Diagnose. Repair. Verify.")
    st.button("➕ New Debug Session", on_click=new_session, use_container_width=True)
    st.button("🕘 Debug History", on_click=go, args=("history",), use_container_width=True)
    st.button("⚙️ Settings", on_click=go, args=("settings",), use_container_width=True)
    st.button("ℹ️ About", on_click=go, args=("about",), use_container_width=True)
    prov = resolve_provider(ss.settings)
    st.divider()
    st.caption(f"Engine: **{'Fallback rules' if prov == 'fallback' else prov.capitalize()}**")


# ---------------- result rendering ----------------
def render_output(res, title="Execution"):
    c1, c2, c3 = st.columns(3)
    c1.markdown(card("Status", "Success" if res["success"] else "Failed"), unsafe_allow_html=True)
    c2.markdown(card("Exit code", res["returncode"]), unsafe_allow_html=True)
    c3.markdown(card("Time", f'{res["duration"]}s'), unsafe_allow_html=True)
    st.markdown("**stdout**")
    st.code(res["stdout"] or "(empty)", language="text")
    st.markdown("**stderr**")
    st.code(res["stderr"] or "(empty)", language="text")


def render_results(res):
    labels = {"success": "✅ Repair Successful", "already_working": "✅ Code executed successfully",
              "failed": "❌ Repair Failed"}
    first, final = res["original_result"], res["final_result"]
    if res["status"] == "success":
        st.success("Repair Successful - the repaired code runs without errors.")
    elif res["status"] == "already_working":
        st.success("Code executed successfully - no repair needed.")
    else:
        st.error(f"Autonomous repair could not resolve the issue after {len(res['attempts'])} attempt(s). "
                 "See the debugging history in the tabs below.")
    tabs = st.tabs(["Overview", "Error Analysis", "AI Diagnosis", "Repaired Code", "Diff",
                    "Execution Output", "Agent Logs"])
    with tabs[0]:
        cols = st.columns(5)
        conf = f'{res["confidence"]:.0%}' if res["confidence"] is not None else "n/a"
        for col, (l, v) in zip(cols, [("Status", labels[res["status"]].split(" ", 1)[1]),
                                      ("Error Type", res["error_type"]), ("Attempts", len(res["attempts"])),
                                      ("Execution Time", f'{final["duration"]}s'), ("Repair Confidence", conf)]):
            col.markdown(card(l, v), unsafe_allow_html=True)
        st.markdown("##### Static analysis")
        st.code(res["analysis"]["summary"], language="text")
        if res["confidence"] is not None:
            st.caption("Confidence is a heuristic estimate - not a guarantee of correctness.")
    with tabs[1]:
        if first["success"]:
            st.info("The original code ran without errors.")
        else:
            st.markdown(f'**Exception:** `{first["error_type"]}`  \n**Message:** {first["error_message"]}  \n'
                        f'**Line:** {first["line_number"]}')
            st.markdown("**Problematic code section**")
            st.code(context(res["original_code"], first["line_number"]), language="python")
            st.markdown("**Traceback**")
            st.code(first["traceback"], language="text")
    with tabs[2]:
        if not res["attempts"]:
            st.info("No diagnosis needed.")
        for a in res["attempts"]:
            d = a["diagnosis"]
            ok = "✅" if a["verified"] else "❌"
            with st.expander(f'{ok} Attempt {a["attempt"]} - {d["error_type"]} ({d["source"]})', expanded=True):
                st.markdown(f'**Root cause:** {d["root_cause"]}  \n**Problem line:** `{d["problem_line"]}`  \n'
                            f'**Repair strategy:** {d["repair_strategy"]}  \n**Explanation:** {d["explanation"]}  \n'
                            f'**Model confidence:** {float(d["confidence"]):.0%}')
                if a["result"] and not a["result"]["success"]:
                    st.code(a["result"]["stderr"], language="text")
    with tabs[3]:
        if res["final_code"].strip() == res["original_code"].strip():
            st.info("No repaired code available (the original code was unchanged).")
        st.code(res["final_code"], language="python")  # has a built-in copy icon
        st.caption("Use the copy icon at the top-right of the code block.")
        b1, b2 = st.columns(2)
        b1.download_button("⬇️ Download .py", res["final_code"], "repaired.py", use_container_width=True)
        if b2.button("▶️ Run Again", use_container_width=True):
            ss.rerun_out = run_code(res["final_code"], int(ss.settings["timeout"]))
        if ss.rerun_out:
            render_output(ss.rerun_out)
    with tabs[4]:
        table, stats = html_diff(res["original_code"], res["final_code"])
        st.caption(f'🟥 removed {stats["removed"]} · 🟩 added {stats["added"]} · 🟨 modified {stats["modified"]}')
        st.markdown(table, unsafe_allow_html=True)
    with tabs[5]:
        render_output(final)
        if not first["success"]:
            with st.expander("Original run output"):
                render_output(first)
    with tabs[6]:
        st.markdown('<div class="tl">' + "".join(
            f'<div class="{e["level"]}"><span class="t">{e["time"]}</span>{html.escape(e["message"])}</div>'
            for e in res["logs"]) + "</div>", unsafe_allow_html=True)


# ---------------- pages ----------------
def page_home():
    st.markdown('<div class="hero"><h1>PyRepair AI</h1><p>Autonomous Python Debugging &amp; Repair Agent</p>'
                '<p><b>Detect. Diagnose. Repair. Verify.</b> · <i>Your AI debugging engineer</i></p></div>',
                unsafe_allow_html=True)
    st.write("")
    c1, c2, c3, c4 = st.columns([3, 2, 1.2, 1])
    up = c1.file_uploader("Upload .py file", type=["py"], label_visibility="collapsed")
    if up is not None and ss.get("last_upload") != (up.name, up.size):
        try:
            ss.last_upload = (up.name, up.size)
            load_code(up.getvalue().decode("utf-8"))
            st.rerun()
        except UnicodeDecodeError:
            st.error("Upload failed: the file is not valid UTF-8 text.")
    ex = c2.selectbox("Example", list(EXAMPLES), label_visibility="collapsed")
    if c3.button("📄 Example code", use_container_width=True):
        try:
            load_code((EXAMPLES_DIR / EXAMPLES[ex]).read_text(encoding="utf-8"))
            st.rerun()
        except OSError as e:
            st.error(f"Could not load example: {e}")
    if c4.button("🗑️ Clear", use_container_width=True):
        load_code("")
        st.rerun()

    if HAS_ACE:
        code = st_ace(value=ss.code, language="python", theme="tomorrow_night", height=320,
                      font_size=14, auto_update=True, key=f"ace_{ss.ver}") or ""
    else:
        code = st.text_area("Python code", ss.code, height=320, key=f"ta_{ss.ver}")
    ss.code = code

    if st.button("🚀 Analyze & Repair", type="primary", use_container_width=True):
        if not code.strip():
            st.error("Please enter or upload some Python code first.")
        else:
            ss.rerun_out = None
            slot = st.empty()
            slot.markdown(stage_html({s: "Pending" for s in STAGES}), unsafe_allow_html=True)
            try:
                with st.spinner("Agent is working..."):
                    res = run_agent(code, ss.settings, lambda s: slot.markdown(stage_html(s.stages), unsafe_allow_html=True))
                ss.result = res
                try:
                    db.save_session(res)
                except Exception as e:
                    st.warning(f"Session could not be saved to history: {e}")
            except Exception as e:
                st.error(f"The agent hit an unexpected problem: {e}")
    elif ss.result:
        st.markdown(stage_html(ss.result["stages"]), unsafe_allow_html=True)

    if ss.result:
        render_results(ss.result)
        return
    st.divider()
    a, b, c = st.columns(3)
    with a:
        st.markdown("#### Recent Sessions")
        try:
            rows = db.list_sessions(5)
        except Exception:
            rows = []
        if not rows:
            st.caption("No sessions yet.")
        for r in rows:
            st.button(f'#{r["id"]} {r["status"]} · {(r["error"] or "no error")[:28]}', key=f'rec{r["id"]}',
                      on_click=open_session, args=(r["id"],), use_container_width=True)
    with b:
        st.markdown("#### Common Errors")
        st.markdown("- **IndexError** – list position doesn't exist\n- **TypeError** – wrong type in an operation\n"
                    "- **NameError** – undefined variable\n- **KeyError** – missing dictionary key\n"
                    "- **ZeroDivisionError**, **AttributeError**, **SyntaxError**")
    with c:
        st.markdown("#### How PyRepair Works")
        st.markdown("1. Static analysis (AST)\n2. Safe execution in a subprocess\n3. Error detection\n"
                    "4. AI / rule-based diagnosis\n5. Minimal repair, re-run (max 3×)\n6. Verification")


def open_session(sid):
    try:
        res = db.get_session(sid)
    except Exception:
        res = None
    if res:
        ss.update(result=res, code=res["original_code"], ver=ss.ver + 1, page="home", rerun_out=None)


def page_history():
    st.header("Debug History")
    try:
        rows = db.list_sessions(50)
    except Exception as e:
        st.error(f"Could not read history: {e}")
        return
    if not rows:
        st.info("No debugging sessions saved yet.")
    for r in rows:
        c1, c2 = st.columns([5, 1])
        c1.markdown(f'**#{r["id"]}** · {r["created_at"]} · `{r["status"]}` · {r["attempts"]} attempt(s)  \n'
                    f'{r["error"] or "No error"}')
        c2.button("Open", key=f'open{r["id"]}', on_click=open_session, args=(r["id"],))


def page_settings():
    st.header("Settings")
    s = ss.settings
    with st.form("settings"):
        s_prov = st.selectbox("AI provider", ["auto", "anthropic", "openai", "fallback"],
                              index=["auto", "anthropic", "openai", "fallback"].index(s["provider"]))
        a_key = st.text_input("Anthropic API key", s["anthropic_key"], type="password")
        o_key = st.text_input("OpenAI-compatible API key", s["openai_key"], type="password")
        base = st.text_input("OpenAI-compatible base URL", s["base_url"])
        model = st.text_input("Model (blank = provider default)", s["model"])
        attempts = st.slider("Maximum repair attempts", 1, 3, int(s["max_attempts"]))
        timeout = st.slider("Execution timeout (seconds)", 2, 30, int(s["timeout"]))
        theme = st.selectbox("Theme", list(THEMES), index=list(THEMES).index(s["theme"]))
        if st.form_submit_button("Save settings"):
            ss.settings = {"provider": s_prov, "anthropic_key": a_key, "openai_key": o_key, "base_url": base,
                           "model": model, "max_attempts": attempts, "timeout": timeout, "theme": theme}
            st.rerun()
    st.caption("Keys entered here live only in this browser session. Use .env for persistent config.")
    if st.button("Clear debug history"):
        try:
            db.clear_history()
            st.success("History cleared.")
        except Exception as e:
            st.error(f"Could not clear history: {e}")


def page_about():
    st.header("About PyRepair AI")
    st.markdown("""An AIML mini-project that demonstrates an **autonomous debugging agent**:

- **AI agents** – a loop that observes, decides and acts without human help
- **Autonomous debugging** – finds and fixes runtime and syntax errors
- **Code analysis** – Python AST static checks
- **Tool use** – the agent calls an executor, analyzer, differ and database
- **Iterative reasoning & reflection** – each failed repair feeds a new traceback into the next attempt
- **Verification** – a repair counts only if the code really runs

⚠️ Code runs in a subprocess with limits, but this is **not** a complete sandbox. Use Docker for untrusted code.""")


{"home": page_home, "history": page_history, "settings": page_settings, "about": page_about}[ss.page]()
