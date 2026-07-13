# xhs_crawler - 小红书数据爬取 & 商品发布

## 项目结构

- `app.py` — 主面板，5个Tab：热帖排行/发布时间优化/内容策略分析/同行分析/评论分析
- `pages/media.py` — 图片分析（调用 xhs_agent 生成 MJ/DALL-E prompt，存 Supabase）
- `pages/keywords.py` — 关键词分类管理（level1/level2）
- `pages/agent.py` — AI运营助手（外部 agent 服务）
- `db.py` — 数据库连接和查询函数

## 数据库关键表

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `xhs_note` | 笔记主表 | note_id, title, source_keyword, tag_list, image_list, liked_count |
| `hot_ranking_snapshot` | 热榜快照 | note_id, rank_all, cos_image_urls |
| `keywords` | 关键词分类 | keyword, level1, level2 |
| `image_analysis_results` | 图片分析结果 | note_id, analysis_type, mj_prompts, dalle_prompts, status |

## Skills

- `/upload-product` — 小红书ARK发布商品固定流程（cookie登录→上传3:4主图→读图取标题→选类目）

## 架构设计（待实现）

### 工具型 Agent vs 流水线型 Agent

| | 流水线型 (现有 xhs_agent) | 工具型 (待实现) |
|--|--|--|
| 架构 | LangGraph StateGraph，固定节点顺序 | LLM 自己决定调用哪些工具 |
| 路径 | 预设固定，LLM 只做路由 | LLM 动态规划执行路径 |
| 输入 | 用户指定 note_id | 用户说主题/关键词，agent 自主发现 |
| 灵活性 | 低 | 高 |

**工具型核心逻辑：**
```
用户消息 → LLM + Tools列表 → LLM决定用哪个工具 → 执行 → 结果回传 → 再次LLM决定 → ...
```

**工具列表（待实现）：**
1. `list_keyword_categories()` — 查 keywords 表 level1/level2 分类
2. `query_hot_notes(keyword, limit)` — 按关键词查热帖
3. `get_note_images(note_id)` — 获取笔记 COS 图片 URL
4. `analyze_image(image_url, analysis_type)` — 调 MiniMax 视觉 API
5. `analyze_note_images(note_id, analysis_type, exclude_indices)` — 批量分析
6. `save_analysis_result(note_id, analysis_type, result)` — 存库
7. `get_pending_analyses()` — 查待审核列表
8. `update_analysis_status(...)` — 更新状态/编辑 prompts

### Human-in-the-Loop 审核流程

分析结果先存 `status='pending'`，设计师可：
1. **审批通过** → `status='approved'`
2. **编辑 prompt** → 修改后 `status='approved'`
3. **删除某张图重分析** → 排除该图重新分析，`status='pending'`

Supabase 改动：
```sql
ALTER TABLE image_analysis_results ADD COLUMN status TEXT DEFAULT 'pending';
```

media.py 改动：顶部 tab `[⚑ 分析] [⏳ 待审核] [✅ 已通过]`

### 热帖按一级分类筛选

热帖排行 Tab 加一级分类筛选 selectbox，按 `source_keyword` 匹配过滤：
1. 从 `keywords` 表读 level1 列表
2. 用户选分类 → 过滤出 source_keyword 包含该分类下任意关键词的笔记
3. 过滤后重新计算热帖分数
