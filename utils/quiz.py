"""自测出题与评判"""
import random
from utils.db import get_top_questions, save_quiz_result


JUDGE_PROMPT = """你是一个地理知识评判老师。根据标准答案判断学生回答是否正确。
标准答案: {standard}
学生回答: {student}
请只输出一个 JSON: {{"result": "正确/部分正确/错误", "explanation": "简短纠正或补充（不超过100字）"}}"""


def get_quiz_questions(mode: str = "top", count: int = 10, difficulty: str = None, kp_id: str = None):
    """获取自测题目列表"""
    if mode == "top":
        questions = get_top_questions(count)
        return [q["question"] for q in questions if q["question"]]
    elif mode == "wrong":
        from utils.db import get_wrong_questions
        questions = get_wrong_questions()
        return [q["question"] for q in questions if q["question"]]
    elif mode == "bank":
        from utils.db import get_bank_quiz_questions
        return get_bank_quiz_questions(count, difficulty, kp_id)
    return []


def judge_answer(llm, question: str, user_answer: str) -> dict:
    """用 LLM 评判用户答案"""
    # 先用 RAG 获取标准答案
    prompt = f"请回答以下地理问题，答案要简洁准确：\n{question}"
    standard = llm.generate(prompt, max_tokens=256, temperature=0.1)

    # 评判
    judge = judge_standard_answer(question, standard, user_answer, llm=llm)
    return {
        "question": question,
        "user_answer": user_answer,
        "standard_answer": standard,
        "result": judge.get("result", "错误"),
        "explanation": judge.get("explanation", ""),
    }


def judge_standard_answer(question: str, standard: str, student: str, llm=None) -> dict:
    """评判学生答案 — 优先用 LLM，fallback 到关键词匹配"""
    import json

    if not student.strip():
        return {"result": "错误", "explanation": "没有作答"}

    if llm is not None:
        try:
            prompt = JUDGE_PROMPT.format(standard=standard, student=student)
            response = llm.generate(prompt, max_tokens=256, temperature=0.1)
            # 尝试提取 JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("\n", 1)[0]
            result = json.loads(response)
            if "result" in result and "explanation" in result:
                return result
        except Exception:
            pass  # LLM 失败则 fallback

    # fallback: 关键词匹配
    student_lower = student.strip().lower()
    standard_lower = standard.strip().lower()

    std_words = set(standard_lower.replace("，", " ").replace("。", " ").replace(",", " ").replace(".", " ").split())
    stu_words = set(student_lower.replace("，", " ").replace("。", " ").replace(",", " ").replace(".", " ").split())

    if not std_words:
        return {"result": "部分正确", "explanation": "无法准确评判"}

    overlap = std_words & stu_words
    ratio = len(overlap) / len(std_words)

    if ratio >= 0.8:
        return {"result": "正确", "explanation": "回答准确"}
    elif ratio >= 0.4:
        return {"result": "部分正确", "explanation": f"部分正确，遗漏了一些关键信息。标准答案：{standard[:100]}"}
    else:
        return {"result": "错误", "explanation": f"与标准答案差异较大。标准答案：{standard[:100]}"}


def save_result(question: str, user_answer: str, judgement: dict, time_spent: float = 0, llm=None, session_id: str = None, profile_id: str = "", retrieved_chunk_ids: list = None):
    """保存自测结果到数据库，可选 LLM 自动分类到知识点"""
    quiz_id = save_quiz_result(
        question=question,
        user_answer=user_answer,
        standard_answer=judgement.get("standard_answer", ""),
        result=judgement.get("result", "错误"),
        explanation=judgement.get("explanation", ""),
        time_spent=time_spent,
        session_id=session_id,
        profile_id=profile_id,
    )

    # 记录 chunk 反馈
    if retrieved_chunk_ids and quiz_id:
        from utils.db import save_chunk_feedback
        result_val = judgement.get("result", "错误")
        for cid in retrieved_chunk_ids:
            try:
                save_chunk_feedback(cid, quiz_id, result_val)
            except Exception:
                pass

    # 自动知识点分类
    if llm is not None and quiz_id:
        try:
            from utils.knowledge_points import classify_quiz_to_kp
            from utils.db import assign_quiz_kp, update_quiz_primary_kp
            kp_id, confidence, secondary = classify_quiz_to_kp(llm, question)
            if kp_id:
                assign_quiz_kp(quiz_id, kp_id, confidence)
                update_quiz_primary_kp(quiz_id, kp_id)
                for sec_kp_id in secondary:
                    assign_quiz_kp(quiz_id, sec_kp_id, confidence * 0.8)
        except Exception:
            pass  # 分类失败不影响主流程

    return quiz_id


# === 知识域分类（新课标高中地理六大领域）===

GEOGRAPHY_DOMAINS = [
    ("自然地理", "气候与天气、地形地貌、水文与水系、土壤、自然植被、自然灾害等自然地理要素"),
    ("人文地理", "人口分布与迁移、城镇与乡村、农业、工业、交通运输、服务业、文化等人类活动"),
    ("区域发展", "区域特征与差异、区域协调发展、流域开发、产业转移、资源跨区域调配"),
    ("资源环境与国家安全", "自然资源利用与保护、生态环境保护、环境污染防治、国家资源安全与海洋权益"),
    ("地理信息技术", "遥感(RS)、地理信息系统(GIS)、全球卫星导航系统(GNSS/北斗)、数字地球"),
    ("地理实践力", "地图判读与绘制、地理观测与考察方法、地理实验与模拟、地理调查"),
]

