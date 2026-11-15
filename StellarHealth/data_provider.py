"""
DATA PROVIDER — bridge between interface and data source.
Values below are fictitious for dashboard preview.
The data team should replace these functions with their own API,
Redis, MQTT, CSV, or database, keeping the documented columns.
"""
from datetime import datetime, timedelta
import pandas as pd
import numpy as np


def get_dashboard_data():
    now = datetime.now()
    crew = pd.DataFrame([
        {"id": "AST-01", "name": "Commander Rivera", "role": "Commander",
         "spo2": 98.0, "heart_rate": 72, "systolic": 118, "diastolic": 76,
         "resp_rate": 15, "temperature": 36.7, "fatigue": 2.0, "stress": 2.5,
         "status": "Normal"},
        {"id": "AST-02", "name": "Pilot Chen", "role": "Pilot",
         "spo2": 96.0, "heart_rate": 81, "systolic": 122, "diastolic": 79,
         "resp_rate": 16, "temperature": 36.8, "fatigue": 3.5, "stress": 3.0,
         "status": "Normal"},
        {"id": "AST-03", "name": "Dr. Morales", "role": "Medical specialist",
         "spo2": 93.0, "heart_rate": 94, "systolic": 128, "diastolic": 84,
         "resp_rate": 19, "temperature": 37.0, "fatigue": 5.5, "stress": 5.0,
         "status": "Caution"},
        {"id": "AST-04", "name": "Eng. Okafor", "role": "Engineering",
         "spo2": 97.0, "heart_rate": 76, "systolic": 120, "diastolic": 78,
         "resp_rate": 15, "temperature": 36.6, "fatigue": 2.8, "stress": 2.0,
         "status": "Normal"},
    ])

    rows = []
    for m in range(59, -1, -1):
        ts = now - timedelta(minutes=m)
        for i, p in crew.iterrows():
            d = np.sin((59 - m) / 8 + i) * 0.6
            rows.append({
                "timestamp": ts,
                "astronaut_id": p.id, "astronaut_name": p["name"],
                "spo2": p.spo2 + d,
                "heart_rate": p.heart_rate + d * 3,
                "systolic": p.systolic + d * 1.5,
                "diastolic": p.diastolic + d,
                "resp_rate": p.resp_rate + d * 0.5,
                "temperature": p.temperature + d * 0.04,
                "context": "rest", "signal_quality": 0.98,
            })
    vitals = pd.DataFrame(rows)

    env = []
    for m in range(59, -1, -1):
        t = 59 - m
        env.append({
            "timestamp": now - timedelta(minutes=m),
            "co2": 850 + np.sin(t / 9) * 25,
            "cabin_pressure": 101.3 + np.sin(t / 13) * 0.15,
            "cabin_temp": 22 + np.sin(t / 10) * 0.4,
            "humidity": 42 + np.sin(t / 8) * 2,
        })

    return {
        "crew": crew,
        "vitals": vitals,
        "environment": pd.DataFrame(env),
        "team": pd.DataFrame([
            {"metric": "Coordination", "value": 92},
            {"metric": "Workload", "value": 64},
        ]),
    }


def get_alerts_data():
    now = datetime.now()
    return pd.DataFrame([
        {"timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
         "astronaut": "AST-03 \u00b7 Dr. Morales",
         "title": "SpO\u2082 below demo target",
         "level": "Caution", "status": "Under review",
         "message": "Simulated reading: verify signal and context before interpreting.",
         "action": "Confirm sensor quality and review trend."},
        {"timestamp": (now - timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S"),
         "astronaut": "Cabin",
         "title": "Environmental variation recorded",
         "level": "Info", "status": "Resolved",
         "message": "Minor simulated cabin temperature variation.",
         "action": "Continue observation and retain record."},
    ])


def get_history_data():
    return get_dashboard_data()["vitals"].tail(40).copy()
