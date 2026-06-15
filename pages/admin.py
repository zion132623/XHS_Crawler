import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

st.set_page_config(page_title="管理后台", page_icon="🔧", layout="wide")


def parse_wan(val):
    if pd.isna(val):
        return 0
    s = str(val).strip()
    if "万" in s:
        return int(float(s.replace("万", "")) * 10000)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _read_csv(file):
    return pd.read_csv(file, encoding="utf-8-sig", engine="python")


def clean_numeric_cols(df, cols):
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_wan)
    return df


# 门禁：仅 admin
if not auth.is_logged_in() or not auth.is_admin():
    st.error("无权访问")
    st.stop()

st.title("🔧 管理后台")

# 初始化 Supabase
if "db_conn" not in st.session_state:
    st.session_state.db_conn = db.connect()

client = st.session_state.db_conn

tab1, tab2, tab3 = st.tabs(["📊 数据库管理", "👤 用户管理", "📥 CSV 导入"])

with tab1:
    st.subheader("数据库统计")
    if st.button("刷新统计"):
        stats = db.table_stats(client)
        st.session_state.db_stats = stats

    if "db_stats" in st.session_state:
        s = st.session_state.db_stats
        col1, col2 = st.columns(2)
        col1.metric("帖子总数", s["contents"])
        col2.metric("评论总数", s["comments"])

    st.divider()
    st.subheader("清空数据")
    st.warning("此操作不可撤销")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("清空全部帖子", type="secondary"):
            try:
                data = client.table("contents").select("note_id").execute()
                ids = [r["note_id"] for r in (data.data or [])]
                if ids:
                    for i in range(0, len(ids), 100):
                        chunk = ids[i:i + 100]
                        client.table("contents").delete().in_("note_id", chunk).execute()
                st.success(f"已删除 {len(ids)} 条帖子")
                st.session_state.db_stats = db.table_stats(client)
            except Exception as e:
                st.error(f"删除失败: {e}")
    with col2:
        if st.button("清空全部评论", type="secondary"):
            try:
                data = client.table("comments").select("comment_id").execute()
                ids = [r["comment_id"] for r in (data.data or [])]
                if ids:
                    for i in range(0, len(ids), 100):
                        chunk = ids[i:i + 100]
                        client.table("comments").delete().in_("comment_id", chunk).execute()
                st.success(f"已删除 {len(ids)} 条评论")
                st.session_state.db_stats = db.table_stats(client)
            except Exception as e:
                st.error(f"删除失败: {e}")

with tab2:
    st.subheader("用户角色管理")
    user_id = st.text_input("用户 UUID", placeholder="从 Supabase Auth → Users 复制 UUID")
    role = st.selectbox("角色", ["viewer", "admin"])
    if st.button("设置角色"):
        if user_id:
            try:
                client.table("user_roles").upsert({"user_id": user_id, "role": role}).execute()
                st.success(f"已设置 {user_id} 为 {role}")
            except Exception as e:
                st.error(f"设置失败: {e}")
        else:
            st.error("请输入用户 UUID")

    st.info("用户 UUID 在 Supabase Dashboard → Authentication → Users 查看")

with tab3:
    st.subheader("导入 CSV 到 Supabase")
    uploaded_c = st.file_uploader("上传 search_contents CSV", type="csv", key="admin_csv_c")
    uploaded_cm = st.file_uploader("上传 search_comments CSV (可选)", type="csv", key="admin_csv_cm")

    if st.button("导入入库", type="primary"):
        if not uploaded_c:
            st.error("请先上传 search_contents CSV")
        else:
            contents = _read_csv(uploaded_c)
            contents = clean_numeric_cols(contents, ["liked_count", "collected_count", "comment_count", "share_count"])
            r1 = db.import_contents(client, contents)

            r2 = {"inserted": 0, "updated": 0}
            if uploaded_cm:
                coms = _read_csv(uploaded_cm)
                coms = clean_numeric_cols(coms, ["like_count", "sub_comment_count"])
                r2 = db.import_comments(client, coms)

            st.session_state.db_stats = db.table_stats(client)
            c1 = r1["inserted"]; u1 = r1["updated"]; c2 = r2["inserted"]; u2 = r2["updated"]
            st.success(f"帖子: 新增 {c1} 条, 更新 {u1} 条 | 评论: 新增 {c2} 条, 更新 {u2} 条")
