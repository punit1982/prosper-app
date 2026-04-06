"""
Onboarding Wizard — Guide new users through Prosper setup
==========================================================
5-step wizard: Welcome > Base Currency > Add Holdings > Quick Tour > Ready!
"""

import streamlit as st
import pandas as pd
from core.settings import load_user_settings, save_user_settings

# ── Session State Initialization ──────────────────────────────────────────────
if "onboarding_step" not in st.session_state:
    st.session_state.onboarding_step = 1

TOTAL_STEPS = 5


def _next_step():
    st.session_state.onboarding_step = min(st.session_state.onboarding_step + 1, TOTAL_STEPS)


def _prev_step():
    st.session_state.onboarding_step = max(st.session_state.onboarding_step - 1, 1)


# ── Progress Bar ──────────────────────────────────────────────────────────────
current_step = st.session_state.onboarding_step
st.progress(current_step / TOTAL_STEPS, text=f"Step {current_step} of {TOTAL_STEPS}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Welcome
# ══════════════════════════════════════════════════════════════════════════════
if current_step == 1:
    st.markdown(
        "<div style='text-align:center;margin-top:2rem'>"
        "<h1 style='font-size:3rem;margin-bottom:0;letter-spacing:-1px'>Prosper</h1>"
        "<p style='color:#888;font-size:1.2rem;margin-top:4px'>"
        "The AI-Native Investment Operating System</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)

    _pad_l, _center, _pad_r = st.columns([1, 2, 1])
    with _center:
        st.markdown(
            "<div style='padding:24px;border-radius:12px;border:1px solid #333'>"
            "<h3 style='margin-top:0'>What Prosper does for you</h3>"
            "<ul style='font-size:1.05rem;line-height:2'>"
            "<li><strong>Upload screenshots or PDFs</strong> from any broker to build your portfolio instantly</li>"
            "<li><strong>AI-powered analysis</strong> with the PROSPER framework — fair value, risk scoring, and conviction ratings</li>"
            "<li><strong>Real-time risk management</strong> with the FORTRESS engine for position sizing and portfolio protection</li>"
            "</ul>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

        if st.button("Get Started", type="primary", use_container_width=True):
            _next_step()
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Set Base Currency
# ══════════════════════════════════════════════════════════════════════════════
elif current_step == 2:
    st.markdown("## Set Your Base Currency")

    st.info(
        "All holdings will be converted to this currency for unified reporting. "
        "You can change this later in Settings."
    )

    _currencies = ["USD", "AED", "EUR", "GBP", "CHF", "SGD", "INR", "HKD"]

    # Load current setting as default
    _current_settings = load_user_settings()
    _current_base = _current_settings.get("base_currency", "USD")
    _default_idx = _currencies.index(_current_base) if _current_base in _currencies else 0

    selected_currency = st.selectbox(
        "Base Currency",
        _currencies,
        index=_default_idx,
        key="_onboarding_currency",
    )

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Back", use_container_width=True):
            _prev_step()
            st.rerun()
    with col_next:
        if st.button("Save & Continue", type="primary", use_container_width=True):
            save_user_settings({"base_currency": selected_currency})
            _next_step()
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Add Your Holdings
# ══════════════════════════════════════════════════════════════════════════════
elif current_step == 3:
    st.markdown("## Add Your Holdings")

    import_method = st.radio(
        "How would you like to add your portfolio?",
        [
            "Upload Screenshot/PDF",
            "Sync from Interactive Brokers (IBKR)",
            "Add Manually Later",
        ],
        key="_onboarding_import_method",
    )

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    # ── Option 1: Upload Screenshot/PDF ──────────────────────────────────────
    if import_method == "Upload Screenshot/PDF":
        uploaded_file = st.file_uploader(
            "Upload a brokerage screenshot or PDF",
            type=["png", "jpg", "jpeg", "pdf", "csv", "xlsx", "xls"],
            key="_onboarding_upload",
        )

        if uploaded_file is not None:
            ext = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""

            if st.button("Parse File", type="primary", use_container_width=True):
                with st.spinner("AI is reading your file..."):
                    try:
                        if ext in ("csv",):
                            df = pd.read_csv(uploaded_file)
                            # Basic CSV parsing — reuse column alias logic
                            from pages import _parse_tabular_for_onboarding
                        elif ext in ("xlsx", "xls"):
                            df = pd.read_excel(uploaded_file)
                        else:
                            # Image or PDF — use AI parser
                            from core.screenshot_parser import parse_brokerage_image

                            uploaded_file.seek(0)
                            if ext == "pdf":
                                media = "application/pdf"
                            else:
                                media = uploaded_file.type

                            result = parse_brokerage_image(uploaded_file.getvalue(), media)

                            if isinstance(result, str):
                                st.error(f"Could not parse file: {result}")
                            elif isinstance(result, list) and len(result) > 0:
                                from core.database import save_holdings

                                holdings_df = pd.DataFrame(result)
                                save_holdings(holdings_df)
                                st.success(
                                    f"Extracted and saved **{len(result)}** holdings! "
                                    f"You can review them in the Portfolio Dashboard."
                                )
                            else:
                                st.warning("No holdings found in the file. Try a clearer image or different file.")
                    except Exception as e:
                        st.error(f"Error parsing file: {e}")

    # ── Option 2: IBKR Sync ─────────────────────────────────────────────────
    elif import_method == "Sync from Interactive Brokers (IBKR)":
        st.markdown(
            "Connect to your Interactive Brokers account using Flex Query. "
            "You can find these values in IBKR Account Management under Reports > Flex Queries."
        )

        ibkr_token = st.text_input("Flex Query Token", type="password", key="_onboarding_ibkr_token")
        ibkr_query_id = st.text_input("Flex Query ID", key="_onboarding_ibkr_query_id")

        if ibkr_token and ibkr_query_id:
            st.info("You can complete the IBKR sync from the IBKR Sync page after setup.")

    # ── Option 3: Add Manually Later ─────────────────────────────────────────
    else:
        st.markdown(
            "<div style='padding:16px;border-radius:12px;border:1px solid #333;color:#888'>"
            "No worries! You can add holdings anytime from the <strong>Upload Portal</strong> "
            "or <strong>IBKR Sync</strong> page in the sidebar."
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Back", use_container_width=True, key="_onboarding_step3_back"):
            _prev_step()
            st.rerun()
    with col_next:
        if st.button("Continue", type="primary", use_container_width=True, key="_onboarding_step3_next"):
            _next_step()
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Quick Tour
# ══════════════════════════════════════════════════════════════════════════════
elif current_step == 4:
    st.markdown("## Quick Tour")
    st.markdown("Here are the key features you will use most:")

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

    row1_c1, row1_c2 = st.columns(2)
    row2_c1, row2_c2 = st.columns(2)

    with row1_c1:
        st.markdown(
            "<div style='padding:20px;border-radius:12px;border:1px solid #333;min-height:140px'>"
            "<div style='font-size:2rem'>&#127968;</div>"
            "<div style='font-weight:700;font-size:1.1rem;margin:8px 0'>Command Center</div>"
            "<div style='color:#888;font-size:0.9rem'>Your portfolio at a glance with AI briefing</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    with row1_c2:
        st.markdown(
            "<div style='padding:20px;border-radius:12px;border:1px solid #333;min-height:140px'>"
            "<div style='font-size:2rem'>&#128300;</div>"
            "<div style='font-weight:700;font-size:1.1rem;margin:8px 0'>Equity Deep Dive</div>"
            "<div style='color:#888;font-size:0.9rem'>14-section PROSPER analysis for any stock</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

    with row2_c1:
        st.markdown(
            "<div style='padding:20px;border-radius:12px;border:1px solid #333;min-height:140px'>"
            "<div style='font-size:2rem'>&#127984;</div>"
            "<div style='font-weight:700;font-size:1.1rem;margin:8px 0'>Risk & Strategy</div>"
            "<div style='color:#888;font-size:0.9rem'>FORTRESS risk engine with position guidance</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    with row2_c2:
        st.markdown(
            "<div style='padding:20px;border-radius:12px;border:1px solid #333;min-height:140px'>"
            "<div style='font-size:2rem'>&#128172;</div>"
            "<div style='font-weight:700;font-size:1.1rem;margin:8px 0'>Ask Prosper</div>"
            "<div style='color:#888;font-size:0.9rem'>Chat with AI about your portfolio</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("Back", use_container_width=True, key="_onboarding_step4_back"):
            _prev_step()
            st.rerun()
    with col_next:
        if st.button("Continue", type="primary", use_container_width=True, key="_onboarding_step4_next"):
            _next_step()
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: You're Ready!
# ══════════════════════════════════════════════════════════════════════════════
elif current_step == 5:
    st.markdown(
        "<div style='text-align:center;margin-top:3rem'>"
        "<h1 style='font-size:2.5rem;margin-bottom:0'>You're All Set!</h1>"
        "<p style='color:#888;font-size:1.1rem;margin-top:8px'>"
        "Prosper is ready to help you manage your investments like a CIO.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    _pad_l, _center, _pad_r = st.columns([1, 2, 1])
    with _center:
        st.markdown(
            "<div style='padding:20px;border-radius:12px;border:1px solid #333;text-align:center'>"
            "<p style='font-size:1.05rem;margin:0'>Your base currency is set, and you can start exploring "
            "your dashboard right away. Upload holdings at any time from the sidebar.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)

        if st.button("Go to Command Center", type="primary", use_container_width=True):
            st.session_state["onboarding_complete"] = True
            # Persist to user preferences so it survives session restarts
            save_user_settings({"onboarding_complete": True})
            # Reset wizard step for clean state
            st.session_state.onboarding_step = 1
            st.switch_page("00_Command_Center")

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

        col_back_final, _ = st.columns([1, 1])
        with col_back_final:
            if st.button("Back", use_container_width=True, key="_onboarding_step5_back"):
                _prev_step()
                st.rerun()
