"""
GhostDebugger — Streamlit Frontend

Live multi-agent debugging UI showing:
- Agent pipeline progress in real time
- Routing decision + model selected
- Root cause analysis
- Verified fix with diff view
- Senior-dev post-mortem explanation
- Live token savings counter
"""

from __future__ import annotations

import os
import time

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GhostDebugger",
    page_icon="👻",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');

  .main { background: #07080f; }
  code, pre, .stCode { font-family: 'JetBrains Mono', monospace !important; }

  .agent-card {
    background: #0d0f1c;
    border: 1px solid #1e2240;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }
  .agent-card.active { border-color: #818cf8; }
  .agent-card.done   { border-color: #22c55e; }
  .agent-card.error  { border-color: #ef4444; }

  .token-counter {
    background: linear-gradient(135deg, #818cf8, #6366f1);
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    color: white;
    font-family: 'JetBrains Mono', monospace;
  }
  .token-big { font-size: 2.5rem; font-weight: 800; line-height: 1; }
  .token-label { font-size: 0.75rem; opacity: 0.8; letter-spacing: 2px; margin-top: 4px; }

  .severity-LOW      { color: #22c55e; }
  .severity-MEDIUM   { color: #f97316; }
  .severity-HIGH     { color: #ef4444; }
  .severity-CRITICAL { color: #dc2626; font-weight: 800; }

  .verified-badge {
    background: #22c55e22;
    border: 1px solid #22c55e;
    color: #22c55e;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
  }
  .unverified-badge {
    background: #f9731622;
    border: 1px solid #f97316;
    color: #f97316;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
  }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 👻 GhostDebugger")
    st.markdown("*Token-efficient multi-agent debugging*")
    st.divider()

    st.markdown("### Agent Pipeline")
    agents = [
        ("🧭", "Complexity Router",  "Routes to optimal model"),
        ("🔬", "Reproducer",         "Runs code, captures error"),
        ("🔍", "Tracer",             "Finds root cause"),
        ("🔧", "Fixer",              "Generates verified patch"),
        ("📋", "Reviewer (Gemma 4)", "Senior-dev post-mortem"),
    ]
    for icon, name, desc in agents:
        st.markdown(f"**{icon} {name}**  \n_{desc}_")

    st.divider()
    st.markdown("### Models")
    st.markdown("🔵 **Router**: Qwen3-8B")
    st.markdown("🟡 **Mid tier**: Llama-3.1-8B")
    st.markdown("🔴 **Heavy tier**: Llama-3.1-70B")
    st.markdown("🟣 **Reviewer**: Gemma 4 31B")

    st.divider()
    # Health check
    try:
        health = requests.get(f"{API_URL}/health", timeout=3).json()
        st.success(f"API online ✓  `v{health.get('version', '?')}`")
    except Exception:
        st.error("API offline — start the backend")

    # Metrics
    try:
        m = requests.get(f"{API_URL}/metrics", timeout=3).json()
        st.divider()
        st.markdown("### Session Stats")
        col1, col2 = st.columns(2)
        col1.metric("Requests", m.get("total_requests", 0))
        col2.metric("Success %", f"{m.get('success_rate_pct', 0)}%")
        col1.metric("Tokens Used", f"{m.get('total_tokens_used', 0):,}")
        col2.metric("Avg Saved", f"{m.get('avg_savings_pct', 0)}%")
    except Exception:
        pass

# ── Main UI ───────────────────────────────────────────────────────────────
st.markdown("# 👻 GhostDebugger")
st.markdown("*Paste broken code. Watch 5 agents debug it live. Get a verified fix.*")
st.divider()

col_input, col_output = st.columns([1, 1], gap="large")

with col_input:
    st.markdown("### 📝 Paste Your Broken Code")

    code_input = st.text_area(
        "Code",
        height=300,
        placeholder="# Paste your buggy Python code here...\n\ndef calculate_average(nums):\n    return sum(nums) / len(nums)\n\nresult = calculate_average([])\nprint(result)",
        label_visibility="collapsed",
    )

    error_hint = st.text_input(
        "Error message (optional — paste what you see in terminal)",
        placeholder="ZeroDivisionError: division by zero",
    )

    debug_btn = st.button(
        "🔍 DEBUG IT",
        type="primary",
        use_container_width=True,
        disabled=not code_input.strip(),
    )

    if code_input.strip():
        with st.expander("Preview code", expanded=False):
            st.code(code_input, language="python")

with col_output:
    st.markdown("### 🧠 Agent Pipeline")

    if debug_btn and code_input.strip():
        # ── Live agent status display ─────────────────────────────────────
        status_slots = []
        agent_names = [
            ("🧭", "Complexity Router",   "Analysing bug complexity..."),
            ("🔬", "Reproducer",          "Running code in sandbox..."),
            ("🔍", "Tracer",              "Tracing root cause..."),
            ("🔧", "Fixer",               "Generating verified patch..."),
            ("📋", "Reviewer (Gemma 4)", "Writing post-mortem..."),
        ]

        for icon, name, msg in agent_names:
            slot = st.empty()
            slot.markdown(f"""
            <div class="agent-card">
              <b>{icon} {name}</b><br>
              <small style="color:#4a5070">Waiting...</small>
            </div>
            """, unsafe_allow_html=True)
            status_slots.append((slot, icon, name))

        token_slot = st.empty()

        # ── Call API ──────────────────────────────────────────────────────
        def update_agent(idx: int, state: str, detail: str = ""):
            slot, icon, name = status_slots[idx]
            css_class = {"running": "active", "done": "done", "error": "error"}.get(state, "")
            indicator = {"running": "⏳", "done": "✅", "error": "❌"}.get(state, "⏸️")
            slot.markdown(f"""
            <div class="agent-card {css_class}">
              <b>{icon} {name}</b> {indicator}<br>
              <small style="color:#6b738f">{detail}</small>
            </div>
            """, unsafe_allow_html=True)

        # Animate agents as running
        for i in range(5):
            update_agent(i, "running", agent_names[i][2])
            time.sleep(0.15)

        with st.spinner(""):
            try:
                t0 = time.time()
                response = requests.post(
                    f"{API_URL}/debug",
                    json={"code": code_input, "error_hint": error_hint},
                    timeout=120,
                )
                elapsed = time.time() - t0

                if response.status_code != 200:
                    st.error(f"API error {response.status_code}: {response.text[:300]}")
                    st.stop()

                data = response.json()

            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to API. Is the backend running?")
                st.stop()
            except requests.exceptions.Timeout:
                st.error("Request timed out (>120s). Try a smaller code snippet.")
                st.stop()

        # Update agent statuses with results
        routing = data.get("routing", {})
        repro   = data.get("reproduction", {})
        cause   = data.get("root_cause", {})
        fix     = data.get("fix", {})
        review  = data.get("review", {})
        tokens  = data.get("token_efficiency", {})

        update_agent(0, "done",
            f"Tier: {routing.get('tier')} → {routing.get('model_used','').split('/')[-1]} | "
            f"{routing.get('bug_type')} | confidence: {routing.get('confidence', 0):.0%}")

        update_agent(1, "done",
            f"{'Error reproduced ✓' if repro.get('reproduced') else 'No runtime error'} — "
            f"{repro.get('error_type', 'OK')}")

        update_agent(2, "done",
            f"Root cause found | confidence: {cause.get('confidence', 0):.0%} | "
            f"lines: {cause.get('faulty_lines', [])}")

        update_agent(3, "done" if fix.get("verified") else "error",
            f"{'✓ Verified' if fix.get('verified') else '⚠ Best-effort'} | "
            f"{len(fix.get('changes_made', []))} change(s) | {fix.get('attempts', 1)} attempt(s)")

        update_agent(4, "done",
            f"Severity: {review.get('severity')} | "
            f"{len(review.get('prevention_tips', []))} prevention tips")

        # Token counter
        savings_pct = tokens.get("savings_pct", 0)
        actual_cost = tokens.get("actual_cost_usd", 0)
        token_slot.markdown(f"""
        <div class="token-counter">
          <div class="token-big">{savings_pct:.0f}%</div>
          <div class="token-label">TOKEN SAVINGS vs ALWAYS-HEAVY-MODEL</div>
          <div style="margin-top:8px;font-size:0.85rem">
            Used: {tokens.get('total_tokens', 0):,} tokens
            &nbsp;·&nbsp;
            Cost: ${actual_cost:.5f}
            &nbsp;·&nbsp;
            Saved: ${tokens.get('savings_usd', 0):.5f}
            &nbsp;·&nbsp;
            {elapsed:.1f}s
          </div>
        </div>
        """, unsafe_allow_html=True)

    elif not debug_btn:
        st.info("Paste your code on the left and hit **DEBUG IT**.")

# ── Results (full width) ──────────────────────────────────────────────────
if debug_btn and code_input.strip() and "data" in dir() and data:
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "🔍 Root Cause", "🔧 Fixed Code", "📋 Post-Mortem", "📊 Token Efficiency"
    ])

    with tab1:
        cause = data.get("root_cause", {})
        st.markdown("### Root Cause Analysis")
        st.markdown(cause.get("explanation", ""))

        if cause.get("faulty_lines"):
            st.markdown(f"**Faulty lines:** `{cause['faulty_lines']}`")

        if cause.get("faulty_snippet"):
            st.markdown("**Faulty code snippet:**")
            st.code(cause["faulty_snippet"], language="python")

        if cause.get("execution_path"):
            with st.expander("Execution path"):
                st.markdown(cause["execution_path"])

        if cause.get("variable_states"):
            with st.expander("Variable states at crash"):
                st.code(cause["variable_states"])

        repro = data.get("reproduction", {})
        if repro.get("traceback"):
            with st.expander("Raw traceback"):
                st.code(repro["traceback"], language="text")

    with tab2:
        fix = data.get("fix", {})
        badge = (
            '<span class="verified-badge">✓ VERIFIED</span>'
            if fix.get("verified")
            else '<span class="unverified-badge">⚠ BEST-EFFORT</span>'
        )
        st.markdown(f"### Fixed Code &nbsp; {badge}", unsafe_allow_html=True)

        if fix.get("changes_made"):
            st.markdown("**Changes made:**")
            for change in fix["changes_made"]:
                st.markdown(f"- {change}")

        st.code(fix.get("fixed_code", "No fix generated"), language="python")

        if fix.get("verification_output"):
            st.markdown("**Verification output:**")
            st.code(fix["verification_output"], language="text")

    with tab3:
        review = data.get("review", {})
        severity = review.get("severity", "MEDIUM")
        confidence = review.get("confidence", 0.0)
        conf_color = "#22c55e" if confidence >= 0.9 else "#f97316" if confidence >= 0.6 else "#ef4444"
        conf_label = (
            "High confidence" if confidence >= 0.9 else
            "Moderate confidence" if confidence >= 0.6 else
            "Low confidence — review recommended"
        )

        col_a, col_b = st.columns([1, 3])
        with col_a:
            st.markdown(f"""
            <div style="text-align:center;">
                <div style="font-size:2.2rem;font-weight:800;color:{conf_color};">
                    {confidence*100:.0f}%
                </div>
                <div style="font-size:0.75rem;color:{conf_color};">{conf_label}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b:
            st.markdown(
                f"### Post-Mortem &nbsp; "
                f'<span class="severity-{severity}">{severity}</span>',
                unsafe_allow_html=True,
            )
            if review.get("fix_risks"):
                st.caption("⚠️ " + " · ".join(review["fix_risks"]))

        st.markdown(review.get("explanation", ""))

        if review.get("prevention_tips"):
            st.markdown("### Prevention Tips")
            for tip in review["prevention_tips"]:
                st.markdown(f"✅ {tip}")

        if review.get("code_quality_notes"):
            st.markdown("### Code Quality Notes")
            for note in review["code_quality_notes"]:
                st.markdown(f"💡 {note}")

        regression = data.get("regression", {})
        if regression.get("generated"):
            st.divider()
            st.markdown("### 🧪 Regression Test")
            if regression.get("passed"):
                st.success("✅ Auto-generated regression test PASSES against this fix")
            else:
                st.warning("⚠️ Regression test did not pass — review manually")

            with st.expander("View regression test"):
                st.code(regression.get("test_code", ""), language="python")

            if st.button("🔄 Re-verify fix live", key="reverify_btn"):
                with st.spinner("Re-running regression test in sandbox..."):
                    try:
                        rv = requests.post(
                            f"{API_URL}/reverify",
                            json={
                                "fixed_code": fix.get("fixed_code", ""),
                                "test_code": regression.get("test_code", ""),
                            },
                            timeout=15,
                        ).json()
                        if rv.get("passed"):
                            st.success("✅ Re-verified — fix still holds")
                        else:
                            st.error("❌ Re-verification failed")
                        st.code(rv.get("output", ""))
                    except Exception as e:
                        st.error(f"Re-verify request failed: {e}")

    with tab4:
        tokens = data.get("token_efficiency", {})
        st.markdown("### Token Efficiency Breakdown")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tokens", f"{tokens.get('total_tokens', 0):,}")
        col2.metric("Actual Cost", f"${tokens.get('actual_cost_usd', 0):.5f}")
        col3.metric("Savings", f"${tokens.get('savings_usd', 0):.5f}")
        col4.metric("Savings %", f"{tokens.get('savings_pct', 0):.1f}%")

        routing = data.get("routing", {})
        st.markdown(f"""
        **Why {tokens.get('savings_pct', 0):.0f}% was saved:**
        The router classified this as **{routing.get('tier')}** complexity
        ({routing.get('bug_type')}) and routed to **{routing.get('model_used','').split('/')[-1]}**
        instead of the heavy 70B model.
        Routing cost: ~{data.get('routing', {}).get('confidence', 0):.0%} confidence decision.
        """)

        breakdown = tokens.get("breakdown", [])
        if breakdown:
            st.markdown("**Per-agent breakdown:**")
            for item in breakdown:
                model_short = item.get("model", "").split("/")[-1]
                st.markdown(
                    f"- `{model_short}`: {item.get('tokens', 0):,} tokens "
                    f"| ${item.get('cost_usd', 0):.6f} "
                    f"| saved ${item.get('savings_usd', 0):.6f}"
                )
