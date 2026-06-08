"""SQLite 数据库封装 - 问答记录 / 自测 / 错题 / 文档元信息"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = "data/stats.db"


def get_db():
    Path("data").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            size INTEGER,
            chunk_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS question_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            question_hash TEXT,
            answer TEXT,
            sources TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS quiz_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            user_answer TEXT,
            standard_answer TEXT,
            result TEXT NOT NULL,
            explanation TEXT,
            mastered INTEGER DEFAULT 0,
            time_spent REAL DEFAULT 0,
            source_question_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT,
            doc_id TEXT,
            chunk_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER REFERENCES entities(id),
            relation TEXT NOT NULL,
            object_id INTEGER REFERENCES entities(id),
            doc_id TEXT
        );

        CREATE TABLE IF NOT EXISTS knowledge_point_taxonomy (
            kp_id TEXT PRIMARY KEY,
            kp_name TEXT NOT NULL,
            chapter_id TEXT NOT NULL,
            chapter_name TEXT NOT NULL,
            domain_id TEXT NOT NULL,
            domain_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunk_knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL,
            kp_id TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            UNIQUE(chunk_id, kp_id)
        );

        CREATE TABLE IF NOT EXISTS quiz_knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            kp_id TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            UNIQUE(quiz_id, kp_id)
        );

        CREATE TABLE IF NOT EXISTS question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            standard_answer TEXT NOT NULL DEFAULT '',
            difficulty TEXT DEFAULT 'medium',
            kp_id TEXT,
            tags TEXT DEFAULT '',
            usage_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS learning_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES learning_plans(id),
            order_index INTEGER NOT NULL,
            kp_id TEXT,
            action_type TEXT DEFAULT 'review',
            description TEXT NOT NULL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chunk_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL,
            quiz_id INTEGER NOT NULL,
            result TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # 为旧数据库补充 primary_kp_id 列
    try:
        conn.execute("ALTER TABLE quiz_history ADD COLUMN primary_kp_id TEXT")
        conn.commit()
    except Exception:
        pass

    # 为旧数据库补充 session_id 列
    try:
        conn.execute("ALTER TABLE quiz_history ADD COLUMN session_id TEXT")
        conn.commit()
    except Exception:
        pass

    # 为 quiz_knowledge_points 补充 created_at 列
    try:
        conn.execute("ALTER TABLE quiz_knowledge_points ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
    except Exception:
        pass

    # 为 chunk_knowledge_points 补充 quality_score 列
    try:
        conn.execute("ALTER TABLE chunk_knowledge_points ADD COLUMN quality_score REAL DEFAULT 0.5")
        conn.commit()
    except Exception:
        pass

    # 为 quiz_history / question_log 补充 profile_id 列
    try:
        conn.execute("ALTER TABLE quiz_history ADD COLUMN profile_id TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE question_log ADD COLUMN profile_id TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    conn.close()


# --- 文档元信息 ---

def add_document(filename: str, size: int, chunk_count: int = 0):
    conn = get_db()
    conn.execute(
        "INSERT INTO documents (filename, size, chunk_count) VALUES (?, ?, ?)",
        (filename, size, chunk_count),
    )
    conn.commit()
    conn.close()


def list_documents():
    conn = get_db()
    rows = conn.execute("SELECT * FROM documents WHERE status='active' ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_document(filename: str):
    conn = get_db()
    conn.execute("UPDATE documents SET status='deleted' WHERE filename=?", (filename,))
    conn.commit()
    conn.close()


def _profile_where(profile_id: str = None, table: str = ""):
    """返回 profile 过滤的 WHERE 子句和参数，None=不过滤"""
    if profile_id is None:
        return "", []
    prefix = f"{table}." if table else ""
    return f"AND {prefix}profile_id = ?", [profile_id]


# --- 问答记录 ---

def log_question(question: str, answer: str, sources: str = "", profile_id: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO question_log (question, question_hash, answer, sources, profile_id) VALUES (?, ?, ?, ?, ?)",
        (question, hash(question.strip().lower()), answer, sources, profile_id),
    )
    conn.commit()
    conn.close()


def get_top_questions(limit: int = 20, profile_id: str = None):
    """按语义哈希聚合高频问题"""
    conn = get_db()
    where, params = _profile_where(profile_id)
    rows = conn.execute(f"""
        SELECT question, question_hash, COUNT(*) as cnt, MAX(created_at) as last_asked
        FROM question_log
        WHERE 1=1 {where}
        GROUP BY question_hash
        ORDER BY cnt DESC
        LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- 自测记录 ---

