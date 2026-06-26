"""Tab 3: 内容策略分析 — TF-IDF + 句式 + 格式."""

import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer

from .common import compute_engagement

# 内容策略专用互动加权 (与 hot_ranking 不同: collected*2, comment*3, share*4)
CONTENT_ENGAGEMENT_WEIGHTS = {
    "liked_count": 1,
    "collected_count": 2,
    "comment_count": 3,
    "share_count": 4,
}

# 疑问句检测正则
Q_MARKERS = re.compile(r"[？?]|[吗呢吧啊]$|什么|怎么|为什么|哪|谁|如何|有没有|是不是|能不能|可不可以|咋|啥")


def load_stopwords():
    """从 Supabase 加载停用词表."""
    import db
    sw_list = []
    try:
        client = db.connect()
        if client:
            start, limit = 0, 1000
            while True:
                res = client.table("stopwords").select("word").range(start, start + limit - 1).execute()
                if not res.data:
                    break
                sw_list.extend(r["word"] for r in res.data)
                if len(res.data) < limit:
                    break
                start += limit
    except Exception:
        pass
    return set(sw_list)


def compute_tfidf(df):
    """title×3 + desc 加权 TF-IDF，按互动分组对比.

    Returns: (kw_df, hot_count, cold_count)
    """
    stops = load_stopwords()

    df_w = df.copy()
    df_w["engagement"] = compute_engagement(df_w, CONTENT_ENGAGEMENT_WEIGHTS)

    df_w["full_text"] = (df_w["title"].fillna("") + " ") * 3 + df_w["desc"].fillna("")

    all_docs = []
    for t in df_w["full_text"]:
        words = [w.strip() for w in jieba.cut(t) if len(w.strip()) >= 2 and w.strip() not in stops]
        all_docs.append(" ".join(words))

    vectorizer = TfidfVectorizer(max_features=200, ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(all_docs)
    feature_names = vectorizer.get_feature_names_out()

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

    kw_df = pd.DataFrame(results).sort_values("hot_tfidf", ascending=False)
    return kw_df, len(df_w[hot_mask]), len(df_w[cold_mask])


def build_tfidf_bar_charts(kw_df):
    """返回 (热门帖高频词图, 热度区分度图)."""
    top_hot = kw_df.nlargest(20, "hot_tfidf")

    fig_hot = px.bar(
        top_hot.iloc[::-1],
        x="hot_tfidf",
        y="keyword",
        orientation="h",
        title="热门帖 TF-IDF Top 20",
        color="hot_tfidf",
        color_continuous_scale="Reds",
    )
    fig_hot.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))

    top_ratio = kw_df.nlargest(20, "ratio")

    fig_ratio = px.bar(
        top_ratio.iloc[::-1],
        x="ratio",
        y="keyword",
        orientation="h",
        title="热门帖 / 普通帖 TF-IDF 比值",
        color="ratio",
        color_continuous_scale="RdYlGn",
    )
    fig_ratio.add_vline(x=1, line_dash="dot", line_color="gray")
    fig_ratio.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))

    return fig_hot, fig_ratio


