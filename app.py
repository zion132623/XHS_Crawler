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
            st.session_state.hot_all = db.query_hot_posts(client)
            st.session_state.hot_normal = db.query_hot_posts(client, post_type="normal")
            st.session_state.hot_video = db.query_hot_posts(client, post_type="video")

    st.info(
        f"📊 帖子 {st.session_state.db_stats.get('xhs_note', 0)} 条 "
        f"| 评论 {st.session_state.db_stats['comments']} 条"
    )

    if auth.is_admin():
        st.page_link("pages/admin.py", label="🔧 管理后台", icon="🔧")
        st.page_link("pages/stopwords.py", label="📝 停用词管理", icon="📝")

    st.divider()
    st.caption(f"👤 {auth.get_current_user().email}")
    st.caption(f"🔑 {st.session_state.get('role', 'viewer')}")
    if st.button("🚪 登出", use_container_width=True):
        auth.logout()
        st.rerun()

df = st.session_state.xhs_note
comments = st.session_state.comments if "comments" in st.session_state else None
hot_all = st.session_state.get("hot_all")

# ==================== Tab 页 ====================
tab_hot, tab_time, tab_content, tab_comments = st.tabs(
    ["🔥 热帖排行", "⏰ 发布时间优化", "📝 内容策略分析", "💬 评论分析"]
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
                 "hot_score", "score_burst", "keyword_count", "final_score"]
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

    # Load stopwords from file
    import os as _os
    _sw_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "stopwords.txt")
    _sw_list = []
    if _os.path.exists(_sw_path):
        with open(_sw_path, "r", encoding="utf-8") as _f:
            _sw_list = [line.strip() for line in _f if line.strip()]
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
# Tab 4: 评论分析
# ============================================================
with tab_comments:
    if comments is not None and len(comments) > 0:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("评论总数", len(comments))
        col2.metric("总点赞", f"{comments['like_count'].sum():,}")
        col3.metric("涉及帖子", comments["note_id"].nunique())
        col4.metric("评论用户", comments["user_id"].nunique())

        st.divider()

        col_left, col_right = st.columns(2)

        with col_left:
            top_n_comments = st.slider("显示热门评论 Top", 5, 50, 20)

            top_c = comments.nlargest(top_n_comments, "like_count")[
                ["content", "like_count", "nickname"]
            ].copy()
            top_c["short"] = top_c["content"].str[:30] + "..."
            top_c = top_c.iloc[::-1]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=[f"{s}<br><sup>{n}</sup>" for s, n in zip(top_c["short"], top_c["nickname"])],
                x=top_c["like_count"],
                orientation="h",
                marker_color=top_c["like_count"],
                marker_colorscale="viridis",
                text=top_c["like_count"],
                textposition="outside",
            ))
            fig.update_layout(height=700, margin=dict(l=20, r=40, t=20, b=20), showlegend=False)
            fig.update_xaxes(title="点赞数")
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            ip_dist = comments["ip_location"].value_counts().head(15)
            fig = px.pie(values=ip_dist.values, names=ip_dist.index, title="评论 IP 属地分布")
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        if "create_time_dt" in comments.columns:
            comments_copy = comments.copy()
            comments_copy["comment_date"] = comments_copy["create_time_dt"].dt.date
            daily_comments = comments_copy["comment_date"].value_counts().sort_index()
            fig = px.bar(
                x=daily_comments.index, y=daily_comments.values,
                title="每日评论数趋势", labels={"x": "日期", "y": "评论数"},
            )
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("📄 评论原始数据"):
            st.dataframe(
                comments.sort_values("like_count", ascending=False),
                use_container_width=True, hide_index=True,
            )
    else:
        st.warning("未加载评论数据")