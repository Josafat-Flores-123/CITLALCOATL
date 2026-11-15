# AstraMed — Astronaut Health Monitoring Interface

Academic prototype for NASA Space Apps Challenge 2026.

> **Disclaimer:** this is a demonstration tool for educational purposes.
> It is not a medical device, does not diagnose, and must not be used for
> clinical decisions. All thresholds and clinical texts are marked as
> *draft* and must be validated with NASA HRP sources and a physician.

## Requirements

- Python 3.11 or higher (versions in `requirements.txt` were tested on Python 3.12)
- No internet connection required (RNF-01)

## Install and run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Run the unit tests from the project root:

```bash
python -m unittest tests.test_rule_engine
```

Open `http://localhost:8501` if the browser does not start automatically.

## Project structure

```
app.py                 # Streamlit interface: capture, evaluation dialog, questionnaire, tabs
data_provider.py       # Fictitious data bridge (replaceable)
rule_engine.py         # validate_reading(), evaluate_reading()
storage.py             # SQLite persistence (data/astramed.db)
components.py          # Traffic light, Web Audio alarm (900/450 Hz), symptom helpers
config/
  thresholds.json      # Biological limits & environment-adjusted ranges
  actions.json         # Suggested actions by state and environment
  symptoms.json        # Symptom questionnaire catalogue
  conditions.json      # Possible causes to rule out
tests/
  test_rule_engine.py  # Unit tests (14 cases)
  __init__.py
.streamlit/
  config.toml          # Dark theme, minimal toolbar (hides Deploy)
data/
  astramed.db          # Auto-created SQLite database (gitignored)
.gitignore
```

## Data provider contract

The interface imports three functions from `data_provider.py`:

- `get_dashboard_data()` — returns a dict with DataFrames `crew`, `vitals`, `environment`, `team`.
- `get_alerts_data()` — returns a DataFrame of alert events.
- `get_history_data()` — returns a DataFrame with historical records.

### Columns

**crew:**
`id, name, role, spo2, heart_rate, systolic, diastolic, resp_rate, temperature, fatigue, stress, status`

**vitals:**
`timestamp, astronaut_id, astronaut_name, spo2, heart_rate, systolic, diastolic, resp_rate, temperature`

Optional vitals columns: `context, signal_quality`

**environment:**
`timestamp, co2, cabin_pressure, cabin_temp, humidity`

**alerts:**
`timestamp, astronaut, title, level, status, message, action`

### Status values

The `status` column in `crew` and the `level`/`status` columns in alerts use
the following English values:

| Column          | Values                                        |
|-----------------|-----------------------------------------------|
| `crew.status`   | `Normal`, `Caution`, `Critical`               |
| `alerts.level`  | `Info`, `Caution`, `Critical`                  |
| `alerts.status` | `Under review`, `Resolved`                    |

For backward compatibility, the interface also accepts the legacy Spanish
values (`Precaución`, `Resuelta`, etc.) and maps them to the correct pill
color and badge.

### Dates

All timestamps are formatted in ISO 8601: `2026-11-15 10:53:51`.

### Dashboard values

The KPI row and the crew list use the latest saved reading of each crew member
(SQLite). Crew members without saved readings keep the provider's fictitious
reading. Active alerts counts crew members whose latest state is Caution or Critical.

## What is demonstration and what is not

- **Demonstration:** all vital-sign values, crew names, alert messages,
  thresholds, clinical texts, and symptom catalogue. Every clinical config
  file includes a `"status": "draft"` disclaimer.
- **Functional:** the rule engine (`validate_reading`, `evaluate_reading`),
  biological-limit validation, environment-adaptive thresholds, SQLite
  persistence, traffic light, evaluation dialog, alarm, and symptom questionnaire.

## Audio alarm

Browsers block sound until the user interacts with the page. Press **Enable audio**
in the sidebar, then a Critical reading plays a 900 Hz / 450 Hz tone every 0.5 s
until **Acknowledge alert** is pressed. If audio is not enabled while a Critical
state is active, a red banner says so.

## Tools used

This section is for the team to honestly declare AI assistance:

- *[To be filled by each team member]*
