"""SQLite 数据库操作（多用户支持）"""

import sqlite3
import os
from .config import DB_PATH


def get_connection():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            mer_name    TEXT DEFAULT '',
            balance     INTEGER NOT NULL,
            tx_name     TEXT DEFAULT '',
            stu_no      TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, amount, mer_name, balance, tx_name, stu_no)
        );
        CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_tx_mer ON transactions(mer_name);
        CREATE INDEX IF NOT EXISTS idx_tx_stu ON transactions(stu_no);
    """)
    conn.commit()
    conn.close()


# ── 查询辅助 ──

def _where_stu(stu_no=""):
    """根据学号生成 WHERE 子句"""
    if stu_no:
        return "AND stu_no = ?"
    return ""


def _where_stu_consumption(stu_no=""):
    """只统计消费记录"""
    where = "WHERE amount < 0"
    if stu_no:
        where += " AND stu_no = ?"
    return where


# ── 多用户 ──

def get_users():
    """获取所有有数据的学号列表"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT stu_no FROM transactions
        WHERE stu_no != ''
        ORDER BY stu_no
    """).fetchall()
    conn.close()
    return [r["stu_no"] for r in rows]


def get_user_summary(stu_no):
    """获取某个用户的消费天数、首次和最近消费"""
    conn = get_connection()
    row = conn.execute(f"""
        SELECT
            COUNT(DISTINCT date(date)) as days,
            MIN(date) as first_date,
            MAX(date) as last_date
        FROM transactions
        WHERE amount < 0 AND stu_no = ?
    """, (stu_no,)).fetchone()
    conn.close()
    return dict(row) if row else {}


# ── 插入 ──

def insert_transactions(tx_list, stu_no=""):
    """批量插入，跳过重复"""
    conn = get_connection()
    inserted = 0
    skipped = 0

    for tx in tx_list:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO transactions
                    (date, amount, mer_name, balance, tx_name, stu_no)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                tx.get("date", ""),
                tx.get("amount", 0),
                tx.get("merName", ""),
                tx.get("balance", 0),
                tx.get("txName", ""),
                stu_no,
            ))
            if conn.total_changes > 0:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    conn.commit()
    conn.close()
    return inserted, skipped


# ── 查询 ──

def get_transaction_count(stu_no=""):
    """获取记录总数（可指定学号）"""
    conn = get_connection()
    where = _where_stu(stu_no)
    sql = f"SELECT COUNT(*) FROM transactions WHERE 1=1 {where}"
    params = (stu_no,) if stu_no else ()
    count = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return count


def get_date_range(stu_no=""):
    """获取该学号的数据时间范围"""
    conn = get_connection()
    where = _where_stu_consumption(stu_no)
    params = (stu_no,) if stu_no else ()
    row = conn.execute(f"""
        SELECT MIN(date) as first, MAX(date) as last
        FROM transactions {where}
    """, params).fetchone()
    conn.close()
    return (row["first"], row["last"]) if row and row["first"] else (None, None)


def get_latest_transaction_date(stu_no=""):
    """获取最新交易时间"""
    conn = get_connection()
    where = _where_stu(stu_no)
    params = (stu_no,) if stu_no else ()
    row = conn.execute(f"""
        SELECT MAX(date) FROM transactions WHERE 1=1 {where}
    """, params).fetchone()
    conn.close()
    return row[0] if row else None


def get_statistics(stu_no=""):
    """获取该学号的统计信息"""
    conn = get_connection()

    where_spent = _where_stu_consumption(stu_no)
    params = (stu_no,) if stu_no else ()

    stats = {}
    stats["total_spent"] = conn.execute(f"""
        SELECT COALESCE(SUM(ABS(amount)), 0) FROM transactions {where_spent}
    """, params).fetchone()[0]

    stats["total_recharge"] = conn.execute(f"""
        SELECT COALESCE(SUM(amount), 0) FROM transactions
        WHERE amount > 0 {_where_stu(stu_no)}
    """, params).fetchone()[0]

    stats["tx_count"] = conn.execute(f"""
        SELECT COUNT(*) FROM transactions {where_spent}
    """, params).fetchone()[0]

    stats["canteen_count"] = conn.execute(f"""
        SELECT COUNT(DISTINCT mer_name) FROM transactions
        WHERE mer_name != '' AND amount < 0 {_where_stu(stu_no)}
    """, params).fetchone()[0]

    conn.close()
    return stats
