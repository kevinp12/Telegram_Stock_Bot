"""database.py
SQLite 資料層：持股、分批成本、FIFO 賣出、已實現損益、雷達清單。
支援多使用者隔離。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
import json

from config import BASE_DIR, DB_NAME

USER_LOG_PATH = Path(BASE_DIR) / "user.log"
USER_LOG_TTL_SECONDS = 7 * 24 * 60 * 60


def _to_ts(dt: datetime) -> float:
    return dt.timestamp()


def get_conn():
    return sqlite3.connect(DB_NAME)


def _now_ts() -> float:
    return datetime.now().timestamp()


def _read_user_log_entries() -> list[dict]:
    if not USER_LOG_PATH.exists():
        return []
    entries: list[dict] = []
    cutoff = _now_ts() - USER_LOG_TTL_SECONDS
    try:
        with USER_LOG_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = float(item.get("ts", 0) or 0)
                if ts >= cutoff:
                    entries.append(item)
    except FileNotFoundError:
        return []
    return entries


def prune_user_log() -> None:
    """清除 user.log 中超過 7 天的暫存紀錄。"""
    entries = _read_user_log_entries()
    if not entries:
        try:
            USER_LOG_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return
    with USER_LOG_PATH.open("w", encoding="utf-8") as handle:
        for item in entries:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def reset_user_log() -> None:
    """保留 user.log，不因重啟清空；僅清理超過 7 天的紀錄。"""
    prune_user_log()


def record_user_interaction(
    user_id: int,
    question: str,
    answer: str | None = None,
    *,
    display_name: str = "",
    username: str = "",
    source: str = "text",
) -> None:
    """寫入 7 天暫存互動紀錄。自然語言與 /ask 可附 answer；其他指令只記 question。"""
    question = (question or "").strip()
    answer = (answer or "").strip() if answer is not None else ""
    if not question:
        return
    prune_user_log()
    item = {
        "ts": _now_ts(),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": int(user_id),
        "display_name": (display_name or "").strip(),
        "username": (username or "").strip(),
        "source": source,
        "question": question[:4000],
        "answer": answer[:12000],
    }
    with USER_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def get_user_interaction_logs(user_id: int, limit: int = 10, page: int = 1) -> tuple[list[dict], int]:
    """讀取指定使用者 7 天內暫存互動紀錄（支援分頁）。"""
    prune_user_log()
    entries = [item for item in _read_user_log_entries() if int(item.get("user_id", 0) or 0) == int(user_id)]
    entries.sort(key=lambda item: (float(item.get("ts", 0) or 0), int(item.get("id", 0) or 0)), reverse=True)
    size = max(1, int(limit))
    total = len(entries)
    total_pages = max(1, (total + size - 1) // size)
    current_page = min(max(1, int(page)), total_pages)
    start = (current_page - 1) * size
    end = start + size
    return entries[start:end], total_pages


def init_db() -> None:
    with get_conn() as conn:
        c = conn.cursor()
        # 建立交易表，增加 user_id
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                model_pref TEXT DEFAULT 'flash',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                buy_price REAL NOT NULL,
                quantity REAL NOT NULL,
                trade_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        # 建立觀察清單表，主鍵改為 (user_id, symbol)
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, symbol)
            )
            """)
        # 建立狙擊名單表
        c.execute("""
            CREATE TABLE IF NOT EXISTS sniper_list (
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, symbol)
            )
            """)
        # 建立統計表，增加 user_id
        c.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (user_id, key)
            )
            """)

        # 建立詳細 Token 日誌表
        c.execute("""
            CREATE TABLE IF NOT EXISTS token_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                model TEXT,
                prompt_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                urls TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

        # 使用者問答紀錄：供後台 /op user log 查詢
        c.execute("""
            CREATE TABLE IF NOT EXISTS qa_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

        # 檢查是否需要遷移舊資料 (如果 user_id 欄位不存在則新增)
        try:
            c.execute("SELECT user_id FROM trades LIMIT 1")
        except sqlite3.OperationalError:
            # 欄位不存在，進行簡單遷移
            # 假設舊資料 user_id 為 0
            c.execute("ALTER TABLE trades ADD COLUMN user_id INTEGER DEFAULT 0")
            c.execute(
                "CREATE TABLE watchlist_new (user_id INTEGER NOT NULL, symbol TEXT NOT NULL, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, symbol))"
            )
            c.execute("INSERT INTO watchlist_new (user_id, symbol, added_date) SELECT 0, symbol, added_date FROM watchlist")
            c.execute("DROP TABLE watchlist")
            c.execute("ALTER TABLE watchlist_new RENAME TO watchlist")

            c.execute("CREATE TABLE stats_new (user_id INTEGER NOT NULL, key TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (user_id, key))")
            c.execute("INSERT INTO stats_new (user_id, key, value) SELECT 0, key, value FROM stats")
            c.execute("DROP TABLE stats")
            c.execute("ALTER TABLE stats_new RENAME TO stats")

        # 如果舊版 users 表沒有 model_pref 欄位，嘗試新增
        c.execute("PRAGMA table_info(users)")
        existing_columns = [row[1] for row in c.fetchall()]
        if "model_pref" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN model_pref TEXT DEFAULT 'flash'")
        if "bc_active" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN bc_active INTEGER DEFAULT 0")
        if "bc_timer" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN bc_timer INTEGER DEFAULT 120")
        if "last_bc_ts" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN last_bc_ts REAL DEFAULT 0")
        if "chart_theme" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN chart_theme TEXT DEFAULT 'dark'")

        conn.commit()


def _ensure_user_stats(c, user_id: int):
    """確保特定使用者的初始統計資料存在。"""
    c.execute("INSERT OR IGNORE INTO stats (user_id, key, value) VALUES (?, 'realized_profit', 0.0)", (user_id,))
    c.execute("INSERT OR IGNORE INTO stats (user_id, key, value) VALUES (?, 'tokens_used_today', 0.0)", (user_id,))
    c.execute("INSERT OR IGNORE INTO stats (user_id, key, value) VALUES (?, 'last_token_reset_date', 0.0)", (user_id,))


def clear_portfolio_db(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM trades WHERE user_id=?", (user_id,))
        # 同時也清除已實現損益統計
        conn.execute("DELETE FROM stats WHERE user_id=? AND key='realized_profit'", (user_id,))
        conn.commit()


def clear_user_all_data(user_id: int) -> None:
    """清空使用者的資產相關資料：買賣、觀察、狙擊、已實現損益。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM trades WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM sniper_list WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM stats WHERE user_id=? AND key='realized_profit'", (user_id,))
        conn.commit()


def delete_user_all_data_by_admin(identifier: str) -> dict | None:
    """依 user_id / username / display_name 找到使用者後，刪除其主要資料並回傳目標資訊。"""
    target = find_user_by_name_or_id(identifier)
    if not target:
        return None

    uid = int(target["user_id"])
    with get_conn() as conn:
        conn.execute("DELETE FROM trades WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM watchlist WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM sniper_list WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM qa_logs WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM token_logs WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM stats WHERE user_id=?", (uid,))
        conn.commit()

    return target


def get_bc_settings(user_id: int) -> tuple[int, int, float]:
    with get_conn() as conn:
        row = conn.execute("SELECT bc_active, bc_timer, last_bc_ts FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return row
        return (0, 120, 0.0)


def update_bc_settings(user_id: int, active: int | None = None, timer: int | None = None, last_ts: float | None = None) -> None:
    with get_conn() as conn:
        if active is not None:
            conn.execute("UPDATE users SET bc_active=? WHERE user_id=?", (active, user_id))
        if timer is not None:
            conn.execute("UPDATE users SET bc_timer=? WHERE user_id=?", (timer, user_id))
        if last_ts is not None:
            conn.execute("UPDATE users SET last_bc_ts=? WHERE user_id=?", (last_ts, user_id))
        conn.commit()


def get_all_active_bc_users() -> list[dict]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT user_id, bc_timer, last_bc_ts FROM users WHERE bc_active=1").fetchall()
        return [dict(r) for r in rows]


def add_or_update_user(user_id: int, display_name: str = "", username: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
            (user_id, username, display_name, bc_active, bc_timer, last_bc_ts)
            VALUES (?, ?, ?, 0, 120, 0)
            """,
            (user_id, username or "", display_name),
        )
        conn.execute(
            "UPDATE users SET username = ?, display_name = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username or "", display_name, user_id),
        )
        conn.commit()


def set_user_model_preference(user_id: int, model_pref: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET model_pref = ? WHERE user_id = ?",
            (model_pref, user_id),
        )
        conn.commit()


def get_user_model_preference(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT model_pref FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
        return "flash"


def set_user_chart_theme(user_id: int, theme: str) -> None:
    choice = (theme or "dark").strip().lower()
    if choice not in {"dark", "light"}:
        choice = "dark"
    with get_conn() as conn:
        conn.execute("UPDATE users SET chart_theme = ? WHERE user_id = ?", (choice, user_id))
        conn.commit()


def get_user_chart_theme(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT chart_theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row[0] in {"dark", "light"}:
            return str(row[0])
        return "dark"


def get_user_display_name(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT display_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else "User"


def get_all_user_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id FROM users UNION SELECT user_id FROM trades UNION SELECT user_id FROM watchlist UNION SELECT user_id FROM stats"
        ).fetchall()
        return sorted({int(r[0]) for r in rows if r and r[0] is not None})


def get_all_users() -> list[dict]:
    """取得所有曾經互動過的使用者，用於後台查詢。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT user_id, username, display_name, first_seen, last_seen
            FROM users
            ORDER BY last_seen DESC, user_id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def find_user_by_name_or_id(identifier: str) -> dict | None:
    """用 user_id、username 或 display_name 尋找使用者。"""
    target = (identifier or "").strip()
    if not target:
        return None

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        if target.isdigit():
            row = conn.execute(
                "SELECT user_id, username, display_name, first_seen, last_seen FROM users WHERE user_id=?",
                (int(target),),
            ).fetchone()
            if row:
                return dict(row)

        username = target[1:] if target.startswith("@") else target
        row = conn.execute(
            """
            SELECT user_id, username, display_name, first_seen, last_seen
            FROM users
            WHERE lower(username)=lower(?) OR lower(display_name)=lower(?)
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (username, target),
        ).fetchone()
        if row:
            return dict(row)

        row = conn.execute(
            """
            SELECT user_id, username, display_name, first_seen, last_seen
            FROM users
            WHERE lower(display_name) LIKE lower(?) OR lower(username) LIKE lower(?)
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (f"%{target}%", f"%{username}%"),
        ).fetchone()
        return dict(row) if row else None


def record_qa_log(user_id: int, question: str, answer: str) -> None:
    """記錄使用者問題與 bot 回答。"""
    question = (question or "").strip()
    answer = (answer or "").strip()
    if not question or not answer:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO qa_logs (user_id, question, answer) VALUES (?, ?, ?)",
            (user_id, question[:4000], answer[:12000]),
        )
        conn.commit()


def get_user_qa_logs(user_id: int, limit: int = 10) -> list[dict]:
    """取得指定使用者最近問答紀錄。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, question, answer, created_at
            FROM qa_logs
            WHERE user_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_tokens(user_id: int) -> tuple[int, str]:
    """獲取指定使用者今日已用 Token 與上次紀錄日期。"""
    with get_conn() as conn:
        _ensure_user_stats(conn.cursor(), user_id)
        t = conn.execute("SELECT value FROM stats WHERE user_id=? AND key='tokens_used_today'", (user_id,)).fetchone()
        d = conn.execute("SELECT value FROM stats WHERE user_id=? AND key='last_token_reset_date'", (user_id,)).fetchone()
        return int(t[0]) if t else 0, str(d[0]) if d else ""


def update_daily_tokens(user_id: int, count: int) -> int:
    """更新指定使用者今日 Token 使用量，若跨日則歸零。"""
    today = datetime.now().strftime("%Y-%m-%d")
    used, last_date = get_daily_tokens(user_id)

    with get_conn() as conn:
        if last_date != today:
            used = count
            conn.execute("UPDATE stats SET value = ? WHERE user_id=? AND key = 'tokens_used_today'", (float(used), user_id))
            conn.execute("UPDATE stats SET value = ? WHERE user_id=? AND key = 'last_token_reset_date'", (today, user_id))
        else:
            used += count
            conn.execute("UPDATE stats SET value = value + ? WHERE user_id=? AND key = 'tokens_used_today'", (float(count), user_id))
        conn.commit()
    return used


def record_token_log(user_id: int | None, model: str, prompt: int, output: int, total: int, urls: list[str] | None = None) -> None:
    """記錄單次 AI 請求的 Token 消耗與相關網址。"""
    import json

    url_json = json.dumps(urls) if urls else None
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO token_logs (user_id, model, prompt_tokens, output_tokens, total_tokens, urls) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, model, prompt, output, total, url_json),
        )
        conn.commit()


def get_token_stats(user_id: int | None = None) -> dict[str, float]:
    """獲取 Token 消耗的統計資訊 (最小、最大、平均)。"""
    query = "SELECT MIN(total_tokens), MAX(total_tokens), AVG(total_tokens) FROM token_logs"
    params = []
    if user_id is not None:
        query += " WHERE user_id = ?"
        params.append(user_id)

    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
        if row and row[0] is not None:
            return {"min": float(row[0]), "max": float(row[1]), "avg": float(row[2])}
    return {"min": 0, "max": 0, "avg": 0}


def save_trade(user_id: int, symbol: str, price: float, quantity: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trades (user_id, symbol, buy_price, quantity) VALUES (?, ?, ?, ?)",
            (user_id, symbol.upper(), float(price), float(quantity)),
        )
        conn.commit()


def get_status(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, buy_price, quantity FROM trades WHERE user_id=? ORDER BY symbol ASC, trade_date ASC, id ASC", (user_id,)
        ).fetchall()
        return rows, []


def get_first_trade_date(user_id: int) -> str | None:
    """取得使用者第一筆交易的日期。"""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT MIN(trade_date) FROM trades WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if row and row[0]:
            return row[0]
        return None


def get_trade_ledger(user_id: int) -> list[dict]:
    """取得使用者完整交易流水（含時間）。"""
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, buy_price, quantity, trade_date
            FROM trades
            WHERE user_id=?
            ORDER BY trade_date ASC, id ASC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "symbol": str(r["symbol"]).upper(),
            "buy_price": float(r["buy_price"]),
            "quantity": float(r["quantity"]),
            "trade_date": str(r["trade_date"]),
        }
        for r in rows
    ]


def get_aggregated_portfolio(user_id: int) -> dict[str, dict[str, float]]:
    stocks, _ = get_status(user_id)
    portfolio: dict[str, dict[str, float]] = {}
    for symbol, price, qty in stocks:
        item = portfolio.setdefault(symbol, {"shares": 0.0, "total_cost": 0.0})
        item["shares"] += float(qty)
        item["total_cost"] += float(price) * float(qty)

    for symbol in list(portfolio.keys()):
        shares = portfolio[symbol]["shares"]
        if shares <= 0:
            del portfolio[symbol]
            continue
        portfolio[symbol]["avg_cost"] = portfolio[symbol]["total_cost"] / shares
    return portfolio


def get_realized_profit(user_id: int) -> float:
    with get_conn() as conn:
        _ensure_user_stats(conn.cursor(), user_id)
        row = conn.execute("SELECT value FROM stats WHERE user_id=? AND key='realized_profit'", (user_id,)).fetchone()
        return float(row[0]) if row else 0.0


def delete_trade(user_id: int, symbol: str, sell_price: float, sell_qty: float) -> tuple[float, float]:
    """FIFO 賣出。回傳 (本次已實現損益, 未成交股數 rem)。"""
    symbol = symbol.upper()
    sell_price = float(sell_price)
    rem = float(sell_qty)
    total_profit = 0.0

    with get_conn() as conn:
        c = conn.cursor()
        _ensure_user_stats(c, user_id)
        rows = c.execute(
            "SELECT id, buy_price, quantity FROM trades WHERE user_id=? AND symbol=? ORDER BY trade_date ASC, id ASC",
            (user_id, symbol),
        ).fetchall()

        for trade_id, buy_price, qty in rows:
            if rem <= 0:
                break
            qty = float(qty)
            used = min(qty, rem)
            total_profit += (sell_price - float(buy_price)) * used
            if used >= qty:
                c.execute("DELETE FROM trades WHERE id=?", (trade_id,))
            else:
                c.execute("UPDATE trades SET quantity=? WHERE id=?", (qty - used, trade_id))
            rem -= used

        if total_profit != 0:
            c.execute("UPDATE stats SET value = value + ? WHERE user_id=? AND key='realized_profit'", (total_profit, user_id))
        conn.commit()

    return total_profit, rem


def get_watchlist(user_id: int) -> list[str]:
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT symbol FROM watchlist WHERE user_id=? ORDER BY added_date ASC", (user_id,)).fetchall()]


def add_watchlist(user_id: int, symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?, ?)",
            (
                user_id,
                symbol.upper(),
            ),
        )
        conn.commit()


def del_watchlist(user_id: int, symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
            (
                user_id,
                symbol.upper(),
            ),
        )
        conn.commit()


def clear_watchlist_db(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
        conn.commit()


def get_sniper_list(user_id: int) -> list[str]:
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT symbol FROM sniper_list WHERE user_id=? ORDER BY added_date ASC", (user_id,)).fetchall()]


def add_sniper(user_id: int, symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sniper_list (user_id, symbol) VALUES (?, ?)",
            (
                user_id,
                symbol.upper(),
            ),
        )
        conn.commit()


def del_sniper(user_id: int, symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM sniper_list WHERE user_id=? AND symbol=?",
            (
                user_id,
                symbol.upper(),
            ),
        )
        conn.commit()


def clear_sniper_list(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sniper_list WHERE user_id=?", (user_id,))
        conn.commit()


def get_all_sniper_targets() -> list[tuple[int, str]]:
    with get_conn() as conn:
        return conn.execute("SELECT user_id, symbol FROM sniper_list").fetchall()
