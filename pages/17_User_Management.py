"""
User Management
===============
- All users: edit profile, change password, manage portfolios
- Admin users: create/edit/delete other users, change roles
- Database is the single source of truth for user data
"""

import os
import pandas as pd
import streamlit as st

st.header("User Management")

# ── Check auth ──────────────────────────────────────────────────────────────
AUTH_ENABLED = os.getenv("PROSPER_AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
if not AUTH_ENABLED:
    st.info("Authentication is disabled. Enable it by setting `PROSPER_AUTH_ENABLED=true`.")
    st.stop()

try:
    import bcrypt
    from core.auth import (
        validate_password, _hash_password, _check_password,
        _db_get_all_users, _db_get_user, _db_create_user,
        _db_update_user, _db_delete_user, _rebuild_yaml_from_db,
    )
except ImportError as e:
    st.error(f"Missing dependency: {e}. Run `pip install streamlit-authenticator bcrypt`.")
    st.stop()

# ── Identify current user ──────────────────────────────────────────────────
current_user = st.session_state.get("username")
if not current_user:
    st.warning("Please log in to access User Management.")
    st.stop()

# Get current user from DB
current_user_data = _db_get_user(current_user)
if not current_user_data:
    st.warning("User not found in database. Please log out and log back in.")
    st.stop()

current_role = current_user_data.get("role", "user")
is_admin = current_role == "admin"

st.caption(f"Logged in as **{current_user}** | Role: **{current_role.title()}**")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: My Profile
# ═════════════════════════════════════════════════════════════════════════════
st.subheader("My Profile")

col_info, col_meta = st.columns([2, 1])

with col_info:
    st.markdown(f"**Display name:** {current_user_data.get('first_name', '')} {current_user_data.get('last_name', '')}")
    st.markdown(f"**Email:** {current_user_data.get('email', 'Not set')}")
    st.markdown(f"**Username:** `{current_user}` _(read-only)_")
    st.markdown(f"**Role:** {current_role.title()}")

with col_meta:
    member_since = current_user_data.get("created_at")
    st.markdown(f"**Member since:** {member_since or 'N/A'}")
    auth_method = st.session_state.get("auth_method", "email")
    method_label = {"google": "🔑 Google", "email": "📧 Email"}.get(auth_method, auth_method)
    st.markdown(f"**Sign-in method:** {method_label}")

# ── Edit Profile ────────────────────────────────────────────────────────────
with st.expander("✏️ Edit Profile", expanded=False):
    with st.form("edit_profile", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            new_first = st.text_input("First Name", value=current_user_data.get("first_name", ""))
        with c2:
            new_last = st.text_input("Last Name", value=current_user_data.get("last_name", ""))
        new_email = st.text_input("Email", value=current_user_data.get("email", ""))

        if st.form_submit_button("Save Profile", use_container_width=True):
            if not new_first.strip() or not new_last.strip():
                st.error("First name and last name are required.")
            elif not new_email.strip() or "@" not in new_email:
                st.error("Please enter a valid email address.")
            else:
                _db_update_user(
                    current_user,
                    first_name=new_first.strip(),
                    last_name=new_last.strip(),
                    email=new_email.strip(),
                )
                _rebuild_yaml_from_db()  # Sync YAML cache
                st.session_state["name"] = f"{new_first.strip()} {new_last.strip()}"
                st.session_state["user_id"] = new_email.strip()
                st.success("✅ Profile updated successfully!")

# ── Change Password ─────────────────────────────────────────────────────────
with st.expander("🔒 Change Password"):
    st.markdown(
        "**Requirements:** min 8 characters, 1 uppercase letter (A-Z), 1 number (0-9)"
    )
    with st.form("change_password", clear_on_submit=True):
        current_pw = st.text_input("Current Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        confirm_pw = st.text_input("Confirm New Password", type="password")

        if st.form_submit_button("Change Password", use_container_width=True):
            if not current_pw or not new_pw or not confirm_pw:
                st.error("All password fields are required.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            else:
                pw_errors = validate_password(new_pw)
                if pw_errors:
                    st.error("Password does not meet requirements: " + "; ".join(pw_errors))
                else:
                    stored_hash = current_user_data.get("password_hash", "")
                    if _check_password(current_pw, stored_hash):
                        new_hash = _hash_password(new_pw)
                        _db_update_user(current_user, password_hash=new_hash)
                        _rebuild_yaml_from_db()  # Sync YAML cache
                        st.success("✅ Password changed successfully!")
                    else:
                        st.error("Current password is incorrect.")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: My Portfolios
# ═════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("My Portfolios")

try:
    from core.database import (
        get_all_portfolios, get_all_holdings,
        create_portfolio, rename_portfolio, delete_portfolio,
    )

    all_portfolios = get_all_portfolios()

    # Filter to current user's portfolios
    if not all_portfolios.empty and "user_id" in all_portfolios.columns:
        my_portfolios = all_portfolios[
            all_portfolios["user_id"].isin([current_user, "default", st.session_state.get("user_id", "")])
        ].copy()
    else:
        my_portfolios = all_portfolios.copy() if not all_portfolios.empty else pd.DataFrame()

    if not my_portfolios.empty:
        rows = []
        for _, p in my_portfolios.iterrows():
            pid = int(p["id"])
            pname = p.get("name", f"Portfolio {pid}")
            try:
                holdings = get_all_holdings(portfolio_id=pid)
                h_count = len(holdings) if not holdings.empty else 0
            except Exception:
                h_count = 0
            rows.append({"ID": pid, "Name": pname, "Holdings": h_count})

        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("No portfolios found. Create one below.")

    # Create Portfolio
    with st.expander("➕ Create New Portfolio"):
        with st.form("create_portfolio", clear_on_submit=True):
            pf_name = st.text_input("Portfolio Name", placeholder="e.g. Growth Stocks")
            pf_desc = st.text_input("Description (optional)")
            if st.form_submit_button("Create Portfolio", use_container_width=True):
                if not pf_name.strip():
                    st.error("Portfolio name is required.")
                else:
                    try:
                        user_id = st.session_state.get("user_id", current_user)
                        new_id = create_portfolio(pf_name.strip(), pf_desc.strip(), user_id=user_id)
                        st.success(f"✅ Portfolio **{pf_name.strip()}** created!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    # Rename / Delete
    if not my_portfolios.empty:
        with st.expander("⚙️ Rename or Delete Portfolio"):
            pf_options = {int(r["id"]): r.get("name", f"Portfolio {r['id']}") for _, r in my_portfolios.iterrows()}
            pf_choice = st.selectbox(
                "Select portfolio", list(pf_options.keys()),
                format_func=lambda x: f"{pf_options[x]} (ID: {x})",
                key="pf_manage_select",
            )
            if pf_choice:
                rc, dc = st.columns(2)
                with rc:
                    with st.form("rename_portfolio", clear_on_submit=True):
                        rn_name = st.text_input("New Name")
                        if st.form_submit_button("Rename", use_container_width=True):
                            if rn_name.strip():
                                rename_portfolio(pf_choice, rn_name.strip())
                                st.success(f"Renamed to **{rn_name.strip()}**.")
                                st.rerun()
                with dc:
                    if pf_choice == 1:
                        st.info("Default portfolio cannot be deleted.")
                    else:
                        st.warning(f"Delete **{pf_options[pf_choice]}**?")
                        confirmed = st.checkbox("I confirm deletion", key=f"confirm_del_pf_{pf_choice}")
                        if st.button("Delete Portfolio", use_container_width=True, disabled=not confirmed):
                            delete_portfolio(pf_choice)
                            st.success("Portfolio deleted.")
                            st.rerun()

except Exception as e:
    st.warning(f"Could not load portfolios: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3: Admin — User Administration
# ═════════════════════════════════════════════════════════════════════════════
if not is_admin:
    st.divider()
    st.caption("Contact an administrator to manage other users or change roles.")
    st.stop()

st.divider()
st.subheader("🔧 Admin — User Directory")

# Load all users from DB
all_users = _db_get_all_users()

if all_users:
    user_rows = []
    for u in all_users:
        user_rows.append({
            "Username": u["username"],
            "Name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
            "Email": u.get("email", ""),
            "Role": u.get("role", "user").title(),
            "Created": u.get("created_at", "N/A"),
        })
    st.dataframe(pd.DataFrame(user_rows), hide_index=True, use_container_width=True)
    st.caption(f"Total users: **{len(user_rows)}**")
else:
    st.info("No users found in the database.")

# ── Create New User (Admin) ─────────────────────────────────────────────────
st.subheader("Create New User")

with st.form("admin_create_user", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        new_first = st.text_input("First Name", key="admin_new_first")
        new_email = st.text_input("Email", key="admin_new_email", placeholder="user@example.com")
        new_pw = st.text_input("Password", type="password", key="admin_new_pw",
                               help="Min 8 chars, 1 uppercase, 1 number")
    with c2:
        new_last = st.text_input("Last Name", key="admin_new_last")
        new_role = st.selectbox("Role", ["user", "admin"], index=0, key="admin_new_role")
        new_pw2 = st.text_input("Confirm Password", type="password", key="admin_new_pw2")

    if st.form_submit_button("Create User", use_container_width=True, type="primary"):
        errors = []
        if not new_first.strip() or not new_last.strip():
            errors.append("First and Last name are required.")
        if not new_email.strip() or "@" not in new_email:
            errors.append("Valid email is required.")
        if new_pw:
            pw_errs = validate_password(new_pw)
            if pw_errs:
                errors.append("Password: " + "; ".join(pw_errs))
            if new_pw != new_pw2:
                errors.append("Passwords do not match.")
        else:
            errors.append("Password is required.")

        username = new_email.split("@")[0].lower().replace(".", "_").replace("-", "_") if new_email else ""
        if username and _db_get_user(username):
            errors.append(f"Username **{username}** already exists.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            hashed = _hash_password(new_pw)
            _db_create_user(username, new_email.strip(), new_first.strip(), new_last.strip(), hashed, new_role)
            _rebuild_yaml_from_db()  # Sync
            st.success(f"✅ User **{username}** created!")
            st.rerun()

# ── Edit / Delete Users (Admin) ─────────────────────────────────────────────
st.subheader("Edit / Remove Users")

other_users = [u for u in all_users if u["username"] != current_user]
if not other_users:
    st.info("No other users to manage.")
else:
    sel_username = st.selectbox(
        "Select user",
        [u["username"] for u in other_users],
        format_func=lambda u: next(
            (f"{x['username']} — {x.get('first_name', '')} {x.get('last_name', '')} ({x.get('role', 'user')})"
             for x in other_users if x["username"] == u),
            u,
        ),
    )

    if sel_username:
        sel_data = _db_get_user(sel_username) or {}

        tab_edit, tab_reset, tab_delete = st.tabs(["Edit Details", "Reset Password", "Remove User"])

        with tab_edit:
            with st.form(f"admin_edit_{sel_username}", clear_on_submit=False):
                ec1, ec2 = st.columns(2)
                with ec1:
                    edit_first = st.text_input("First Name", value=sel_data.get("first_name", ""))
                    edit_email = st.text_input("Email", value=sel_data.get("email", ""))
                with ec2:
                    edit_last = st.text_input("Last Name", value=sel_data.get("last_name", ""))
                    edit_role = st.selectbox(
                        "Role", ["user", "admin"],
                        index=0 if sel_data.get("role", "user") == "user" else 1,
                    )

                if st.form_submit_button("Save Changes", use_container_width=True):
                    if not edit_first.strip() or not edit_last.strip():
                        st.error("Name fields are required.")
                    else:
                        _db_update_user(
                            sel_username,
                            first_name=edit_first.strip(),
                            last_name=edit_last.strip(),
                            email=edit_email.strip(),
                            role=edit_role,
                        )
                        _rebuild_yaml_from_db()
                        st.success(f"✅ User **{sel_username}** updated.")
                        st.rerun()

        with tab_reset:
            st.markdown("**Requirements:** min 8 chars, 1 uppercase, 1 number")
            with st.form(f"admin_reset_{sel_username}", clear_on_submit=True):
                reset_pw = st.text_input("New Password", type="password")
                reset_pw2 = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Reset Password", use_container_width=True):
                    if not reset_pw:
                        st.error("Password is required.")
                    elif reset_pw != reset_pw2:
                        st.error("Passwords do not match.")
                    else:
                        pw_errs = validate_password(reset_pw)
                        if pw_errs:
                            st.error("Does not meet requirements: " + "; ".join(pw_errs))
                        else:
                            new_hash = _hash_password(reset_pw)
                            _db_update_user(sel_username, password_hash=new_hash)
                            _rebuild_yaml_from_db()
                            st.success(f"✅ Password for **{sel_username}** has been reset.")

        with tab_delete:
            st.warning(f"⚠️ This will permanently remove **{sel_username}** and all their data.")
            confirmed = st.checkbox("I confirm deletion", key=f"confirm_del_{sel_username}")
            if st.button(f"Delete {sel_username}", type="primary",
                         use_container_width=True, disabled=not confirmed):
                _db_delete_user(sel_username)
                _rebuild_yaml_from_db()
                st.success(f"User **{sel_username}** has been removed.")
                st.rerun()