CLASSIFY_PROMPT = """你是一个高中地理知识分类助手。请判断以下地理题目属于哪个知识域。

知识域列表：
{domain_list}

请只输出知识域的名字（如"自然地理"），不要输出任何解释或其他内容。

题目：{question}
属于哪个知识域？"""


def classify_domain(llm, question: str) -> str:
    """用 LLM 将题目分类到知识域"""
    domain_list = "\n".join(f"- {name}: {desc}" for name, desc in GEOGRAPHY_DOMAINS)
    prompt = CLASSIFY_PROMPT.format(domain_list=domain_list, question=question)
    try:
        result = llm.generate(prompt, max_tokens=32, temperature=0.1).strip()
        for name, _desc in GEOGRAPHY_DOMAINS:
            if name in result:
                return name
        return "其他"
    except Exception:
        return "未分类"


def build_domain_mastery(llm):
    """
    构建知识域掌握度：
    1. 获取所有去重题目
    2. LLM 分类到知识域
    3. 从 quiz_history 计算每个知识域的正确率
    返回 {domain: {"correct": int, "total": int, "rate": float}}
    """
    from utils.db import get_all_distinct_questions, get_db

    questions = get_all_distinct_questions()
    if not questions:
        return {}

    # 逐题分类（去重缓存）
    domain_map = {}
    for q in questions:
        domain_map[q] = classify_domain(llm, q)

    # 按知识域统计正确率
    conn = get_db()
    rows = conn.execute("SELECT question, result FROM quiz_history").fetchall()
    conn.close()

    domain_stats = {}
    for name, _desc in GEOGRAPHY_DOMAINS:
        domain_stats[name] = {"correct": 0, "total": 0}
    domain_stats["其他"] = {"correct": 0, "total": 0}

    for row in rows:
        q = row["question"]
        domain = domain_map.get(q, "其他")
        if domain not in domain_stats:
            domain = "其他"
        domain_stats[domain]["total"] += 1
        if row["result"] == "正确":
            domain_stats[domain]["correct"] += 1

    # 计算掌握率，过滤 total=0 的域
    result = {}
    for domain, stats in domain_stats.items():
        if stats["total"] > 0:
            result[domain] = {
                "correct": stats["correct"],
                "total": stats["total"],
                "rate": round(stats["correct"] / stats["total"] * 100, 1),
            }

    return result


DEPENDENCY_PROMPT = """你是一个高中地理教学专家。地理学科各知识域之间存在因果和支撑关系，例如：
- 自然地理（气候、地貌、水文）是理解人文地理（农业、城市选址、交通）的基础
- 区域发展的前提是掌握区域的自然地理和人文地理特征
- 地理信息技术（GIS、遥感）依赖于对地理要素和空间关系的理解

以下是学生的各知识域掌握率：

{domain_summary}

领域间常见的因果链：
1. 自然地理 → 人文地理（自然条件是人类活动的基础）
2. 自然地理 → 区域发展（自然特征是区域差异的根本）
3. 人文地理 → 区域发展（人类活动塑造区域格局）
4. 自然地理 + 人文地理 → 资源环境与国家安全
5. 地理实践力 ← 所有其他领域（综合应用能力）

请分析：
1. 找出当前最弱的知识域，逆推因果链上可能影响它的前置薄弱域
2. 给出明确的复习顺序建议（例如："先补 X → 再加强 Y → 最后攻克 Z"）
3. 控制在150字以内"""


def analyze_knowledge_dependency(llm, domain_mastery: dict) -> str:
    """LLM 分析知识域间的因果依赖，给出复习路径"""
    if not domain_mastery:
        return "数据不足，无法分析知识依赖关系"

    domain_summary = "\n".join(
        f"- {d}: 掌握率 {v['rate']}%"
        for d, v in sorted(domain_mastery.items(), key=lambda kv: kv[1]["rate"])
    )
    prompt = DEPENDENCY_PROMPT.format(domain_summary=domain_summary)
    try:
        return llm.generate(prompt, max_tokens=256, temperature=0.3)
    except Exception:
        return "LLM 分析失败，请重试"


RISK_PROMPT = """你是一个高中地理教学评估专家。请根据以下学生的知识域掌握情况，预测学习风险。

各知识域掌握率：
{domain_summary}

已知信息：
- 掌握率低于50%的领域是当前的薄弱环节
- 掌握率在50%-70%的领域处于"边缘"状态，容易下滑
- 相邻知识域之间有关联性，一个域的薄弱可能拖累相邻域

请分析：
1. 哪些知识域处于临界状态，有下滑风险
2. 这些风险域可能被哪些薄弱域拖累
3. 给出1-2条具体的预防建议
4. 控制在150字以内"""


def predict_risk(llm, domain_mastery: dict) -> str:
    """LLM 预测薄弱点风险，给出预防建议"""
    if not domain_mastery:
        return "数据不足，无法进行风险预测"

    domain_summary = "\n".join(
        f"- {d}: 掌握率 {v['rate']}%"
        for d, v in sorted(domain_mastery.items(), key=lambda kv: kv[1]["rate"])
    )
    prompt = RISK_PROMPT.format(domain_summary=domain_summary)
    try:
        return llm.generate(prompt, max_tokens=256, temperature=0.3)
    except Exception:
        return "LLM 分析失败，请重试"
