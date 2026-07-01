"""Design Tutor — 多模态设计建议页面（多帖子多图同时丢给 M3）.

鉴权：普通登录即可，同 stopwords.py 风格.
持久化：无（仅 st.session_state）.
"""

import streamlit as st
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

st.set_page_config(page_title="Design Tutor", page_icon="🎨", layout="wide")

if not auth.is_logged_in():
    st.error("请先登录")
    st.stop()

st.title("🎨 Design Tutor")
st.caption("从热门帖批量取图 → 喂给 MiniMax-M3 多模态 → 拿设计建议。仅本次会话保留。")

NOTE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,32}$")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


# =============================================================================
# 模型参数模板 — 在这里调参，实时生效
# =============================================================================

# System prompt 模板 {num_images} = 已选图片数量（自动填充）
DEFAULT_SYSTEM_PROMPT = (
    "You are a design tutor specializing in Xiaohongshu (RED) visual trends. "
    "Analyze the provided images and give actionable design advice. "
    "Always respond in Chinese. Output structured JSON when requested."
)

# 生成参数模板（会在 UI 侧边栏显示）
DEFAULT_MODEL_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 2048,
    "top_p": 0.9,
    "top_k": 0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "stop": "",
    "response_format": "",
}


def _get_model_params(session_params: dict) -> dict:
    """从传入参数生成 API 调用用的 dict，None/空值不传入."""
    api_params = {}
    for k, v in session_params.items():
        if v is None or v == "":
            continue
        if k == "stop" and v:
            api_params["stop"] = v
        elif k == "response_format" and v:
            api_params["response_format"] = {"type": v}
        elif k in DEFAULT_MODEL_PARAMS:
            api_params[k] = v
    return api_params


def _is_image_url(u: str) -> bool:
    path = u.split("?")[0].lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTS)


@st.cache_data(ttl=60)
def load_hot_with_cos(_client):
    """拉 hot_ranking_snapshot 当前在榜、cos_image_urls 非空的帖子."""
    res = (
        _client.table("hot_ranking_snapshot")
        .select("note_id,title,nickname,rank_all,cos_image_urls")
        .is_("exit_time", "null")
        .order("rank_all", desc=False)
        .execute()
    )
    rows = []
    for r in res.data or []:
        urls = r.get("cos_image_urls") or []
        if not isinstance(urls, list) or len(urls) == 0:
            continue
        n_img = sum(1 for u in urls if _is_image_url(u))
        if n_img == 0:
            continue
        rows.append(r)
    return rows


client = st.session_state.get("db_conn") or db.connect()
st.session_state.db_conn = client

# ---------------- Sidebar: 选择帖子 ----------------
with st.sidebar:
    st.subheader("🗂 选帖子")
    hot_rows = load_hot_with_cos(client)
    if not hot_rows:
        st.info("当前热帖里没有已上传 COS 图的。请先在 admin 下载并上传。")
        selected = []
    else:
        opts = []
        for r in hot_rows:
            urls = r["cos_image_urls"]
            n_total = len(urls)
            n_img = sum(1 for u in urls if _is_image_url(u))
            n_vid = n_total - n_img
            label = f"🖼️{n_img}"
            if n_vid:
                label += f" (视频×{n_vid})"
            label += f" [#{r['rank_all']}] {str(r['title'])[:30]} — @{r.get('nickname','')}"
            opts.append({
                "note_id": r["note_id"],
                "label": label,
                "urls": [u for u in urls if _is_image_url(u)],
                "title": r.get("title", ""),
            })
        labels = [o["label"] for o in opts]
        picked_labels = st.multiselect(
            "已上传 COS 的热门帖子（仅图片）",
            labels,
            default=labels[: min(3, len(labels))],
        )
        selected = [o for o in opts if o["label"] in picked_labels]

    st.divider()
    st.subheader("⚙️ 模型")
    model_name = st.text_input(
        "Model", value=os.getenv("MINIMAX_MODEL", "MiniMax-M3"),
        help="模型名称，如 MiniMax-M3、gpt-4o 等"
    )

    st.divider()
    st.subheader("📐 生成参数")

    # Temperature
    temperature = st.slider(
        "temperature（随机性）",
        min_value=0.0, max_value=2.0,
        value=DEFAULT_MODEL_PARAMS["temperature"],
        step=0.05,
        help="0=固定输出，2=高度随机。设计建议推荐 0.5-0.8，头脑风暴推荐 0.9+",
    )

    # Max tokens
    max_tokens = st.slider(
        "max_tokens（最大长度）",
        min_value=256, max_value=8192,
        value=DEFAULT_MODEL_PARAMS["max_tokens"],
        step=256,
        help="单次回复最大 token 数，超出会截断",
    )

    # Top P
    top_p = st.slider(
        "top_p（核采样）",
        min_value=0.0, max_value=1.0,
        value=DEFAULT_MODEL_PARAMS["top_p"],
        step=0.05,
        help="通常与 temperature 二选一；设为 1.0 则不限制",
    )

    # Frequency penalty
    frequency_penalty = st.slider(
        "frequency_penalty（重复惩罚）",
        min_value=0.0, max_value=2.0,
        value=DEFAULT_MODEL_PARAMS["frequency_penalty"],
        step=0.1,
        help=">0.5 减少重复内容，0=无惩罚",
    )

    # Presence penalty
    presence_penalty = st.slider(
        "presence_penalty（话题新鲜度）",
        min_value=0.0, max_value=2.0,
        value=DEFAULT_MODEL_PARAMS["presence_penalty"],
        step=0.1,
        help=">0 鼓励引入新话题，0=无",
    )

    st.divider()
    st.subheader("🧠 System Prompt")
    system_prompt = st.text_area(
        "System",
        value=DEFAULT_SYSTEM_PROMPT,
        height=120,
        help="{num_images} 会被自动替换为已选图片数量",
    )

    st.divider()
    st.subheader("🔧 其他")
    include_thinking = st.checkbox("显示思考内容", value=True)

    # 收集所有参数到 session_state
    st.session_state.model_params = {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "stop": DEFAULT_MODEL_PARAMS["stop"],
        "response_format": DEFAULT_MODEL_PARAMS["response_format"],
    }
    st.session_state.system_prompt = system_prompt

