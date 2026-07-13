import streamlit as st
import pandas as pd
import sys, os
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

MEDIACRAWLER_DIR = "/Users/zion/Desktop/MediaCrawler/MediaCrawler"
CRAWL_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawl_logs")
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")

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


def _run_crawl(cmd, note_id, extra_info):
    """启动爬虫脚本（Popen），让脚本自己开 log 文件，admin 这边不写 log.
    返回 (script_pid, log_path)，log_path 和 crawler_pid 都从脚本打印的
    `OK ... pid=<crawler_pid> log=...` 行解析出. crawler_pid 是 MediaCrawler
    主进程的 pid，用于判断爬虫是否还在跑.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    process = subprocess.Popen(
        cmd,
        cwd=MEDIACRAWLER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    line = process.stdout.readline().strip()
    log_path = ""
    crawler_pid = process.pid
    for token in line.split():
        if token.startswith("pid="):
            crawler_pid = int(token[len("pid="):])
        elif token.startswith("log="):
            log_path = token[len("log="):]

    st.session_state.last_crawl = {
        "process": process,
        "note_id": note_id,
        "log_path": log_path,
        "pid": crawler_pid,
        "started_at": timestamp,
        **extra_info,
    }
    return crawler_pid, log_path


def _launch_detail_crawl(note_id, max_comments, enable_proxy, proxy_provider):
    """单条笔记详情 + 评论爬取 — 委派给 scripts/crawl_detail.py."""
    client = st.session_state.db_conn
    with st.spinner("查询笔记信息..."):
        res = client.table("xhs_note").select("note_id,xsec_token,title,nickname").eq("note_id", note_id).execute()
        note_data = res.data[0] if res.data else None
    if not note_data:
        st.error(f"未找到笔记 `{note_id}`")
        st.stop()

    title = str(note_data.get("title", ""))[:60]
    nickname = note_data.get("nickname", "")

    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "crawl_detail.py"),
           "--note-id", note_id, "--max-comments", str(max_comments)]
    if enable_proxy:
        cmd.extend(["--proxy", proxy_provider])

    pid, log_path = _run_crawl(cmd, note_id, extra_info={
        "title": title, "nickname": nickname,
        "max_comments": max_comments, "type": "detail",
    })
    st.success(f"✅ 爬虫已启动 (PID: {pid})")


def _launch_keyword_crawl(keywords, max_notes, max_comments, enable_proxy, proxy_provider):
    """关键词搜索爬取 — 委派给 scripts/crawl_keyword.py."""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "crawl_keyword.py"),
           "--keywords", keywords,
           "--max-notes", str(max_notes),
           "--max-comments", str(max_comments)]
    if enable_proxy:
        cmd.extend(["--proxy", proxy_provider])

    kw_short = keywords.replace(" ", "_")[:20]
    pid, log_path = _run_crawl(cmd, kw_short, extra_info={
        "title": f"关键词: {keywords}", "nickname": "",
        "max_comments": max_comments, "type": "search", "max_notes": max_notes,
    })
    st.success(f"✅ 关键词爬取已启动 (PID: {pid}, 关键词: {keywords})")


with tab4:
    st.subheader("🚀 MediaCrawler 爬取控制")

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

    # Load note_ids from hot ranking snapshot
    commented_ids = set()
    try:
        cdata = client.table("xhs_note_comment").select("note_id").execute()
        if cdata.data:
            commented_ids = {r["note_id"] for r in cdata.data}
    except Exception:
        pass

    # 一级分类筛选
    level1s, _ = db.get_all_levels(client)
    level1_filter = st.selectbox(
        "🏷️ 一级分类筛选",
        ["全部"] + level1s if level1s else ["全部"],
        key="crawl_level1_filter",
        disabled=crawl_running,
    )

    hot_note_opts_raw = []
    try:
        if level1_filter != "全部" and level1s:
            # 从 hot_ranking_by_level1 读取
            res = client.table("hot_ranking_by_level1") \
                .select("note_id,title,nickname,rank,source_keyword") \
                .eq("level1", level1_filter) \
                .order("rank", desc=False) \
                .execute()
            if res.data:
                for r in res.data:
                    nid = r["note_id"]
                    prefix_parts = []
                    prefix_parts.append("✅" if nid in commented_ids else "🆕")
                    hot_note_opts_raw.append({
                        "label": f"{' '.join(prefix_parts)} [#{r['rank']}] {r['title'][:40]} — @{r['nickname']} ({nid})",
                        "note_id": nid,
                        "has_comments": nid in commented_ids,
                        "cos_count": 0,
                    })
        else:
            # 从 hot_ranking_snapshot 读取
            res = client.table("hot_ranking_snapshot") \
                .select("note_id,title,nickname,rank_all,cos_image_urls") \
                .is_("exit_time", "null") \
                .order("rank_all", desc=False) \
                .execute()
            if res.data:
                for r in res.data:
                    nid = r["note_id"]
                    prefix_parts = []
                    prefix_parts.append("✅" if nid in commented_ids else "🆕")
                    cos_urls = r.get("cos_image_urls") or []
                    n_cos = len(cos_urls) if isinstance(cos_urls, list) else 0
                    if n_cos > 0:
                        prefix_parts.append(f"🖼️×{n_cos}")
                    hot_note_opts_raw.append({
                        "label": f"{' '.join(prefix_parts)} [#{r['rank_all']}] {r['title'][:40]} — @{r['nickname']} ({nid})",
                        "note_id": nid,
                        "has_comments": nid in commented_ids,
                        "cos_count": n_cos,
                    })
    except Exception:
        pass

    _SEL_KEY = "crawl_hot_note_select"

    col1, col2 = st.columns([2, 1])

    with col1:
        only_new = st.checkbox("只显示未爬评论的帖子", value=False, disabled=crawl_running)
        if hot_note_opts_raw:
            if only_new:
                filtered = [o for o in hot_note_opts_raw if not o["has_comments"]]
            else:
                filtered = hot_note_opts_raw
            labels = [""] + [o["label"] for o in filtered]
            # Reset selection after a crawl finishes
            if st.session_state.get("_clear_sel"):
                st.session_state[_SEL_KEY] = ""
                st.session_state["_clear_sel"] = False
            selected = st.selectbox(
                "从热帖快照选择笔记",
                labels,
                index=0,
                disabled=crawl_running,
                key=_SEL_KEY,
            )
            note_id = selected.split("(")[-1].rstrip(")") if selected else ""
        else:
            note_id = ""
        manual_id = st.text_input(
            "或手动输入笔记 ID",
            placeholder="粘贴 note_id",
            disabled=crawl_running,
            key="manual_note_id",
        )
        note_id = manual_id or note_id
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

    if st.button("🚀 启动详情爬取", type="primary", disabled=(not note_id or crawl_running), use_container_width=True):
        _launch_detail_crawl(note_id, max_comments, enable_proxy, proxy_provider)
        st.session_state["_clear_sel"] = True
        st.rerun()

    # ======== 关键词搜索爬取 ========
    st.divider()
    st.subheader("🔍 关键词搜索爬取")

    kw_col1, kw_col2, kw_col3 = st.columns(3)
    with kw_col1:
        keywords = st.text_input("搜索关键词", placeholder="例如: 原创车贴", disabled=crawl_running)
    with kw_col2:
        kw_notes = st.slider("爬取笔记数", 5, 300, 20, step=5, disabled=crawl_running)
    with kw_col3:
        kw_comments = st.slider("每笔记评论数", 0, 200, 0, step=10, disabled=crawl_running)

    if st.button("🔍 启动关键词爬取", type="primary", disabled=(not keywords or crawl_running), use_container_width=True):
        _launch_keyword_crawl(keywords, kw_notes, kw_comments, enable_proxy, proxy_provider)
        st.rerun()

    # ======== OpenCLI 图片下载 ========
    st.divider()
    st.subheader("📸 OpenCLI 图片下载")

    img_note_id = ""
    if hot_note_opts_raw:
        img_labels = [""] + [o["label"] for o in hot_note_opts_raw]
        img_selected = st.selectbox(
            "从热帖快照选择笔记",
            img_labels, index=0,
            disabled=crawl_running,
            key="img_note_select",
        )
        if img_selected:
            img_note_id = img_selected.split("(")[-1].rstrip(")")
    manual_img = st.text_input(
        "或手动输入笔记 URL / note_id",
        placeholder="粘贴完整URL或note_id",
        disabled=crawl_running, key="manual_img_id",
    )

    output_dir = st.text_input(
        "输出目录", value=os.path.expanduser("~/Desktop/xhs_images"),
        disabled=crawl_running, key="opencli_output",
    )

    auto_upload_cos = st.checkbox(
        "下载完成后自动上传 COS 并回写 hot_ranking_snapshot",
        value=True, disabled=crawl_running, key="auto_upload_cos",
        help="要求该 note_id 已存在于 hot_ranking_snapshot，否则不允许下载",
    )

    manual_target = manual_img or img_note_id
    if auto_upload_cos and manual_target:
        check_nid = (
            manual_target.split("/explore/")[-1].split("?")[0]
            if manual_target.startswith("http") else manual_target
        )
        try:
            check_res = client.table("hot_ranking_snapshot") \
                .select("note_id") \
                .eq("note_id", check_nid) \
                .execute()
            if not check_res.data:
                st.warning(
                    f"⚠️ `{check_nid}` 不在 hot_ranking_snapshot 表里，"
                    "开启「自动上传 COS」时不允许下载。先保存热门快照，或取消勾选。"
                )
        except Exception:
            pass

    if st.button(
        "📸 下载图片", type="primary",
        disabled=(not manual_target or crawl_running),
        use_container_width=True,
    ):
        if manual_target.startswith("http"):
            nid = manual_target.split("/explore/")[-1].split("?")[0]
        else:
            nid = manual_target

        if auto_upload_cos:
            try:
                check_res = client.table("hot_ranking_snapshot") \
                    .select("note_id") \
                    .eq("note_id", nid) \
                    .execute()
                if not check_res.data:
                    st.error(
                        f"❌ `{nid}` 不在 hot_ranking_snapshot 表里，无法启动下载。"
                        "请先保存热门快照再试。"
                    )
                    st.stop()
            except Exception as e:
                st.error(f"❌ 校验 hot_ranking_snapshot 失败: {e}")
                st.stop()

        cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "download_images.py"),
               "--note-id", nid, "--output-dir", output_dir]
        pid, log_path = _run_crawl(cmd, nid[:12], extra_info={
            "title": f"图片下载: {nid}", "nickname": "",
            "max_comments": 0, "type": "opencli",
            "auto_upload_cos": auto_upload_cos,
            "target_note_id": nid,
        })
        st.success(f"✅ OpenCLI 已启动 (PID: {pid}) → {output_dir}")
        st.rerun()

    # ======== 爬取状态 + 实时日志（自动刷新） ========
    @st.fragment(run_every=3)
    def _render_crawl_status():
        if "last_crawl" not in st.session_state:
            return
        lc = st.session_state.last_crawl
        pid = lc.get("pid")

        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False

        st.divider()
        st.subheader("📡 爬取状态")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if alive:
                st.success("🟢 运行中")
            else:
                st.info("🔴 已结束")
        with col_b:
            st.metric("PID", pid or "-")
        with col_c:
            st.metric("评论上限", lc.get("max_comments", 0))

        st.caption(f"📌 笔记: **{str(lc.get('title',''))[:50]}** — @{lc.get('nickname','')}")
        st.caption(f"🕐 启动: {lc.get('started_at','')} | 📄 日志: `{lc.get('log_path','')}`")

        log_path = lc.get("log_path", "")
        if log_path and os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    lines = f.readlines()
                tail = lines[-80:] if len(lines) > 80 else lines
                with st.expander(f"📄 实时日志（最近 {len(tail)} 行 / 共 {len(lines)} 行）", expanded=alive):
                    st.code("".join(tail), language="log")
            except Exception:
                pass

        if not alive:
            st.success("✅ 爬取任务已结束，可发起新任务")

            if (
                lc.get("type") == "opencli"
                and lc.get("auto_upload_cos")
                and not lc.get("upload_triggered")
                and not lc.get("upload_result")
            ):
                target_nid = lc.get("target_note_id")
                if target_nid:
                    st.session_state.last_crawl["upload_triggered"] = True
                    with st.spinner(f"📤 自动上传 COS + 回写: {target_nid[:12]}..."):
                        try:
                            proc = subprocess.run(
                                [
                                    sys.executable,
                                    "scripts/upload_to_cos.py",
                                    "--include-videos",
                                    "--note-id", target_nid,
                                ],
                                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                capture_output=True, text=True, timeout=300,
                            )
                            st.session_state.last_crawl["upload_result"] = {
                                "returncode": proc.returncode,
                                "stdout": proc.stdout[-2000:],
                                "stderr": proc.stderr[-1000:],
                            }
                        except Exception as e:
                            st.session_state.last_crawl["upload_result"] = {
                                "returncode": -1,
                                "stdout": "",
                                "stderr": str(e),
                            }
                    st.rerun()

            ur = lc.get("upload_result")
            if ur:
                if ur["returncode"] == 0:
                    st.success("✅ COS 上传 + 回写完成")
                else:
                    st.error(f"❌ COS 上传 / 回写失败 (rc={ur['returncode']})")
                with st.expander("📄 upload_to_cos.py 输出", expanded=(ur["returncode"] != 0)):
                    st.code(ur["stdout"] + ("\n[stderr]\n" + ur["stderr"] if ur["stderr"] else ""))

    _render_crawl_status()
