import os
import requests
import streamlit as st

# API base: prefer Streamlit secrets, then ENV, then localhost
API_BASE = st.secrets.get("api_base", os.environ.get("API_BASE", "http://localhost:8000"))


def health_check(timeout: int = 5):
    r = requests.get(f"{API_BASE}/health", timeout=timeout)
    r.raise_for_status()
    return r.json()


def run_debug(code: str, error_hint: str = "", timeout: int = 300):
    r = requests.post(
        f"{API_BASE}/debug",
        json={"code": code, "error_hint": error_hint},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def reverify(fixed_code: str, test_code: str, timeout: int = 60):
    r = requests.post(
        f"{API_BASE}/reverify",
        json={"fixed_code": fixed_code, "test_code": test_code},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


st.set_page_config(page_title="GhostDebugger — Streamlit Frontend")
st.title("GhostDebugger — Streamlit Frontend")

st.markdown(f"**Backend:** {API_BASE}")

if st.button("Health check"):
    try:
        st.json(health_check())
    except Exception as e:
        st.error(f"Health check failed: {e}")

with st.form("debug_form"):
    st.header("Debug code")
    code = st.text_area("Buggy Python code", height=300)
    error_hint = st.text_input("Error hint (optional)")
    submitted = st.form_submit_button("Run debug")
    if submitted:
        if not code.strip():
            st.error("Please paste some code to debug.")
        else:
            with st.spinner("Running debug pipeline... this can take a while"):
                try:
                    result = run_debug(code, error_hint)
                    st.success("Debug completed")
                    st.json(result)
                except Exception as e:
                    st.error(f"Request failed: {e}")
