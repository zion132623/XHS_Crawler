"""Tab 5: 评论分析 — 评论画像、图片率、@率、时序."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from analytics.common import parse_comment_pictures


def load_all_comments(client) -> pd.DataFrame:
    """从 xhs_note_comment 表全量拉取评论."""
    if not client:
        return pd.DataFrame()
    data = []
    start, limit = 0, 1000
    while True:
        res = client.table("xhs_note_comment").select("*").range(start, start + limit - 1).execute()
        if not res.data:
            break
        data.extend(res.data)
        if len(res.data) < limit:
            break
        start += limit
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    # 强转数值列，避免 Supabase 返回 string 导致 .mean() 报错
    for _col in ["like_count", "sub_comment_count"]:
        if _col in df.columns:
            df[_col] = pd.to_numeric(df[_col], errors="coerce").fillna(0).astype(int)

    df["create_time_dt"] = pd.to_datetime(df["create_time"], unit="ms", errors="coerce")
    df["pics_list"] = df["pictures"].apply(parse_comment_pictures)
    df["has_pic"] = df["pics_list"].apply(len) > 0
    df["has_at"] = df["content"].fillna("").apply(lambda x: "@" in str(x))
    df["content_len"] = df["content"].fillna("").apply(lambda x: len(str(x).strip()))
    df["is_empty"] = df["content_len"] == 0
    return df


def build_overview(df: pd.DataFrame) -> dict:
    """总览指标."""
    total = len(df)
    if total == 0:
        return {"total": 0, "pic_rate": 0, "at_rate": 0, "empty_rate": 0,
                "sub_rate": 0, "avg_likes": 0, "unique_notes": 0, "unique_users": 0}
    return {
        "total": total,
        "pic_rate": df["has_pic"].mean(),
        "at_rate": df["has_at"].mean(),
        "empty_rate": df["is_empty"].mean(),
        "sub_rate": (df["sub_comment_count"].fillna(0) > 0).mean(),
        "avg_likes": df["like_count"].fillna(0).mean(),
        "unique_notes": df["note_id"].nunique(),
        "unique_users": df["user_id"].nunique(),
    }


def build_timeline(df: pd.DataFrame) -> go.Figure:
    """评论量日趋势."""
    if df.empty or "create_time_dt" not in df.columns:
        return go.Figure()
    daily = df.set_index("create_time_dt").resample("D").size().reset_index(name="count")
    daily["date"] = daily["create_time_dt"].dt.strftime("%m-%d")

    fig = px.bar(
        daily, x="date", y="count",
        title="每日评论量",
        labels={"date": "日期", "count": "评论数"},
        color="count", color_continuous_scale="Blues",
    )
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def build_empty_trend(df: pd.DataFrame) -> go.Figure:
    """留白评论占比日趋势."""
    if df.empty or "create_time_dt" not in df.columns:
        return go.Figure()
    daily = df.set_index("create_time_dt").resample("D").agg(
        total=("note_id", "size"),
        empty=("is_empty", "sum"),
    ).reset_index()
    daily["empty_rate"] = daily["empty"] / daily["total"]
    daily["date"] = daily["create_time_dt"].dt.strftime("%m-%d")

    fig = px.line(
        daily, x="date", y="empty_rate",
        title="留白评论占比趋势",
        labels={"date": "日期", "empty_rate": "留白率"},
        markers=True,
    )
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20),
                      yaxis_tickformat=".0%")
    return fig


def build_note_comment_ranking(df: pd.DataFrame, notes_df: pd.DataFrame) -> pd.DataFrame:
    """按笔记维度聚合评论指标."""
    if df.empty:
        return pd.DataFrame()

    agg = df.groupby("note_id").agg(
        评论数=("comment_id", "size"),
        图片评论=("has_pic", "sum"),
        at_mention=("has_at", "sum"),
        留白数=("is_empty", "sum"),
        总点赞=("like_count", "sum"),
        评论用户=("user_id", "nunique"),
        子评论=("sub_comment_count", "sum"),
    ).reset_index()

    agg["图片率"] = (agg["图片评论"] / agg["评论数"] * 100).round(1)
    agg["at率"] = (agg["at_mention"] / agg["评论数"] * 100).round(1)
    agg["留白率"] = (agg["留白数"] / agg["评论数"] * 100).round(1)

    # Merge title from notes_df
    if notes_df is not None and not notes_df.empty and "note_id" in notes_df.columns:
        agg = agg.merge(
            notes_df[["note_id", "title", "nickname"]],
            on="note_id", how="left"
        )
    else:
        agg["title"] = ""
        agg["nickname"] = ""

    return agg.sort_values("评论数", ascending=False)


def build_commenter_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """评论用户排行."""
    if df.empty:
        return pd.DataFrame()
    agg = df.groupby(["user_id", "nickname"]).agg(
        评论数=("comment_id", "size"),
        图片评论=("has_pic", "sum"),
        获赞=("like_count", "sum"),
        平均长度=("content_len", "mean"),
    ).reset_index()
    agg["平均长度"] = agg["平均长度"].round(0).astype(int)
    return agg.sort_values("评论数", ascending=False)


def build_ip_distribution(df: pd.DataFrame) -> go.Figure:
    """评论 IP 属地分布."""
    if df.empty or "ip_location" not in df.columns:
        return go.Figure()
    ip = df["ip_location"].value_counts().head(15)
    fig = px.pie(
        values=ip.values, names=ip.index,
        title="评论 IP 属地分布",
    )
    fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def build_quality_radar(df: pd.DataFrame, notes_df: pd.DataFrame) -> go.Figure:
    """各笔记评论质量雷达图."""
    ranking = build_note_comment_ranking(df, notes_df)
    if ranking.empty or len(ranking) < 1:
        return go.Figure()

    cats = ["图片率", "at率", "子评论率"]
    fig = go.Figure()
    for _, row in ranking.head(6).iterrows():
        title = str(row.get("title", ""))[:12] or row["note_id"][:12]
        fig.add_trace(go.Scatterpolar(
            r=[
                row["图片率"],
                row["at率"],
                row["子评论"] / max(row["评论数"], 1) * 100,
            ],
            theta=cats,
            fill="toself",
            name=title,
        ))
    fig.update_layout(height=400, margin=dict(l=40, r=40, t=20, b=20))
    return fig
