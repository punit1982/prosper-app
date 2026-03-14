"""
User Management
===============
Admin users can create, edit, and delete users.
Regular users can edit their own profile (name, email, password).
"""

import os
import streamlit as st

st.header("👥 User Management")

# ── Check if auth is enabled ─────────────────────────────────────────────────
AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
if not AUTH_ENABLED:
    st.info("Authentication is disabled. Enable it by setting `PROSPER_AUTH_ENABLED=true` in your `.env` file.")
    st.stop()

# ── Load auth config ─────────────────────────────────────────────────────────
try:
    import yaml
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
    with open(_AUTH_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


config = _load_config()
credentials = config.get("credentials", {}).get("usernames", {})

# ── Identify current user ────────────────────────────────────────────────────
current_user = st.session_state.get("username", None)
if not current_user:
    st.warning("Please log in to access User Management.")
    st.stop()

current_role = credentials.get(current_user, {}).get("role", "user")
is_admin = current_role == "admin"

st.caption(f"Logged in as **{current_user}** · Role: **{current_role.title()}**")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: My Profile (all users)
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("🧑 My Profile")

user_data = credentials.get(current_user, {})

with st.form("edit_profile", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        new_first = st.text_input("First Name", value=user_data.get("first_name", ""))
    with col2:
        new_last = st.text_input("Last Name", value=user_data.get("last_name", ""))
    new_email = st.text_input("Email", value=user_data.get("email", ""))

    submitted = st.form_submit_button("💾 Update Profile", use_container_width=True)
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
with st.expander("🔑 Change Password"):
    with st.form("change_password", clear_on_submit=True):
        current_pw = st.text_input("Current Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        confirm_pw = st.text_input("Confirm New Password", type="password")

        pw_submitted = st.form_submit_button("🔄 Change Password", use_container_width=True)
        if pw_submitted:
            if not current_pw or not new_pw or not confirm_pw:
                st.error("All password fields are required.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                import bcrypt
                stored_hash = user_data.get("password", "")
                if bcrypt.checkpw(current_pw.encode(), stored_hash.encode()):
                    new_hash = stauth.Hasher.hash(new_pw)
                    config = _load_config()
                    config["credentials"]["usernames"][current_user]["password"] = new_hash
                    _save_config(config)
                    st.success("Password changed successfully!")
                else:
                    st.error("Current password is incorrect.")

if not is_admin:
    st.divider()
    st.caption("Contact an administrator to manage other users or change roles.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Admin — All Users (admin only)
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🛡️ Admin — User Directory")

config = _load_config()
credentials = config.get("credentials", {}).get("usernames", {})

# ── Users Table ──────────────────────────────────────────────────────────────
user_rows = []
for uname, udata in credentials.items():
    user_rows.append({
        "Username": uname,
        "First Name": udata.get("first_name", ""),
        "Last Name": udata.get("last_name", ""),
        "Email": udata.get("email", ""),
        "Role": udata.get("role", "user").title(),
    })

if user_rows:
    import pandas as pd
    users_df = pd.DataFrame(user_rows)
    st.dataframe(users_df, hide_index=True, use_container_width=True)
    st.caption(f"Total users: **{len(user_rows)}**")

# ── Create New User ──────────────────────────────────────────────────────────
st.subheader("➕ Create New User")

with st.form("create_user", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        new_username = st.text_input("Username", placeholder="e.g. john_doe")
        new_user_first = st.text_input("First Name", key="new_first")
        new_user_email = st.text_input("Email", key="new_email", placeholder="user@example.com")
    with c2:
        new_user_pw = st.text_input("Initial Password", type="password", help="Min 6 characters")
        new_user_last = st.text_input("Last Name", key="new_last")
        new_user_role = st.selectbox("Role", ["user", "admin"], index=0)

    create_submitted = st.form_submit_button("✅ Create User", use_container_width=True, type="primary")
    if create_submitted:
        errors = []
        if not new_username or not new_username.strip():
            errors.append("Username is required.")
        elif not new_username.strip().isidentifier():
            errors.append("Username must be alphanumeric (underscores allowed, no spaces).")
        if new_username.strip().lower() in {u.lower() for u in credentials}:
            errors.append(f"Username **{new_username}** already exists.")
        if not new_user_first.strip() or not new_user_last.strip():
            errors.append("First and Last name are required.")
        if not new_user_email.strip() or "@" not in new_user_email:
            errors.append("Valid email is required.")
        if not new_user_pw or len(new_user_pw) < 6:
            errors.append("Password must be at least 6 characters.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            hashed_pw = stauth.Hasher.hash(new_user_pw)
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
st.subheader("✏️ Edit / Remove Users")

other_users = [u for u in credentials if u != current_user]
if not other_users:
    st.info("No other users to manage. You're the only user in the system.")
else:
    selected_user = st.selectbox(
        "Select user to manage",
        other_users,
        format_func=lambda u: f"{u} — {credentials[u].get('first_name', '')} {credentials[u].get('last_name', '')} ({credentials[u].get('role', 'user')})",
    )

    if selected_user:
        sel_data = credentials[selected_user]

        tab_edit, tab_reset, tab_delete = st.tabs(["📝 Edit Details", "🔑 Reset Password", "🗑️ Remove User"])

        with tab_edit:
            with st.form(f"edit_{selected_user}", clear_on_submit=False):
                ec1, ec2 = st.columns(2)
                with ec1:
                    edit_first = st.text_input("First Name", value=sel_data.get("first_name", ""), key=f"ef_{selected_user}")
                    edit_email = st.text_input("Email", value=sel_data.get("email", ""), key=f"ee_{selected_user}")
                with ec2:
                    edit_last = st.text_input("Last Name", value=sel_data.get("last_name", ""), key=f"el_{selected_user}")
                    edit_role = st.selectbox(
                        "Role",
                        ["user", "admin"],
                        index=0 if sel_data.get("role", "user") == "user" else 1,
                        key=f"er_{selected_user}",
                    )

                edit_submitted = st.form_submit_button("💾 Save Changes", use_container_width=True)
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
            with st.form(f"reset_{selected_user}", clear_on_submit=True):
                reset_pw = st.text_input("New Password", type="password", key=f"rp_{selected_user}")
                reset_confirm = st.text_input("Confirm Password", type="password", key=f"rc_{selected_user}")
                reset_submitted = st.form_submit_button("🔄 Reset Password", use_container_width=True)
                if reset_submitted:
                    if not reset_pw or len(reset_pw) < 6:
                        st.error("Password must be at least 6 characters.")
                    elif reset_pw != reset_confirm:
                        st.error("Passwords do not match.")
                    else:
                        new_hash = stauth.Hasher.hash(reset_pw)
                        config = _load_config()
                        config["credentials"]["usernames"][selected_user]["password"] = new_hash
                        _save_config(config)
                        st.success(f"Password for **{selected_user}** has been reset.")

        with tab_delete:
            st.warning(f"⚠️ This will permanently remove **{selected_user}** from the system.")
            if st.button(f"🗑️ Delete {selected_user}", type="primary", use_container_width=True):
                config = _load_config()
                if selected_user in config["credentials"]["usernames"]:
                    del config["credentials"]["usernames"][selected_user]
                    _save_config(config)
                    st.success(f"User **{selected_user}** has been removed.")
                    st.rerun()
