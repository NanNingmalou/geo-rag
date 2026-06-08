"""知识点管理 - 三级分类目录、LLM 辅助分类、掌握度计算"""
import json
import os
import pandas as pd

TAXONOMY_PATH = "data/knowledge_taxonomy.json"


# ============================================================
# 分类目录管理
# ============================================================

def load_taxonomy() -> list[dict]:
    """从 JSON 加载完整分类目录"""
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("taxonomy", [])


def sync_taxonomy_to_db() -> int:
    """将分类目录同步到 SQLite taxonomy 表，返回同步的 KP 数量"""
    from utils.db import upsert_kp

    taxonomy = load_taxonomy()
    count = 0
    for domain in taxonomy:
        for chapter in domain.get("chapters", []):
            for kp in chapter.get("knowledge_points", []):
                upsert_kp(
                    kp_id=kp["kp_id"],
                    kp_name=kp["kp_name"],
                    chapter_id=chapter["chapter_id"],
                    chapter_name=chapter["chapter_name"],
                    domain_id=domain["domain_id"],
                    domain_name=domain["domain_name"],
                )
                count += 1
    return count


def get_taxonomy_as_df() -> pd.DataFrame:
    """返回分类目录的扁平 DataFrame"""
    from utils.db import get_all_kps
    rows = get_all_kps()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def get_chapters_by_domain(domain_id: str = None):
    """按域筛选章节"""
    from utils.db import get_chapters
    chapters = get_chapters()
    if domain_id:
        chapters = [c for c in chapters if c["domain_id"] == domain_id]
    return chapters


def get_kps_by_chapter(chapter_id: str):
    """按章筛选知识点"""
    from utils.db import get_all_kps
    all_kps = get_all_kps()
    return [kp for kp in all_kps if kp["chapter_id"] == chapter_id]


def get_kps_by_domain(domain_id: str):
    """按域筛选知识点"""
    from utils.db import get_all_kps
    all_kps = get_all_kps()
    return [kp for kp in all_kps if kp["domain_id"] == domain_id]


def build_kp_list_str(domain_id: str = None):
    """构建「知识点ID | 名称 | 章 | 域」列表字符串，供 LLM prompt 使用"""
    from utils.db import get_all_kps
    all_kps = get_all_kps()
    if domain_id:
        all_kps = [kp for kp in all_kps if kp["domain_id"] == domain_id]

    lines = []
    for kp in all_kps:
        lines.append(f"{kp['kp_id']} | {kp['kp_name']} | {kp['chapter_name']} | {kp['domain_name']}")
    return "\n".join(lines)


# ============================================================
# LLM 辅助：Chunk 打标签
# ============================================================

# 批处理 prompt：一次处理多个 chunk
BATCH_CHUNK_PROMPT = """你是一个高中地理教学专家。请为以下每个文本片段判断涉及的知识点。

知识点列表（格式：知识点ID | 知识点名称 | 所属章）：
{kp_list}

文本片段：
{chunk_entries}

请输出一个 JSON 对象（不要包含任何其他内容），key 是 chunk ID，value 是知识点数组：
{{
  "chunk_id_1": [{{"kp_id": "知识点ID", "confidence": 0.9}}],
  "chunk_id_2": [],
  ...
}}

规则：
1. 每个 chunk 最多列2个知识点
2. confidence 表示相关程度（0.0~1.0），低于0.5不要列
3. 不相关的 chunk 给空数组
4. 只输出JSON，不要解释"""


def _keyword_match_chunk(chunk_text: str) -> list[str]:
    """用关键词匹配快速找出 chunk 可能涉及的知识点，返回 kp_id 列表"""
    from utils.db import get_all_kps
    all_kps = get_all_kps()
    matches = []
    for kp in all_kps:
        kp_name = kp["kp_name"]
        # 精确匹配知识点名称（如"大气受热过程"出现在文本中）
        if kp_name in chunk_text:
            matches.append(kp["kp_id"])
        else:
            # 模糊匹配：知识点名称的关键子串（长度>=3的字词）
            for term in [kp_name[i:i+3] for i in range(0, len(kp_name)-2)]:
                if term in chunk_text and len(term) >= 3:
                    matches.append(kp["kp_id"])
                    break
    return list(set(matches))[:3]


