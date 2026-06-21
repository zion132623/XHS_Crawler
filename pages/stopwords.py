import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

st.set_page_config(page_title="停用词管理", page_icon="📝", layout="wide")

if not auth.is_logged_in():
    st.error("请先登录")
    st.stop()

st.title("📝 停用词管理")

DEFAULT_WORDS = [
    "的","了","在","是","我","有","和","就","不","人",
    "都","一","这","他","她","它","们","那","些","做",
    "什么","怎么","如果","因为","所以","但是","可以","觉得","感觉",
    "这个","那个","真的","还是","然后","已经","非常","就是","好像",
    "应该","一点","一下","有点","大家","或者","还有","不是","不过",
    "确实","其实","很多","可能","需要","想","让","被","把","能",
    "对","从","没","吗","吧","呢","啊","呀","哦","嗯",
    "么","也","还","太","挺","更","最","又","再","才",
    "刚","哈","啦","哟","嘛","哇","嘻","嘿","呵",
    "小红书","车贴","贴","车","话题",
]


def load_stopwords():
    client = db.connect()
    if not client:
        return []
    words = []
    start, limit = 0, 1000
    while True:
        res = client.table("stopwords").select("word").range(start, start + limit - 1).execute()
        if not res.data:
            break
        words.extend(r["word"] for r in res.data)
        if len(res.data) < limit:
            break
        start += limit
    return sorted(words)


def add_stopwords(new_words):
    client = db.connect()
    if not client:
        return 0
    batch = [{"word": w} for w in new_words]
    res = client.table("stopwords").upsert(batch, on_conflict="word").execute()
    return len(res.data) if res.data else 0


def delete_stopwords(words_to_delete):
    client = db.connect()
    if not client:
        return 0
    count = 0
    for w in words_to_delete:
        res = client.table("stopwords").delete().eq("word", w).execute()
        if res.data:
            count += 1
    return count


def reset_stopwords():
    client = db.connect()
    if not client:
        return
    client.table("stopwords").delete().neq("word", "__IMPOSSIBLE__").execute()
    batch = [{"word": w} for w in DEFAULT_WORDS]
    client.table("stopwords").upsert(batch, on_conflict="word").execute()


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

    new_words = st.text_area(
        "添加停用词（一行一个）",
        placeholder="输入新词，每行一个...",
        height=120,
    )
    if st.button("➕ 添加", use_container_width=True):
        added = [w.strip() for w in new_words.split("\n") if w.strip()]
        if added:
            existing = set(load_stopwords())
            really_new = [w for w in added if w not in existing]
            if really_new:
                add_stopwords(really_new)
                st.success(f"已添加 {len(really_new)} 个新词")
            else:
                st.info("所有词都已存在")
            st.rerun()

    del_words = st.text_area(
        "删除停用词（一行一个）",
        placeholder="输入要删除的词，每行一个...",
        height=120,
    )
    if st.button("🗑️ 删除", use_container_width=True):
        removed = [w.strip() for w in del_words.split("\n") if w.strip()]
        if removed:
            del_count = delete_stopwords(removed)
            st.success(f"已删除 {del_count} 个词")
            st.rerun()

    if st.button("🔄 重置为默认", use_container_width=True, type="secondary"):
        reset_stopwords()
        st.success("已重置为默认停用词")
        st.rerun()
