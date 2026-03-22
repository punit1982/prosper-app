"""
User Management
===============
Admin users can create, edit, and delete users.
Regular users can edit their own profile (name, email, password)
and manage their portfolios.
"""

import os
import re
import tempfile

import streamlit as st

st.header("User Management")

# ── Check if auth is enabled ─────────────────────────────────────────────────
AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
if not AUTH_ENABLED:
    st.info("Authentication is disabled. Enable it by setting `PROSPER_AUTH_ENABLED=true` in your `.env` file.")
    st.stop()

# ── Load auth config ─────────────────────────────────────────────────────────
try:
    import yaml
    import bcrypt
    import streamlit_authenticator as stauth
except ImportError:
    st.error("Missing dependency: `streamlit-authenticator`. Run `pip install streamlit-authenticator`.")
    st.stop()

_AUTH_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auth_config.yaml")

if not os.path.exists(_AUTH_PATH):
    st.error("Auth config file not found. Please set up authentication first.")
    st.stop()


def _load_config():
    with open(_AUTH_PATH) as f:
        return yaml.safe_load(f)


def _save_config(config):
    """Atomically write auth_config.yaml using temp file + rename."""
    dir_path = os.path.dirname(_AUTH_PATH)
    with tempfile.NamedTemporaryFile("w", dir=dir_path, delete=False, suffix=".yaml") as tmp:
        yaml.dump(config, tmp, default_flow_style=False)
        tmp_path = tmp.name
    os.replace(tmp_path, _AUTH_PATH)


def _hash_password(plain: str) -> str:
    """Hash a password using streamlit-authenticator's Hasher (single string arg)."""
    return stauth.Hasher.hash(plain)


def _validate_password(pw: str) -> list[str]:
    """Return a list of validation error strings. Empty list means valid."""
    errors = []
    if len(pw) < 8:
        errors.append("At least 8 characters")
    if not re.search(r"[A-Z]", pw):
        errors.append("At least one uppercase letter")
    if not re.search(r"\d", pw):
        errors.append("At least one number")
    return errors


config = _load_config()
credentials = config.get("credentials", {}).get("usernames", {})

# ── Identify current user ────────────────────────────────────────────────────
current_user = st.session_state.get("username", None)
if not current_user:
    st.warning("Please log in to access User Management.")
    st.stop()

current_role = credentials.get(current_user, {}).get("role", "user")
is_admin = current_role == "admin"

st.caption(f"Logged in as **{current_user}** | Role: **{current_role.title()}**")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: My Profile (all authenticated users)
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("My Profile")

user_data = credentials.get(current_user, {})

col_info, col_meta = st.columns([2, 1])

with col_info:
    st.markdown(f"**Display name:** {user_data.get('first_name', '')} {user_data.get('last_name', '')}")
    st.markdown(f"**Email:** {user_data.get('email', 'Not set')}")
    st.markdown(f"**Username:** `{current_user}` (read-only)")
    st.markdown(f"**Role:** {current_role.title()} (read-only)")

with col_meta:
    member_since = user_data.get("created_at") or user_data.get("member_since")
    if member_since:
        st.markdown(f"**Member since:** {member_since}")
    else:
        st.markdown("**Member since:** N/A")

