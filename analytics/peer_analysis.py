"""Tab 4: 同行分析 — 创作者画像 + 标签共现 + 我 vs 同行对比."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .common import parse_wan, compute_engagement


MY_SHOP_USER_ID = "5d0cf92a0000000012020861"
MY_SHOP_NAME = "wireless shop无线商店"


def preprocess_creator_data(df_notes, df_creators):
    """预处理创作者数据：解析万单位、统计帖子数."""
    creators_df = df_creators.copy()
    for col in ["fans", "follows", "interaction"]:
        if col in creators_df.columns:
            creators_df[col] = creators_df[col].apply(parse_wan)

    if "user_id" in df_notes.columns:
        post_counts = df_notes["user_id"].value_counts()
    else:
        post_counts = pd.Series()
    creators_df["post_count"] = creators_df["user_id"].map(post_counts).fillna(0).astype(int)
    return creators_df


def build_post_tags_df(df):
    """从 xhs_note.tag_list 构建 post-level 标签 DataFrame."""
    rows = []
    if "user_id" not in df.columns or "tag_list" not in df.columns:
        return pd.DataFrame(columns=["user_id", "tag_name"])

    for _, note in df.iterrows():
        uid = note.get("user_id")
        raw_tags = note.get("tag_list", "")
        if not uid or pd.isna(raw_tags) or not str(raw_tags).strip():
            continue
        tags = [t.strip() for t in str(raw_tags).split(",") if t.strip()]
        for tag in tags:
            rows.append({"user_id": uid, "tag_name": tag})
    return pd.DataFrame(rows)


def build_creator_post_count_chart(creators_df):
    """创作者帖子数 Top 15."""
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
    return fig


def build_type_distribution_chart(df):
    """帖子类型分布饼图."""
    type_counts = df["type"].value_counts()
    type_labels = {"normal": "图文", "video": "视频"}
    type_names = [type_labels.get(t, t) for t in type_counts.index]
    fig = px.pie(values=type_counts.values, names=type_names, title="帖子类型分布")
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
    return fig


def build_tag_frequency_charts(post_tags_df, my_uid, my_name):
    """返回 (全部标签 Top 25 图, 我方标签 vs 同行图)."""
    tag_freq = post_tags_df["tag_name"].value_counts().head(25)

    fig_all = px.bar(
        x=tag_freq.values, y=tag_freq.index,
        orientation="h",
        title="全部帖子标签 Top 25",
        labels={"x": "出现次数", "y": "标签"},
        color=tag_freq.values,
        color_continuous_scale="Reds",
    )
    fig_all.update_layout(height=500, margin=dict(l=20, r=20, t=40, b=20))

    # 我方标签 vs 同行标签
    my_tags_series = post_tags_df[post_tags_df["user_id"] == my_uid]["tag_name"].value_counts()
    others_tags_series = post_tags_df[post_tags_df["user_id"] != my_uid]["tag_name"].value_counts()

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

    fig_my = go.Figure()
    fig_my.add_trace(go.Bar(
        y=tag_labels, x=others_vals,
        orientation="h", name="同行使用次数",
        marker_color="#b0c4de",
    ))
    fig_my.add_trace(go.Bar(
        y=tag_labels, x=my_vals,
        orientation="h", name=f"{my_name} 使用次数",
        marker_color="#ff6b6b",
    ))
    fig_my.update_layout(
        title=f"{my_name} 标签 vs 同行 (按同行热度排序)",
        xaxis=dict(title="出现次数"),
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
        barmode="overlay",
    )

    return fig_all, fig_my


def build_tag_cooccurrence(post_tags_df):
    """标签共现分析 (post-level) — 返回 (共现矩阵图, Top 10 标签对图) 或 None."""
    if post_tags_df.empty or post_tags_df["user_id"].nunique() < 3:
        return None, None

    # Post-level co-occurrence: 同一个帖子里的标签对
    post_tag_groups = post_tags_df.groupby("user_id").apply(
        lambda g: list(g["tag_name"].unique())
    )
    post_tag_groups = post_tag_groups[post_tag_groups.apply(len) >= 2]

    if len(post_tag_groups) < 5:
        return None, None

    cooccur = {}
    tag_freq_all = {}
    for tags in post_tag_groups:
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

    fig_matrix = go.Figure(
        data=go.Heatmap(
            z=matrix.values,
            x=top_tags,
            y=top_tags,
            colorscale="YlOrRd",
            text=matrix.values.astype(int),
            texttemplate="%{text}",
            hovertemplate="%{x} <-> %{y}<br>共现: %{z}<extra></extra>",
        )
    )
    fig_matrix.update_layout(
        title="帖子标签共现矩阵 (Top 15)",
        height=550,
        margin=dict(l=20, r=20, t=40, b=80),
        xaxis=dict(tickangle=45),
    )

    top_pairs = sorted(cooccur.items(), key=lambda x: x[1], reverse=True)[:10]
    pair_labels = [f"{a} <-> {b}" for (a, b), _ in top_pairs]
    pair_counts = [cnt for _, cnt in top_pairs]

    fig_pairs = px.bar(
        x=pair_counts, y=pair_labels,
        orientation="h",
        title="Top 10 标签组合",
        labels={"x": "共现次数", "y": "标签对"},
        color=pair_counts,
        color_continuous_scale="Purples",
    )
    fig_pairs.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20))

    return fig_matrix, fig_pairs


def build_my_vs_peer_tag_comparison(post_tags_df, my_uid, my_name, peer_uid, peer_name):
    """我 vs 选定同行标签对比图."""
    if post_tags_df.empty:
        return None

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

    if diff_df.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=diff_df["tag"], x=diff_df["peer_count"],
        orientation="h", name=f"👥 {peer_name}",
        marker_color="#b0c4de",
    ))
    fig.add_trace(go.Bar(
        y=diff_df["tag"], x=diff_df["my_count"],
        orientation="h", name=f"🏠 {my_name}",
        marker_color="#ff6b6b",
    ))
    fig.update_layout(
        title=f"帖子标签对比：🏠 {my_name} vs 👥 {peer_name}",
        xaxis=dict(title="出现次数"),
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        barmode="overlay",
    )
    return fig
