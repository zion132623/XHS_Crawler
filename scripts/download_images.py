"""opencli 下载指定 note_id / URL 的小红书图片.

用法:
    python scripts/download_images.py --note-id 6a2ab2100000000008031aa1
    python scripts/download_images.py --url "https://www.xiaohongshu.com/explore/XXX"
    python scripts/download_images.py --note-id XXX --output-dir ~/Desktop/xhs_images

工作机制:
    1. 从 Supabase xhs_note 取 xsec_token 拼签名 URL
    2. 调用 `opencli xiaohongshu download <url> --output <dir>`
    3. 日志写到 crawl_logs/download_{note_id[:12]}_{timestamp}.log

注意: 下载完通常接着跑 scripts/upload_to_cos.py 做 COS 上传+回写
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

CRAWL_LOG_DIR = ROOT / "crawl_logs"
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Desktop/xhs_images")


def extract_note_id(target: str) -> str:
    if target.startswith("http"):
        return target.split("/explore/")[-1].split("?")[0]
    return target


def build_url(note_id: str, xsec: str) -> str:
    if xsec:
        return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec}&xsec_source=pc_search"
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def launch(target: str, output_dir: str = DEFAULT_OUTPUT_DIR,
           log_dir: Path = CRAWL_LOG_DIR) -> tuple[int, Path, str]:
    nid = extract_note_id(target)

    client = db.connect()
    xsec = ""
    if client:
        res = client.table("xhs_note").select("xsec_token").eq("note_id", nid).execute()
        if res.data:
            xsec = res.data[0].get("xsec_token", "")

    url = build_url(nid, xsec)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"download_{nid[:12]}_{timestamp}.log"
    cmd = ["opencli", "xiaohongshu", "download", url, "--output", output_dir]

    with log_path.open("w") as f:
        f.write("=== OpenCLI 图片下载 ===\n")
        f.write(f"启动时间: {datetime.datetime.now()}\nCMD: {' '.join(cmd)}\n")
        f.write(f"url={url} output={output_dir}\n")
        f.write("=" * 50 + "\n\n")
        process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)

    return process.pid, log_path, nid


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="下载小红书图片 (opencli)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--note-id", help="note_id (自动从 Supabase 取 xsec_token)")
    g.add_argument("--url", help="完整 explore URL")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    p.add_argument("--log-dir", default=str(CRAWL_LOG_DIR), help="日志目录")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        target = args.note_id or args.url
        pid, log_path, nid = launch(
            target=target,
            output_dir=args.output_dir,
            log_dir=Path(args.log_dir),
        )
        print(f"OK note_id={nid} pid={pid} log={log_path}", flush=True)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