# ── Edit Profile Form ────────────────────────────────────────────────────────
with st.expander("Edit Profile", expanded=False):
    with st.form("edit_profile", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            new_first = st.text_input("First Name", value=user_data.get("first_name", ""))
        with col2:
            new_last = st.text_input("Last Name", value=user_data.get("last_name", ""))
        new_email = st.text_input("Email", value=user_data.get("email", ""))

        submitted = st.form_submit_button("Save Profile", use_container_width=True)
        if submitted:
            if not new_first.strip() or not new_last.strip():
                st.error("First name and last name are required.")
            elif not new_email.strip() or "@" not in new_email:
                st.error("Please enter a valid email address.")
            else:
                config = _load_config()
                config["credentials"]["usernames"][current_user]["first_name"] = new_first.strip()
                config["credentials"]["usernames"][current_user]["last_name"] = new_last.strip()
                config["credentials"]["usernames"][current_user]["email"] = new_email.strip()
                _save_config(config)
                st.session_state["name"] = f"{new_first.strip()} {new_last.strip()}"
                st.success("Profile updated successfully!")

# ── Change Password ──────────────────────────────────────────────────────────
with st.expander("Change Password"):
    st.markdown(
        """**Password requirements:**
- Minimum **8 characters**
- At least one **uppercase** letter (A-Z)
- At least one **number** (0-9)"""
    )

    with st.form("change_password", clear_on_submit=True):
        current_pw = st.text_input("Current Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        confirm_pw = st.text_input("Confirm New Password", type="password")

        pw_submitted = st.form_submit_button("Change Password", use_container_width=True)
        if pw_submitted:
            if not current_pw or not new_pw or not confirm_pw:
                st.error("All password fields are required.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            else:
                pw_errors = _validate_password(new_pw)
                if pw_errors:
                    st.error("Password does not meet requirements: " + "; ".join(pw_errors))
                else:
                    stored_hash = user_data.get("password", "")
                    if bcrypt.checkpw(current_pw.encode(), stored_hash.encode()):
                        new_hash = _hash_password(new_pw)
                        config = _load_config()
                        config["credentials"]["usernames"][current_user]["password"] = new_hash
                        _save_config(config)
                        st.success("Password changed successfully!")
                    else:
                        st.error("Current password is incorrect.")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: My Portfolios (all authenticated users)
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("My Portfolios")

try:
    from core.database import (
        init_db,
        get_all_portfolios,
        get_all_holdings,
        create_portfolio,
        rename_portfolio,
        delete_portfolio,
    )
    init_db()

    all_portfolios = get_all_portfolios()

    # Filter to current user's portfolios (user_id matches username or 'default')
    if not all_portfolios.empty and "user_id" in all_portfolios.columns:
        my_portfolios = all_portfolios[
            all_portfolios["user_id"].isin([current_user, "default"])
        ].copy()
    else:
        my_portfolios = all_portfolios.copy() if not all_portfolios.empty else None

    if my_portfolios is not None and not my_portfolios.empty:
        rows = []
        for _, p in my_portfolios.iterrows():
            pid = int(p["id"])
            pname = p.get("name", f"Portfolio {pid}")
            desc = p.get("description", "")
            created = p.get("created_at", "")
            # Get holdings count
            try:
                holdings = get_all_holdings(portfolio_id=pid)
                h_count = len(holdings) if not holdings.empty else 0
                total_val = None
                if h_count > 0 and "market_value" in holdings.columns:
                    total_val = holdings["market_value"].sum()
            except Exception:
                h_count = 0
                total_val = None

            row = {
                "ID": pid,
                "Name": pname,
                "Holdings": h_count,
            }
            if total_val is not None:
                row["Total Value"] = f"${total_val:,.2f}"
            rows.append(row)

        import pandas as pd
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("No portfolios found. Create one below.")

    # ── Create Portfolio ──
    with st.expander("Create New Portfolio"):
        with st.form("create_portfolio", clear_on_submit=True):
            pf_name = st.text_input("Portfolio Name", placeholder="e.g. Growth Stocks")
            pf_desc = st.text_input("Description (optional)", placeholder="e.g. Long-term growth holdings")
            pf_submit = st.form_submit_button("Create Portfolio", use_container_width=True)
            if pf_submit:
                if not pf_name.strip():
                    st.error("Portfolio name is required.")
                else:
                    try:
                        new_id = create_portfolio(pf_name.strip(), pf_desc.strip())
                        st.success(f"Portfolio **{pf_name.strip()}** created (ID: {new_id}).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to create portfolio: {e}")

    # ── Rename / Delete Portfolio ──
    if my_portfolios is not None and not my_portfolios.empty:
        with st.expander("Rename or Delete Portfolio"):
            pf_options = {int(r["id"]): r.get("name", f"Portfolio {r['id']}") for _, r in my_portfolios.iterrows()}
            pf_choice = st.selectbox(
                "Select portfolio",
                list(pf_options.keys()),
                format_func=lambda x: f"{pf_options[x]} (ID: {x})",
                key="pf_manage_select",
            )

            if pf_choice:
                rename_col, delete_col = st.columns(2)
                with rename_col:
                    with st.form("rename_portfolio", clear_on_submit=True):
                        rn_name = st.text_input("New Name", placeholder="Enter new name")
                        rn_submit = st.form_submit_button("Rename", use_container_width=True)
                        if rn_submit:
                            if not rn_name.strip():
                                st.error("Name cannot be empty.")
                            else:
                                rename_portfolio(pf_choice, rn_name.strip())
                                st.success(f"Renamed to **{rn_name.strip()}**.")
                                st.rerun()

                with delete_col:
                    if pf_choice == 1:
                        st.info("The default portfolio cannot be deleted.")
                    else:
                        st.warning(f"Delete **{pf_options[pf_choice]}**?")
                        confirm_key = f"confirm_del_pf_{pf_choice}"
                        confirmed = st.checkbox("I confirm deletion", key=confirm_key)
                        if st.button("Delete Portfolio", use_container_width=True, disabled=not confirmed):
                            delete_portfolio(pf_choice)
                            st.success(f"Portfolio deleted.")
                            st.rerun()

except ImportError:
    st.info("Portfolio management requires the database module. It will be available once the app is fully set up.")
except Exception as e:
    st.warning(f"Could not load portfolios: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Admin — User Administration (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
if not is_admin:
    st.divider()
    st.caption("Contact an administrator to manage other users or change roles.")
    st.stop()

st.divider()
st.subheader("Admin -- User Directory")

config = _load_config()
credentials = config.get("credentials", {}).get("usernames", {})

# ── Users Table ──────────────────────────────────────────────────────────────
import pandas as pd

user_rows = []
for uname, udata in credentials.items():
    row = {
        "Username": uname,
        "Name": f"{udata.get('first_name', '')} {udata.get('last_name', '')}".strip(),
        "Email": udata.get("email", ""),
        "Role": udata.get("role", "user").title(),
    }
    # Try to get portfolio count
    try:
        all_pf = get_all_portfolios()
        if not all_pf.empty and "user_id" in all_pf.columns:
            count = len(all_pf[all_pf["user_id"].isin([uname, "default"])])
        else:
            count = "-"
        row["Portfolios"] = count
    except Exception:
        row["Portfolios"] = "-"
    user_rows.append(row)

if user_rows:
    users_df = pd.DataFrame(user_rows)
    st.dataframe(users_df, hide_index=True, use_container_width=True)
    st.caption(f"Total users: **{len(user_rows)}**")

# ── Create New User ──────────────────────────────────────────────────────────
st.subheader("Create New User")

with st.form("create_user", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        new_username = st.text_input("Username", placeholder="e.g. john_doe")
        new_user_first = st.text_input("First Name", key="new_first")
        new_user_email = st.text_input("Email", key="new_email", placeholder="user@example.com")
    with c2:
        new_user_pw = st.text_input(
            "Initial Password",
            type="password",
            help="Min 8 chars, 1 uppercase letter, 1 number",
        )
        new_user_last = st.text_input("Last Name", key="new_last")
        new_user_role = st.selectbox("Role", ["user", "admin"], index=0)

    create_submitted = st.form_submit_button("Create User", use_container_width=True, type="primary")
    if create_submitted:
        errors = []
        if not new_username or not new_username.strip():
            errors.append("Username is required.")
        elif not new_username.strip().replace("_", "").isalnum():
            errors.append("Username must be alphanumeric (underscores allowed, no spaces).")
        if new_username and new_username.strip().lower() in {u.lower() for u in credentials}:
            errors.append(f"Username **{new_username}** already exists.")
        if not new_user_first.strip() or not new_user_last.strip():
            errors.append("First and Last name are required.")
        if not new_user_email.strip() or "@" not in new_user_email:
            errors.append("Valid email is required.")
        if new_user_pw:
            pw_errs = _validate_password(new_user_pw)
            if pw_errs:
                errors.append("Password: " + "; ".join(pw_errs))
        else:
            errors.append("Password is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            hashed_pw = _hash_password(new_user_pw)
            config = _load_config()
            config["credentials"]["usernames"][new_username.strip().lower()] = {
                "email": new_user_email.strip(),
                "first_name": new_user_first.strip(),
                "last_name": new_user_last.strip(),
                "password": hashed_pw,
                "role": new_user_role,
            }
            _save_config(config)
            st.success(f"User **{new_username.strip().lower()}** created successfully!")
            st.rerun()

# ── Edit / Delete Existing Users ─────────────────────────────────────────────
st.subheader("Edit / Remove Users")

other_users = [u for u in credentials if u != current_user]
if not other_users:
    st.info("No other users to manage. You are the only user in the system.")
else:
    selected_user = st.selectbox(
        "Select user to manage",
        other_users,
        format_func=lambda u: (
            f"{u} -- {credentials[u].get('first_name', '')} "
            f"{credentials[u].get('last_name', '')} "
            f"({credentials[u].get('role', 'user')})"
        ),
    )

    if selected_user:
        sel_data = credentials[selected_user]

        tab_edit, tab_reset, tab_delete = st.tabs(["Edit Details", "Reset Password", "Remove User"])

        with tab_edit:
            with st.form(f"edit_{selected_user}", clear_on_submit=False):
                ec1, ec2 = st.columns(2)
                with ec1:
                    edit_first = st.text_input(
                        "First Name", value=sel_data.get("first_name", ""), key=f"ef_{selected_user}"
                    )
                    edit_email = st.text_input(
                        "Email", value=sel_data.get("email", ""), key=f"ee_{selected_user}"
                    )
                with ec2:
                    edit_last = st.text_input(
                        "Last Name", value=sel_data.get("last_name", ""), key=f"el_{selected_user}"
                    )
                    edit_role = st.selectbox(
                        "Role",
                        ["user", "admin"],
                        index=0 if sel_data.get("role", "user") == "user" else 1,
                        key=f"er_{selected_user}",
                    )

                edit_submitted = st.form_submit_button("Save Changes", use_container_width=True)
                if edit_submitted:
                    if not edit_first.strip() or not edit_last.strip():
                        st.error("Name fields are required.")
                    else:
                        config = _load_config()
                        config["credentials"]["usernames"][selected_user]["first_name"] = edit_first.strip()
                        config["credentials"]["usernames"][selected_user]["last_name"] = edit_last.strip()
                        config["credentials"]["usernames"][selected_user]["email"] = edit_email.strip()
                        config["credentials"]["usernames"][selected_user]["role"] = edit_role
                        _save_config(config)
                        st.success(f"User **{selected_user}** updated.")
                        st.rerun()

        with tab_reset:
            st.markdown(
                "**Requirements:** Min 8 chars, 1 uppercase, 1 number"
            )
            with st.form(f"reset_{selected_user}", clear_on_submit=True):
                reset_pw = st.text_input("New Password", type="password", key=f"rp_{selected_user}")
                reset_confirm = st.text_input("Confirm Password", type="password", key=f"rc_{selected_user}")
                reset_submitted = st.form_submit_button("Reset Password", use_container_width=True)
                if reset_submitted:
                    if not reset_pw:
                        st.error("Password is required.")
                    elif reset_pw != reset_confirm:
                        st.error("Passwords do not match.")
                    else:
                        pw_errs = _validate_password(reset_pw)
                        if pw_errs:
                            st.error("Password does not meet requirements: " + "; ".join(pw_errs))
                        else:
                            new_hash = _hash_password(reset_pw)
                            config = _load_config()
                            config["credentials"]["usernames"][selected_user]["password"] = new_hash
                            _save_config(config)
                            st.success(f"Password for **{selected_user}** has been reset.")

        with tab_delete:
            st.warning(f"This will permanently remove **{selected_user}** from the system.")
            confirm_key = f"confirm_del_{selected_user}"
            confirmed = st.checkbox("I confirm I want to delete this user", key=confirm_key)
            if st.button(
                f"Delete {selected_user}",
                type="primary",
                use_container_width=True,
                disabled=not confirmed,
            ):
                config = _load_config()
                if selected_user in config["credentials"]["usernames"]:
                    del config["credentials"]["usernames"][selected_user]
                    _save_config(config)
                    st.success(f"User **{selected_user}** has been removed.")
                    st.rerun()
