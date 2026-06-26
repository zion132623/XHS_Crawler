"""Tab 1: 热帖排行 — 三种榜单 + 关键词 + 散点图."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def filter_hot_df(session, post_type: str) -> pd.DataFrame:
    """根据帖子类型返回对应热帖 DataFrame."""
    if post_type == "全部":
        return session.hot_all
    elif post_type == "视频 (video)":
        return session.hot_video
    else:
        return session.hot_normal


def build_kw_bar_chart(hot_df: pd.DataFrame) -> go.Figure:
    """热帖关键词分布柱状图."""
    kw_raw = hot_df.get("source_keyword", pd.Series(dtype=str))
    kw_per_post = kw_raw.fillna("").apply(
        lambda x: [k.strip() for k in str(x).split(",") if k.strip()]
    )
    kw_series = kw_per_post.explode()
    kw_counts = kw_series.value_counts()

    fig = px.bar(
        x=kw_counts.values, y=kw_counts.index,
        orientation="h",
        title="热门帖关键词分布",
        labels={"x": "帖子数", "y": "搜索关键词"},
        color=kw_counts.values,
        color_continuous_scale="Blues",
    )
    fig.update_layout(height=max(200, len(kw_counts) * 30), margin=dict(l=20, r=20, t=40, b=20))
    return fig, kw_series


def build_multi_kw_table(df: pd.DataFrame) -> tuple:
    """返回 (多关键词帖子 DataFrame, 数量, 总数)."""
    kw_all_raw = df.get("source_keyword", pd.Series(dtype=str))
    kw_all_per_post = kw_all_raw.fillna("").apply(
        lambda x: [k.strip() for k in str(x).split(",") if k.strip()]
    )
    multi_mask = kw_all_per_post.apply(len) > 1
    multi_df = df[multi_mask][
        ["title", "nickname", "source_keyword", "liked_count", "comment_count", "note_url"]
    ].copy().sort_values("liked_count", ascending=False)
    return multi_df, multi_mask.sum(), len(df)


def build_ranking_table(display: pd.DataFrame) -> pd.DataFrame:
    """构造排行展示用 DataFrame."""
    table_data = display[
        ["title", "nickname", "liked_count", "collected_count",
         "comment_count", "share_count", "hours_ago",
         "hot_score", "score_burst", "keyword_count", "source_keyword", "final_score"]
    ].copy()
    table_data["hours_ago"] = table_data["hours_ago"].astype(int)
    return table_data


RANKING_COLUMN_CONFIG = {
    "title": "标题",
    "nickname": "作者",
    "liked_count": "点赞",
    "collected_count": "收藏",
    "comment_count": "评论",
    "share_count": "分享",
    "hours_ago": "发帖(h)",
    "hot_score": "热门分",
    "score_burst": "潜力分",
    "keyword_count": "关键词数",
    "source_keyword": "搜索关键词",
    "final_score": "综合分",
}


def build_hot_vs_burst_scatter(hot_df: pd.DataFrame) -> go.Figure:
    """热门分 × 潜力分 散点图."""
    fig = px.scatter(
        hot_df,
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
    return fig


def build_time_decay_scatter(hot_df: pd.DataFrame) -> go.Figure:
    """时间衰减趋势散点图."""
    size_col = "score_base" if "score_base" in hot_df.columns else "hot_score"
    fig = px.scatter(
        hot_df,
        x="hours_ago",
        y="final_score",
        size=size_col,
        hover_data=["title", "nickname"],
        color="score_burst",
        color_continuous_scale="Blues",
        title="时间衰减趋势",
    )
    fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
    return fig
