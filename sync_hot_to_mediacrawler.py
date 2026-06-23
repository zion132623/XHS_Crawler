#!/usr/bin/env python3
"""
Bridge: Fetch hot note rankings from Supabase → Feed to MediaCrawler for full crawl.

Usage:
    # Dry-run: just print the URLs that would be crawled
    python sync_hot_to_mediacrawler.py --dry-run

    # Crawl top 20 hot notes with comments (up to 200 each)
    python sync_hot_to_mediacrawler.py --limit 20 --max-comments 200

    # Filter by a specific source keyword
    python sync_hot_to_mediacrawler.py --source-keyword "原创车贴"

How it works:
    1. Connects to the same Supabase as the Streamlit app
    2. Pulls hot note rankings using the same scoring algorithm
    3. Gets note_id + xsec_token for each hot post
    4. Constructs full URLs MediaCrawler's detail mode can consume
    5. Invokes MediaCrawler main.py with --type detail --specified_id "..."
"""

import os
import sys
import argparse
import subprocess
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---- Config ------------------------------------------------
MEDIACRAWLER_DIR = "/Users/zion/Desktop/MediaCrawler/MediaCrawler"
# ------------------------------------------------------------


def get_db_client():
    """Import db module and get Supabase client."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db

    client = db.connect()
    if not client:
        print("[Bridge] ERROR: Cannot connect to Supabase.")
        print("Check SUPABASE_URL / SUPABASE_ANON_KEY in .env")
        sys.exit(1)
    return db, client


def get_hot_note_urls(db, client, limit: int = 20, source_keyword: str = "") -> list[dict]:
    """
    Get hot notes from Supabase and construct full note URLs.

    Returns list of dicts: {note_id, title, nickname, url, final_score}
    """
    # Use query_hot_posts for the exact ranking algorithm
    hot_df = db.query_hot_posts(client, limit=limit * 2)  # fetch extra for keyword filter

    if hot_df.empty:
        print("[Bridge] No hot posts found.")
        return []

    # If source_keyword filter is specified, re-query with keyword
    if source_keyword:
        # Get all contents to filter by keyword
        raw_df = db.query_contents(client)
        if not raw_df.empty:
            matched_ids = raw_df[
                raw_df.get("source_keyword", "").fillna("").str.contains(source_keyword, case=False)
            ]["note_id"].tolist()
            hot_df = hot_df[hot_df["note_id"].isin(matched_ids)]

    hot_df = hot_df.head(limit)

    # Get xsec_token from Supabase for each note_id
    note_ids = hot_df["note_id"].tolist()
    xsec_map = {}
    for i in range(0, len(note_ids), 500):
        chunk = note_ids[i : i + 500]
        res = client.table("xhs_note").select("note_id,xsec_token").in_("note_id", chunk).execute()
        for row in (res.data or []):
            xsec_map[row["note_id"]] = row.get("xsec_token", "")

    result = []
    for _, row in hot_df.iterrows():
        note_id = row["note_id"]
        xsec_token = xsec_map.get(note_id, "")

        if xsec_token:
            url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
        else:
            url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_source=pc_search"

        result.append({
            "note_id": note_id,
            "title": row.get("title", ""),
            "nickname": row.get("nickname", ""),
            "url": url,
            "final_score": row.get("final_score", 0),
        })

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Fetch hot XHS notes from Supabase and crawl via MediaCrawler"
    )
    parser.add_argument("--limit", type=int, default=20, help="Number of hot notes to crawl")
    parser.add_argument("--max-comments", type=int, default=200, help="Max comments per note")
    parser.add_argument("--source-keyword", type=str, default="", help="Filter by source_keyword (e.g. '原创车贴')")
    parser.add_argument("--dry-run", action="store_true", help="Only print URLs without crawling")
    parser.add_argument("--save-data-option", type=str, default="json", help="MediaCrawler save format: json/jsonl/csv/excel/postgres/db")
    parser.add_argument("--concurrency", type=int, default=1, help="Max concurrency for MediaCrawler")
    args = parser.parse_args()

    db, client = get_db_client()

    print(f"[Bridge] Fetching top {args.limit} hot notes from Supabase ...")
    notes = get_hot_note_urls(db, client, limit=args.limit, source_keyword=args.source_keyword)

    if not notes:
        print("[Bridge] No notes to crawl.")
        return

    print(f"[Bridge] Got {len(notes)} notes:\n")
    for i, n in enumerate(notes, 1):
        print(f"  {i:2}. [{n['final_score']:>8.2f}] {n['title'][:50]:50s}  @{n['nickname']}")
        print(f"      {n['note_id']}")

    if args.dry_run:
        print(f"\n[Bridge] --- Full URLs ({len(notes)} notes) ---")
        for n in notes:
            print(n["url"])
        print("\n[Dry-run] Add --dry-run is set. No crawling performed.")
        return

    # Build MediaCrawler command
    url_list = ",".join(n["url"] for n in notes)

    cmd = [
        sys.executable, "main.py",
        "--platform", "xhs",
        "--lt", "cookie",
        "--type", "detail",
        "--specified_id", url_list,
        "--get_comment", "true",
        "--get_sub_comment", "false",
        "--save_data_option", args.save_data_option,
        "--max_comments_count_singlenotes", str(args.max_comments),
        "--crawler_max_notes_count", str(len(notes)),
        "--max_concurrency_num", str(args.concurrency),
    ]

    print(f"\n[Bridge] Launching MediaCrawler (detail mode, {len(notes)} notes, {args.max_comments} comments/note)...")
    print(f"[Bridge] CWD: {MEDIACRAWLER_DIR}")
    print(f"[Bridge] CMD: {' '.join(cmd)}\n")
    print("-" * 60)

    result = subprocess.run(cmd, cwd=MEDIACRAWLER_DIR)

    if result.returncode == 0:
        print(f"\n[Bridge] Done. Crawled {len(notes)} notes successfully.")
    else:
        print(f"\n[Bridge] MediaCrawler exited with code {result.returncode}")


if __name__ == "__main__":
    main()