def classify_chunks_to_kps(llm, chunk_ids: list[str] = None, batch_size: int = 5,
                           progress_callback=None) -> dict:
    """混合策略：关键词秒杀 + LLM 批处理兜底"""
    from utils.db import get_chunk_kps, assign_chunk_kp
    from utils.db import get_unclassified_chunk_ids as db_unclassified

    if chunk_ids is None:
        chunk_ids = db_unclassified()

    if not chunk_ids:
        return {}

    with open("data/nodes.json", "r", encoding="utf-8") as f:
        all_nodes = json.load(f)

    kp_list_str = build_kp_list_str()
    results = {}
    total = len(chunk_ids)

    # 第一轮：关键词匹配（秒级）
    need_llm = []
    for idx, cid in enumerate(chunk_ids):
        node = all_nodes.get(cid, {})
        text = node.get("text", "")

        kp_ids = _keyword_match_chunk(text)
        if kp_ids:
            for kp_id in kp_ids:
                assign_chunk_kp(cid, kp_id, 0.85)
            results[cid] = [(kp_id, 0.85) for kp_id in kp_ids]
        else:
            need_llm.append(cid)

        if progress_callback:
            progress_callback(idx + 1, total)

    kw_count = len(chunk_ids) - len(need_llm)

    # 第二轮：LLM 批处理（只处理关键词没匹配上的）
    if need_llm and llm:
        for i in range(0, len(need_llm), batch_size):
            batch = need_llm[i:i + batch_size]

            # 组装批处理 prompt
            entries = []
            for cid in batch:
                node = all_nodes.get(cid, {})
                text = node.get("text", "")[:300]
                entries.append(f"[ID: {cid}]\n{text}")

            chunk_entries = "\n\n---\n\n".join(entries)

            try:
                response = llm.generate(
                    BATCH_CHUNK_PROMPT.format(kp_list=kp_list_str, chunk_entries=chunk_entries),
                    max_tokens=1024,
                    temperature=0.1,
                )
                response = response.strip()
                if response.startswith("```"):
                    response = response.split("\n", 1)[1].rsplit("\n", 1)[0]

                parsed = json.loads(response)
                for cid in batch:
                    entries_list = parsed.get(cid, [])
                    for entry in entries_list:
                        conf = float(entry.get("confidence", 0.8))
                        if conf >= 0.5:
                            assign_chunk_kp(cid, entry["kp_id"], conf)
                            if cid not in results:
                                results[cid] = []
                            results[cid].append((entry["kp_id"], conf))
            except Exception:
                # 批处理失败时，对这批逐条重试
                for cid in batch:
                    node = all_nodes.get(cid, {})
                    text = node.get("text", "")[:400]
                    try:
                        resp = llm.generate(
                            CHUNK_CLASSIFY_PROMPT.format(kp_list=kp_list_str, chunk_text=text),
                            max_tokens=256,
                            temperature=0.1,
                        )
                        resp = resp.strip()
                        if resp.startswith("```"):
                            resp = resp.split("\n", 1)[1].rsplit("\n", 1)[0]
                        parsed = json.loads(resp)
                        for entry in parsed.get("knowledge_points", []):
                            conf = float(entry.get("confidence", 0.8))
                            if conf >= 0.5:
                                assign_chunk_kp(cid, entry["kp_id"], conf)
                                if cid not in results:
                                    results[cid] = []
                                results[cid].append((entry["kp_id"], conf))
                    except Exception:
                        pass

            if progress_callback:
                progress_callback(kw_count + min(i + batch_size, len(need_llm)), total)

    return results


# 单 chunk prompt（LLM 批处理失败时的降级方案）
CHUNK_CLASSIFY_PROMPT = """你是一个高中地理教学专家。请根据以下文本片段，判断它涉及哪些知识点。

可选知识点列表（格式：知识点ID | 知识点名称 | 所属章 | 所属域）：
{kp_list}

文本片段：
{chunk_text}

请输出一个 JSON（不要包含任何其他内容）：
{{"knowledge_points": [{{"kp_id": "知识点ID", "confidence": 0.95}}, ...]}}

规则：
1. 最多列出3个最相关的知识点
2. confidence 表示相关程度（0.0 ~ 1.0），低于 0.5 不要列出
3. 如果没有明确相关的知识点，返回空数组：{{"knowledge_points": []}}"""


