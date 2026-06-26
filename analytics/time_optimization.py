"""Tab 2: 发布时间优化 — 热度矩阵 + 时段建议."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .common import compute_engagement

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_heatmap_matrices(df):
    """返回 (pivot_mean, pivot_count) 两个矩阵."""
    df_t = df.copy()
    df_t["hour"] = df_t["publish_hour"]
    df_t["weekday"] = df_t["publish_weekday"]
    df_t["engagement"] = compute_engagement(df_t)

    heat_data = df_t.groupby(["weekday", "hour"])["engagement"].agg(["mean", "count"]).reset_index()
    heat_data["log_mean"] = np.log1p(heat_data["mean"])

    pivot_mean = heat_data.pivot(index="weekday", columns="hour", values="log_mean").fillna(0)
    pivot_count = heat_data.pivot(index="weekday", columns="hour", values="count").fillna(0)

    for d in range(7):
        if d not in pivot_mean.index:
            pivot_mean.loc[d] = 0
            pivot_count.loc[d] = 0
    pivot_mean = pivot_mean.sort_index()
    pivot_count = pivot_count.sort_index()

    return pivot_mean, pivot_count


def build_heatmap_figure(pivot, title, colorscale, text_template):
    """生成单张热力图."""
    z = pivot.values
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=[f"{h:02d}:00" for h in range(24)],
            y=WEEKDAY_CN,
            colorscale=colorscale,
            text=np.round(z, 1) if text_template == "number" else z.astype(int),
            texttemplate="%{text}",
            hovertemplate="%{y} %{x}<br>%{z}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def build_distribution_comparison(df):
    """返回 (时段对比图, 星期对比图)."""
    df_t = df.copy()
    df_t["hour"] = df_t["publish_hour"]
    df_t["weekday"] = df_t["publish_weekday"]
    df_t["engagement"] = compute_engagement(df_t)
    threshold = df_t["engagement"].quantile(0.7)
    hot_posts = df_t[df_t["engagement"] >= threshold]

    all_hours = df_t["hour"].value_counts().reindex(range(24), fill_value=0)
    hot_hours = hot_posts["hour"].value_counts().reindex(range(24), fill_value=0)

    fig_hour = go.Figure()
    fig_hour.add_trace(go.Bar(
        x=list(range(24)), y=all_hours.values,
        name="全部帖子", marker_color="#b0c4de", opacity=0.7,
    ))
    fig_hour.add_trace(go.Bar(
        x=list(range(24)), y=hot_hours.values,
        name="热门帖 (Top 30%)", marker_color="#ff6b6b",
    ))
    fig_hour.update_layout(
        title="发帖时段分布对比",
        xaxis=dict(title="小时", tickmode="linear", dtick=2),
        yaxis=dict(title="帖子数"),
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        barmode="overlay",
    )

    all_weekday = df_t["weekday"].value_counts().reindex(range(7), fill_value=0)
    hot_weekday = hot_posts["weekday"].value_counts().reindex(range(7), fill_value=0)

    fig_weekday = go.Figure()
    fig_weekday.add_trace(go.Bar(
        x=WEEKDAY_CN, y=all_weekday.values,
        name="全部帖子", marker_color="#b0c4de", opacity=0.7,
    ))
    fig_weekday.add_trace(go.Bar(
        x=WEEKDAY_CN, y=hot_weekday.values,
        name="热门帖 (Top 30%)", marker_color="#ff6b6b",
    ))
    fig_weekday.update_layout(
        title="发帖星期分布对比",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        barmode="overlay",
    )

    return fig_hour, fig_weekday


def get_best_time_recommendations(df):
    """返回最佳时段推荐列表和统计信息."""
    df_t = df.copy()
    df_t["hour"] = df_t["publish_hour"]
    df_t["weekday"] = df_t["publish_weekday"]
    df_t["engagement"] = compute_engagement(df_t)

    heat_data = df_t.groupby(["weekday", "hour"])["engagement"].agg(["mean", "count"]).reset_index()
    best_cells = heat_data.nlargest(5, "mean")

    recs = []
    for _, row in best_cells.iterrows():
        d = WEEKDAY_CN[int(row["weekday"])]
        h = int(row["hour"])
        n = int(row["count"])
        avg_eng = int(row["mean"])
        recs.append({
            "day": d,
            "hour_start": h,
            "hour_end": h + 1,
            "avg_engagement": avg_eng,
            "post_count": n,
        })

    overall_avg = df_t["engagement"].mean()
    best_avg = best_cells["mean"].iloc[0]
    multiplier_worst = best_avg / heat_data["mean"].min()
    multiplier_overall = best_avg / overall_avg

    return recs, multiplier_worst, multiplier_overall
