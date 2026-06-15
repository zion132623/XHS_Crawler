import os
import pandas as pd
from typing import Optional
from supabase import create_client, Client


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


CONTENTS_COLS = [
    "note_id", "type", "title", "desc", "video_url",
    "time", "last_update_time", "user_id", "nickname", "avatar",
    "liked_count", "collected_count", "comment_count", "share_count",
    "ip_location", "image_list", "tag_list", "last_modify_ts",
    "note_url", "source_keyword", "xsec_token",
    "publish_time_str", "update_time_str", "modify_time_str",
]

COMMENTS_COLS = [
    "comment_id", "create_time", "ip_location", "note_id", "content",
    "user_id", "nickname", "avatar", "sub_comment_count", "pictures",
    "parent_comment_id", "last_modify_ts", "like_count",
    "create_time_str", "modify_time_str",
]


def _get_client() -> Optional[Client]:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def connect(db_path: str = None):
    """Return Supabase client or None if not configured."""
    return _get_client()


def init_db(client: Client):
    """Init schema via Supabase SQL editor — called once. No-op in SDK mode.
    Run this SQL in Supabase Dashboard:

    CREATE TABLE IF NOT EXISTS contents (
        note_id TEXT PRIMARY KEY,
        type TEXT, title TEXT, "desc" TEXT, video_url TEXT,
        time BIGINT, last_update_time BIGINT,
        user_id TEXT, nickname TEXT, avatar TEXT,
        liked_count INTEGER, collected_count INTEGER,
        comment_count INTEGER, share_count INTEGER,
        ip_location TEXT, image_list TEXT, tag_list TEXT,
        last_modify_ts BIGINT, note_url TEXT,
        source_keyword TEXT, xsec_token TEXT,
        publish_time_str TEXT, update_time_str TEXT, modify_time_str TEXT
    );

    CREATE TABLE IF NOT EXISTS comments (
        comment_id TEXT PRIMARY KEY,
        create_time BIGINT, ip_location TEXT,
        note_id TEXT, content TEXT,
        user_id TEXT, nickname TEXT, avatar TEXT,
        sub_comment_count INTEGER, pictures TEXT,
        parent_comment_id TEXT, last_modify_ts BIGINT,
        like_count INTEGER,
        create_time_str TEXT, modify_time_str TEXT
    );

    CREATE TABLE IF NOT EXISTS user_roles (
        user_id UUID PRIMARY KEY REFERENCES auth.users(id),
        role TEXT NOT NULL DEFAULT 'viewer'
    );
    """
    pass


def _clean_row(row: dict) -> dict:
    import math
    for k, v in row.items():
        if v is None:
            continue
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            row[k] = None
    return row


def _df_to_batch(df: pd.DataFrame, cols: list) -> list:
    """Convert DataFrame to list of dicts with NaN → None."""
    df_sub = df[cols].copy()
    df_sub = df_sub.where(pd.notna(df_sub), None)
    df_sub = df_sub.astype(object)
    batch = df_sub.to_dict(orient="records")
    return [_clean_row(r) for r in batch]


def import_contents(client: Client, df: pd.DataFrame) -> int:
    if not client or df.empty:
        return 0
    existing_cols = [c for c in CONTENTS_COLS if c in df.columns]
    batch = _df_to_batch(df, existing_cols)
    if not batch:
        return 0
    client.table("contents").upsert(batch, on_conflict="note_id").execute()
    return len(batch)


def import_comments(client: Client, df: pd.DataFrame) -> int:
    if not client or df.empty:
        return 0
    existing_cols = [c for c in COMMENTS_COLS if c in df.columns]
    batch = _df_to_batch(df, existing_cols)
    if not batch:
        return 0
    client.table("comments").upsert(batch, on_conflict="comment_id").execute()
    return len(batch)


def query_contents(client: Client) -> pd.DataFrame:
    if not client:
        return pd.DataFrame()
    data = []
    start, limit = 0, 1000
    while True:
        res = client.table("contents").select("*").range(start, start + limit - 1).execute()
        if not res.data:
            break
        data.extend(res.data)
        if len(res.data) < limit:
            break
        start += limit
    return pd.DataFrame(data)


def query_comments(client: Client) -> pd.DataFrame:
    if not client:
        return pd.DataFrame()
    data = []
    start, limit = 0, 1000
    while True:
        res = client.table("comments").select("*").range(start, start + limit - 1).execute()
        if not res.data:
            break
        data.extend(res.data)
        if len(res.data) < limit:
            break
        start += limit
    return pd.DataFrame(data)


def table_stats(client: Client) -> dict:
    if not client:
        return {"contents": 0, "comments": 0}
    try:
        n1 = client.table("contents").select("note_id", count="exact").execute().count
        n2 = client.table("comments").select("comment_id", count="exact").execute().count
    except Exception:
        return {"contents": 0, "comments": 0}
    return {"contents": n1 or 0, "comments": n2 or 0}
