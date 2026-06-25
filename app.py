import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
import jieba
import math
import re
import os
from datetime import datetime

# Try st.secrets first (Streamlit Cloud), fall back to .env (local)
try:
    os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
    os.environ["SUPABASE_ANON_KEY"] = st.secrets["SUPABASE_ANON_KEY"]
except Exception:
    from dotenv import load_dotenv
    load_dotenv()

import db
import auth


@st.dialog("💬 笔记评论", width="large")
def show_comments_dialog(note_id, note_title, note_url):
    st.markdown(f"**📌 [{note_title}]({note_url})**" if note_url else f"**📌 {note_title}")

    client = db.connect()
    if not client:
        st.error("无法连接 Supabase")
        return

    with st.spinner("加载评论中..."):
        comments_df = db.query_xhs_note_comments(client)
        note_comments = pd.DataFrame()
        if not comments_df.empty and "note_id" in comments_df.columns:
            note_comments = comments_df[comments_df["note_id"] == note_id].copy()

    if note_comments.empty:
        st.info("该笔记暂无评论")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("评论总数", len(note_comments))
    col2.metric("总点赞", f"{note_comments['like_count'].astype(int).sum():,}")
    col3.metric("评论用户", note_comments["user_id"].nunique())

    st.divider()

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

    st.divider()
    st.subheader("IP 属地分布")
    if "ip_location" in note_comments.columns:
        ip_dist = note_comments["ip_location"].value_counts().head(15)
        if not ip_dist.empty:
            import plotly.express as px
            fig = px.pie(values=ip_dist.values, names=ip_dist.index, title="评论 IP 属地")
            st.plotly_chart(fig, use_container_width=True)


st.set_page_config(page_title="XHS 运营分析", page_icon="📊", layout="wide")
st.title("📊 小红书「原创车贴」运营分析")

# ==================== 会话恢复 ====================
auth.restore_session()

# ==================== 登录门禁 ====================
if not auth.is_logged_in():
    col_form, col_space = st.columns([1, 1.5])
    with col_form:
        st.subheader("🔐 登录")
        email = st.text_input("邮箱", key="login_email")
        password = st.text_input("密码", type="password", key="login_pw")
        if st.button("登录", use_container_width=True):
            auth.login(email, password)
            st.rerun()
    st.stop()


# ==================== 工具函数 ====================
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


def clean_numeric_cols(df, cols):
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_wan)
    return df


def enrich_time_cols(df):
    df["publish_time"] = pd.to_datetime(df["time"], unit="ms")
    df["update_time"] = pd.to_datetime(df["last_update_time"], unit="ms")
    df["publish_hour"] = df["publish_time"].dt.hour
    df["publish_weekday"] = df["publish_time"].dt.weekday  # 0=Mon
    df["publish_date"] = df["publish_time"].dt.date
    return df


