import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
    os.environ["SUPABASE_ANON_KEY"] = st.secrets["SUPABASE_ANON_KEY"]
except Exception:
    from dotenv import load_dotenv
    load_dotenv()

import db
import auth

st.set_page_config(page_title="笔记评论", page_icon="💬", layout="wide")

auth.restore_session()
if not auth.is_logged_in():
    st.warning("请先登录")
    st.stop()

note_id = st.session_state.get("view_note_id")
note_title = st.session_state.get("view_note_title", "")
note_url = st.session_state.get("view_note_url", "")

st.markdown(f"## 💬 笔记评论")
st.markdown(f"**📌 [{note_title}]({note_url})**" if note_url else f"**📌 {note_title}**")

if not note_id:
    st.warning("未选择笔记，请从热帖排行进入")
    st.stop()

client = db.connect()
if not client:
    st.error("无法连接 Supabase")
    st.stop()

with st.spinner("加载评论中..."):
    comments_df = db.query_xhs_note_comments(client)
    note_comments = pd.DataFrame()
    if not comments_df.empty and "note_id" in comments_df.columns:
        note_comments = comments_df[comments_df["note_id"] == note_id].copy()

if note_comments.empty:
    st.info("该笔记暂无评论")
    st.stop()

# Stats
col1, col2, col3 = st.columns(3)
col1.metric("评论总数", len(note_comments))
col2.metric("总点赞", f"{note_comments['like_count'].astype(int).sum():,}")
col3.metric("评论用户", note_comments["user_id"].nunique())

st.divider()

# Convert time
if "create_time" in note_comments.columns:
    note_comments["评论时间"] = pd.to_datetime(
        note_comments["create_time"], unit="ms", errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M")

display_cols = [c for c in ["content", "like_count", "nickname", "ip_location", "评论时间", "sub_comment_count"] if c in note_comments.columns]

st.dataframe(
    note_comments.sort_values("like_count", ascending=False)[display_cols],
    column_config={
        "content": "评论内容",
        "like_count": "点赞",
        "nickname": "用户",
        "ip_location": "IP属地",
        "评论时间": "时间",
        "sub_comment_count": "回复数",
    },
    use_container_width=True,
    hide_index=True,
    height=700,
)

# IP distribution
st.divider()
st.subheader("IP 属地分布")
if "ip_location" in note_comments.columns:
    ip_dist = note_comments["ip_location"].value_counts().head(15)
    if not ip_dist.empty:
        import plotly.express as px
        fig = px.pie(values=ip_dist.values, names=ip_dist.index, title="评论 IP 属地")
        st.plotly_chart(fig, use_container_width=True)

st.page_link("app.py", label="⬅️ 返回热帖排行", icon="⬅️")