def classify_single_chunk(llm, chunk_id: str) -> list[dict]:
    """对单个 chunk 进行 LLM 知识点分类"""
    from utils.db import assign_chunk_kp

    with open("data/nodes.json", "r", encoding="utf-8") as f:
        all_nodes = json.load(f)

    node = all_nodes.get(chunk_id, {})
    text = node.get("text", "")[:500]

    # 先试关键词
    kp_ids = _keyword_match_chunk(text)
    if kp_ids:
        result = []
        for kp_id in kp_ids:
            assign_chunk_kp(chunk_id, kp_id, 0.85)
            result.append({"kp_id": kp_id, "confidence": 0.85})
        return result

    # 关键词没命中，用 LLM
    kp_list_str = build_kp_list_str()
    try:
        response = llm.generate(
            CHUNK_CLASSIFY_PROMPT.format(kp_list=kp_list_str, chunk_text=text),
            max_tokens=256,
            temperature=0.1,
        )
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1].rsplit("\n", 1)[0]

        parsed = json.loads(response)
        result = []
        for entry in parsed.get("knowledge_points", []):
            conf = float(entry.get("confidence", 0.8))
            if conf >= 0.5:
                assign_chunk_kp(chunk_id, entry["kp_id"], conf)
                result.append({"kp_id": entry["kp_id"], "confidence": conf})
        return result
    except Exception:
        return []


# ============================================================
# LLM 辅助：自测题目分类
# ============================================================

QUIZ_CLASSIFY_PROMPT = """你是一个高中地理教学专家。请判断以下地理题目主要考察哪个知识点。

可选知识点列表（格式：知识点ID | 知识点名称 | 所属章 | 所属域）：
{kp_list}

题目：
{question}

请输出一个 JSON（不要包含任何其他内容）：
{{"kp_id": "最相关知识点ID", "confidence": 0.95, "secondary_kp_ids": []}}

规则：
1. 选择最匹配的一个知识点作为主知识点
2. confidence 表示匹配置信度（0.0 ~ 1.0），低于 0.3 时 kp_id 填 null
3. secondary_kp_ids 是次要关联的知识点 ID 列表（最多2个）
4. 如果无法判断属于哪个知识点，输出：{{"kp_id": null, "confidence": 0.0, "secondary_kp_ids": []}}"""


def classify_quiz_to_kp(llm, question: str) -> tuple:
    """对单道自测题目进行知识点分类，返回 (kp_id, confidence, secondary_kp_ids)"""
    kp_list_str = build_kp_list_str()

    try:
        response = llm.generate(
            QUIZ_CLASSIFY_PROMPT.format(kp_list=kp_list_str, question=question),
            max_tokens=256,
            temperature=0.1,
        )
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1].rsplit("\n", 1)[0]

        parsed = json.loads(response)
        kp_id = parsed.get("kp_id")
        confidence = float(parsed.get("confidence", 0.5))
        secondary = parsed.get("secondary_kp_ids", [])
        return kp_id, confidence, secondary
    except Exception:
        return None, 0.0, []


def classify_quiz_batch(llm, quiz_ids: list[int] = None,
                        progress_callback=None) -> dict:
    """批量对自测记录进行知识点分类"""
    from utils.db import assign_quiz_kp, update_quiz_primary_kp

    if quiz_ids is None:
        from utils.db import get_quiz_ids_without_kp
        quiz_ids = get_quiz_ids_without_kp()

    from utils.db import get_db
    results = {}

    for qid in quiz_ids:
        conn = get_db()
        row = conn.execute(
            "SELECT id, question FROM quiz_history WHERE id = ?", (qid,)
        ).fetchone()
        conn.close()

        if not row:
            continue

        kp_id, confidence, secondary = classify_quiz_to_kp(llm, row["question"])
        if kp_id:
            assign_quiz_kp(qid, kp_id, confidence)
            update_quiz_primary_kp(qid, kp_id)
            for sec_kp_id in secondary:
                assign_quiz_kp(qid, sec_kp_id, confidence * 0.8)
            results[qid] = (kp_id, confidence)

        if progress_callback:
            progress_callback(len(results), len(quiz_ids))

    return results


# ============================================================
# 掌握度计算
# ============================================================

