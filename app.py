import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import sys
import importlib

# Try st.secrets first (Streamlit Cloud), fall back to .env (local)
try:
    os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
    os.environ["SUPABASE_ANON_KEY"] = st.secrets["SUPABASE_ANON_KEY"]
except Exception:
    from dotenv import load_dotenv
    load_dotenv()

import db
import auth

# Analytics modules — force-reload each rerun so Streamlit hot-reload picks up fixes
for _mod_name in [
    "analytics.common", "analytics.hot_ranking",
    "analytics.time_optimization", "analytics.content_strategy",
    "analytics.peer_analysis", "analytics.comments",
]:
    if _mod_name in sys.modules:
        importlib.reload(sys.modules[_mod_name])

import analytics.common
import analytics.hot_ranking as hot_mod
import analytics.time_optimization as time_mod
import analytics.content_strategy as content_mod
import analytics.peer_analysis as peer_mod
import analytics.comments as comments_mod
from analytics.common import clean_numeric_cols, enrich_time_cols


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

    # ---- 数据预处理 ----
    for _col in ["like_count", "sub_comment_count"]:
        if _col in note_comments.columns:
            note_comments[_col] = note_comments[_col].apply(db._safe_int)

    if "create_time" in note_comments.columns:
        note_comments["评论时间"] = pd.to_datetime(
            note_comments["create_time"], unit="ms", errors="coerce"
        ).dt.strftime("%Y-%m-%d %H:%M")

    note_comments["display_content"] = note_comments["content"].apply(
        lambda x: x if (x and str(x).strip()) else "[图片]"
    )
    note_comments["has_pic"] = note_comments["pictures"].apply(
        lambda p: bool(p and str(p) not in ('""', '[]', '') and 'http' in str(p))
    )

    # ---- 顶部统计 ----
    col1, col2, col3 = st.columns(3)
    col1.metric("评论总数", len(note_comments))
    col2.metric("总点赞", f"{note_comments['like_count'].astype(int).sum():,}")
    col3.metric("评论用户", note_comments["user_id"].nunique())

    st.divider()

    display_cols = [
        c for c in ["display_content", "has_pic", "like_count", "nickname",
                     "ip_location", "评论时间", "sub_comment_count"]
        if c in note_comments.columns
    ]

    st.dataframe(
        note_comments.sort_values("like_count", ascending=False)[display_cols],
        column_config={
            "display_content": "评论内容",
            "has_pic": st.column_config.CheckboxColumn("有图"),
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


def _init_hot_ranking(client):
    """读宽表，表空则计算三种 post_type 并写入."""
    try:
        loaded = db.load_hot_ranking(client)
        if not loaded.empty:
            return _split_ranking(loaded)
    except Exception as e:
        st.warning(f"读表失败: {e}")

    df_all = db.query_hot_posts(client)
    df_normal = db.query_hot_posts(client, post_type="normal")
    df_video = db.query_hot_posts(client, post_type="video")
    try:
        db.save_hot_ranking(client, df_all, df_normal, df_video)
    except Exception as e:
        st.warning(f"写表失败: {e}")
    return {"hot_all": df_all, "hot_normal": df_normal, "hot_video": df_video}


def _split_ranking(wide_df):
    """宽表拆回三个 DataFrame（按 rank_all/rank_normal/rank_video 过滤排序）."""
    import pandas as pd

    def _extract(rank_col):
        df = wide_df[wide_df[rank_col].notna()].copy()
        df = df.sort_values(rank_col)
        df = df.drop(columns=["id", "entry_time", "exit_time",
                              "rank_all", "rank_normal", "rank_video"], errors="ignore")
        return df

    return {
        "hot_all": _extract("rank_all"),
        "hot_normal": _extract("rank_normal"),
        "hot_video": _extract("rank_video"),
    }


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
            st.session_state.all_comments = comments_mod.load_all_comments(client)
            hot_maps = _init_hot_ranking(client)
            st.session_state.hot_all = hot_maps["hot_all"]
            st.session_state.hot_normal = hot_maps["hot_normal"]
            st.session_state.hot_video = hot_maps["hot_video"]
            st.session_state.creators = db.query_creators(client)

    st.info(
        f"📊 帖子 {st.session_state.db_stats.get('xhs_note', 0)} 条 "
        f"| 评论 {st.session_state.db_stats['comments']} 条 "
        f"| 创作者 {len(st.session_state.creators)} 位"
    )

    if st.button("🔄 刷新热帖排行", use_container_width=True):
        client = st.session_state.get("db_conn") or db.connect()
        with st.spinner("重新计算热帖..."):
            df_all = db.query_hot_posts(client)
            df_normal = db.query_hot_posts(client, post_type="normal")
            df_video = db.query_hot_posts(client, post_type="video")
            try:
                db.save_hot_ranking(client, df_all, df_normal, df_video)
            except Exception as e:
                st.warning(f"写表失败: {e}")
            st.session_state.hot_all = df_all
            st.session_state.hot_normal = df_normal
            st.session_state.hot_video = df_video
        st.rerun()

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


def _render_tab_safe(tab_name, render_func):
    """用 try/except 包裹 tab 渲染，失败不影响其他 tab."""
    try:
        render_func()
    except Exception as e:
        st.error(f"**{tab_name}** 模块加载失败: {e}")
        st.caption("请检查数据源或联系管理员")


# ==================== Tab 页 ====================
tab_hot, tab_time, tab_content, tab_peers, tab_comments = st.tabs(
    ["🔥 热帖排行", "⏰ 发布时间优化", "📝 内容策略分析", "🔍 同行分析", "💬 评论分析"]
)


# ============================================================
# Tab 1: 热帖排行
# ============================================================
def _render_tab_hot():
    if hot_all is None or hot_all.empty:
        st.warning("暂无热帖数据")
        return

    post_type = st.selectbox("帖子类型", ["全部", "图文 (normal)", "视频 (video)"])

    df_hot = hot_mod.filter_hot_df(st.session_state, post_type)
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
    fig_kw, kw_series = hot_mod.build_kw_bar_chart(df_hot)
    if not kw_series.empty and kw_series.nunique() > 0:
        st.plotly_chart(fig_kw, use_container_width=True)
    else:
        st.info("暂无关键词数据")

    # Multi-keyword posts from ALL notes
    multi_df, multi_count, total_count = hot_mod.build_multi_kw_table(df)
    st.markdown(f"🔗 **多关键词帖子 · 全部** ({multi_count} / {total_count})")
    if multi_count > 0:
        st.dataframe(
            multi_df,
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

    # Comments viewer
    st.subheader("💬 查看笔记评论")
    note_opts_cols = [c for c in ["note_id", "title", "nickname", "comment_count", "note_url"] if c in df_hot.columns]
    note_options = df_hot[note_opts_cols].copy()
    commented_ids = st.session_state.get("commented_note_ids", set())
    if commented_ids:
        note_options = note_options[note_options["note_id"].isin(commented_ids)]
    if note_options.empty:
        st.info("暂无有评论的帖子")
    else:
        note_options["label"] = note_options.apply(
            lambda r: f"[{r['comment_count']}评] {str(r['title'])[:50]} — @{r['nickname']} ({str(r['note_id'])[:12]}...)",
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

    view_mode = st.radio("榜单切换", ["综合榜", "热门榜", "潜力榜"], horizontal=True)

    sort_map = {"综合榜": "final_score", "热门榜": "hot_score", "潜力榜": "score_burst"}
    sort_col = sort_map[view_mode]

    display = df_hot.sort_values(sort_col, ascending=False).head(20)

    col_left, col_right = st.columns([1.2, 1])

    with col_left:
        st.subheader("📋 排行榜")
        table_data = hot_mod.build_ranking_table(display)
        st.dataframe(
            table_data,
            column_config=hot_mod.RANKING_COLUMN_CONFIG,
            use_container_width=True,
            hide_index=True,
            height=700,
        )

    with col_right:
        st.subheader("热门 vs 潜力")
        fig = hot_mod.build_hot_vs_burst_scatter(df_hot)
        st.plotly_chart(fig, use_container_width=True)

        fig2 = hot_mod.build_time_decay_scatter(df_hot)
        st.plotly_chart(fig2, use_container_width=True)


# ============================================================
# Tab 2: 发布时间优化
# ============================================================
def _render_tab_time():
    st.subheader("📅 时段 × 周几 热度矩阵")

    pivot_mean, pivot_count = time_mod.build_heatmap_matrices(df)

    weekday_cn = time_mod.WEEKDAY_CN

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
    fig_hour, fig_weekday = time_mod.build_distribution_comparison(df)

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(fig_hour, use_container_width=True)
    with col_b:
        st.plotly_chart(fig_weekday, use_container_width=True)

    # Best time recommendation
    st.divider()
    st.subheader("💡 最佳发布时间建议")

    recs, mult_worst, mult_overall = time_mod.get_best_time_recommendations(df)

    for r in recs:
        st.markdown(
            f"- **{r['day']} {r['hour_start']:02d}:00~{r['hour_end']:02d}:00** "
            f"— 平均互动 `{r['avg_engagement']:,}`，帖子数 `{r['post_count']}`"
        )

    st.caption(
        f"最佳时段互动均值是最低时段的 **{mult_worst:.1f} 倍**，"
        f"整体平均的 **{mult_overall:.1f} 倍**"
    )


# ============================================================
# Tab 3: 内容策略分析 (TF-IDF)
# ============================================================
def _render_tab_content():
    st.subheader("📝 关键词热度分析")

    if st.button("🔄 刷新 TF-IDF 分析"):
        st.cache_data.clear()

    @st.cache_data(ttl=86400)
    def _cached_tfidf(_df):
        return content_mod.compute_tfidf(_df)

    df_content = df.copy()
    kw_df, hot_n, cold_n = _cached_tfidf(df_content)

    st.caption(f"热门组 (Top 30%): {hot_n} 篇 | 普通组 (Bottom 30%): {cold_n} 篇")

    fig_hot, fig_ratio = content_mod.build_tfidf_bar_charts(kw_df)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("🔥 热门帖高频词")
        st.plotly_chart(fig_hot, use_container_width=True)

    with col_b:
        st.subheader("📊 热度区分度 (Ratio)")
        st.plotly_chart(fig_ratio, use_container_width=True)

    st.divider()

    # Sentence type analysis
    st.subheader("❓ 句式分析：陈述 vs 疑问")
    q_result = content_mod.analyze_question_type(df_content)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("疑问句帖数", q_result["q_count"])
    with col_b:
        st.metric("陈述句帖数", q_result["s_count"])
    with col_c:
        st.metric("疑问占比", f"{q_result['q_ratio']:.1%}")

    col_l, col_r = st.columns(2)
    with col_l:
        st.plotly_chart(q_result["fig_avg"], use_container_width=True)
    with col_r:
        st.plotly_chart(q_result["fig_ratio"], use_container_width=True)

    hot_q = q_result["hot_q_ratio"]
    cold_q = q_result["cold_q_ratio"]
    if hot_q > cold_q * 1.3:
        st.success(f"疑问句在热门组占比 **{hot_q:.1%}**，高出普通组 **{cold_q:.1%}** 的 **{hot_q / max(cold_q, 0.01):.1f}** 倍 —— 疑问式标题可能更有吸引力")
    elif cold_q > hot_q * 1.3:
        st.info(f"陈述句在普通组占比更高，疑问句在热门组反而少，数据不支持疑问式标题优势")
    else:
        st.info("疑问句和陈述句在热度上无明显差异")

    st.divider()

    # Post format analysis
    st.subheader("📐 帖子格式分析：图片数 / 标题字数 / 描述字数")
    fmt_result = content_mod.analyze_post_format(df)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**图片数量**")
        st.plotly_chart(fmt_result["fig_imgs"], use_container_width=True)
    with col_b:
        st.markdown("**标题字数**")
        st.plotly_chart(fmt_result["fig_title"], use_container_width=True)
    with col_c:
        st.markdown("**描述字数**")
        st.plotly_chart(fmt_result["fig_desc"], use_container_width=True)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("热门帖平均图片数", f"{fmt_result['hot_avg_imgs']:.1f} 张")
    with col_b:
        st.metric("热门帖平均标题字数", f"{fmt_result['hot_avg_title_len']:.0f} 字")
    with col_c:
        st.metric("热门帖平均描述字数", f"{fmt_result['hot_avg_desc_len']:.0f} 字")

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
def _render_tab_peers():
    if creators.empty:
        st.warning("暂无创作者数据，请先爬取同行数据")
        return

    MY_UID = peer_mod.MY_SHOP_USER_ID
    MY_NAME = peer_mod.MY_SHOP_NAME

    creators_df = peer_mod.preprocess_creator_data(df, creators)

    # KPI cards
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("创作者总数", len(creators_df))
    col2.metric("帖子总数", creators_df["post_count"].sum())
    col3.metric("平均粉丝", f"{creators_df['fans'].mean():,.0f}")
    col4.metric("平均互动", f"{creators_df['interaction'].mean():,.0f}")

    st.divider()

    # Peer selector
    peer_options = creators_df[creators_df["user_id"] != MY_UID][["user_id", "nickname", "post_count"]].copy()
    peer_options["label"] = peer_options.apply(
        lambda r: f"{r['nickname']} (帖子:{r['post_count']}) [{str(r['user_id'])[:12]}...]",
        axis=1,
    )
    peer_options = peer_options.sort_values("post_count", ascending=False)

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

    # My shop notes
    st.subheader(f"🏠 我方店铺 · {MY_NAME}")
    my_notes = df[df["user_id"] == MY_UID].copy()
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

    # Peer notes
    st.subheader(f"👥 同行 · {peer_nickname}")
    peer_notes = df[df["user_id"] == peer_uid].copy()
    if not peer_notes.empty:
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

    # Post profiling
    st.subheader("📊 帖子画像分析")

    col_a, col_b = st.columns(2)
    with col_a:
        fig = peer_mod.build_creator_post_count_chart(creators_df)
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        if "type" in df.columns:
            fig = peer_mod.build_type_distribution_chart(df)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("无帖子类型数据")

    st.divider()

    # Tag analysis
    post_tags_df = peer_mod.build_post_tags_df(df)

    if not post_tags_df.empty:
        st.subheader("🏷️ 帖子标签热度 Top 25")
        fig_all_tags, fig_my_tags = peer_mod.build_tag_frequency_charts(post_tags_df, MY_UID, MY_NAME)

        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(fig_all_tags, use_container_width=True)
        with col_b:
            st.plotly_chart(fig_my_tags, use_container_width=True)
    else:
        st.info("帖子暂无标签数据")

    st.divider()

    # Tag co-occurrence
    st.subheader("🔗 帖子标签交叉分析")

    if not post_tags_df.empty and post_tags_df["user_id"].nunique() >= 3:
        fig_matrix, fig_pairs = peer_mod.build_tag_cooccurrence(post_tags_df)
        if fig_matrix is not None:
            col_a, col_b = st.columns([1.2, 1])
            with col_a:
                st.plotly_chart(fig_matrix, use_container_width=True)
            with col_b:
                st.plotly_chart(fig_pairs, use_container_width=True)
        else:
            st.info("有 ≥2 个标签的创作者不足 5 位，无法进行共现分析")
    else:
        st.info("需要至少 3 位有帖子标签的创作者才能进行交叉分析")

    st.divider()

    # My vs peer tag comparison
    if not post_tags_df.empty:
        st.subheader("🏷️ 帖子标签对比：🏠 我方 vs 👥 同行")
        fig = peer_mod.build_my_vs_peer_tag_comparison(
            post_tags_df, MY_UID, MY_NAME, peer_uid, peer_nickname
        )
        if fig is not None:
            st.markdown(
                f"**🏠 我方 · {MY_NAME}** · "
                f"帖子 {len(my_notes)} 条 · "
                f"**👥 {peer_nickname}** · "
                f"帖子 {len(peer_notes)} 条"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("我方帖子暂无标签")
    else:
        st.info("无帖子标签数据")


# ============================================================
# Tab 5: 评论分析
# ============================================================
def _render_tab_comments():
    all_cmt = st.session_state.get("all_comments", pd.DataFrame())
    if all_cmt.empty:
        st.warning("暂无评论数据")
        return

    notes_df = st.session_state.get("xhs_note", pd.DataFrame())

    # ---- KPI ----
    ov = comments_mod.build_overview(all_cmt)
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("评论总数", ov["total"])
    col2.metric("涉及笔记", ov["unique_notes"])
    col3.metric("评论用户", ov["unique_users"])
    col4.metric("图片率", f"{ov['pic_rate']:.1%}")
    col5.metric("@提及率", f"{ov['at_rate']:.1%}")
    col6.metric("留白率", f"{ov['empty_rate']:.1%}")

    st.divider()

    # ---- 时序 ----
    col_l, col_r = st.columns(2)
    with col_l:
        fig_timeline = comments_mod.build_timeline(all_cmt)
        st.plotly_chart(fig_timeline, use_container_width=True)
    with col_r:
        fig_empty = comments_mod.build_empty_trend(all_cmt)
        st.plotly_chart(fig_empty, use_container_width=True)

    st.divider()

    # ---- 笔记维度 ----
    st.subheader("📊 笔记评论排名")
    ranking = comments_mod.build_note_comment_ranking(all_cmt, notes_df)
    if not ranking.empty:
        st.dataframe(
            ranking,
            column_config={
                "title": "笔记标题",
                "nickname": "作者",
                "评论数": st.column_config.NumberColumn("评论数"),
                "图片率": st.column_config.ProgressColumn("图片率", format="%.0f%%", min_value=0, max_value=100),
                "at率": st.column_config.ProgressColumn("at率", format="%.0f%%", min_value=0, max_value=100),
                "留白率": st.column_config.ProgressColumn("留白率", format="%.0f%%", min_value=0, max_value=100),
                "总点赞": "评论点赞",
                "评论用户": "用户数",
            },
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ---- 用户 + IP ----
    col_l, col_r = st.columns([1, 1])
    with col_l:
        st.subheader("👤 评论用户排行")
        commenters = comments_mod.build_commenter_ranking(all_cmt)
        if not commenters.empty:
            st.dataframe(
                commenters.head(20),
                column_config={
                    "nickname": "用户",
                    "评论数": "评论数",
                    "图片评论": "图片评论",
                    "获赞": "获赞",
                    "平均长度": "均字数",
                },
                use_container_width=True,
                hide_index=True,
                height=400,
            )
    with col_r:
        st.subheader("🌍 IP 分布")
        fig_ip = comments_mod.build_ip_distribution(all_cmt)
        st.plotly_chart(fig_ip, use_container_width=True)

    st.divider()

    # ---- 雷达图 ----
    st.subheader("🎯 评论质量雷达")
    fig_radar = comments_mod.build_quality_radar(all_cmt, notes_df)
    st.plotly_chart(fig_radar, use_container_width=True)

# ==================== Render all tabs with error boundaries ====================
with tab_hot:
    _render_tab_safe("🔥 热帖排行", _render_tab_hot)

with tab_time:
    _render_tab_safe("⏰ 发布时间优化", _render_tab_time)

with tab_content:
    _render_tab_safe("📝 内容策略分析", _render_tab_content)

with tab_peers:
    _render_tab_safe("🔍 同行分析", _render_tab_peers)

with tab_comments:
    _render_tab_safe("💬 评论分析", _render_tab_comments)
