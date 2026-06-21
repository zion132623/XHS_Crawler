import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth

st.set_page_config(page_title="停用词管理", page_icon="📝", layout="wide")

# Admin only
if not auth.is_logged_in() or not auth.is_admin():
    st.error("无权访问")
    st.stop()

st.title("📝 停用词管理")

STOPWORDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "stopwords.txt",
)


def load_stopwords():
    if not os.path.exists(STOPWORDS_PATH):
        return []
    with open(STOPWORDS_PATH, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_stopwords(words):
    with open(STOPWORDS_PATH, "w", encoding="utf-8") as f:
        for w in sorted(set(words)):
            f.write(w + "\n")


words = load_stopwords()

col_a, col_b = st.columns([2, 1])

with col_a:
    st.subheader(f"当前停用词 ({len(words)} 个)")

    search = st.text_input("搜索", placeholder="输入关键词筛选...")
    filtered = [w for w in words if search in w] if search else words

    st.dataframe(
        [{"词": w} for w in filtered],
        use_container_width=True,
        hide_index=True,
        height=500,
    )

with col_b:
    st.subheader("操作")

    # Add
    new_words = st.text_area(
        "添加停用词（一行一个）",
        placeholder="输入新词，每行一个...",
        height=120,
    )
    if st.button("➕ 添加", use_container_width=True):
        added = [w.strip() for w in new_words.split("\n") if w.strip()]
        if added:
            all_words = set(words)
            new_count = 0
            for w in added:
                if w not in all_words:
                    all_words.add(w)
                    new_count += 1
            save_stopwords(list(all_words))
            st.success(f"已添加 {new_count} 个新词（{len(added) - new_count} 个已存在）")
            st.rerun()

    # Delete
    del_words = st.text_area(
        "删除停用词（一行一个）",
        placeholder="输入要删除的词，每行一个...",
        height=120,
    )
    if st.button("🗑️ 删除", use_container_width=True):
        removed = [w.strip() for w in del_words.split("\n") if w.strip()]
        if removed:
            all_words = set(words)
            del_count = 0
            for w in removed:
                if w in all_words:
                    all_words.remove(w)
                    del_count += 1
            save_stopwords(list(all_words))
            st.success(f"已删除 {del_count} 个词")
            st.rerun()

    # Reset
    if st.button("🔄 重置为默认", use_container_width=True, type="secondary"):
        save_stopwords([
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
            "都", "一", "这", "他", "她", "它", "们", "那", "些", "做",
            "什么", "怎么", "如果", "因为", "所以", "但是", "可以", "觉得", "感觉",
            "这个", "那个", "真的", "还是", "然后", "已经", "非常", "就是", "好像",
            "应该", "一点", "一下", "有点", "大家", "或者", "还有", "不是", "不过",
            "确实", "其实", "很多", "可能", "需要", "想", "让", "被", "把", "能",
            "对", "从", "没", "吗", "吧", "呢", "啊", "呀", "哦", "嗯",
            "么", "也", "还", "太", "挺", "更", "最", "又", "再", "才",
            "刚", "哈", "啦", "哟", "嘛", "哇", "嘻", "嘿", "呵",
            "小红书", "车贴", "贴", "车", "话题",
        ])
        st.success("已重置为默认停用词")
        st.rerun()
