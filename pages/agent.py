import streamlit as st
import requests
import os

st.set_page_config(page_title="AI 运营助手", page_icon="🤖", layout="wide")

st.title("🤖 AI 运营助手")

st.markdown("输入主题，获取**关键词分析 + 封面设计 Prompt + 文字热梗 + 完整运营策略**")

message = st.text_area(
    "请输入你的问题",
    placeholder="例如：帮我分析车贴这个赛道，给一份完整的运营策略",
    height=100,
)

col_url, col_btn = st.columns([3, 1])

with col_url:
    agent_url = st.text_input(
        "Agent 服务地址",
        value=os.getenv("XHS_AGENT_URL", "http://localhost:8000"),
    )

with col_btn:
    st.write("")
    st.write("")
    run = st.button("🚀 分析", type="primary", use_container_width=True)

if run and message:
    with st.spinner("AI 分析中，请稍候..."):
        try:
            resp = requests.post(
                f"{agent_url.rstrip('/')}/invoke",
                json={"message": message},
                timeout=180,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.last_result = data
            else:
                st.error(f"请求失败: {resp.status_code} - {resp.text}")
                st.session_state.last_result = None
        except Exception as e:
            st.error(f"连接失败: {e}")
            st.session_state.last_result = None

if "last_result" in st.session_state and st.session_state.last_result:
    data = st.session_state.last_result
    intent = data.get("intent", "")
    theme = data.get("theme", "")
    thread_id = data.get("thread_id", "")

    st.divider()
    st.caption(f"**Intent:** `{intent}`  |  **Theme:** `{theme}`  |  **Thread:** `{thread_id[:16]}...`")

    # 根据 intent 选择展示方式
    if intent == "strategy":
        tab_kw, tab_design, tab_text, tab_strategy = st.tabs([
            "🔑 关键词矩阵",
            "🎨 封面设计 Prompt",
            "✍️ 文字热梗 & Prompt",
            "📋 运营策略",
        ])

        with tab_kw:
            kw_md = data.get("keywords_md", "")
            if kw_md:
                st.markdown(kw_md)
            else:
                st.info("无关键词数据")

        with tab_design:
            dp = data.get("design_prompt", "")
            if dp:
                st.markdown("```\n" + dp + "\n```")
            else:
                st.info("无封面设计 Prompt")

        with tab_text:
            tp = data.get("text_prompt", "")
            if tp:
                st.markdown(tp)
            else:
                st.info("无文字热梗数据")

        with tab_strategy:
            strategy = data.get("strategy", {})
            if strategy:
                themes = strategy.get("themes", [])
                if themes:
                    st.subheader("🎯 主题方向")
                    for t in themes:
                        st.markdown(f"- **{t.get('theme', '')}** — {t.get('why', '')}")
                    st.divider()

                titles = strategy.get("title_candidates", [])
                if titles:
                    st.subheader("✍️ 标题候选")
                    for t in titles:
                        st.markdown(f"- {t.get('title', '')}  _(切入: {t.get('angle', '')})_")
                    st.divider()

                tags = strategy.get("tags", [])
                if tags:
                    st.subheader("🏷️ 推荐标签")
                    st.markdown(" ".join(f"`{x}`" for x in tags))
                    st.divider()

                brief = strategy.get("image_prompt_brief", "")
                if brief:
                    st.subheader("🎨 封面意图")
                    st.markdown(brief)
                    st.divider()

                schedule = strategy.get("schedule", "")
                if schedule:
                    st.subheader("⏰ 发布建议")
                    st.markdown(schedule)
            else:
                st.info("无策略数据")

    else:
        # keywords / design / chat 等意图，直接显示 output
        output = data.get("output", "")
        if output:
            st.markdown(output)
        else:
            st.info("无输出内容")

    # 展开 steps
    with st.expander("📊 执行步骤"):
        for step in data.get("steps", []):
            st.json(step)
