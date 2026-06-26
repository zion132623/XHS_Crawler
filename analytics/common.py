import pandas as pd
import numpy as np
import os
import platform


# 统一互动加权 (collected > comment > share > liked)
ENGAGEMENT_WEIGHTS = {
    "liked_count": 1,
    "collected_count": 5,
    "comment_count": 4,
    "share_count": 3,
}


def parse_wan(val):
    """解析带 '万' 单位的数值字符串为整数."""
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
    """批量清理数值列（处理 '万' 等单位）."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_wan)
    return df


def enrich_time_cols(df):
    """补时间相关字段（转为北京时间 UTC+8）."""
    df["publish_time"] = pd.to_datetime(df["time"], unit="ms") + pd.Timedelta(hours=8)
    df["update_time"] = pd.to_datetime(df["last_update_time"], unit="ms") + pd.Timedelta(hours=8)
    df["publish_hour"] = df["publish_time"].dt.hour
    df["publish_weekday"] = df["publish_time"].dt.weekday  # 0=Mon
    df["publish_date"] = df["publish_time"].dt.date
    return df


def compute_engagement(df, weights=None):
    """计算加权互动分."""
    w = weights or ENGAGEMENT_WEIGHTS
    score = pd.Series(0, index=df.index, dtype=float)
    for col, weight in w.items():
        if col in df.columns:
            score += df[col].fillna(0).astype(float) * weight
    return score


def get_font_path():
    """返回系统可用的中文字体路径."""
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
