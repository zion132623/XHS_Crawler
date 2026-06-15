import streamlit as st
import os
from typing import Optional
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

COOKIE_ACCESS = "sb_access_token"
COOKIE_REFRESH = "sb_refresh_token"


def _get_client() -> Optional[Client]:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def _save_session(session):
    """Persist session tokens to cookies so refresh doesn't log out."""
    if session:
        st.cookies[COOKIE_ACCESS] = session.access_token
        st.cookies[COOKIE_REFRESH] = session.refresh_token


def _clear_cookies():
    if COOKIE_ACCESS in st.cookies:
        st.cookies[COOKIE_ACCESS] = ""
    if COOKIE_REFRESH in st.cookies:
        st.cookies[COOKIE_REFRESH] = ""


def restore_session() -> bool:
    """Try to restore Supabase session from cookies. Call once on app start."""
    if "user" in st.session_state:
        return True
    client = _get_client()
    if not client:
        return False
    refresh = st.cookies.get(COOKIE_REFRESH)
    access = st.cookies.get(COOKIE_ACCESS)
    if not refresh or not access:
        return False
    try:
        res = client.auth.set_session(access, refresh)
        if res.user:
            st.session_state.user = res.user
            st.session_state.session = res.session
            role = get_user_role(res.user.id)
            st.session_state.role = role
            _save_session(res.session)
            return True
    except Exception:
        _clear_cookies()
    return False


def login(email: str, password: str) -> Optional[dict]:
    client = _get_client()
    if not client:
        st.error("Supabase 未配置，请设置 SUPABASE_URL 和 SUPABASE_ANON_KEY 环境变量")
        return None
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = res.user
            st.session_state.session = res.session
            role = get_user_role(res.user.id)
            st.session_state.role = role
            _save_session(res.session)
            return res.user
    except Exception as e:
        st.error(f"登录失败: {e}")
    return None


def register(email: str, password: str) -> Optional[dict]:
    client = _get_client()
    if not client:
        return None
    try:
        res = client.auth.sign_up({"email": email, "password": password})
        if res.user:
            st.success("注册成功，请检查邮箱确认（如开启了邮箱验证）")
            return res.user
    except Exception as e:
        st.error(f"注册失败: {e}")
    return None


def logout():
    for key in ["user", "session", "role"]:
        st.session_state.pop(key, None)
    _clear_cookies()
    st.rerun()


def get_current_user() -> Optional[dict]:
    return st.session_state.get("user")


def get_user_role(user_id: str = None) -> str:
    uid = user_id or (get_current_user() and get_current_user().id)
    if not uid:
        return "viewer"
    client = _get_client()
    if not client:
        return "viewer"
    try:
        res = client.table("user_roles").select("role").eq("user_id", uid).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["role"]
    except Exception:
        pass
    return "viewer"


def set_user_role(user_id: str, role: str):
    client = _get_client()
    if not client:
        return
    client.table("user_roles").upsert({"user_id": user_id, "role": role}).execute()


def is_admin() -> bool:
    return st.session_state.get("role") == "admin"


def is_logged_in() -> bool:
    return "user" in st.session_state