def save_quiz_result(question: str, user_answer: str, standard_answer: str,
                     result: str, explanation: str, time_spent: float = 0,
                     session_id: str = None, profile_id: str = ""):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO quiz_history (question, user_answer, standard_answer, result, explanation, time_spent, session_id, profile_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (question, user_answer, standard_answer, result, explanation, time_spent, session_id, profile_id))
    quiz_id = cur.lastrowid
    conn.commit()
    conn.close()
    return quiz_id


def get_quiz_stats(profile_id: str = None):
    conn = get_db()
    where, params = _profile_where(profile_id)
    row = conn.execute(f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result='正确' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN result='部分正确' THEN 1 ELSE 0 END) as partial,
            SUM(CASE WHEN result='错误' THEN 1 ELSE 0 END) as wrong,
            AVG(time_spent) as avg_time
        FROM quiz_history
        WHERE 1=1 {where}
    """, params).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_wrong_questions(profile_id: str = None):
    """获取错题本题目（未掌握的）"""
    conn = get_db()
    where, params = _profile_where(profile_id)
    rows = conn.execute(f"""
        SELECT question, COUNT(*) as wrong_count, MAX(created_at) as last_wrong,
               GROUP_CONCAT(result, '|') as results
        FROM quiz_history
        WHERE result IN ('错误', '部分正确') AND mastered = 0 {where}
        GROUP BY question
        ORDER BY wrong_count DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_quiz_detail(question: str):
    """获取某道题的历史作答详情"""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM quiz_history WHERE question = ? ORDER BY created_at DESC
    """, (question,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_mastered(question: str):
    """标记题目为已掌握"""
    conn = get_db()
    conn.execute("UPDATE quiz_history SET mastered = 1 WHERE question = ?", (question,))
    conn.commit()
    conn.close()


def get_question_error_stats(limit: int = 20, profile_id: str = None):
    """获取每道题的作答统计（错误率降序）"""
    conn = get_db()
    where, params = _profile_where(profile_id)
    rows = conn.execute(f"""
        SELECT
            question,
            COUNT(*) as total,
            SUM(CASE WHEN result = '正确' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN result = '错误' THEN 1 ELSE 0 END) as wrong,
            SUM(CASE WHEN result = '部分正确' THEN 1 ELSE 0 END) as partial
        FROM quiz_history
        WHERE 1=1 {where}
        GROUP BY question
        HAVING total > 0
        ORDER BY (CAST(wrong AS FLOAT) + CAST(partial AS FLOAT) * 0.5) / total DESC
        LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_distinct_questions(profile_id: str = None):
    """获取所有不重复的题目"""
    conn = get_db()
    where, params = _profile_where(profile_id)
    rows = conn.execute(f"""
        SELECT DISTINCT question
        FROM quiz_history
        WHERE 1=1 {where}
        ORDER BY question
    """, params).fetchall()
    conn.close()
    return [r["question"] for r in rows]


def clear_question_log():
    """清空问答记录"""
    conn = get_db()
    conn.execute("DELETE FROM question_log")
    conn.commit()
    conn.close()


# --- 知识点分类目录 ---

def upsert_kp(kp_id: str, kp_name: str, chapter_id: str, chapter_name: str,
              domain_id: str, domain_name: str):
    """插入或更新知识点"""
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO knowledge_point_taxonomy (kp_id, kp_name, chapter_id, chapter_name, domain_id, domain_name)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (kp_id, kp_name, chapter_id, chapter_name, domain_id, domain_name))
    conn.commit()
    conn.close()