def build_kp_mastery(profile_id: str = None) -> pd.DataFrame:
    """计算每个知识点的掌握度，返回 DataFrame"""
    from utils.db import get_quiz_mastery_by_kp, get_all_kps

    rows = get_quiz_mastery_by_kp(profile_id)
    if not rows:
        all_kps = get_all_kps()
        df = pd.DataFrame(all_kps) if all_kps else pd.DataFrame()
        if not df.empty:
            df["total"] = 0
            df["correct"] = 0
            df["partial"] = 0
            df["wrong"] = 0
            df["mastery_rate"] = 0.0
        return df

    df = pd.DataFrame(rows)
    df["mastery_rate"] = (
        (df["correct"] + df["partial"] * 0.5) / df["total"] * 100
    ).round(1)
    return df


def build_chapter_mastery(kp_mastery: pd.DataFrame = None) -> pd.DataFrame:
    """汇总到章级别掌握度"""
    if kp_mastery is None:
        kp_mastery = build_kp_mastery()
    if kp_mastery.empty:
        return pd.DataFrame()

    chapter = kp_mastery.groupby(["chapter_id", "chapter_name", "domain_id", "domain_name"]).agg(
        total=("total", "sum"),
        correct=("correct", "sum"),
        partial=("partial", "sum"),
        wrong=("wrong", "sum"),
    ).reset_index()
    chapter["mastery_rate"] = (
        (chapter["correct"] + chapter["partial"] * 0.5) / chapter["total"] * 100
    ).round(1)
    return chapter


def build_domain_mastery_v2(kp_mastery: pd.DataFrame = None) -> dict:
    """汇总到域级别掌握度（替代 LLM 分类方法）"""
    if kp_mastery is None:
        kp_mastery = build_kp_mastery()
    if kp_mastery.empty:
        return {}

    domain = kp_mastery.groupby(["domain_id", "domain_name"]).agg(
        total=("total", "sum"),
        correct=("correct", "sum"),
        partial=("partial", "sum"),
    ).reset_index()

    result = {}
    for _, row in domain.iterrows():
        if row["total"] > 0:
            rate = (row["correct"] + row["partial"] * 0.5) / row["total"] * 100
            result[row["domain_name"]] = {
                "correct": int(row["correct"]),
                "total": int(row["total"]),
                "rate": round(rate, 1),
            }
    return result


def get_chapter_heatmap_data(profile_id: str = None) -> pd.DataFrame:
    """构建章×域掌握度热力图数据（透视表）"""
    chapter = build_chapter_mastery(build_kp_mastery(profile_id))
    if chapter.empty:
        return pd.DataFrame()

    pivot = chapter.pivot_table(
        values="mastery_rate",
        index="chapter_name",
        columns="domain_name",
        aggfunc="mean",
    )
    return pivot


def get_weakest_kps(threshold: float = 50.0, limit: int = 10, profile_id: str = None) -> list[dict]:
    """获取最薄弱的知识点列表"""
    df = build_kp_mastery(profile_id)
    if df.empty:
        return []

    weak = df[df["mastery_rate"] < threshold].nsmallest(limit, "mastery_rate")
    return weak[["kp_id", "kp_name", "chapter_name", "domain_name", "mastery_rate", "total"]].to_dict("records")


def get_chapter_mastery_sorted() -> list[dict]:
    """章掌握度排序列表（供可视化使用）"""
    df = build_chapter_mastery()
    if df.empty:
        return []
    return df.sort_values("mastery_rate").to_dict("records")


# ============================================================
# 检索增强（可选）
# ============================================================

def get_kps_for_chunk(chunk_id: str) -> list[dict]:
    """查询某 chunk 对应的知识点"""
    from utils.db import get_chunk_kps
    return get_chunk_kps(chunk_id)


def get_chunks_for_kp(kp_id: str, limit: int = 50) -> list[str]:
    """按知识点反查 chunk ID 列表"""
    from utils.db import get_chunks_for_kp
    rows = get_chunks_for_kp(kp_id, limit)
    return [r["chunk_id"] for r in rows]


# ============================================================
# 学习进度时间序列
# ============================================================

def build_mastery_timeline(kp_id: str = None, domain_id: str = None, chapter_id: str = None, profile_id: str = None) -> pd.DataFrame:
    """
    按 session 累计计算掌握度时间序列。
    支持按知识点/域/章过滤。
    返回 DataFrame: session_id, session_time, cumulative_total, cumulative_rate
    """
    from utils.db import get_mastery_timeline as db_timeline

    rows = db_timeline(kp_id=kp_id, domain_id=domain_id, chapter_id=chapter_id, profile_id=profile_id)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["session_label"] = [f"第{i+1}轮" for i in range(len(df))]
    return df