# ---------------- 主面板：图缩略图 + prompt + 调模型 ----------------
st.subheader("🖼 已选图片预览")
if not selected:
    st.warning("左侧至少选一个帖子")
else:
    flat_imgs = []
    for s in selected:
        for u in s["urls"]:
            flat_imgs.append((s["note_id"], u))
    flat_imgs = flat_imgs[:24]

    cols_per_row = 4
    for i in range(0, len(flat_imgs), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, (nid, url) in enumerate(flat_imgs[i : i + cols_per_row]):
            with cols[j]:
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.code(url)
                st.caption(f"{nid[:8]}…")

st.divider()

DEFAULT_PROMPT = (
    "请基于这些小红书热门帖图片，给出可执行的设计建议。"
    "用 JSON 输出，每条建议含：category、advice、confidence（高/中/低）、ref_note_ids。"
)
prompt = st.text_area(
    "💬 Prompt（发给 M3）",
    value=DEFAULT_PROMPT,
    height=160,
    help="会被拼到多模态 content 的 text 部分；图片在前，按顺序。",
)

col_run, col_clear = st.columns([1, 1])
with col_run:
    run = st.button(
        "🚀 调 MiniMax-M3",
        type="primary",
        disabled=(not selected or not prompt.strip()),
        use_container_width=True,
    )
with col_clear:
    if st.button("🧹 清结果", use_container_width=True):
        for k in ["dt_result", "dt_thinking", "dt_error"]:
            st.session_state.pop(k, None)
        st.rerun()

if run:
    base_url = os.getenv("MINIMAX_BASE_URL")
    api_key = os.getenv("MINIMAX_API_KEY")

    if not (base_url and api_key):
        st.error("❌ .env 缺 MINIMAX_BASE_URL 或 MINIMAX_API_KEY")
        st.stop()

    user_content = []
    for nid, url in flat_imgs:
        user_content.append({"type": "text", "text": f"[{nid}]"})
        user_content.append({"type": "image_url", "image_url": {"url": url}})
    user_content.append({"type": "text", "text": prompt})

    msgs = [
        {
            "role": "system",
            "content": st.session_state.system_prompt.format(num_images=len(flat_imgs)),
        },
        {"role": "user", "content": user_content},
    ]

    # 生成 API 参数
    api_params = _get_model_params(st.session_state.model_params)

    with st.spinner("调用 M3 中…"):
        try:
            from openai import OpenAI
            oc = OpenAI(api_key=api_key, base_url=base_url)
            resp = oc.chat.completions.create(
                model=model_name,
                messages=msgs,
                **api_params,
                extra_body={"reasoning_split": True},
            )
            msg = resp.choices[0].message
            st.session_state.dt_result = msg.content
            rd = getattr(msg, "reasoning_details", None)
            st.session_state.dt_thinking = (
                "\n".join(d.get("text", "") for d in rd) if rd else None
            )
            st.session_state.dt_error = None
        except Exception as e:
            st.session_state.dt_error = f"{type(e).__name__}: {e}"
            st.session_state.dt_result = None
            st.session_state.dt_thinking = None

# ---------------- 结果区 ----------------
if "dt_error" in st.session_state and st.session_state.dt_error:
    st.error(st.session_state.dt_error)

if st.session_state.get("dt_result"):
    if include_thinking and st.session_state.get("dt_thinking"):
        with st.expander("🧠 Thinking", expanded=False):
            st.code(st.session_state.dt_thinking)
    st.subheader("✨ M3 回复")
    st.markdown(st.session_state.dt_result)