def _get_font_path():
    import platform, os
    if platform.system() == "Darwin":
        return "/System/Library/Fonts/PingFang.ttc"
    for path in [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            return path
    return None


# ==================== 侧边栏 ====================
with st.sidebar:
    st.header("📂 数据管理")

    if "xhs_note" not in st.session_state:
        with st.spinner("连接 Supabase..."):
            client = db.connect()
            if not client:
                st.error("Supabase 未配置")
                st.stop()
            st.session_state.db_conn = client
            stats = db.table_stats(client)
            st.session_state.db_stats = stats
            st.session_state.xhs_note = enrich_time_cols(db.query_contents(client))
            st.session_state.xhs_note = clean_numeric_cols(
                st.session_state.xhs_note,
                ["liked_count", "collected_count", "comment_count", "share_count"],
            )
            comments_data = db.query_comments(client)
            if not comments_data.empty and "create_time" in comments_data.columns:
                comments_data = clean_numeric_cols(comments_data, ["like_count", "sub_comment_count"])
                comments_data["create_time_dt"] = pd.to_datetime(comments_data["create_time"], unit="ms")
            st.session_state.comments = comments_data
            st.session_state.commented_note_ids = db.get_commented_note_ids(client)
            st.session_state.hot_all = db.query_hot_posts(client)
            st.session_state.hot_normal = db.query_hot_posts(client, post_type="normal")
            st.session_state.hot_video = db.query_hot_posts(client, post_type="video")
            st.session_state.creators = db.query_creators(client)

    st.info(
        f"📊 帖子 {st.session_state.db_stats.get('xhs_note', 0)} 条 "
        f"| 评论 {st.session_state.db_stats['comments']} 条 "
        f"| 创作者 {len(st.session_state.creators)} 位"
    )

    st.page_link("pages/stopwords.py", label="📝 停用词管理", icon="📝")

    if auth.is_admin():
        st.page_link("pages/admin.py", label="🔧 管理后台", icon="🔧")

    st.divider()
    st.caption(f"👤 {auth.get_current_user().email}")
    st.caption(f"🔑 {st.session_state.get('role', 'viewer')}")
    if st.button("🚪 登出", use_container_width=True):
        auth.logout()
        st.rerun()

df = st.session_state.xhs_note
comments = st.session_state.comments if "comments" in st.session_state else None
hot_all = st.session_state.get("hot_all")
creators = st.session_state.get("creators", pd.DataFrame())

# ==================== Tab 页 ====================
tab_hot, tab_time, tab_content, tab_peers = st.tabs(
    ["🔥 热帖排行", "⏰ 发布时间优化", "📝 内容策略分析", "🔍 同行分析"]
)

# ============================================================
# Tab 1: 热帖排行
# ============================================================
with tab_hot:
    if hot_all is None or hot_all.empty:
        st.warning("暂无热帖数据")
    else:
        post_type = st.selectbox(
            "帖子类型", ["全部", "图文 (normal)", "视频 (video)"],
        )
        if post_type == "全部":
            df_hot = st.session_state.hot_all
        elif post_type == "视频 (video)":
            df_hot = st.session_state.hot_video
        else:
            df_hot = st.session_state.hot_normal

        if df_hot.empty:
            st.warning(f"该类型暂无帖子")
            st.stop()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("帖子总数", len(df_hot))
        col2.metric("平均热度", f"{df_hot['hot_score'].mean():.2f}")
        burst_count = (df_hot["score_burst"] > 0).sum()
        col3.metric("有增量帖子", burst_count)
        col4.metric("最高综合分", f"{df_hot['final_score'].max():.2f}")

        # Hot keyword distribution
        kw_raw = df_hot.get("source_keyword", pd.Series(dtype=str))
        kw_per_post = kw_raw.fillna("").apply(
            lambda x: [k.strip() for k in str(x).split(",") if k.strip()]
        )
        kw_series = kw_per_post.explode()

        if not kw_series.empty and kw_series.nunique() > 0:
            kw_counts = kw_series.value_counts()
            fig_kw = px.bar(
                x=kw_counts.values, y=kw_counts.index,
                orientation="h",
                title="热门帖关键词分布",
                labels={"x": "帖子数", "y": "搜索关键词"},
                color=kw_counts.values,
                color_continuous_scale="Blues",
            )
            fig_kw.update_layout(height=max(200, len(kw_counts) * 30), margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_kw, use_container_width=True)
        else:
            st.info("暂无关键词数据")

        # Multi-keyword posts from ALL notes
        kw_all_raw = df.get("source_keyword", pd.Series(dtype=str))
        kw_all_per_post = kw_all_raw.fillna("").apply(
            lambda x: [k.strip() for k in str(x).split(",") if k.strip()]
        )
        multi_kw_all_mask = kw_all_per_post.apply(len) > 1
        multi_kw_all_count = multi_kw_all_mask.sum()

        st.markdown(f"🔗 **多关键词帖子 · 全部** ({multi_kw_all_count} / {len(df)})")
        if multi_kw_all_count > 0:
            multi_kw_all_df = df[multi_kw_all_mask][
                ["title", "nickname", "source_keyword", "liked_count", "comment_count", "note_url"]
            ].copy()
            st.dataframe(
                multi_kw_all_df.sort_values("liked_count", ascending=False),
                column_config={
                    "title": "标题",
                    "nickname": "作者",
                    "source_keyword": "关键词",
                    "liked_count": "点赞",
                    "comment_count": "评论",
                    "note_url": st.column_config.LinkColumn("链接"),
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无多关键词帖子")

        st.divider()

        # 💬 热帖评论查看
        st.subheader("💬 查看笔记评论")
        note_opts_cols = [c for c in ["note_id", "title", "nickname", "comment_count", "note_url"] if c in df_hot.columns]
        note_options = df_hot[note_opts_cols].copy()
        # 只看 xhs_note_comment 表中实际有评论的帖子
        commented_ids = st.session_state.get("commented_note_ids", set())
        if commented_ids:
            note_options = note_options[note_options["note_id"].isin(commented_ids)]
        if note_options.empty:
            st.info("暂无有评论的帖子")
        else:
            note_options["label"] = note_options.apply(
                lambda r: f"[{r['comment_count']}评] {r['title'][:50]} — @{r['nickname']} ({r['note_id'][:12]}...)",
                axis=1,
            )
            note_options = note_options.sort_values("comment_count", ascending=False)
            selected_note_label = st.selectbox(
                "选择笔记查看评论",
                note_options["label"].tolist(),
                key="comment_view_selector",
            )
            if selected_note_label:
                sel_row = note_options[note_options["label"] == selected_note_label].iloc[0]
                if st.button("📥 查看评论", key="load_comments_btn", type="primary"):
                    show_comments_dialog(
                        sel_row["note_id"],
                        sel_row["title"],
                        sel_row["note_url"] if "note_url" in sel_row.index else "",
                    )

        st.divider()

        view_mode = st.radio(
            "榜单切换",
            ["综合榜", "热门榜", "潜力榜"],
            horizontal=True,
        )

        if view_mode == "综合榜":
            sort_col = "final_score"
        elif view_mode == "热门榜":
            sort_col = "hot_score"
        else:
            sort_col = "score_burst"

        display = df_hot.sort_values(sort_col, ascending=False).head(20)

        col_left, col_right = st.columns([1.2, 1])

        with col_left:
            st.subheader("📋 排行榜")

            table_data = display[
                ["title", "nickname", "liked_count", "collected_count",
                 "comment_count", "share_count", "hours_ago",
                 "hot_score", "score_burst", "keyword_count", "source_keyword", "final_score"]
            ].copy()
            table_data["hours_ago"] = table_data["hours_ago"].astype(int)

            st.dataframe(
                table_data,
                column_config={
                    "title": "标题",
                    "nickname": "作者",
                    "liked_count": "点赞",
                    "collected_count": "收藏",
                    "comment_count": "评论",
                    "share_count": "分享",
                    "hours_ago": "发帖(h)",
                    "hot_score": st.column_config.NumberColumn("热门分", format="%.2f"),
                    "score_burst": st.column_config.NumberColumn("潜力分", format="%.4f"),
                    "keyword_count": "关键词数",
                    "source_keyword": "搜索关键词",
                    "final_score": st.column_config.NumberColumn("综合分", format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
                height=700,
            )

        with col_right:
            st.subheader("热门 vs 潜力")

            fig = px.scatter(
                df_hot,
                x="hot_score",
                y="score_burst",
                size="final_score",
                hover_data=["title", "nickname"],
                color="final_score",
                color_continuous_scale="RdYlGn",
                title="热门分 × 潜力分",
            )
            fig.add_hline(y=0.001, line_dash="dot", line_color="gray")
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

            fig2 = px.scatter(
                df_hot,
                x="hours_ago",
                y="final_score",
                size="score_base" if "score_base" in df_hot.columns else "hot_score",
                hover_data=["title", "nickname"],
                color="score_burst",
                color_continuous_scale="Blues",
                title="时间衰减趋势",
            )
            fig2.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig2, use_container_width=True)


# ============================================================
# Tab 2: 发布时间优化
# ============================================================
with tab_time:
    st.subheader("📅 时段 × 周几 热度矩阵")

    df_t = df.copy()
    df_t["hour"] = df_t["publish_hour"]
    df_t["weekday"] = df_t["publish_weekday"]

    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    # Compute average engagement per hour-weekday cell
    df_t["engagement"] = (
        df_t["liked_count"] + df_t["collected_count"] + df_t["comment_count"] + df_t["share_count"]
    )

    heat_data = df_t.groupby(["weekday", "hour"])["engagement"].agg(["mean", "count"]).reset_index()
    heat_data["log_mean"] = np.log1p(heat_data["mean"])

    pivot_mean = heat_data.pivot(index="weekday", columns="hour", values="log_mean").fillna(0)
    pivot_count = heat_data.pivot(index="weekday", columns="hour", values="count").fillna(0)

    # Ensure all weekdays and hours present
    for d in range(7):
        if d not in pivot_mean.index:
            pivot_mean.loc[d] = 0
            pivot_count.loc[d] = 0
    pivot_mean = pivot_mean.sort_index()
    pivot_count = pivot_count.sort_index()

    col1, col2 = st.columns([1, 1])

    with col1:
        fig = go.Figure(
            data=go.Heatmap(
                z=pivot_mean.values,
                x=[f"{h:02d}:00" for h in range(24)],
                y=weekday_cn,
                colorscale="YlOrRd",
                text=np.round(pivot_mean.values, 1),
                texttemplate="%{text}",
                hovertemplate="%{y} %{x}<br>log(互动均值): %{z:.1f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="互动热度矩阵 (log 均值)",
            height=350,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure(
            data=go.Heatmap(
                z=pivot_count.values,
                x=[f"{h:02d}:00" for h in range(24)],
                y=weekday_cn,
                colorscale="Blues",
                text=pivot_count.values.astype(int),
                texttemplate="%{text}",
                hovertemplate="%{y} %{x}<br>帖子数: %{z}<extra></extra>",
            )
        )
        fig.update_layout(
            title="发帖数量矩阵",
            height=350,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Top vs Bottom comparison
    st.subheader("Top 30% 热门帖 vs 全部帖子 — 发布时间分布")

    col_a, col_b = st.columns(2)

    with col_a:
        threshold = df_t["engagement"].quantile(0.7)
        hot_posts = df_t[df_t["engagement"] >= threshold]

        all_hours = df_t["hour"].value_counts().reindex(range(24), fill_value=0)
        hot_hours = hot_posts["hour"].value_counts().reindex(range(24), fill_value=0)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=list(range(24)), y=all_hours.values,
            name="全部帖子", marker_color="#b0c4de", opacity=0.7,
        ))
        fig.add_trace(go.Bar(
            x=list(range(24)), y=hot_hours.values,
            name="热门帖 (Top 30%)", marker_color="#ff6b6b",
        ))
        fig.update_layout(
            title="发帖时段分布对比",
            xaxis=dict(title="小时", tickmode="linear", dtick=2),
            yaxis=dict(title="帖子数"),
            height=350,
            margin=dict(l=20, r=20, t=40, b=20),
            barmode="overlay",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        all_weekday = df_t["weekday"].value_counts().reindex(range(7), fill_value=0)
        hot_weekday = hot_posts["weekday"].value_counts().reindex(range(7), fill_value=0)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=weekday_cn, y=all_weekday.values,
            name="全部帖子", marker_color="#b0c4de", opacity=0.7,
        ))
        fig.add_trace(go.Bar(
            x=weekday_cn, y=hot_weekday.values,
            name="热门帖 (Top 30%)", marker_color="#ff6b6b",
        ))
        fig.update_layout(
            title="发帖星期分布对比",
            height=350,
            margin=dict(l=20, r=20, t=40, b=20),
            barmode="overlay",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Best time recommendation
    st.divider()
    st.subheader("💡 最佳发布时间建议")

    best_cells = heat_data.nlargest(5, "mean")
    recs = []
    for _, row in best_cells.iterrows():
        d = weekday_cn[int(row["weekday"])]
        h = int(row["hour"])
        n = int(row["count"])
        avg_eng = int(row["mean"])
        recs.append(f"**{d} {h:02d}:00~{h+1:02d}:00** — 平均互动 `{avg_eng:,}`，帖子数 `{n}`")

    for r in recs:
        st.markdown(f"- {r}")

    overall_avg = df_t["engagement"].mean()
    best_avg = best_cells["mean"].iloc[0]
    st.caption(
        f"最佳时段互动均值是最低时段的 **{best_avg / heat_data['mean'].min():.1f} 倍**，"
        f"整体平均的 **{best_avg / overall_avg:.1f} 倍**"
    )


# ============================================================
# Tab 3: 内容策略分析 (TF-IDF)
# ============================================================
with tab_content:
    st.subheader("📝 关键词热度分析")

    # Load stopwords from Supabase
    _sw_list = []
    try:
        _sw_client = db.connect()
        if _sw_client:
            _start, _limit = 0, 1000
            while True:
                _res = _sw_client.table("stopwords").select("word").range(_start, _start + _limit - 1).execute()
                if not _res.data:
                    break
                _sw_list.extend(r["word"] for r in _res.data)
                if len(_res.data) < _limit:
                    break
                _start += _limit
    except Exception:
        pass
    STOPS = set(_sw_list)

    if st.button("🔄 刷新 TF-IDF 分析"):
        st.cache_data.clear()

    @st.cache_data(ttl=86400)
    def compute_tfidf(_df):
        """title×3 + desc weighted TF-IDF, split by engagement groups."""
        df_w = _df.copy()
        df_w["engagement"] = (
            df_w["liked_count"] + df_w["collected_count"] * 2
            + df_w["comment_count"] * 3 + df_w["share_count"] * 4
        )

        # Combined text: title weighted ×3
        df_w["full_text"] = (
            (df_w["title"].fillna("") + " ") * 3 + df_w["desc"].fillna("")
        )

        # Tokenize
        all_docs = []
        for t in df_w["full_text"]:
            words = [w.strip() for w in jieba.cut(t) if len(w.strip()) >= 2 and w.strip() not in STOPS]
            all_docs.append(" ".join(words))

        # TF-IDF
        from sklearn.feature_extraction.text import TfidfVectorizer
        vectorizer = TfidfVectorizer(max_features=200, ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(all_docs)
        feature_names = vectorizer.get_feature_names_out()

        # Hot vs Cold group comparison
        top_thresh = df_w["engagement"].quantile(0.7)
        bot_thresh = df_w["engagement"].quantile(0.3)

        hot_mask = df_w["engagement"] >= top_thresh
        cold_mask = df_w["engagement"] <= bot_thresh

        hot_tfidf = np.array(tfidf_matrix[hot_mask.to_numpy()].mean(axis=0)).flatten()
        cold_tfidf = np.array(tfidf_matrix[cold_mask.to_numpy()].mean(axis=0)).flatten()
        all_tfidf = np.array(tfidf_matrix.mean(axis=0)).flatten()

        results = []
        for i, name in enumerate(feature_names):
            if hot_tfidf[i] > 0 or cold_tfidf[i] > 0:
                ratio = hot_tfidf[i] / max(cold_tfidf[i], 0.0001)
                results.append({
                    "keyword": name,
                    "hot_tfidf": round(hot_tfidf[i], 4),
                    "cold_tfidf": round(cold_tfidf[i], 4),
                    "all_tfidf": round(all_tfidf[i], 4),
                    "ratio": round(ratio, 2),
                })

        kw_df = pd.DataFrame(results)
        kw_df = kw_df.sort_values("hot_tfidf", ascending=False)
        return kw_df, len(df_w[hot_mask]), len(df_w[cold_mask])

    df_content = df.copy()
    kw_df, hot_n, cold_n = compute_tfidf(df_content)

    st.caption(f"热门组 (Top 30%): {hot_n} 篇 | 普通组 (Bottom 30%): {cold_n} 篇")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("🔥 热门帖高频词")
        top_hot = kw_df.nlargest(20, "hot_tfidf")

        fig = px.bar(
            top_hot.iloc[::-1],
            x="hot_tfidf",
            y="keyword",
            orientation="h",
            title="热门帖 TF-IDF Top 20",
            color="hot_tfidf",
            color_continuous_scale="Reds",
        )
        fig.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("📊 热度区分度 (Ratio)")
        top_ratio = kw_df.nlargest(20, "ratio")

        fig = px.bar(
            top_ratio.iloc[::-1],
            x="ratio",
            y="keyword",
            orientation="h",
            title="热门帖 / 普通帖 TF-IDF 比值",
            color="ratio",
            color_continuous_scale="RdYlGn",
        )
        fig.add_vline(x=1, line_dash="dot", line_color="gray")
        fig.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ---- 句式分析 ----
    st.subheader("❓ 句式分析：陈述 vs 疑问")

    Q_MARKERS = re.compile(r"[？?]|[吗呢吧啊]$|什么|怎么|为什么|哪|谁|如何|有没有|是不是|能不能|可不可以|咋|啥")

    df_q = df_content.copy()
    df_q["is_question"] = df_q["title"].fillna("").apply(
        lambda t: bool(Q_MARKERS.search(str(t)))
    )
    q_count = df_q["is_question"].sum()
    s_count = (~df_q["is_question"]).sum()

    df_q["engagement"] = (
        df_q["liked_count"] + df_q["collected_count"] * 2
        + df_q["comment_count"] * 3 + df_q["share_count"] * 4
    )

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.metric("疑问句帖数", q_count)
    with col_b:
        st.metric("陈述句帖数", s_count)
    with col_c:
        ratio_str = f"{q_count / max(s_count, 1):.1%}"
        st.metric("疑问占比", ratio_str)

    col_l, col_r = st.columns(2)

    with col_l:
        # Average engagement by sentence type
        q_avg = df_q[df_q["is_question"]]["engagement"].mean()
        s_avg = df_q[~df_q["is_question"]]["engagement"].mean()

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=["陈述句", "疑问句"],
            y=[s_avg, q_avg],
            marker_color=["#b0c4de", "#ff6b6b"],
            text=[f"{s_avg:,.0f}", f"{q_avg:,.0f}"],
            textposition="outside",
        ))
        fig.update_layout(
            title="平均互动量对比",
            height=400,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        # Hot vs Cold group: question ratio
        top_thresh = df_q["engagement"].quantile(0.7)
        bot_thresh = df_q["engagement"].quantile(0.3)

        hot_q_ratio = df_q[df_q["engagement"] >= top_thresh]["is_question"].mean()
        cold_q_ratio = df_q[df_q["engagement"] <= bot_thresh]["is_question"].mean()
        all_q_ratio = df_q["is_question"].mean()

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=["热门组", "全部", "普通组"],
            y=[hot_q_ratio * 100, all_q_ratio * 100, cold_q_ratio * 100],
            marker_color=["#ff6b6b", "#fdcb6e", "#b0c4de"],
            text=[f"{hot_q_ratio:.1%}", f"{all_q_ratio:.1%}", f"{cold_q_ratio:.1%}"],
            textposition="outside",
        ))
        fig.update_layout(
            title="疑问句占比 (热门 vs 普通)",
            yaxis=dict(title="疑问句占比 (%)"),
            height=400,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    if hot_q_ratio > cold_q_ratio * 1.3:
        st.success(f"疑问句在热门组占比 **{hot_q_ratio:.1%}**，高出普通组 **{cold_q_ratio:.1%}** 的 **{hot_q_ratio / max(cold_q_ratio, 0.01):.1f}** 倍 —— 疑问式标题可能更有吸引力")
    elif cold_q_ratio > hot_q_ratio * 1.3:
        st.info(f"陈述句在普通组占比更高，疑问句在热门组反而少，数据不支持疑问式标题优势")
    else:
        st.info("疑问句和陈述句在热度上无明显差异")

    st.divider()

    # ---- 帖子格式分析 ----
    st.subheader("📐 帖子格式分析：图片数 / 标题字数 / 描述字数")

    df["image_count"] = df["image_list"].fillna("").apply(
        lambda x: len([u for u in str(x).split(",") if u.strip()]) if x else 0
    )
    df["title_len"] = df["title"].fillna("").apply(len)
    df["desc_len"] = df["desc"].fillna("").apply(len)
    df["engagement"] = (
        df["liked_count"] + df["collected_count"] * 2
        + df["comment_count"] * 3 + df["share_count"] * 4
    )
    top_thresh = df["engagement"].quantile(0.7)
    hot_mask = df["engagement"] >= top_thresh

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("**图片数量**")
        all_imgs = df["image_count"].value_counts().reindex(range(0, 19), fill_value=0)
        hot_imgs = df[hot_mask]["image_count"].value_counts().reindex(range(0, 19), fill_value=0)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=list(range(19)), y=all_imgs.values, name="全部", marker_color="#b0c4de", opacity=0.7))
        fig.add_trace(go.Bar(x=list(range(19)), y=hot_imgs.values, name="热门 (Top 30%)", marker_color="#ff6b6b"))
        fig.update_layout(title="图片数量分布", xaxis=dict(title="图片数", dtick=2), yaxis=dict(title="帖子数"), height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay")
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown("**标题字数**")
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=df["title_len"], name="全部", marker_color="#b0c4de", opacity=0.7, nbinsx=20))
        fig.add_trace(go.Histogram(x=df[hot_mask]["title_len"], name="热门 (Top 30%)", marker_color="#ff6b6b", nbinsx=20))
        fig.update_layout(title="标题字数分布", xaxis=dict(title="字数"), yaxis=dict(title="帖子数"), height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay")
        st.plotly_chart(fig, use_container_width=True)

    with col_c:
        st.markdown("**描述字数**")
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=df["desc_len"], name="全部", marker_color="#b0c4de", opacity=0.7, xbins=dict(size=10)))
        fig.add_trace(go.Histogram(x=df[hot_mask]["desc_len"], name="热门 (Top 30%)", marker_color="#ff6b6b", xbins=dict(size=10)))
        fig.update_layout(title="描述字数分布", xaxis=dict(title="字数"), yaxis=dict(title="帖子数"), height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay")
        st.plotly_chart(fig, use_container_width=True)

    # Summary stats
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("热门帖平均图片数", f"{df[hot_mask]['image_count'].mean():.1f} 张")
    with col_b:
        st.metric("热门帖平均标题字数", f"{df[hot_mask]['title_len'].mean():.0f} 字")
    with col_c:
        st.metric("热门帖平均描述字数", f"{df[hot_mask]['desc_len'].mean():.0f} 字")

    st.divider()

    st.subheader("💡 关键词建议")
    ratio_words = kw_df[kw_df["ratio"] > 1.5].nlargest(10, "hot_tfidf")
    if not ratio_words.empty:
        st.markdown("**与高热度相关的关键词：**")
        for _, r in ratio_words.iterrows():
            st.markdown(
                f"- **{r['keyword']}** — 热门 TF-IDF `{r['hot_tfidf']:.4f}` "
                f"(×{r['ratio']:.1f} vs 普通帖)"
            )
    else:
        st.info("暂无显著区分词，数据积累后会更明显")

    with st.expander("📄 完整关键词表"):
        st.dataframe(kw_df, use_container_width=True, hide_index=True)


# ============================================================
# Tab 4: 同行分析
# ============================================================
MY_SHOP_USER_ID = "5d0cf92a0000000012020861"
MY_SHOP_NAME = "wireless shop无线商店"

with tab_peers:
    if creators.empty:
        st.warning("暂无创作者数据，请先爬取同行数据")
        st.stop()

    import json

    # --- 数据预处理 ---
    creators_df = creators.copy()
    for col in ["fans", "follows", "interaction"]:
        if col in creators_df.columns:
            creators_df[col] = creators_df[col].apply(parse_wan)

    # 统计每个创作者的帖子数
    post_counts = df["user_id"].value_counts() if "user_id" in df.columns else pd.Series()
    creators_df["post_count"] = creators_df["user_id"].map(post_counts).fillna(0).astype(int)

    # ---- 从帖子 (xhs_note) 构建标签数据 ----
    # xhs_note.tag_list 是逗号分隔的字符串: "tag1,tag2,tag3"
    post_tag_rows = []
    if "user_id" in df.columns and "tag_list" in df.columns:
        for _, note in df.iterrows():
            uid = note.get("user_id")
            raw_tags = note.get("tag_list", "")
            if not uid or pd.isna(raw_tags) or not str(raw_tags).strip():
                continue
            tags = [t.strip() for t in str(raw_tags).split(",") if t.strip()]
            for tag in tags:
                post_tag_rows.append({
                    "user_id": uid,
                    "tag_name": tag,
                })

    post_tags_df = pd.DataFrame(post_tag_rows)

    # --- KPI 卡片 ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("创作者总数", len(creators_df))
    total_posts = creators_df["post_count"].sum()
    col2.metric("帖子总数", total_posts)
    col3.metric("平均粉丝", f"{creators_df['fans'].mean():,.0f}")
    col4.metric("平均互动", f"{creators_df['interaction'].mean():,.0f}")

    st.divider()

    # --- 我方店铺 (固定) ---
    my_row = creators_df[creators_df["user_id"] == MY_SHOP_USER_ID]
    my_me = my_row.iloc[0] if not my_row.empty else None
    my_uid = MY_SHOP_USER_ID
    my_nickname = MY_SHOP_NAME

    # --- 同行选择器 (排除我方) ---
    peer_options = creators_df[creators_df["user_id"] != MY_SHOP_USER_ID][["user_id", "nickname", "post_count"]].copy()
    peer_options["label"] = peer_options.apply(
        lambda r: f"{r['nickname']} (帖子:{r['post_count']}) [{r['user_id'][:12]}...]",
        axis=1,
    )
    peer_options = peer_options.sort_values("post_count", ascending=False)

    # Default to chilltto if available
    peer_default_idx = 0
    chilltto_idx = peer_options[peer_options["nickname"].str.contains("chilltto", case=False, na=False)].index
    if not chilltto_idx.empty:
        peer_default_idx = peer_options.index.get_loc(chilltto_idx[0])

    peer_label = st.selectbox(
        "👥 选择同行进行对比",
        peer_options["label"].tolist(),
        index=peer_default_idx,
        key="peer_selector",
    )
    peer_uid = peer_options[peer_options["label"] == peer_label]["user_id"].iloc[0]
    peer_nickname = peer_options[peer_options["label"] == peer_label]["nickname"].iloc[0]
    peer_row = creators_df[creators_df["user_id"] == peer_uid]
    peer_me = peer_row.iloc[0] if not peer_row.empty else None

    # ============================================================
    # 📌 我方店铺帖子
    # ============================================================
    st.subheader(f"🏠 我方店铺 · {MY_SHOP_NAME}")

    my_notes = df[df["user_id"] == my_uid].copy()
    if not my_notes.empty:
        my_notes["publish_dt"] = pd.to_datetime(my_notes["time"], unit="ms")
        my_notes["engagement"] = (
            my_notes["liked_count"] + my_notes["collected_count"] * 2
            + my_notes["comment_count"] * 3 + my_notes["share_count"] * 4
        )
        my_notes_display = my_notes.sort_values("publish_dt", ascending=False)[
            ["title", "publish_dt", "liked_count", "collected_count",
             "comment_count", "share_count", "engagement", "note_url"]
        ].copy()
        my_notes_display["publish_dt"] = my_notes_display["publish_dt"].dt.strftime("%Y-%m-%d %H:%M")

        st.dataframe(
            my_notes_display,
            column_config={
                "title": "标题",
                "publish_dt": "发布时间",
                "liked_count": "点赞",
                "collected_count": "收藏",
                "comment_count": "评论",
                "share_count": "分享",
                "engagement": st.column_config.NumberColumn("互动分", format="%.0f"),
                "note_url": st.column_config.LinkColumn("链接"),
            },
            use_container_width=True,
            hide_index=True,
            height=350,
        )
        st.caption(f"共 {len(my_notes)} 条帖子")
    else:
        st.info("暂无我方店铺帖子数据")

    st.divider()

    # ============================================================
    # 📌 同行帖子
    # ============================================================
    st.subheader(f"👥 同行 · {peer_nickname}")

    peer_notes = df[df["user_id"] == peer_uid].copy()
    if not peer_notes.empty and peer_me is not None:
        peer_notes["publish_dt"] = pd.to_datetime(peer_notes["time"], unit="ms")
        peer_notes["engagement"] = (
            peer_notes["liked_count"] + peer_notes["collected_count"] * 2
            + peer_notes["comment_count"] * 3 + peer_notes["share_count"] * 4
        )
        peer_notes_display = peer_notes.sort_values("publish_dt", ascending=False)[
            ["title", "publish_dt", "liked_count", "collected_count",
             "comment_count", "share_count", "engagement", "note_url"]
        ].copy()
        peer_notes_display["publish_dt"] = peer_notes_display["publish_dt"].dt.strftime("%Y-%m-%d %H:%M")

        st.dataframe(
            peer_notes_display,
            column_config={
                "title": "标题",
                "publish_dt": "发布时间",
                "liked_count": "点赞",
                "collected_count": "收藏",
                "comment_count": "评论",
                "share_count": "分享",
                "engagement": st.column_config.NumberColumn("互动分", format="%.0f"),
                "note_url": st.column_config.LinkColumn("链接"),
            },
            use_container_width=True,
            hide_index=True,
            height=350,
        )
        st.caption(f"共 {len(peer_notes)} 条帖子")
    else:
        st.info("暂无同行帖子数据")

    st.divider()

    # ============================================================
    # Section 1: 帖子画像分析 (基于 xhs_note)
    # ============================================================
    st.subheader("📊 帖子画像分析")

    col_a, col_b = st.columns(2)

    with col_a:
        # 各创作者帖子数量分布
        top_posters = creators_df.nlargest(15, "post_count")[
            ["nickname", "post_count"]
        ].sort_values("post_count")
        fig = px.bar(
            x=top_posters["post_count"], y=top_posters["nickname"],
            orientation="h",
            title="创作者帖子数 Top 15",
            labels={"x": "帖子数", "y": ""},
            color=top_posters["post_count"],
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        # 帖子类型分布 (normal vs video)
        if "type" in df.columns:
            type_counts = df["type"].value_counts()
            type_labels = {"normal": "图文", "video": "视频"}
            type_names = [type_labels.get(t, t) for t in type_counts.index]
            fig = px.pie(
                values=type_counts.values, names=type_names,
                title="帖子类型分布",
            )
            fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("无帖子类型数据")

    st.divider()

    # 帖子标签频率 Top 25
    if not post_tags_df.empty:
        st.subheader("🏷️ 帖子标签热度 Top 25")
        tag_freq = post_tags_df["tag_name"].value_counts().head(25)

        col_a, col_b = st.columns(2)

        with col_a:
            fig = px.bar(
                x=tag_freq.values, y=tag_freq.index,
                orientation="h",
                title="全部帖子标签 Top 25",
                labels={"x": "出现次数", "y": "标签"},
                color=tag_freq.values,
                color_continuous_scale="Reds",
            )
            fig.update_layout(height=500, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            # 我方标签 vs 同行标签
            my_tags_series = post_tags_df[post_tags_df["user_id"] == my_uid]["tag_name"].value_counts().head(20)
            others_tags_series = post_tags_df[post_tags_df["user_id"] != my_uid]["tag_name"].value_counts()

            # 按同行热度排序的我方标签
            my_tags_ranked = my_tags_series.index.tolist()
            my_tags_with_freq = [
                (t, my_tags_series.get(t, 0), others_tags_series.get(t, 0))
                for t in my_tags_ranked
            ]
            my_tags_with_freq.sort(key=lambda x: x[2], reverse=True)
            top_my_tags = my_tags_with_freq[:20]

            tag_labels = [t[0] for t in top_my_tags]
            my_vals = [t[1] for t in top_my_tags]
            others_vals = [t[2] for t in top_my_tags]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=tag_labels, x=others_vals,
                orientation="h", name="同行使用次数",
                marker_color="#b0c4de",
            ))
            fig.add_trace(go.Bar(
                y=tag_labels, x=my_vals,
                orientation="h", name="🏠 我方使用次数",
                marker_color="#ff6b6b",
            ))
            fig.update_layout(
                title="🏠 我方 标签 vs 同行 (按同行热度排序)",
                xaxis=dict(title="出现次数"),
                height=500,
                margin=dict(l=20, r=20, t=40, b=20),
                barmode="overlay",
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("帖子暂无标签数据")

    st.divider()

    # ============================================================
    # Section 2: 帖子标签交叉分析 (基于帖子)
    # ============================================================
    st.subheader("🔗 帖子标签交叉分析")

    if not post_tags_df.empty and post_tags_df["user_id"].nunique() >= 3:
        # 为每个创作者构建标签列表（去重）
        creator_tag_groups = post_tags_df.groupby("user_id").apply(
            lambda g: list(g["tag_name"].unique())
        )
        creator_tag_groups = creator_tag_groups[creator_tag_groups.apply(len) >= 2]

        if len(creator_tag_groups) >= 5:
            cooccur = {}
            tag_freq_all = {}
            for tags in creator_tag_groups:
                for t in tags:
                    tag_freq_all[t] = tag_freq_all.get(t, 0) + 1
                for i in range(len(tags)):
                    for j in range(i + 1, len(tags)):
                        a, b = sorted([tags[i], tags[j]])
                        cooccur[(a, b)] = cooccur.get((a, b), 0) + 1

            top_tags = sorted(tag_freq_all, key=tag_freq_all.get, reverse=True)[:15]
            matrix = pd.DataFrame(0, index=top_tags, columns=top_tags)
            for (a, b), cnt in cooccur.items():
                if a in top_tags and b in top_tags:
                    matrix.loc[a, b] = cnt
                    matrix.loc[b, a] = cnt
            for t in top_tags:
                matrix.loc[t, t] = tag_freq_all[t]

            col_a, col_b = st.columns([1.2, 1])

            with col_a:
                fig = go.Figure(
                    data=go.Heatmap(
                        z=matrix.values,
                        x=top_tags,
                        y=top_tags,
                        colorscale="YlOrRd",
                        text=matrix.values.astype(int),
                        texttemplate="%{text}",
                        hovertemplate="%{x} ↔ %{y}<br>共现: %{z}<extra></extra>",
                    )
                )
                fig.update_layout(
                    title="帖子标签共现矩阵 (Top 15)",
                    height=550,
                    margin=dict(l=20, r=20, t=40, b=80),
                    xaxis=dict(tickangle=45),
                )
                st.plotly_chart(fig, use_container_width=True)

            with col_b:
                top_pairs = sorted(cooccur.items(), key=lambda x: x[1], reverse=True)[:10]
                pair_labels = [f"{a}\n↔\n{b}" for (a, b), _ in top_pairs]
                pair_counts = [cnt for _, cnt in top_pairs]

                fig = px.bar(
                    x=pair_counts, y=pair_labels,
                    orientation="h",
                    title="Top 10 标签组合",
                    labels={"x": "共现次数", "y": "标签对"},
                    color=pair_counts,
                    color_continuous_scale="Purples",
                )
                fig.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("有 ≥2 个标签的创作者不足 5 位，无法进行共现分析")
    else:
        st.info("需要至少 3 位有帖子标签的创作者才能进行交叉分析")

    st.divider()

    # ============================================================
    # Section 3: 帖子标签对比
    # ============================================================
    if not post_tags_df.empty:
        st.subheader("🏷️ 帖子标签对比：🏠 我方 vs 👥 同行")

        my_tag_freq = post_tags_df[post_tags_df["user_id"] == my_uid]["tag_name"].value_counts()
        peer_tag_freq = post_tags_df[post_tags_df["user_id"] == peer_uid]["tag_name"].value_counts()

        diff_data = []
        for tag in my_tag_freq.head(15).index:
            diff_data.append({
                "tag": tag,
                "my_count": int(my_tag_freq.get(tag, 0)),
                "peer_count": int(peer_tag_freq.get(tag, 0)),
            })
        diff_df = pd.DataFrame(diff_data)

        if not diff_df.empty:
            st.markdown(
                f"**🏠 我方 · {MY_SHOP_NAME}** · "
                f"帖子 {len(my_notes)} 条 · "
                f"**👥 {peer_nickname}** · "
                f"帖子 {len(peer_notes)} 条"
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=diff_df["tag"], x=diff_df["peer_count"],
                orientation="h", name=f"👥 {peer_nickname}",
                marker_color="#b0c4de",
            ))
            fig.add_trace(go.Bar(
                y=diff_df["tag"], x=diff_df["my_count"],
                orientation="h", name="🏠 我方",
                marker_color="#ff6b6b",
            ))
            fig.update_layout(
                title=f"帖子标签对比：🏠 我方 vs 👥 {peer_nickname}",
                xaxis=dict(title="出现次数"),
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
                barmode="overlay",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("我方帖子暂无标签")
    else:
        st.info("无帖子标签数据")