def build_domain_timelines(profile_id: str = None):
    """
    返回每个域的累计掌握度时间序列，用于多线折线图。
    """
    from utils.db import get_domains
    domains = get_domains()
    result = {}
    for d in domains:
        df = build_mastery_timeline(domain_id=d["domain_id"], profile_id=profile_id)
        if not df.empty and len(df) >= 1:
            result[d["domain_name"]] = df
    return result


def build_progress_delta():
    """
    计算最近一轮相对于之前的知识点进步速度。
    返回 DataFrame: kp_name, domain_name, chapter_name, prev_rate, curr_rate, delta
    """
    from utils.db import get_all_kps, get_mastery_timeline as db_timeline

    kps = get_all_kps()
    if not kps:
        return pd.DataFrame()

    deltas = []
    for kp in kps:
        timeline = db_timeline(kp_id=kp["kp_id"])
        if len(timeline) < 2:
            continue
        # 最近一轮 vs 更早的平均
        curr = timeline[-1]["cumulative_rate"]
        prev = timeline[-2]["cumulative_rate"]
        if curr - prev != 0:
            deltas.append({
                "kp_id": kp["kp_id"],
                "kp_name": kp["kp_name"],
                "chapter_name": kp["chapter_name"],
                "domain_name": kp["domain_name"],
                "prev_rate": prev,
                "curr_rate": curr,
                "delta": round(curr - prev, 1),
            })

    if not deltas:
        return pd.DataFrame()
    return pd.DataFrame(deltas).sort_values("delta", ascending=False)


# ============================================================
# 学习计划生成
# ============================================================

LEARNING_PLAN_PROMPT = """你是一个高中地理教学专家。请根据学生的知识掌握情况，生成一个结构化的复习计划。

学生掌握数据（按掌握率从低到高排列）：
{weakest_kps_summary}

{progress_summary}

{error_summary}

知识域间的依赖关系：
- 自然地理（气候、地貌、水文）→ 人文地理（农业、城市、交通）
- 自然地理 → 区域发展
- 人文地理 → 区域发展
- 自然地理 + 人文地理 → 资源环境与国家安全
- 所有域 → 地理实践力（综合应用）

请输出一个 JSON 数组（不要包含任何其他内容），每个元素是一个复习步骤：
[
  {{
    "kp_id": "知识点ID（从上方数据中选取）",
    "action_type": "review|practice|retry_wrong|read",
    "description": "具体的复习建议（30字以内）",
    "reason": "为什么这一步很重要（20字以内）"
  }},
  ...
]

规则：
1. 输出6-8个步骤，按优先级从高到低排序
2. 优先安排"前置依赖"薄弱的知识点（如气候没掌握会影响农业理解，先安排气候）
3. 每个步骤指向一个具体的知识点，kp_id 必须从上方数据中选取
4. action_type 含义：review=回顾教材/笔记, practice=做练习题, retry_wrong=重做错题, read=阅读相关资料
5. 步骤之间要有逻辑递进关系，先基础后综合
6. 如果错题数据显示某些知识点错误率高，优先安排 retry_wrong 类型的步骤"""


