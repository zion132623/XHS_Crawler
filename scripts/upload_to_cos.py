"""opencli 下载的图/视频 → 腾讯 COS 上传 → URL 回写 hot_ranking_snapshot.

用法:
    python scripts/upload_to_cos.py                  # 默认 jpg/png/webp, 跳过 mp4
    python scripts/upload_to_cos.py --include-videos # 含 mp4
    python scripts/upload_to_cos.py --dry-run        # 只扫不传不写
    python scripts/upload_to_cos.py --note-id NOTE   # 只处理单个帖子
    python scripts/upload_to_cos.py --dedup          # 跳过 COS 已存在同名
    python scripts/upload_to_cos.py --no-writeback   # 传图但不写表
    python scripts/upload_to_cos.py --root PATH      # 自定义根目录
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))            # 让 "import db" 能找到 xhs_crawler/db.py
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))     # 让 "import cos_utils" 能找到同级脚本

import cos_utils  # noqa: E402  本地模块
from cos_utils import (  # noqa: E402  本地模块
    BUCKET,
    REGION,
    content_type_for,
    exists,
    make_client,
    make_public_url,
    upload_file,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov"}
NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,32}$")

COS_KEY_PREFIX = "xhs_images"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="opencli 图片 → COS → 回写 hot_ranking_snapshot")
    p.add_argument("--root", default=os.path.expanduser("~/Desktop/xhs_images"),
                   help="本地根目录（默认 ~/Desktop/xhs_images）")
    p.add_argument("--note-id", default="", help="只处理单个 note_id")
    p.add_argument("--include-videos", action="store_true",
                   help="包含 mp4/mov（默认只传图片）")
    p.add_argument("--dedup", action="store_true",
                   help="跳过 COS 上已存在的同名文件（HEAD 检查）")
    p.add_argument("--dry-run", action="store_true", help="只扫不传不写")
    p.add_argument("--no-writeback", action="store_true", help="只上传，不回写 hot_ranking_snapshot")
    return p.parse_args()


def iter_note_dirs(root: Path, only: str = "") -> list[Path]:
    """按文件名是否为合法 note_id 过滤顶层子目录."""
    if only:
        return [root / only] if (root / only).is_dir() else []
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if not NOTE_ID_RE.match(p.name):
            print(f"   ⏭️ 跳过非 note_id 目录: {p.name}")
            continue
        out.append(p)
    return out


def list_files(note_dir: Path, include_videos: bool) -> list[Path]:
    exts = IMAGE_EXTS | (VIDEO_EXTS if include_videos else set())
    files = []
    for p in sorted(note_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in exts:
            continue
        files.append(p)
    return files


def upload_one(client, note_id: str, local_path: Path, dedup: bool) -> str | None:
    """单文件上传. 返回公开 URL 或 None (跳过/失败)."""
    rel = f"{note_id}/{local_path.name}"
    cos_key = f"{COS_KEY_PREFIX}/{rel}"
    public_url = make_public_url(cos_key)

    if dedup and exists(client, cos_key):
        print(f"   ⏭️ {rel} (已存在)")
        return None  # 用 None 表示"跳过但 URL 仍应入表"

    print(f"📤 {rel} ({local_path.stat().st_size:,} bytes)")
    print(f"   cos_key: {cos_key}")
    print(f"   url:     {public_url}")
    print(f"   ctype:   {content_type_for(local_path)}")

    try:
        actual_url = upload_file(client, cos_key, local_path)
        print("   ✅ uploaded")
        return actual_url
    except Exception as e:
        print(f"   ❌ failed: {e}")
        return False  # False 表示"失败不入表"


def writeback(client_supabase, urls_by_note: dict[str, list[str]]):
    """按 note_id 聚合 URL 数组，UPSERT 到 hot_ranking_snapshot.cos_image_urls."""
    if not urls_by_note:
        print("📝 无 URL 需要回写")
        return 0
    print("\n📝 回写 hot_ranking_snapshot:")
    count = 0
    for nid, urls in urls_by_note.items():
        # 排序保证幂等：避免 _1 后上传触发 _2 时也写 _1 —— 共同出现时只看最终集合
        urls_sorted = sorted(set(urls))
        rec = {"note_id": nid, "cos_image_urls": urls_sorted}
        try:
            client_supabase.table("hot_ranking_snapshot").upsert(
                rec, on_conflict="note_id"
            ).execute()
            print(f"   {nid} → cos_image_urls ({len(urls_sorted)} 个)")
            count += 1
        except Exception as e:
            print(f"   {nid} → ❌ 写表失败: {e}")
    return count


def main():
    args = parse_args()
    root = Path(args.root).expanduser()

    print(f"🔍 扫描 {root}")
    if args.dry_run:
        print("   (dry-run 模式：只扫不传不写)")

    note_dirs = iter_note_dirs(root, args.note_id)
    if not note_dirs:
        print(f"❌ 没有可处理的 note_id 目录 (root={root})")
        return

    total_files = 0
    img_count = 0
    vid_count = 0
    for d in note_dirs:
        fs = list_files(d, args.include_videos)
        total_files += len(fs)
        for f in fs:
            if f.suffix.lower() in IMAGE_EXTS:
                img_count += 1
            else:
                vid_count += 1

    print(f"   note_ids: {[d.name for d in note_dirs]}")
    print(f"   文件数: {total_files} (img={img_count}, video={vid_count})")

    # 接入 Supabase
    import db
    sb_client = db.connect() if not args.no_writeback else None
    if not args.no_writeback and sb_client is None:
        print("❌ Supabase 连接失败（db.connect() 返回 None），但继续上传...")
        sb_client = None

    cos_client = make_client()

    uploaded = skipped = failed = 0
    urls_by_note: dict[str, list[str]] = {}

    if not args.dry_run:
        for d in note_dirs:
            nid = d.name
            urls_by_note[nid] = []
            for f in list_files(d, args.include_videos):
                result = upload_one(cos_client, nid, f, args.dedup)
                if result is None:  # dedup 跳过
                    skipped += 1
                    # 跳过时也要把 COS 上现成的 URL 算出来写回表
                    rel = f"{nid}/{f.name}"
                    urls_by_note[nid].append(make_public_url(f"{COS_KEY_PREFIX}/{rel}"))
                elif result is False:  # 失败
                    failed += 1
                else:  # 成功
                    urls_by_note[nid].append(result)
                    uploaded += 1

        if not args.no_writeback and sb_client is not None:
            writeback(sb_client, urls_by_note)

    print("\n════════════════════════════════════")
    if args.dry_run:
        print(f"扫描 {len(note_dirs)} 个 note_id / {total_files} 个文件（dry-run）")
    else:
        print(f"扫描 {len(note_dirs)} 个 note_id / {total_files} 个文件")
        print(f"已上传 {uploaded} / 跳过 {skipped} / 失败 {failed}")
        if not args.no_writeback and sb_client is not None:
            print(f"回写 {len(urls_by_note)} 条 hot_ranking_snapshot 记录")
        elif args.no_writeback:
            print("回写: 跳过（--no-writeback）")
        else:
            print("回写: 跳过（Supabase 未连接）")
    print("════════════════════════════════════")


if __name__ == "__main__":
    main()
