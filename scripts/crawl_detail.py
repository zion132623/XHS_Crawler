"""启动 MediaCrawler 单条详情页爬取 (cookies 已在 MediaCrawler 目录里).

用法:
    python scripts/crawl_detail.py --note-id NOTE_ID [--max-comments 200]
    python scripts/crawl_detail.py --note-id NOTE_ID --proxy kuaidaili
    python scripts/crawl_detail.py --note-id NOTE_ID --output-dir ./crawl_logs

工作机制:
    1. 从 Supabase xhs_note 表读 xsec_token
    2. 拼成带签名的 explore URL
    3. Popen MediaCrawler 的 main.py, stdout/stderr 全部写日志
    4. 返回 (pid, log_path) 让调用方 (Streamlit / LangGraph node) 做后续轮询
"""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))
import db  # noqa: E402

MEDIACRAWLER_DIR = Path("/Users/zion/Desktop/MediaCrawler/MediaCrawler")
MEDIACRAWLER_PYTHON = MEDIACRAWLER_DIR / ".venv" / "bin" / "python"
CRAWL_LOG_DIR = ROOT / "crawl_logs"


def build_url(note_id: str, xsec: str) -> str:
    if xsec:
        return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec}&xsec_source=pc_search"
    return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_source=pc_search"


def build_cmd(note_id: str, xsec: str, max_comments: int, enable_proxy: bool, proxy_provider: str) -> list[str]:
    cmd = [
        str(MEDIACRAWLER_PYTHON), "main.py",
        "--platform", "xhs", "--lt", "qrcode",
        "--type", "detail",
        "--specified_id", build_url(note_id, xsec),
        "--get_comment", "true",
        "--get_sub_comment", "false",
        "--save_data_option", "postgres",
        "--max_comments_count_singlenotes", str(max_comments),
        "--crawler_max_notes_count", "1",
        "--max_concurrency_num", "1",
    ]
    if enable_proxy:
        cmd.extend(["--enable_ip_proxy", "true", "--ip_proxy_provider_name", proxy_provider])
    return cmd


def launch(note_id: str, max_comments: int = 200, enable_proxy: bool = True,
           proxy_provider: str = "kuaidaili", log_dir: Path = CRAWL_LOG_DIR) -> tuple[int, Path]:
    client = db.connect()
    if not client:
        raise RuntimeError("Supabase 未配置 (检查 .env)")
    res = client.table("xhs_note").select("note_id,xsec_token,title,nickname").eq("note_id", note_id).execute()
    if not res.data:
        raise ValueError(f"未找到 note_id={note_id}")
    note = res.data[0]
    xsec = note.get("xsec_token", "")

    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"crawl_{note_id[:12]}_{timestamp}.log"
    cmd = build_cmd(note_id, xsec, max_comments, enable_proxy, proxy_provider)

    with log_path.open("w") as f:
        f.write("=== MediaCrawler 详情爬取 ===\n")
        f.write(f"启动时间: {datetime.datetime.now()}\nCMD: {' '.join(cmd)}\n")
        f.write(f"title={note.get('title','')[:60]} nickname={note.get('nickname','')}\n")
        f.write("=" * 50 + "\n\n")
        process = subprocess.Popen(cmd, cwd=str(MEDIACRAWLER_DIR), stdout=f, stderr=subprocess.STDOUT)

    return process.pid, log_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if False else "单条详情爬取")
    p.add_argument("--note-id", required=True, help="目标 note_id")
    p.add_argument("--max-comments", type=int, default=200, help="每帖最大评论数 (10-200)")
    p.add_argument("--proxy", choices=["kuaidaili", "kuaidaili_kps", "wandouhttp", "static"],
                   help="启用代理时的服务商名；不传则不代理")
    p.add_argument("--output-dir", default=str(CRAWL_LOG_DIR), help="日志输出目录")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        pid, log_path = launch(
            note_id=args.note_id,
            max_comments=args.max_comments,
            enable_proxy=bool(args.proxy),
            proxy_provider=args.proxy or "kuaidaili",
            log_dir=Path(args.output_dir),
        )
        print(f"OK pid={pid} log={log_path}", flush=True)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
