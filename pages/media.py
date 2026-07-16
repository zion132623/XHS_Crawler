"""Streamlit Media 画廊 — 只读, 通过 HTTPS 拉 COS 上由 xhs_agent 维护的 manifest.json.

不依赖任何本地文件 / SQLite, 可直接部署到 GitHub Pages / Streamlit Cloud.

数据流:
  xhs_agent → design_agent/manifest.json (公网) → streamlit fetch → 渲染
"""
import streamlit as st
import json
import os
import ssl
import urllib.request
from pathlib import Path

st.set_page_config(page_title="📸 Media 画廊", page_icon="📸", layout="wide")

# 鉴权 (保留) — 复用 app.py 的会话
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import auth
    if not auth.is_logged_in():
        st.error("请先登录")
        st.stop()
except Exception:
    pass  # 未配置 auth 时跳过 (本地调试用)


# ── Constants ──────────────────────────────────────────
# 公网 manifest URL — 由 xhs_agent image_generate_agent 维护
COS_BUCKET = "xhscrawler-1316994008"
COS_REGION = "ap-guangzhou"
MANIFEST_URL = os.getenv(
    "XHS_MANIFEST_URL",
    f"https://{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com/design_agent/manifest.json",
)

PROMPT_TYPE_LABEL = {
    "text": "🅣 文字型",
    "pattern": "🅟 图案型",
}


# ── Helpers ──────────────────────────────────────────

def _fetch_manifest(url: str, timeout: int = 15):
    """HTTPS GET manifest.json. 返回 (manifest_dict, error_string).

    macOS 系统 Python 的 OpenSSL 不信任 COS 中间证书 — 用 certifi 包提供的 CA bundle.
    (Streamlit Cloud Linux 容器自带完整 CA, 这段兼容层不会出问题.)
    """
    try:
        import certifi  # streamlit 部署环境装这个 (xhs_crawler 已装)
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # fallback: 用系统默认 (Linux / 已打过 patch 的 mac env 通)
        ctx = ssl.create_default_context()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "xhs-streamlit/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8")), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


@st.cache_data(ttl=60, show_spinner=False)
def load_manifest() -> tuple[dict | None, str | None]:
    """Streamlit 缓存的 manifest 加载 (60s)."""
    return _fetch_manifest(MANIFEST_URL)


# ── UI ─────────────────────────────────────────────────
st.title("📸 Media 画廊")
st.caption(f"📂 数据源：`{MANIFEST_URL}` (公网只读 · 无凭据)")

manifest, err = load_manifest()
if err or not manifest:
    st.error(f"❌ 拉取 manifest 失败: {err or '空响应'}")
    st.info("请确认 xhs_agent 已运行 `/image_generate` 至少一次 — 它会写入 `design_agent/manifest.json`。")
    st.stop()

if manifest.get("schema") != "xhs_agent/manifest@1":
    st.error(f"❌ manifest schema 不匹配: {manifest.get('schema')}")
    st.stop()

items: list[dict] = manifest.get("items") or []
if not items:
    st.warning("⚠️ manifest 为空数组。请在 xhs_agent 跑 `/image_generate` 生成图片。")
    st.stop()

# Stat cards
total = len(items)
text_n = sum(1 for x in items if x.get("prompt_type") == "text")
pattern_n = sum(1 for x in items if x.get("prompt_type") == "pattern")
other_n = total - text_n - pattern_n

c1, c2, c3, c4 = st.columns(4)
c1.metric("🖼️ 总数", total)
c2.metric("🅣 文字型", text_n)
c3.metric("🅟 图案型", pattern_n)
c4.metric("🕒 最近更新", (manifest.get("updated_at") or "")[:16].replace("T", " ") + "Z")

st.divider()

# Filter
col_f1, col_f2 = st.columns([1, 4])
with col_f1:
    type_filter = st.radio(
        "类型筛选",
        options=["all", "text", "pattern"],
        format_func=lambda x: {"all": "全部", "text": "🅣 文字型", "pattern": "🅟 图案型"}[x],
        horizontal=True,
    )

filtered = items if type_filter == "all" else [
    x for x in items if x.get("prompt_type") == type_filter
]
with col_f2:
    st.caption(f"筛选后共 **{len(filtered)}** / {total} 条")

if not filtered:
    st.info(f"当前筛选 `{type_filter}` 无数据")
    st.stop()

# Gallery grid (3 columns)
COLS_PER_ROW = 3
for i in range(0, len(filtered), COLS_PER_ROW):
    chunk = filtered[i:i + COLS_PER_ROW]
    cols = st.columns(COLS_PER_ROW)
    for col, item in zip(cols, chunk):
        with col:
            ptype = item.get("prompt_type") or "?"
            badge = PROMPT_TYPE_LABEL.get(ptype, f"❓ {ptype}")
            pid = item.get("prompt_id", "?")
            st.markdown(f"**{badge}** &nbsp; `<pid={pid}>`")

            cos_url = item.get("cos_url") or ""
            if cos_url:
                try:
                    st.image(cos_url, use_container_width=True)
                except Exception as e:
                    st.error(f"图片加载失败: {e}")
            else:
                st.warning("无 COS URL")

            prompt = item.get("prompt_text") or ""
            with st.expander("📝 prompt", expanded=False):
                st.code((prompt[:600] + "…") if len(prompt) > 600 else prompt, language=None)

            if cos_url:
                st.caption(f"🔗 [打开原图]({cos_url})")

st.divider()
st.caption("🛰️ 缓存 60s · 部署到 GitHub 即可用，无凭据、无本地依赖")
