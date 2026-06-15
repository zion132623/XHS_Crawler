import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from wordcloud import WordCloud
from collections import Counter
import jieba
import re
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
import db
import auth

st.set_page_config(page_title="XHS 数据看板", page_icon="📊", layout="wide")
st.title("📊 小红书「原创车贴」数据看板")

# ==================== 会话恢复 ====================
auth.restore_session()

# ==================== 登录门禁 ====================
if not auth.is_logged_in():
    col_form, col_space = st.columns([1, 1.5])
    with col_form:
        st.subheader("🔐 登录")
        login_tab, reg_tab = st.tabs(["登录", "注册"])
        with login_tab:
            email = st.text_input("邮箱", key="login_email")
            password = st.text_input("密码", type="password", key="login_pw")
            if st.button("登录", use_container_width=True):
                auth.login(email, password)
                st.rerun()
        with reg_tab:
            reg_email = st.text_input("邮箱", key="reg_email")
            reg_pw = st.text_input("密码", type="password", key="reg_pw")
            if st.button("注册", use_container_width=True):
                auth.register(reg_email, reg_pw)
    st.stop()

# ==================== 辅助函数 ====================
def parse_wan(val):
    """Convert '3.9万' → 39000, '1万' → 10000, keep pure numbers."""
    if pd.isna(val):
        return 0
    s = str(val).strip()
    if "万" in s:
        num = float(s.replace("万", ""))
        return int(num * 10000)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def clean_numeric_cols(df, cols):
    """Apply parse_wan to each column and cast to int."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_wan)
    return df


def enrich_time_cols(df):
    df["publish_time"] = pd.to_datetime(df["time"], unit="ms")
    df["update_time"] = pd.to_datetime(df["last_update_time"], unit="ms")
    df["publish_hour"] = df["publish_time"].dt.hour
    df["publish_weekday"] = df["publish_time"].dt.day_name()
    df["publish_date"] = df["publish_time"].dt.date
    return df


def _get_font_path():
    """Return a Chinese-compatible font path for the current OS."""
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

    # ---- 自动连接 Supabase + 加载数据 ----
    if "contents" not in st.session_state:
        with st.spinner("连接 Supabase..."):
            client = db.connect()
            if not client:
                st.error("Supabase 未配置，请设置 SUPABASE_URL 和 SUPABASE_ANON_KEY")
                st.stop()
            st.session_state.db_conn = client
            stats = db.table_stats(client)
            st.session_state.db_stats = stats
            st.session_state.contents = enrich_time_cols(db.query_contents(client))
            st.session_state.contents = clean_numeric_cols(st.session_state.contents, ["liked_count", "collected_count", "comment_count", "share_count"])
            comments_data = db.query_comments(client)
            comments_data = clean_numeric_cols(comments_data, ["like_count", "sub_comment_count"])
            comments_data["create_time_dt"] = pd.to_datetime(comments_data["create_time"], unit="ms")
            st.session_state.comments = comments_data

    st.info(f"📊 帖子 {st.session_state.db_stats['contents']} 条 | 评论 {st.session_state.db_stats['comments']} 条")

    # ---- Admin 入口 ----
    if auth.is_admin():
        st.page_link("pages/admin.py", label="🔧 管理后台", icon="🔧")

    st.divider()
    st.caption(f"👤 {auth.get_current_user().email}")
    st.caption(f"🔑 {st.session_state.get('role', 'viewer')}")
    if st.button("🚪 登出", use_container_width=True):
        auth.logout()
        st.rerun()

df = st.session_state.contents
comments = st.session_state.comments if "comments" in st.session_state else None

# ==================== 筛选器 ====================
with st.sidebar:
    st.header("🎛️ 筛选器")

    # 日期范围
    if "publish_date" in df.columns:
        min_date = df["publish_date"].min()
        max_date = df["publish_date"].max()
        date_range = st.date_input("发布时间范围", [min_date, max_date])

    # 互动量阈值
    min_likes = int(df["liked_count"].min())
    max_likes = int(df["liked_count"].max())
    like_range = st.slider("点赞数范围", min_likes, max_likes, (min_likes, max_likes))

    # 帖子类型
    types = st.multiselect("帖子类型", df["type"].unique().tolist(), default=df["type"].unique().tolist())

    # 时间粒度
    time_granularity = st.selectbox("时间粒度", ["小时", "星期", "日期"], index=2)

# 应用筛选
mask = (
    df["liked_count"].between(like_range[0], like_range[1]) &
    df["type"].isin(types)
)
if "publish_date" in df.columns and len(date_range) == 2:
    mask &= df["publish_date"].between(date_range[0], date_range[1])

filtered_df = df[mask]

# ==================== Tab 页 ====================
tab1, tab2, tab3, tab4 = st.tabs(["📋 数据概览", "☁️ 词云分析", "⏰ 时间分析", "💬 评论分析"])

# ==================== Tab 1: 数据概览 ====================
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("帖子数", len(filtered_df))
    col2.metric("总点赞", f"{filtered_df['liked_count'].sum():,}")
    col3.metric("总评论", f"{filtered_df['comment_count'].sum():,}")
    col4.metric("总收藏", f"{filtered_df['collected_count'].sum():,}")

    st.divider()

    # Top N 选择
    top_n = st.slider("显示 Top", 5, 50, 15, key="top_n_overview")

    col_left, col_right = st.columns(2)

    with col_left:
        metric = st.selectbox("排序指标", ["liked_count", "comment_count", "collected_count", "share_count"],
                              format_func=lambda x: {"liked_count": "点赞", "comment_count": "评论", "collected_count": "收藏", "share_count": "分享"}[x])

        top_data = filtered_df.nlargest(top_n, metric)[["title", metric, "nickname"]].copy()
        top_data["short_title"] = top_data["title"].str[:25] + "..."
        top_data = top_data.iloc[::-1]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=[f"{t}<br><sup>{n}</sup>" for t, n in zip(top_data["short_title"], top_data["nickname"])],
            x=top_data[metric],
            orientation="h",
            marker_color=top_data[metric],
            marker_colorscale="plasma",
            text=top_data[metric],
            textposition="outside",
        ))
        fig.update_layout(height=600, margin=dict(l=20, r=40, t=20, b=20), showlegend=False)
        metric_cn = {"liked_count": "点赞", "comment_count": "评论", "collected_count": "收藏", "share_count": "分享"}[metric]
        fig.update_xaxes(title=metric_cn)
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        # 互动量分布直方图
        fig = px.histogram(filtered_df, x=metric, nbins=20, title=f"{metric_cn}分布",
                           color_discrete_sequence=["#636efa"])
        fig.update_layout(height=600)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # 数据表
    with st.expander("📄 原始数据"):
        cols_show = ["title", "nickname", "liked_count", "comment_count", "collected_count",
                     "share_count", "publish_time", "ip_location", "type"]
        st.dataframe(filtered_df[cols_show].sort_values("liked_count", ascending=False),
                     use_container_width=True, hide_index=True)

# ==================== Tab 2: 词云分析 ====================
with tab2:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        max_words = st.slider("最大词数", 20, 300, 150)
    with col2:
        min_word_len = st.slider("最小词长", 1, 4, 2)
    with col3:
        colormap_choice = st.selectbox("配色方案", ["plasma", "viridis", "magma", "inferno", "coolwarm", "Spectral"])
    with col4:
        wc_width = st.slider("词云宽度", 400, 1600, 1000, step=50)

    # 停用词
    default_stopwords = "的 了 在 是 我 有 和 就 不 人 都 一 这 他 她 它 们 那 些 做 什么 怎么 如果 因为 所以 但是 可以 觉得 感觉 这个 那个 真的 还是 然后 已经 非常 就是 好像 应该 一点 一下 有点 大家 或者 还有 不是 不过 确实 其实 很多 可能 需要 想 让 被 把 能 对 从 没 吗 吧 呢 啊 呀 哦 嗯 么 也 还 太 挺 更 最 又 再 才 刚 哈 啦 哟 嘛 哇 嘻 嘿 呵 小红书 车贴 贴 车 话题 like the to and a of in is it for http https com www video image note notes xhs xiaohongshu"
    stopwords_input = st.text_area("停用词 (空格分隔)", default_stopwords, height=80)

    stopwords = set(stopwords_input.split())

    # 选择文本来源
    text_source = st.multiselect("文本来源", ["title", "desc"], default=["title", "desc"])

    if st.button("🔄 生成词云"):
        combined_text = ""
        for src in text_source:
            combined_text += " ".join(filtered_df[src].fillna("").astype(str)) + " "

        words = jieba.cut(combined_text)
        filtered_words = []
        for w in words:
            w = w.strip()
            if len(w) >= min_word_len and w not in stopwords and not w.isdigit():
                filtered_words.append(w)

        counter = Counter(filtered_words)

        col_chart, col_freq = st.columns([1.5, 1])

        with col_chart:
            wc = WordCloud(
                width=wc_width,
                height=int(wc_width * 0.6),
                background_color="white",
                font_path=_get_font_path(),
                max_words=max_words,
                collocations=False,
                colormap=colormap_choice,
            ).generate_from_frequencies(counter)

            fig, ax = __import__("matplotlib.pyplot", fromlist=["subplots"]).subplots(figsize=(wc_width/100, wc_width*0.6/100))
            ax.imshow(wc, interpolation="bilinear")
            ax.axis("off")
            st.pyplot(fig)

        with col_freq:
            top_words = counter.most_common(50)
            word_df = pd.DataFrame(top_words, columns=["词", "次数"])
            fig = px.bar(word_df.head(20).iloc[::-1], x="次数", y="词", orientation="h",
                         title="Top 20 高频词", color="次数", color_continuous_scale=colormap_choice)
            fig.update_layout(height=600)
            st.plotly_chart(fig, use_container_width=True)

# ==================== Tab 3: 时间分析 ====================
with tab3:
    col1, col2 = st.columns(2)

    with col1:
        if time_granularity == "小时":
            time_dist = filtered_df["publish_hour"].value_counts().sort_index()
            fig = px.bar(x=time_dist.index, y=time_dist.values, title="发帖时段分布",
                         labels={"x": "小时", "y": "帖子数"}, color_discrete_sequence=["#ff6b6b"])
            fig.update_xaxes(tickmode="linear", dtick=1)
            st.plotly_chart(fig, use_container_width=True)

        elif time_granularity == "星期":
            weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            time_dist = filtered_df["publish_weekday"].value_counts().reindex(weekday_order).fillna(0)
            fig = px.bar(x=weekday_cn, y=time_dist.values, title="发帖星期分布",
                         labels={"x": "星期", "y": "帖子数"}, color_discrete_sequence=["#4ecdc4"])
            st.plotly_chart(fig, use_container_width=True)

        else:
            time_dist = filtered_df["publish_date"].value_counts().sort_index()
            fig = px.line(x=time_dist.index, y=time_dist.values, title="每日发帖趋势",
                          markers=True, labels={"x": "日期", "y": "帖子数"})
            fig.update_traces(line_color="#6c5ce7")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 时间范围统计
        if "publish_time" in filtered_df.columns:
            st.subheader("时间统计")
            t_min = filtered_df["publish_time"].min()
            t_max = filtered_df["publish_time"].max()
            st.metric("最早帖子", t_min.strftime("%Y-%m-%d %H:%M"))
            st.metric("最新帖子", t_max.strftime("%Y-%m-%d %H:%M"))
            st.metric("时间跨度", f"{(t_max - t_min).days} 天")

            # 更新延迟分析
            filtered_df_copy = filtered_df.copy()
            filtered_df_copy["update_delta_hours"] = (filtered_df_copy["update_time"] - filtered_df_copy["publish_time"]).dt.total_seconds() / 3600

            delta_bins = [0, 1, 6, 24, 72, 168, float("inf")]
            delta_labels = ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", ">7d"]
            filtered_df_copy["delta_group"] = pd.cut(filtered_df_copy["update_delta_hours"], bins=delta_bins, labels=delta_labels)
            delta_dist = filtered_df_copy["delta_group"].value_counts().reindex(delta_labels).fillna(0)

            fig = px.bar(x=delta_labels, y=delta_dist.values, title="发布到更新间隔",
                         labels={"x": "时间差", "y": "帖子数"}, color_discrete_sequence=["#fdcb6e"])
            st.plotly_chart(fig, use_container_width=True)

    # 热度时间趋势
    st.divider()
    st.subheader("互动量与发布时间关系")
    metric_choice = st.selectbox("选择指标", ["liked_count", "comment_count", "collected_count", "share_count"],
                                 format_func=lambda x: {"liked_count": "点赞", "comment_count": "评论", "collected_count": "收藏", "share_count": "分享"}[x],
                                 key="time_metric")

    filtered_sorted = filtered_df.sort_values("publish_time")
    fig = px.scatter(filtered_sorted, x="publish_time", y=metric_choice,
                     size="liked_count", hover_data=["title", "nickname"],
                     color=metric_choice, color_continuous_scale="plasma",
                     title=f"发布时间 vs {metric_choice}")
    st.plotly_chart(fig, use_container_width=True)

# ==================== Tab 4: 评论分析 ====================
with tab4:
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

            top_c = comments.nlargest(top_n_comments, "like_count")[["content", "like_count", "nickname"]].copy()
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
            # 评论 IP 分布
            ip_dist = comments["ip_location"].value_counts().head(15)
            fig = px.pie(values=ip_dist.values, names=ip_dist.index, title="评论 IP 属地分布")
            st.plotly_chart(fig, use_container_width=True)

        # 评论时间趋势
        st.divider()
        if "create_time_dt" in comments.columns:
            comments_copy = comments.copy()
            comments_copy["comment_date"] = comments_copy["create_time_dt"].dt.date
            daily_comments = comments_copy["comment_date"].value_counts().sort_index()
            fig = px.bar(x=daily_comments.index, y=daily_comments.values,
                         title="每日评论数趋势", labels={"x": "日期", "y": "评论数"})
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("📄 评论原始数据"):
            st.dataframe(comments.sort_values("like_count", ascending=False),
                         use_container_width=True, hide_index=True)
    else:
        st.warning("未加载评论数据，请上传 search_comments CSV")
