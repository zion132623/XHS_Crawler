"""启动 MediaCrawler 关键词搜索爬取.

用法:
    python scripts/crawl_keyword.py --keywords "原创车贴"
    python scripts/crawl_keyword.py --keywords "可爱 车贴" --max-notes 50 --max-comments 30
    python scripts/crawl_keyword.py --keywords "原创车贴" --proxy kuaidaili
    python scripts/crawl_keyword.py --keywords "原创车贴" --output-dir ./crawl_logs

工作机制:
    1. 直接传 keywords 给 MediaCrawler 的 search 模式
    2. Popen main.py 写日志
    3. 日志命名规范 crawl_{keywords[:20]}_{timestamp}.log
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MEDIACRAWLER_DIR = Path("/Users/zion/Desktop/MediaCrawler/MediaCrawler")
MEDIACRAWLER_PYTHON = MEDIACRAWLER_DIR / ".venv" / "bin" / "python"
CRAWL_LOG_DIR = ROOT / "crawl_logs"


def build_cmd(keywords: str, max_notes: int, max_comments: int,
              enable_proxy: bool, proxy_provider: str) -> list[str]:
    cmd = [
        str(MEDIACRAWLER_PYTHON), "main.py",
        "--platform", "xhs", "--lt", "qrcode",
        "--type", "search",
        "--keywords", keywords,
        "--save_data_option", "postgres",
        "--crawler_max_notes_count", str(max_notes),
        "--max_concurrency_num", "1",
    ]
    if max_comments > 0:
        cmd.extend([
            "--get_comment", "true",
            "--max_comments_count_singlenotes", str(max_comments),
        ])
    if enable_proxy:
        cmd.extend(["--enable_ip_proxy", "true", "--ip_proxy_provider_name", proxy_provider])
    return cmd


def launch(keywords: str, max_notes: int = 20, max_comments: int = 0,
           enable_proxy: bool = True, proxy_provider: str = "kuaidaili",
           log_dir: Path = CRAWL_LOG_DIR) -> tuple[int, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    kw_short = keywords.replace(" ", "_")[:20]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"crawl_{kw_short}_{timestamp}.log"
    cmd = build_cmd(keywords, max_notes, max_comments, enable_proxy, proxy_provider)

    with log_path.open("w") as f:
        f.write("=== MediaCrawler 关键词搜索 ===\n")
        f.write(f"启动时间: {datetime.datetime.now()}\nCMD: {' '.join(cmd)}\n")
        f.write(f"keywords={keywords} max_notes={max_notes} max_comments={max_comments}\n")
        f.write("=" * 50 + "\n\n")
        process = subprocess.Popen(cmd, cwd=str(MEDIACRAWLER_DIR), stdout=f, stderr=subprocess.STDOUT)

    return process.pid, log_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="关键词搜索爬取")
    p.add_argument("--keywords", required=True, help="搜索关键词，多个词用空格分隔")
    p.add_argument("--max-notes", type=int, default=20, help="最大爬取笔记数 (5-300)")
    p.add_argument("--max-comments", type=int, default=0, help="每帖最大评论数 (0 表示不爬)")
    p.add_argument("--proxy", choices=["kuaidaili", "kuaidaili_kps", "wandouhttp", "static"],
                   help="启用代理时的服务商名")
    p.add_argument("--output-dir", default=str(CRAWL_LOG_DIR), help="日志输出目录")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        pid, log_path = launch(
            keywords=args.keywords,
            max_notes=args.max_notes,
            max_comments=args.max_comments,
            enable_proxy=bool(args.proxy),
            proxy_provider=args.proxy or "kuaidaili",
            log_dir=Path(args.output_dir),
        )
        print(f"OK keywords={args.keywords} pid={pid} log={log_path}", flush=True)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