def analyze_question_type(df):
    """句式分析：返回统计数据 + 图表."""
    df_q = df.copy()
    df_q["is_question"] = df_q["title"].fillna("").apply(
        lambda t: bool(Q_MARKERS.search(str(t)))
    )
    q_count = int(df_q["is_question"].sum())
    s_count = int((~df_q["is_question"]).sum())

    df_q["engagement"] = compute_engagement(df_q, CONTENT_ENGAGEMENT_WEIGHTS)
    q_avg = df_q[df_q["is_question"]]["engagement"].mean()
    s_avg = df_q[~df_q["is_question"]]["engagement"].mean()

    top_thresh = df_q["engagement"].quantile(0.7)
    bot_thresh = df_q["engagement"].quantile(0.3)
    hot_q_ratio = df_q[df_q["engagement"] >= top_thresh]["is_question"].mean()
    cold_q_ratio = df_q[df_q["engagement"] <= bot_thresh]["is_question"].mean()
    all_q_ratio = df_q["is_question"].mean()

    # 平均互动对比图
    fig_avg = go.Figure()
    fig_avg.add_trace(go.Bar(
        x=["陈述句", "疑问句"],
        y=[s_avg, q_avg],
        marker_color=["#b0c4de", "#ff6b6b"],
        text=[f"{s_avg:,.0f}", f"{q_avg:,.0f}"],
        textposition="outside",
    ))
    fig_avg.update_layout(title="平均互动量对比", height=400, margin=dict(l=20, r=20, t=40, b=20))

    # 疑问句占比对比图
    fig_ratio_q = go.Figure()
    fig_ratio_q.add_trace(go.Bar(
        x=["热门组", "全部", "普通组"],
        y=[hot_q_ratio * 100, all_q_ratio * 100, cold_q_ratio * 100],
        marker_color=["#ff6b6b", "#fdcb6e", "#b0c4de"],
        text=[f"{hot_q_ratio:.1%}", f"{all_q_ratio:.1%}", f"{cold_q_ratio:.1%}"],
        textposition="outside",
    ))
    fig_ratio_q.update_layout(
        title="疑问句占比 (热门 vs 普通)",
        yaxis=dict(title="疑问句占比 (%)"),
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return {
        "q_count": q_count,
        "s_count": s_count,
        "q_ratio": q_count / max(s_count, 1),
        "q_avg": q_avg,
        "s_avg": s_avg,
        "hot_q_ratio": hot_q_ratio,
        "cold_q_ratio": cold_q_ratio,
        "all_q_ratio": all_q_ratio,
        "fig_avg": fig_avg,
        "fig_ratio": fig_ratio_q,
    }


def analyze_post_format(df):
    """帖子格式分析：图片数 / 标题字数 / 描述字数."""
    df_f = df.copy()
    df_f["image_count"] = df_f["image_list"].fillna("").apply(
        lambda x: len([u for u in str(x).split(",") if u.strip()]) if x else 0
    )
    df_f["title_len"] = df_f["title"].fillna("").apply(len)
    df_f["desc_len"] = df_f["desc"].fillna("").apply(len)
    df_f["engagement"] = compute_engagement(df_f, CONTENT_ENGAGEMENT_WEIGHTS)
    top_thresh = df_f["engagement"].quantile(0.7)
    hot_mask = df_f["engagement"] >= top_thresh

    # 图片数量分布图
    all_imgs = df_f["image_count"].value_counts().reindex(range(0, 19), fill_value=0)
    hot_imgs = df_f[hot_mask]["image_count"].value_counts().reindex(range(0, 19), fill_value=0)

    fig_imgs = go.Figure()
    fig_imgs.add_trace(go.Bar(x=list(range(19)), y=all_imgs.values, name="全部", marker_color="#b0c4de", opacity=0.7))
    fig_imgs.add_trace(go.Bar(x=list(range(19)), y=hot_imgs.values, name="热门 (Top 30%)", marker_color="#ff6b6b"))
    fig_imgs.update_layout(
        title="图片数量分布", xaxis=dict(title="图片数", dtick=2), yaxis=dict(title="帖子数"),
        height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay",
    )

    # 标题字数分布图
    fig_title = go.Figure()
    fig_title.add_trace(go.Histogram(x=df_f["title_len"], name="全部", marker_color="#b0c4de", opacity=0.7, nbinsx=20))
    fig_title.add_trace(go.Histogram(x=df_f[hot_mask]["title_len"], name="热门 (Top 30%)", marker_color="#ff6b6b", nbinsx=20))
    fig_title.update_layout(
        title="标题字数分布", xaxis=dict(title="字数"), yaxis=dict(title="帖子数"),
        height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay",
    )

    # 描述字数分布图
    fig_desc = go.Figure()
    fig_desc.add_trace(go.Histogram(x=df_f["desc_len"], name="全部", marker_color="#b0c4de", opacity=0.7, xbins=dict(size=10)))
    fig_desc.add_trace(go.Histogram(x=df_f[hot_mask]["desc_len"], name="热门 (Top 30%)", marker_color="#ff6b6b", xbins=dict(size=10)))
    fig_desc.update_layout(
        title="描述字数分布", xaxis=dict(title="字数"), yaxis=dict(title="帖子数"),
        height=350, margin=dict(l=20, r=20, t=40, b=20), barmode="overlay",
    )

    return {
        "fig_imgs": fig_imgs,
        "fig_title": fig_title,
        "fig_desc": fig_desc,
        "hot_avg_imgs": df_f[hot_mask]["image_count"].mean(),
        "hot_avg_title_len": df_f[hot_mask]["title_len"].mean(),
        "hot_avg_desc_len": df_f[hot_mask]["desc_len"].mean(),
    }
