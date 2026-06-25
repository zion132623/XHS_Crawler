import streamlit as st
import pandas as pd
import sys, os
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

MEDIACRAWLER_DIR = "/Users/zion/Desktop/MediaCrawler/MediaCrawler"
MEDIACRAWLER_PYTHON = os.path.join(MEDIACRAWLER_DIR, ".venv", "bin", "python")
CRAWL_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawl_logs")

st.set_page_config(page_title="管理后台", page_icon="🔧", layout="wide")


def parse_wan(val):
    if pd.isna(val):
        return 0
    s = str(val).strip()
    if "万" in s:
        return int(float(s.replace("万", "")) * 10000)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _read_csv(file):
    return pd.read_csv(file, encoding="utf-8-sig", engine="python")


def clean_numeric_cols(df, cols):
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_wan)
    return df


# 门禁：仅 admin
if not auth.is_logged_in() or not auth.is_admin():
    st.error("无权访问")
    st.stop()

st.title("🔧 管理后台")

# 初始化 Supabase
if "db_conn" not in st.session_state:
    st.session_state.db_conn = db.connect()

client = st.session_state.db_conn

tab1, tab2, tab3, tab4 = st.tabs(["📊 数据库管理", "👤 用户管理", "📥 CSV 导入", "🚀 爬虫控制"])

with tab1:
    st.subheader("数据库统计")
    if st.button("刷新统计"):
        stats = db.table_stats(client)
        st.session_state.db_stats = stats

    if "db_stats" in st.session_state:
        s = st.session_state.db_stats
        col1, col2 = st.columns(2)
        col1.metric("帖子总数", s["xhs_note"])
        col2.metric("评论总数", s["comments"])

    st.divider()
    st.subheader("清空数据")
    st.warning("此操作不可撤销")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("清空全部帖子", type="secondary"):
            try:
                data = client.table("xhs_note").select("note_id").execute()
                ids = [r["note_id"] for r in (data.data or [])]
                if ids:
                    for i in range(0, len(ids), 100):
                        chunk = ids[i:i + 100]
                        client.table("xhs_note").delete().in_("note_id", chunk).execute()
                st.success(f"已删除 {len(ids)} 条帖子")
                st.session_state.db_stats = db.table_stats(client)
            except Exception as e:
                st.error(f"删除失败: {e}")
    with col2:
        if st.button("清空全部评论", type="secondary"):
            try:
                data = client.table("comments").select("comment_id").execute()
                ids = [r["comment_id"] for r in (data.data or [])]
                if ids:
                    for i in range(0, len(ids), 100):
                        chunk = ids[i:i + 100]
                        client.table("comments").delete().in_("comment_id", chunk).execute()
                st.success(f"已删除 {len(ids)} 条评论")
                st.session_state.db_stats = db.table_stats(client)
            except Exception as e:
                st.error(f"删除失败: {e}")

with tab2:
    st.subheader("用户管理")

    sub_a, sub_b = st.columns(2)

    with sub_a:
        st.caption("创建新用户（自动设角色）")
        new_email = st.text_input("邮箱", key="new_user_email")
        new_pw = st.text_input("密码", type="password", key="new_user_pw")
        new_role = st.selectbox("角色", ["viewer", "admin"], key="new_user_role")
        if st.button("创建用户", use_container_width=True):
            if new_email and new_pw:
                try:
                    res = client.auth.sign_up(
                        {"email": new_email, "password": new_pw}
                    )
                    if res.user:
                        uid = res.user.id
                        client.table("user_roles").upsert(
                            {"user_id": uid, "role": new_role}
                        ).execute()
                        st.success(f"用户 {new_email} 已创建，角色: {new_role}")
                    else:
                        st.success(f"用户 {new_email} 已创建（需确认邮箱后首次登录）")
                except Exception as e:
                    st.error(f"创建失败: {e}")
            else:
                st.error("请输入邮箱和密码")

    with sub_b:
        st.caption("已有用户改角色")
        user_id = st.text_input("用户 UUID", placeholder="粘贴 UUID")
        role = st.selectbox("角色", ["viewer", "admin"], key="set_role")
        if st.button("设置角色", use_container_width=True):
            if user_id:
                try:
                    client.table("user_roles").upsert({"user_id": user_id, "role": role}).execute()
                    st.success(f"已设置 {user_id} 为 {role}")
                except Exception as e:
                    st.error(f"设置失败: {e}")
            else:
                st.error("请输入用户 UUID")

        st.info("UUID 从 Supabase Dashboard → Authentication → Users 查看")

with tab3:
    st.subheader("导入 CSV 到 Supabase")
    uploaded_c = st.file_uploader("上传 search_contents CSV", type="csv", key="admin_csv_c")
    uploaded_cm = st.file_uploader("上传 search_comments CSV (可选)", type="csv", key="admin_csv_cm")

    if st.button("导入入库", type="primary"):
        if not uploaded_c:
            st.error("请先上传 search_contents CSV")
        else:
            contents = _read_csv(uploaded_c)
            contents = clean_numeric_cols(contents, ["liked_count", "collected_count", "comment_count", "share_count"])
            r1 = db.import_contents(client, contents)

            r2 = {"inserted": 0, "updated": 0}
            if uploaded_cm:
                coms = _read_csv(uploaded_cm)
                coms = clean_numeric_cols(coms, ["like_count", "sub_comment_count"])
                r2 = db.import_comments(client, coms)

            st.session_state.db_stats = db.table_stats(client)
            c1 = r1["inserted"]; u1 = r1["updated"]; c2 = r2["inserted"]; u2 = r2["updated"]
            st.success(f"帖子: 新增 {c1} 条, 更新 {u1} 条 | 评论: 新增 {c2} 条, 更新 {u2} 条")