def generate_learning_plan(llm) -> dict:
    """
    LLM 生成结构化学习计划并保存到数据库。
    返回: {"plan_id": int, "items": list[dict], "generated_at": str}
    """
    import json as json_mod
    from utils.db import (
        create_learning_plan, add_plan_item, get_quiz_mastery_by_kp,
        get_wrong_questions, get_all_kps,
    )

    # 1. 收集 KP 掌握度数据
    rows = get_quiz_mastery_by_kp()
    if rows:
        df = pd.DataFrame(rows)
        df["rate"] = ((df["correct"] + df["partial"] * 0.5) / df["total"] * 100).round(1)
        weakest = df[df["total"] > 0].sort_values("rate").head(15)
        kp_lines = []
        for _, r in weakest.iterrows():
            kp_lines.append(f"- {r['kp_id']} | {r['kp_name']} | {r['domain_name']}·{r['chapter_name']} | 掌握率 {r['rate']}%（{int(r['total'])}题）")
        weakest_summary = "\n".join(kp_lines) if kp_lines else "暂无数据"
    else:
        weakest_summary = "暂无自测数据"

    # 2. 收集进步/退步趋势（直接调用同模块函数）
    delta_df = build_progress_delta()
    if not delta_df.empty:
        improving = delta_df[delta_df["delta"] > 0].head(3)
        declining = delta_df[delta_df["delta"] < 0].head(3)
        progress_parts = []
        if not improving.empty:
            progress_parts.append("进步最快: " + ", ".join(
                f"{r['kp_name']}(+{r['delta']:.0f}%)" for _, r in improving.iterrows()
            ))
        if not declining.empty:
            progress_parts.append("退步最快: " + ", ".join(
                f"{r['kp_name']}({r['delta']:.0f}%)" for _, r in declining.iterrows()
            ))
        progress_summary = "最近趋势：\n" + "\n".join(progress_parts) if progress_parts else "最近趋势：无明显变化"
    else:
        progress_summary = "最近趋势：数据不足"

    # 3. 收集错题信息
    wrong_qs = get_wrong_questions()
    if wrong_qs:
        wrong_lines = [f"- {q['question'][:60]}（错{q['wrong_count']}次）" for q in wrong_qs[:5]]
        error_summary = "高频错题：\n" + "\n".join(wrong_lines)
    else:
        error_summary = "高频错题：暂无错题"

    # 4. 构造 prompt 并调用 LLM
    prompt = LEARNING_PLAN_PROMPT.format(
        weakest_kps_summary=weakest_summary,
        progress_summary=progress_summary,
        error_summary=error_summary,
    )

    response = llm.generate(prompt, max_tokens=1024, temperature=0.3)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("\n", 1)[0]

    try:
        steps = json_mod.loads(response)
        if not isinstance(steps, list):
            steps = []
    except Exception:
        # 尝试修复常见格式问题
        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                steps = json_mod.loads(response[start:end])
            else:
                steps = []
        except Exception:
            return {"plan_id": None, "items": [], "generated_at": "", "error": "LLM 返回的 JSON 无法解析，请重试"}

    if not steps:
        return {"plan_id": None, "items": [], "generated_at": "", "error": "LLM 未返回有效的计划步骤，请重试"}

    # 5. 保存到数据库
    plan_id = create_learning_plan()
    for i, step in enumerate(steps):
        kp_id = step.get("kp_id", "")
        # 验证 kp_id 存在
        kps = get_all_kps()
        valid_ids = {k["kp_id"] for k in kps}
        if kp_id and kp_id not in valid_ids:
            kp_id = ""

        add_plan_item(
            plan_id=plan_id,
            order_index=i + 1,
            kp_id=kp_id,
            action_type=step.get("action_type", "review"),
            description=step.get("description", ""),
            reason=step.get("reason", ""),
        )

    # 6. 返回结果
    from utils.db import get_active_plan as db_get_active_plan
    _, items = db_get_active_plan()
    from datetime import datetime

    return {
        "plan_id": plan_id,
        "items": items,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
# 数据回填
# ============================================================

def retrofit_all(llm, progress_callback=None):
    """一键回填：同步分类目录 + 分类所有未标记的 chunk 和 quiz"""
    stats = {"kps_synced": 0, "chunks_classified": 0, "quizzes_classified": 0}

    # Step 1: 同步分类目录
    stats["kps_synced"] = sync_taxonomy_to_db()

    # Step 2: 分类未标记的 chunk
    from utils.db import get_unclassified_chunk_ids
    unclassified_chunks = get_unclassified_chunk_ids()
    if unclassified_chunks:
        def chunk_progress(current, total):
            if progress_callback:
                progress_callback(f"分类文本块: {current}/{total}", current, total)

        results = classify_chunks_to_kps(llm, unclassified_chunks, progress_callback=chunk_progress)
        stats["chunks_classified"] = sum(len(v) for v in results.values())

    # Step 3: 分类未标记的 quiz
    from utils.db import get_quiz_ids_without_kp
    unclassified_quizzes = get_quiz_ids_without_kp()
    if unclassified_quizzes:
        def quiz_progress(current, total):
            if progress_callback:
                progress_callback(f"分类自测记录: {current}/{total}", current, total)

        quiz_results = classify_quiz_batch(llm, unclassified_quizzes, progress_callback=quiz_progress)
        stats["quizzes_classified"] = len(quiz_results)

    return stats
