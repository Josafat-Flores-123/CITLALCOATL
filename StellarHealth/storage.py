import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
import pandas as pd

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "astramed.db"


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                astronaut_id   TEXT NOT NULL,
                astronaut_name TEXT NOT NULL,
                context     TEXT    DEFAULT 'rest',
                environment TEXT    DEFAULT 'iss',
                spo2        REAL    NOT NULL,
                heart_rate  REAL    NOT NULL,
                systolic    REAL    NOT NULL,
                diastolic   REAL    NOT NULL,
                resp_rate   REAL    NOT NULL,
                temperature REAL    NOT NULL,
                signal_quality  REAL DEFAULT 1.0,
                movement_detected INTEGER DEFAULT 0,
                state       TEXT    NOT NULL,
                causes      TEXT    DEFAULT '[]',
                explanation TEXT
            );
            CREATE TABLE IF NOT EXISTS symptom_reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                reading_id  INTEGER,
                timestamp   TEXT    NOT NULL,
                astronaut_id TEXT   NOT NULL,
                symptoms_json TEXT  NOT NULL,
                notes       TEXT,
                FOREIGN KEY (reading_id) REFERENCES readings (id)
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT    UNIQUE NOT NULL,
                timestamp   TEXT    NOT NULL,
                astronaut_id TEXT   NOT NULL,
                environment TEXT    NOT NULL,
                max_state   TEXT    NOT NULL,
                causes_json TEXT    NOT NULL,
                actions_json TEXT   NOT NULL,
                report_md   TEXT    NOT NULL
            );
        """)


def save_reading(data: Dict[str, Any], state: str, causes: list,
                 explanation: str = "", db_path: Path = DB_PATH) -> int:
    init_db(db_path)
    ts = data.get("timestamp")
    if not ts:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(ts, datetime):
        ts = ts.strftime("%Y-%m-%d %H:%M:%S")

    causes_json = json.dumps(causes, ensure_ascii=False)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute("""
            INSERT INTO readings (
                timestamp, astronaut_id, astronaut_name, context, environment,
                spo2, heart_rate, systolic, diastolic, resp_rate, temperature,
                signal_quality, movement_detected, state, causes, explanation
            ) VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?,?, ?,?,?)
        """, (
            str(ts),
            str(data.get("astronaut_id", "AST-01")),
            str(data.get("astronaut_name", "Commander Rivera")),
            str(data.get("context", "rest")),
            str(data.get("environment", "iss")),
            float(data["spo2"]),
            float(data["heart_rate"]),
            float(data["systolic"]),
            float(data["diastolic"]),
            float(data["resp_rate"]),
            float(data["temperature"]),
            float(data.get("signal_quality", 1.0)),
            1 if data.get("movement_detected") else 0,
            str(state),
            causes_json,
            str(explanation),
        ))
        conn.commit()
        return cur.lastrowid


def get_latest_readings(astronaut_id: Optional[str] = None, limit: int = 50,
                        db_path: Path = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        q = "SELECT * FROM readings"
        params: list = []
        if astronaut_id:
            q += " WHERE astronaut_id = ?"
            params.append(astronaut_id)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql_query(q, conn, params=params)


def get_latest_per_astronaut(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Return the most recent reading for each astronaut_id."""
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        return pd.read_sql_query("""
            SELECT r.* FROM readings r
            INNER JOIN (
                SELECT astronaut_id, MAX(id) AS max_id
                FROM readings GROUP BY astronaut_id
            ) g ON r.id = g.max_id
        """, conn)


def save_symptom_report(reading_id: Optional[int], astronaut_id: str,
                        symptoms_json: str, notes: str = "",
                        db_path: Path = DB_PATH) -> int:
    init_db(db_path)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute("""
            INSERT INTO symptom_reports (reading_id, timestamp, astronaut_id, symptoms_json, notes)
            VALUES (?,?,?,?,?)
        """, (reading_id, ts, astronaut_id, symptoms_json, notes))
        conn.commit()
        return cur.lastrowid


def update_reading_evaluation(reading_id: int, state: str, causes: list,
                              explanation: str, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE readings SET state = ?, causes = ?, explanation = ? WHERE id = ?",
            (str(state), json.dumps(causes, ensure_ascii=False), str(explanation), reading_id),
        )
        conn.commit()