with tab4:
    st.subheader("🚀 MediaCrawler 爬取控制")
    st.caption("对单条笔记触发详情爬取，含评论（最多 200 条）")

    # Check if a crawl is already running
    crawl_running = False
    if "last_crawl" in st.session_state:
        lc = st.session_state.last_crawl
        pid = lc.get("pid")
        if pid:
            try:
                os.kill(pid, 0)  # signal 0 = check if process exists
                crawl_running = True
            except OSError:
                crawl_running = False

    if crawl_running:
        lc = st.session_state.last_crawl
        col_warn, col_stop = st.columns([3, 1])
        with col_warn:
            st.warning(f"⚠️ 爬虫正在运行中 (PID: {lc['pid']}, 启动于 {lc.get('started_at', '')})")
        with col_stop:
            if st.button("🛑 强制中断", type="secondary", use_container_width=True):
                try:
                    os.kill(lc["pid"], 9)  # SIGKILL
                    st.session_state.last_crawl["pid"] = None
                    st.success("已发送中断信号")
                    st.rerun()
                except OSError as e:
                    st.error(f"中断失败: {e}")

    col1, col2 = st.columns([2, 1])

    with col1:
        note_id = st.text_input(
            "笔记 ID (note_id)",
            placeholder="粘贴小红书的 note_id，例如 6a37d5ef000000000f01f2b6",
            disabled=crawl_running,
        )
    with col2:
        max_comments = st.slider("最大评论数", 10, 200, 200, step=10, disabled=crawl_running)

    # Proxy settings
    with st.expander("🌐 代理设置"):
        enable_proxy = st.checkbox("启用 IP 代理", value=True, disabled=crawl_running)
        proxy_provider = st.selectbox(
            "代理服务商",
            ["kuaidaili", "kuaidaili_kps", "wandouhttp", "static"],
            index=0,
            disabled=(not enable_proxy or crawl_running),
        )

    if st.button("🚀 启动爬取", type="primary", disabled=(not note_id or crawl_running), use_container_width=True):
        # Fetch xsec_token from Supabase
        with st.spinner("查询笔记信息..."):
            try:
                res = client.table("xhs_note").select("note_id,xsec_token,title,nickname").eq("note_id", note_id).execute()
                note_data = res.data[0] if res.data else None
            except Exception as e:
                st.error(f"查询 Supabase 失败: {e}")
                st.stop()

        if not note_data:
            st.error(f"未找到笔记 `{note_id}`，请先通过 CSV 导入或搜索爬取入库")
            st.stop()

        xsec_token = note_data.get("xsec_token", "")
        if xsec_token:
            url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
        else:
            url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_source=pc_search"

        title = str(note_data.get("title", ""))[:60]
        nickname = note_data.get("nickname", "")

        st.info(f"**目标**: [{title}]({url}) — @{nickname}")

        # Build command
        cmd = [
            MEDIACRAWLER_PYTHON, "main.py",
            "--platform", "xhs",
            "--lt", "cookie",
            "--type", "detail",
            "--specified_id", url,
            "--get_comment", "true",
            "--get_sub_comment", "false",
            "--save_data_option", "postgres",
            "--max_comments_count_singlenotes", str(max_comments),
            "--crawler_max_notes_count", "1",
            "--max_concurrency_num", "1",
        ]

        if enable_proxy:
            cmd.extend([
                "--enable_ip_proxy", "true",
                "--ip_proxy_provider_name", proxy_provider,
            ])

        # Prepare log file
        os.makedirs(CRAWL_LOG_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(CRAWL_LOG_DIR, f"crawl_{note_id[:12]}_{timestamp}.log")

        with open(log_path, "w") as log_file:
            log_file.write(f"=== MediaCrawler 爬取任务 ===\n")
            log_file.write(f"Note ID: {note_id}\nURL: {url}\nMax Comments: {max_comments}\n")
            log_file.write(f"启动时间: {datetime.datetime.now()}\nCMD: {' '.join(cmd)}\n")
            log_file.write("=" * 50 + "\n\n")

            process = subprocess.Popen(
                cmd,
                cwd=MEDIACRAWLER_DIR,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

        st.session_state.last_crawl = {
            "note_id": note_id,
            "title": title,
            "nickname": nickname,
            "url": url,
            "max_comments": max_comments,
            "log_path": log_path,
            "pid": process.pid,
            "started_at": timestamp,
        }

        st.success(f"✅ 爬虫已启动 (PID: {process.pid})")
        st.caption(f"日志文件: `{log_path}`")

    # Show last crawl info
    if "last_crawl" in st.session_state:
        lc = st.session_state.last_crawl
        st.divider()
        st.caption("**上次爬取任务**")
        st.json({
            "note_id": lc["note_id"],
            "标题": lc.get("title", ""),
            "作者": lc.get("nickname", ""),
            "评论上限": lc["max_comments"],
            "PID": lc["pid"],
            "启动时间": lc["started_at"],
            "日志文件": lc["log_path"],
        })
