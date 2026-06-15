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


def _fetch_existing(client: Client, table: str, ids: list, key: str) -> dict:
    """Fetch existing records keyed by primary key."""
    existing = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        res = client.table(table).select("*").in_(key, chunk).execute()
        for r in (res.data or []):
            existing[r[key]] = r
    return existing


def _merge_keywords(old_val, new_val) -> str:
    """Merge source_keyword values, deduplicate."""
    keywords = set()
    if old_val:
        for k in str(old_val).split(","):
            k = k.strip()
            if k:
                keywords.add(k)
    if new_val:
        for k in str(new_val).split(","):
            k = k.strip()
            if k:
                keywords.add(k)
    return ",".join(sorted(keywords))


def import_contents(client: Client, df: pd.DataFrame) -> dict:
    """Import contents with merge logic. Returns {"inserted": N, "updated": N}."""
    if not client or df.empty:
        return {"inserted": 0, "updated": 0}
    existing_cols = [c for c in CONTENTS_COLS if c in df.columns]
    batch = _df_to_batch(df, existing_cols)
    if not batch:
        return {"inserted": 0, "updated": 0}

    incoming_ids = [r["note_id"] for r in batch]
    existing = _fetch_existing(client, "contents", incoming_ids, "note_id")

    to_insert = []
    to_update = []
    increasing_rows = []
    update_count = 0

    count_cols = ["liked_count", "collected_count", "comment_count", "share_count"]

    for row in batch:
        nid = row["note_id"]
        if nid in existing:
            old = existing[nid]
            merged = dict(old)
            changed = False

            # 合并 source_keyword
            merged["source_keyword"] = _merge_keywords(
                old.get("source_keyword"), row.get("source_keyword")
            )

            # 更新互动量（取最新值）
            for c in count_cols:
                if c in row and row[c] is not None:
                    if int(row[c]) != int(old.get(c, 0)):
                        merged[c] = int(row[c])
                        changed = True

            # 更新其他非空字段
            for c in ["title", "desc", "video_url", "tag_list", "image_list",
                       "note_url", "xsec_token", "type", "nickname", "avatar",
                       "last_update_time",
                       "publish_time_str", "update_time_str", "modify_time_str"]:
                if row.get(c) and row[c] != old.get(c):
                    merged[c] = row[c]
                    changed = True

            if changed:
                to_update.append(merged)
                update_count += 1

            # 记录增量数据
            inc_row = {"note_id": nid}
            has_change = False

            # 互动量：记录差值
            for c in count_cols:
                new_val = row.get(c)
                old_val = old.get(c, 0) if nid in existing else 0
                if new_val is not None and int(new_val) != int(old_val):
                    inc_row[c] = int(new_val) - int(old_val)
                    has_change = True

            # last_update_time：记录新值
            new_ts = row.get("last_update_time")
            old_ts = old.get("last_update_time") if nid in existing else None
            if new_ts and new_ts != old_ts:
                inc_row["last_update_time"] = new_ts
                has_change = True

            if has_change:
                increasing_rows.append(inc_row)
        else:
            to_insert.append(row)

    inserted_count = 0
    if to_insert:
        client.table("contents").upsert(to_insert, on_conflict="note_id").execute()
        inserted_count = len(to_insert)

    if to_update:
        client.table("contents").upsert(to_update, on_conflict="note_id").execute()

    if increasing_rows:
        client.table("increasing").insert(increasing_rows).execute()

    return {"inserted": inserted_count, "updated": update_count}


def import_comments(client: Client, df: pd.DataFrame) -> dict:
    """Import comments with merge logic. Returns {"inserted": N, "updated": N}."""
    if not client or df.empty:
        return {"inserted": 0, "updated": 0}
    existing_cols = [c for c in COMMENTS_COLS if c in df.columns]
    batch = _df_to_batch(df, existing_cols)
    if not batch:
        return {"inserted": 0, "updated": 0}

    incoming_ids = [r["comment_id"] for r in batch]
    existing = _fetch_existing(client, "comments", incoming_ids, "comment_id")

    to_insert = []
    to_update = []
    update_count = 0

    for row in batch:
        cid = row["comment_id"]
        if cid in existing:
            old = existing[cid]
            merged = dict(old)
            changed = False

            if "like_count" in row and row["like_count"] is not None:
                if int(row["like_count"]) != int(old.get("like_count", 0)):
                    merged["like_count"] = int(row["like_count"])
                    changed = True

            if "sub_comment_count" in row and row["sub_comment_count"] is not None:
                if int(row["sub_comment_count"]) != int(old.get("sub_comment_count", 0)):
                    merged["sub_comment_count"] = int(row["sub_comment_count"])
                    changed = True

            for c in ["content", "pictures", "ip_location", "create_time_str", "modify_time_str"]:
                if row.get(c) and row[c] != old.get(c):
                    merged[c] = row[c]
                    changed = True

            if changed:
                to_update.append(merged)
                update_count += 1
        else:
            to_insert.append(row)

    inserted_count = 0
    if to_insert:
        client.table("comments").upsert(to_insert, on_conflict="comment_id").execute()
        inserted_count = len(to_insert)

    if to_update:
        client.table("comments").upsert(to_update, on_conflict="comment_id").execute()

    return {"inserted": inserted_count, "updated": update_count}


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