def get_all_kps():
    """获取所有知识点"""
    conn = get_db()
    rows = conn.execute("""
        SELECT kp_id, kp_name, chapter_id, chapter_name, domain_id, domain_name
        FROM knowledge_point_taxonomy ORDER BY domain_id, chapter_id, kp_id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kp_by_id(kp_id: str):
    """按 ID 获取单个知识点"""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM knowledge_point_taxonomy WHERE kp_id = ?", (kp_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_chapters():
    """获取所有去重章节"""
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT chapter_id, chapter_name, domain_id, domain_name
        FROM knowledge_point_taxonomy ORDER BY domain_id, chapter_id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_domains():
    """获取所有去重域"""
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT domain_id, domain_name FROM knowledge_point_taxonomy ORDER BY domain_id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kp_taxonomy_stats():
    """分类目录统计"""
    conn = get_db()
    kp_count = conn.execute("SELECT COUNT(*) FROM knowledge_point_taxonomy").fetchone()[0]
    ch_count = conn.execute(
        "SELECT COUNT(DISTINCT chapter_id) FROM knowledge_point_taxonomy"
    ).fetchone()[0]
    dom_count = conn.execute(
        "SELECT COUNT(DISTINCT domain_id) FROM knowledge_point_taxonomy"
    ).fetchone()[0]
    conn.close()
    return {"kp_count": kp_count, "chapter_count": ch_count, "domain_count": dom_count}


# --- Chunk ↔ 知识点映射 ---

def assign_chunk_kp(chunk_id: str, kp_id: str, confidence: float = 1.0):
    """为文本块分配知识点标签（upsert）"""
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO chunk_knowledge_points (chunk_id, kp_id, confidence)
        VALUES (?, ?, ?)
    """, (chunk_id, kp_id, confidence))
    conn.commit()
    conn.close()


