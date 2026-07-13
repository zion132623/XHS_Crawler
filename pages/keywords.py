import streamlit as st
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth
import db

st.set_page_config(page_title="关键词管理", page_icon="🏷️", layout="wide")

if not auth.is_logged_in():
    st.error("请先登录")
    st.stop()

st.title("🏷️ 关键词管理")

client = db.connect()
if not client:
    st.error("无法连接 Supabase")
    st.stop()


def load_all_source_keywords():
    """从 xhs_note.source_keyword 提取所有唯一关键词"""
    df = db.query_contents(client)
    if df.empty or "source_keyword" not in df.columns:
        return set()
    keywords = set()
    for val in df["source_keyword"].dropna():
        for k in str(val).split(","):
            k = k.strip()
            if k:
                keywords.add(k)
    return keywords


def load_keywords():
    """从 keywords 表加载已分类的关键词"""
    return db.get_keywords(client)


def load_level1s():
    """获取所有一级分类名"""
    return db.get_all_levels(client)[0]


def update_keyword_level1(keyword, level1):
    """更新某关键词的一级分类"""
    existing = db.get_keywords(client, search=keyword)
    if existing:
        db.update_keyword(client, existing[0]["id"], level1=level1)
    else:
        db.create_keyword(client, keyword, level1=level1)


def add_level1(name):
    """新增一级分类（存入 keywords 表）"""
    existing = load_level1s()
    if name.strip() and name.strip() not in existing:
        db.create_keyword(client, name.strip(), level1=name.strip())


def delete_keyword(keyword):
    """删除关键词（仅从 keywords 表删除，不影响 xhs_note）"""
    existing = db.get_keywords(client, search=keyword)
    if existing:
        db.delete_keyword(client, existing[0]["id"])


# 加载数据
source_keywords = load_all_source_keywords()  # 所有来自笔记的关键词
classified = load_keywords()  # keywords 表中已分类的
level1s = load_level1s()

# 建立 keyword -> level1 的映射
kw_level1_map = {kw["keyword"]: kw.get("level1") for kw in classified}

# 合并：所有 source_keyword + 已在 keywords 表中的分类
all_display = []
for kw in sorted(source_keywords):
    all_display.append({
        "keyword": kw,
        "level1": kw_level1_map.get(kw),
    })

# 分类管理区
st.subheader("📁 一级分类管理")
col_cat, col_add = st.columns([3, 1])

with col_cat:
    if level1s:
        st.write(" | ".join(level1s))
    else:
        st.info("暂无一级分类")

with col_add:
    new_l1 = st.text_input("新增分类", placeholder="输入名称...", key="new_l1_name")
    if st.button("➕ 添加", use_container_width=True):
        if new_l1.strip():
            add_level1(new_l1.strip())
            st.success(f"已添加: {new_l1}")
            st.rerun()
        else:
            st.warning("请输入分类名")

st.divider()

# 关键词列表
st.subheader(f"关键词列表 ({len(all_display)} 个)")

# 筛选
col_filter_l1, col_filter_search = st.columns([1, 2])
with col_filter_l1:
    filter_l1 = st.selectbox("筛选一级分类", ["全部"] + level1s, key="filter_l1")

with col_filter_search:
    filter_search = st.text_input("搜索关键词", placeholder="输入关键词...", key="filter_search")

# 筛选后的列表
filtered = all_display
if filter_l1 != "全部":
    filtered = [r for r in filtered if r["level1"] == filter_l1]
if filter_search:
    filtered = [r for r in filtered if filter_search in r["keyword"]]

st.write(f"共 {len(filtered)} 个关键词")

# 展示
for i, row in enumerate(filtered):
    col_kw, col_l1, col_act = st.columns([3, 2, 1])

    with col_kw:
        st.write(f"**{row['keyword']}**")

    with col_l1:
        selected = st.selectbox(
            "一级分类",
            ["(无)"] + level1s,
            index=(["(无)"] + level1s).index(row["level1"]) if row["level1"] in level1s else 0,
            key=f"l1_{i}_{row['keyword']}",
            label_visibility="collapsed",
        )
        if selected != "(无)" and selected != row["level1"]:
            update_keyword_level1(row["keyword"], selected)
            st.rerun()

    with col_act:
        if st.button("🗑️", key=f"del_{i}_{row['keyword']}", help="从分类中移除"):
            delete_keyword(row["keyword"])
            st.rerun()

    st.divider()