def get_chunk_kps(chunk_id: str):
    """获取文本块的知识点标签列表"""
    conn = get_db()
    rows = conn.execute("""
        SELECT ckp.kp_id, kpt.kp_name, kpt.chapter_name, kpt.domain_name, ckp.confidence
        FROM chunk_knowledge_points ckp
        JOIN knowledge_point_taxonomy kpt ON ckp.kp_id = kpt.kp_id
        WHERE ckp.chunk_id = ?
        ORDER BY ckp.confidence DESC
    """, (chunk_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_chunks_for_kp(kp_id: str, limit: int = 50):
    """按知识点反查文本块"""
    conn = get_db()
    rows = conn.execute("""
        SELECT chunk_id, confidence FROM chunk_knowledge_points
        WHERE kp_id = ? ORDER BY confidence DESC LIMIT ?
    """, (kp_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unclassified_chunk_ids():
    """获取未分类的 chunk ID 列表"""
    conn = get_db()
    rows = conn.execute("""
        SELECT chunk_id FROM chunk_knowledge_points
    """).fetchall()
    classified = {r["chunk_id"] for r in rows}
    conn.close()

    import json, os
    nodes_path = "data/nodes.json"
    if not os.path.exists(nodes_path):
        return []
    with open(nodes_path, "r", encoding="utf-8") as f:
        all_nodes = json.load(f)
    return [nid for nid in all_nodes if nid not in classified]


def get_kp_assignment_stats():
    """获取 chunk 分类覆盖率统计"""
    import json, os
    conn = get_db()
    classified = conn.execute("SELECT COUNT(DISTINCT chunk_id) FROM chunk_knowledge_points").fetchone()[0]
    conn.close()

    nodes_path = "data/nodes.json"
    total = 0
    if os.path.exists(nodes_path):
        with open(nodes_path, "r", encoding="utf-8") as f:
            total = len(json.load(f))
    return {"total_chunks": total, "classified_chunks": classified,
            "unclassified": total - classified}


# --- 自测 ↔ 知识点映射 ---

def assign_quiz_kp(quiz_id: int, kp_id: str, confidence: float = 1.0):
    """为自测记录分配知识点标签（upsert）"""
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO quiz_knowledge_points (quiz_id, kp_id, confidence)
        VALUES (?, ?, ?)
    """, (quiz_id, kp_id, confidence))
    conn.commit()
    conn.close()


def get_quiz_kp(quiz_id: int):
    """获取自测记录的知识点标签"""
    conn = get_db()
    rows = conn.execute("""
        SELECT qkp.kp_id, kpt.kp_name, kpt.chapter_name, kpt.domain_name, qkp.confidence
        FROM quiz_knowledge_points qkp
        JOIN knowledge_point_taxonomy kpt ON qkp.kp_id = kpt.kp_id
        WHERE qkp.quiz_id = ?
        ORDER BY qkp.confidence DESC
    """, (quiz_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_quiz_primary_kp(quiz_id: int, kp_id: str):
    """更新 quiz_history 的 primary_kp_id"""
    conn = get_db()
    conn.execute("UPDATE quiz_history SET primary_kp_id = ? WHERE id = ?", (kp_id, quiz_id))
    conn.commit()
    conn.close()


def get_quiz_ids_without_kp():
    """获取未分配知识点的自测记录 ID 列表"""
    conn = get_db()
    rows = conn.execute("""
        SELECT qh.id FROM quiz_history qh
        LEFT JOIN quiz_knowledge_points qkp ON qh.id = qkp.quiz_id
        WHERE qkp.kp_id IS NULL
        ORDER BY qh.id
    """).fetchall()
    conn.close()
    return [r["id"] for r in rows]


def get_quiz_mastery_by_kp(profile_id: str = None):
    """按知识点聚合自测掌握度"""
    conn = get_db()
    where, params = _profile_where(profile_id, "qh")
    rows = conn.execute(f"""
        SELECT
            kpt.kp_id,
            kpt.kp_name,
            kpt.chapter_id,
            kpt.chapter_name,
            kpt.domain_id,
            kpt.domain_name,
            COUNT(qh.id) as total,
            SUM(CASE WHEN qh.result = '正确' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN qh.result = '部分正确' THEN 1 ELSE 0 END) as partial,
            SUM(CASE WHEN qh.result = '错误' THEN 1 ELSE 0 END) as wrong
        FROM quiz_knowledge_points qkp
        JOIN quiz_history qh ON qkp.quiz_id = qh.id
        JOIN knowledge_point_taxonomy kpt ON qkp.kp_id = kpt.kp_id
        WHERE 1=1 {where}
        GROUP BY kpt.kp_id
        ORDER BY kpt.domain_id, kpt.chapter_id, kpt.kp_id
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- 学习进度时间序列 ---

def get_sessions(profile_id: str = None):
    """返回所有自测轮次及统计"""
    conn = get_db()
    where, params = _profile_where(profile_id)
    rows = conn.execute(f"""
        SELECT
            session_id,
            MIN(created_at) as start_time,
            MAX(created_at) as end_time,
            COUNT(*) as question_count,
            SUM(CASE WHEN result = '正确' THEN 1 ELSE 0 END) as correct,
            SUM(CASE WHEN result = '部分正确' THEN 1 ELSE 0 END) as partial,
            SUM(CASE WHEN result = '错误' THEN 1 ELSE 0 END) as wrong
        FROM quiz_history
        WHERE session_id IS NOT NULL {where}
        GROUP BY session_id
        ORDER BY MIN(created_at)
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_mastery_timeline(kp_id: str = None, domain_id: str = None, chapter_id: str = None, profile_id: str = None):
    """
    按 session 累计计算掌握度时间序列。
    """
    conn = get_db()

    where_parts = ["qkp.kp_id IS NOT NULL"]
    params = []

    if kp_id:
        where_parts.append("qkp.kp_id = ?")
        params.append(kp_id)
    if domain_id:
        where_parts.append("kpt.domain_id = ?")
        params.append(domain_id)
    if chapter_id:
        where_parts.append("kpt.chapter_id = ?")
        params.append(chapter_id)
    if profile_id is not None:
        where_parts.append("qh.profile_id = ?")
        params.append(profile_id)

    where_clause = " AND ".join(where_parts)

    rows = conn.execute(f"""
        SELECT
            qh.session_id,
            MIN(qh.created_at) as session_time,
            COUNT(qh.id) as session_total,
            SUM(CASE WHEN qh.result = '正确' THEN 1 ELSE 0 END) as session_correct,
            SUM(CASE WHEN qh.result = '部分正确' THEN 1 ELSE 0 END) as session_partial
        FROM quiz_history qh
        JOIN quiz_knowledge_points qkp ON qh.id = qkp.quiz_id
        JOIN knowledge_point_taxonomy kpt ON qkp.kp_id = kpt.kp_id
        WHERE {where_clause} AND qh.session_id IS NOT NULL
        GROUP BY qh.session_id
        ORDER BY MIN(qh.created_at)
    """, params).fetchall()
    conn.close()

    if not rows:
        return []

    # 累计计算
    timeline = []
    cum_total = 0
    cum_correct = 0
    cum_partial = 0

    for r in rows:
        cum_total += r["session_total"]
        cum_correct += r["session_correct"]
        cum_partial += r["session_partial"]
        rate = (cum_correct + cum_partial * 0.5) / cum_total * 100 if cum_total > 0 else 0
        timeline.append({
            "session_id": r["session_id"],
            "session_time": r["session_time"],
            "cumulative_total": cum_total,
            "cumulative_correct": cum_correct,
            "cumulative_partial": cum_partial,
            "cumulative_rate": round(rate, 1),
        })

    return timeline


def backfill_session_ids():
    """为旧数据回填 session_id：同一分钟内的答题视为同一轮"""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, created_at FROM quiz_history
        WHERE session_id IS NULL
        ORDER BY created_at
    """).fetchall()

    if not rows:
        conn.close()
        return 0

    import uuid
    sessions = {}
    count = 0
    for r in rows:
        ts = r["created_at"]
        key = ts[:16]  # "2026-05-13 01:11"
        if key not in sessions:
            sessions[key] = str(uuid.uuid4())
        conn.execute("UPDATE quiz_history SET session_id = ? WHERE id = ?",
                     (sessions[key], r["id"]))
        count += 1

    conn.commit()
    conn.close()
    return count


# --- 题库管理 ---

def add_bank_question(question: str, standard_answer: str = "", difficulty: str = "medium",
                      kp_id: str = None, tags: str = ""):
    """添加题库题目，返回 id"""
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO question_bank (question, standard_answer, difficulty, kp_id, tags)
        VALUES (?, ?, ?, ?, ?)
    """, (question, standard_answer, difficulty, kp_id, tags))
    qid = cur.lastrowid
    conn.commit()
    conn.close()
    return qid


def update_bank_question(qid: int, **kwargs):
    """更新题库题目，kwargs 可包含 question, standard_answer, difficulty, kp_id, tags"""
    if not kwargs:
        return
    allowed = {"question", "standard_answer", "difficulty", "kp_id", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    values = list(updates.values())
    values.append(qid)
    conn = get_db()
    conn.execute(f"UPDATE question_bank SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_bank_question(qid: int):
    """删除题库题目"""
    conn = get_db()
    conn.execute("DELETE FROM question_bank WHERE id = ?", (qid,))
    conn.commit()
    conn.close()


def get_bank_questions(search: str = None, difficulty: str = None, kp_id: str = None,
                       limit: int = 50, offset: int = 0):
    """分页查询题库，支持搜索/难度/知识点筛选"""
    conn = get_db()
    where_parts = []
    params = []

    if search:
        where_parts.append("qb.question LIKE ?")
        params.append(f"%{search}%")
    if difficulty:
        where_parts.append("qb.difficulty = ?")
        params.append(difficulty)
    if kp_id:
        where_parts.append("qb.kp_id = ?")
        params.append(kp_id)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    rows = conn.execute(f"""
        SELECT qb.*, kpt.kp_name, kpt.chapter_name, kpt.domain_name
        FROM question_bank qb
        LEFT JOIN knowledge_point_taxonomy kpt ON qb.kp_id = kpt.kp_id
        WHERE {where_clause}
        ORDER BY qb.updated_at DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bank_question_count(search: str = None, difficulty: str = None, kp_id: str = None):
    """获取筛选后题目总数"""
    conn = get_db()
    where_parts = []
    params = []

    if search:
        where_parts.append("question LIKE ?")
        params.append(f"%{search}%")
    if difficulty:
        where_parts.append("difficulty = ?")
        params.append(difficulty)
    if kp_id:
        where_parts.append("kp_id = ?")
        params.append(kp_id)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    count = conn.execute(
        f"SELECT COUNT(*) FROM question_bank WHERE {where_clause}", params
    ).fetchone()[0]
    conn.close()
    return count


def get_bank_quiz_questions(count: int = 10, difficulty: str = None, kp_id: str = None):
    """随机抽取 N 道题供自测使用，返回问题文本列表"""
    conn = get_db()
    where_parts = []
    params = []

    if difficulty:
        where_parts.append("difficulty = ?")
        params.append(difficulty)
    if kp_id:
        where_parts.append("kp_id = ?")
        params.append(kp_id)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"

    rows = conn.execute(f"""
        SELECT question FROM question_bank
        WHERE {where_clause}
        ORDER BY RANDOM()
        LIMIT ?
    """, params + [count]).fetchall()
    conn.close()

    questions = [r["question"] for r in rows if r["question"]]

    # 更新 usage_count
    if questions:
        conn = get_db()
        conn.execute(f"""
            UPDATE question_bank SET usage_count = usage_count + 1
            WHERE question IN ({','.join('?' for _ in questions)})
        """, questions)
        conn.commit()
        conn.close()

    return questions


def get_bank_standard_answer(question: str):
    """根据题目文本获取题库中的标准答案"""
    conn = get_db()
    row = conn.execute(
        "SELECT standard_answer FROM question_bank WHERE question = ? LIMIT 1",
        (question,)
    ).fetchone()
    conn.close()
    return row["standard_answer"] if row else None


def increment_bank_correct(question: str):
    """增加某题的正确计数"""
    conn = get_db()
    conn.execute(
        "UPDATE question_bank SET correct_count = correct_count + 1 WHERE question = ?",
        (question,)
    )
    conn.commit()
    conn.close()


def get_kp_name_by_id(kp_id: str):
    """根据 kp_id 获取知识点名称"""
    conn = get_db()
    row = conn.execute(
        "SELECT kp_name FROM knowledge_point_taxonomy WHERE kp_id = ?", (kp_id,)
    ).fetchone()
    conn.close()
    return row["kp_name"] if row else ""


# --- 学习计划 ---

def deactivate_plans():
    """将所有活跃计划设为 is_active=0"""
    conn = get_db()
    conn.execute("UPDATE learning_plans SET is_active = 0 WHERE is_active = 1")
    conn.commit()
    conn.close()


def create_learning_plan():
    """创建新计划（先将旧计划 deactivate），返回 plan_id"""
    deactivate_plans()
    conn = get_db()
    cur = conn.execute("INSERT INTO learning_plans (is_active) VALUES (1)")
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()
    return plan_id


def add_plan_item(plan_id: int, order_index: int, kp_id: str, action_type: str,
                  description: str, reason: str = ""):
    """添加计划项"""
    conn = get_db()
    conn.execute("""
        INSERT INTO plan_items (plan_id, order_index, kp_id, action_type, description, reason)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (plan_id, order_index, kp_id, action_type, description, reason))
    conn.commit()
    conn.close()


def get_active_plan():
    """获取当前活跃计划，返回 (plan_dict, items_list) 或 (None, [])"""
    conn = get_db()
    plan = conn.execute(
        "SELECT * FROM learning_plans WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not plan:
        conn.close()
        return None, []

    items = conn.execute("""
        SELECT pi.*, kpt.kp_name, kpt.chapter_name, kpt.domain_name
        FROM plan_items pi
        LEFT JOIN knowledge_point_taxonomy kpt ON pi.kp_id = kpt.kp_id
        WHERE pi.plan_id = ?
        ORDER BY pi.order_index
    """, (plan["id"],)).fetchall()
    conn.close()
    return dict(plan), [dict(r) for r in items]


def get_plan_items(plan_id: int):
    """获取指定计划的所有项"""
    conn = get_db()
    items = conn.execute("""
        SELECT pi.*, kpt.kp_name, kpt.chapter_name, kpt.domain_name
        FROM plan_items pi
        LEFT JOIN knowledge_point_taxonomy kpt ON pi.kp_id = kpt.kp_id
        WHERE pi.plan_id = ?
        ORDER BY pi.order_index
    """, (plan_id,)).fetchall()
    conn.close()
    return [dict(r) for r in items]


def complete_plan_item(item_id: int):
    """标记计划项为已完成"""
    conn = get_db()
    conn.execute("""
        UPDATE plan_items SET status = 'completed', completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (item_id,))
    conn.commit()
    conn.close()


def skip_plan_item(item_id: int):
    """跳过计划项"""
    conn = get_db()
    conn.execute("UPDATE plan_items SET status = 'skipped' WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def reset_plan_item(item_id: int):
    """重置计划项为待完成"""
    conn = get_db()
    conn.execute("UPDATE plan_items SET status = 'pending', completed_at = NULL WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def get_plan_history():
    """获取历史计划列表"""
    conn = get_db()
    plans = conn.execute("""
        SELECT lp.*, COUNT(pi.id) as total_items,
               SUM(CASE WHEN pi.status = 'completed' THEN 1 ELSE 0 END) as completed_items
        FROM learning_plans lp
        LEFT JOIN plan_items pi ON lp.id = pi.plan_id
        WHERE lp.is_active = 0
        GROUP BY lp.id
        ORDER BY lp.created_at DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return [dict(r) for r in plans]


# --- Chunk 反馈与质量分 ---

def save_chunk_feedback(chunk_id: str, quiz_id: int, result: str):
    """记录一条 chunk 反馈（该 chunk 被检索后，答题结果如何）"""
    conn = get_db()
    conn.execute(
        "INSERT INTO chunk_feedback (chunk_id, quiz_id, result) VALUES (?, ?, ?)",
        (chunk_id, quiz_id, result),
    )
    conn.commit()
    conn.close()


def get_chunk_quality(chunk_id: str) -> float:
    """获取单个 chunk 的质量分（从 feedback 实时计算），无数据返回 0.5（中性）"""
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) as cnt,
               SUM(CASE WHEN result='正确' THEN 1.0 WHEN result='部分正确' THEN 0.5 ELSE 0.0 END) as score_sum
        FROM chunk_feedback WHERE chunk_id = ?
    """, (chunk_id,)).fetchone()
    conn.close()
    if row["cnt"] >= 3:
        score = row["score_sum"] / row["cnt"]
        return max(0.1, min(0.9, score))
    return 0.5


def get_chunk_qualities(chunk_ids: list[str]) -> dict:
    """批量获取 chunk 质量分，返回 {chunk_id: score}"""
    if not chunk_ids:
        return {}
    conn = get_db()
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(f"""
        SELECT chunk_id,
               COUNT(*) as cnt,
               SUM(CASE WHEN result='正确' THEN 1.0 WHEN result='部分正确' THEN 0.5 ELSE 0.0 END) as score_sum
        FROM chunk_feedback WHERE chunk_id IN ({placeholders})
        GROUP BY chunk_id
    """, chunk_ids).fetchall()
    conn.close()

    result = {}
    for r in rows:
        if r["cnt"] >= 3:
            score = r["score_sum"] / r["cnt"]
            result[r["chunk_id"]] = max(0.1, min(0.9, score))

    for cid in chunk_ids:
        if cid not in result:
            result[cid] = 0.5
    return result


def calculate_chunk_quality():
    """返回 chunk 质量分统计（质量分由 get_chunk_quality 实时计算，此函数返回统计）"""
    return get_chunk_quality_stats()


def get_chunk_quality_stats():
    """获取 chunk 质量分分布统计"""
    import json, os

    conn = get_db()
    total_feedback = conn.execute("SELECT COUNT(*) FROM chunk_feedback").fetchone()[0]
    chunks_with_fb = conn.execute(
        "SELECT COUNT(DISTINCT chunk_id) FROM chunk_feedback"
    ).fetchone()[0]

    # 计算各质量段数量
    rows = conn.execute("""
        SELECT chunk_id,
               COUNT(*) as cnt,
               SUM(CASE WHEN result='正确' THEN 1.0 WHEN result='部分正确' THEN 0.5 ELSE 0.0 END) as score_sum
        FROM chunk_feedback
        GROUP BY chunk_id
        HAVING cnt >= 3
    """).fetchall()
    conn.close()

    low = mid = high = 0
    for r in rows:
        score = r["score_sum"] / r["cnt"]
        if score < 0.4:
            low += 1
        elif score > 0.6:
            high += 1
        else:
            mid += 1

    # 总 chunk 数
    nodes_path = "data/nodes.json"
    total_chunks = 0
    if os.path.exists(nodes_path):
        with open(nodes_path, "r", encoding="utf-8") as f:
            total_chunks = len(json.load(f))

    return {
        "total_chunks": total_chunks,
        "total_feedback": total_feedback,
        "chunks_with_feedback": chunks_with_fb,
        "low_quality": low,
        "mid_quality": mid,
        "high_quality": high,
    }
