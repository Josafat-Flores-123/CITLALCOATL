import html
import json
from datetime import datetime
from typing import Dict
from pathlib import Path 

import pandas as pd
import plotly.express as px
import streamlit as st

from components import traffic_light, render_alarm, get_symptom_groups, get_severity_levels
from data_provider import get_dashboard_data, get_alerts_data, get_history_data
from rule_engine import (
    validate_reading, evaluate_reading, state_code,
    ENVIRONMENTS, STATE_LABELS, STATE_SYMBOLS, THRESHOLDS, EvaluationResult,
)
import storage

LOGO = Path(__file__).parent / "assets" / "logo.png"


# ── Minimal CSS (< 40 lines) ──────────────────────────────────────────────
st.markdown("""
<style>
.stApp{background:#0F1117;color:#E8EAF0;font-family:system-ui,"Segoe UI",Roboto,sans-serif;font-size:14px}
[data-testid="stSidebar"]{background:#181B24;border-right:1px solid #2A2F3D}
.block-container{padding-top:1.5rem;max-width:1440px}
div[data-testid="stMetric"]{background:#181B24;border:1px solid #2A2F3D;border-radius:6px;padding:16px}
div[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;color:#E8EAF0}
div[data-testid="stMetricDelta"]{display:none}
.stButton button,.stDownloadButton button{border-radius:6px;background:#181B24;color:#E8EAF0;border:1px solid #2A2F3D}
.pnl{background:#181B24;border:1px solid #2A2F3D;border-radius:6px;padding:16px}
.pill{display:inline-block;border-radius:6px;padding:4px 8px;font-size:12px;font-weight:600;font-variant-numeric:tabular-nums}
.p-g{background:#132a20;color:#3DDC84;border:1px solid #3DDC84}
.p-y{background:#2e2612;color:#FFC533;border:1px solid #FFC533}
.p-r{background:#331518;color:#FF5D5D;border:1px solid #FF5D5D}
.p-b{background:#142236;color:#6AA9FF;border:1px solid #6AA9FF}
.muted{color:#A3ABBB;font-size:13px}
.tab-num{font-variant-numeric:tabular-nums}
.alarm-banner{background:#FF5D5D20;border:1px solid #FF5D5D;border-radius:6px;padding:10px 16px;color:#FF5D5D;font-weight:600;margin-bottom:12px}
</style>
""", unsafe_allow_html=True)

storage.init_db()

# ── Helpers ────────────────────────────────────────────────────────────────

CREW_AGES = {"AST-01": 47, "AST-02": 36, "AST-03": 42, "AST-04": 38}
CREW_LABELS = ["AST-01 \u00b7 Commander Rivera", "AST-02 \u00b7 Pilot Chen",
               "AST-03 \u00b7 Dr. Morales", "AST-04 \u00b7 Eng. Okafor"]
VITAL_COLS = ["spo2", "heart_rate", "systolic", "diastolic", "resp_rate", "temperature"]
INDICATOR_LABELS = {
    "spo2": "SpO\u2082", "heart_rate": "Heart rate", "systolic": "Systolic BP",
    "diastolic": "Diastolic BP", "resp_rate": "Resp. rate", "temperature": "Temperature",
}
FORM_DEFAULTS = {"f_spo2": 98.0, "f_hr": 72.0, "f_sys": 118.0, "f_dia": 76.0,
                 "f_rr": 15.0, "f_temp": 36.6, "f_sq": 0.95, "f_mov": False}

ENV_IDS = list(ENVIRONMENTS.keys())
ENV_LABELS = list(ENVIRONMENTS.values())

for _k, _v in FORM_DEFAULTS.items():
    st.session_state.setdefault(_k, _v)
st.session_state.setdefault("audio_enabled", False)
st.session_state.setdefault("alarm_acknowledged", False)


def _pill_cls(status: str) -> str:
    return {"green": "p-g", "yellow": "p-y", "red": "p-r"}.get(state_code(status), "p-b")


def _chart(fig, height=300):
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#A3ABBB", family="system-ui,sans-serif"),
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h", y=1.08),
        xaxis=dict(gridcolor="#2A2F3D"), yaxis=dict(gridcolor="#2A2F3D"),
    )
    return fig


def reset_form():
    # Runs as a button callback: widget keys can only be written before the widgets render
    st.session_state.update(FORM_DEFAULTS)
    st.session_state["last_invalid"] = None


def acknowledge_alert():
    st.session_state["alarm_acknowledged"] = True


def save_symptoms():
    # Callback: reads the dialog widgets, stores the report and re-evaluates with the symptoms
    groups = get_symptom_groups()
    cleaned = {item["id"]: st.session_state.get(f"sym_{item['id']}", "None").lower()
               for g in groups.values() for item in g["items"]}
    notes = st.session_state.get("sym_notes", "")
    reading = st.session_state.get("last_reading") or {}
    reading_id = st.session_state.get("last_reading_id")
    ast_id = reading.get("astronaut_id") or st.session_state.get("f_ast", CREW_LABELS[0]).split(" \u00b7 ")[0]
    storage.save_symptom_report(reading_id, ast_id, json.dumps(cleaned, ensure_ascii=False), notes)

    prev = st.session_state.get("last_eval")
    if prev is not None and prev.is_valid and reading_id:
        new = evaluate_reading(reading, environment=reading.get("environment", "iss"),
                               symptoms=cleaned, age=CREW_AGES.get(ast_id, 40))
        storage.update_reading_evaluation(reading_id, new.state, new.possible_causes, new.alert_explanation)
        st.session_state["last_eval"] = new
        if new.state == "red" and prev.state != "red":
            st.session_state["alarm_acknowledged"] = False
        st.session_state["symptoms_saved_for"] = reading_id

    for g in groups.values():
        for item in g["items"]:
            st.session_state[f"sym_{item['id']}"] = "None"
    st.session_state["sym_notes"] = ""
    st.session_state["symptoms_saved"] = True
    st.session_state["toast"] = "Symptom report saved."


@st.dialog("Evaluation result", width="large")
def evaluation_dialog():
    ev: EvaluationResult = st.session_state.get("last_eval")
    if ev is None:
        st.info("No evaluation available.")
        return
    traffic_light(ev.state)

    st.markdown("**Readings that triggered this state**")
    flagged = {k: v for k, v in ev.indicator_states.items() if v["state"] != "green"}
    if flagged:
        for k, v in flagged.items():
            extra = f" ({v['hr_pct_max']}% of HR max)" if "hr_pct_max" in v else ""
            st.markdown(f"- {STATE_SYMBOLS[v['state']]} **{INDICATOR_LABELS.get(k, k)}** {v['value']:g}{extra}: {v['reason']}")
    else:
        st.markdown("All indicators are within their normal range.")
    st.caption(f"Rule: {ev.alert_explanation}")

    if ev.possible_causes:
        st.markdown("**Possible causes to rule out**")
        for c in ev.possible_causes:
            st.markdown(f"- **{c['label']}**: {c['why']}")
        st.caption("Decision support only. Clinical texts are drafts, not validated by NASA HRP or a physician.")

    st.markdown("**Suggested actions**")
    for a in ev.actions:
        st.markdown(f"- {a}")
    st.markdown(f"**Next measurement:** in {ev.next_measurement_minutes} minutes")

    b1, b2, b3 = st.columns(3)
    with b1:
        if ev.state == "red":
            if st.session_state["alarm_acknowledged"]:
                st.success("Alert acknowledged.")
            elif st.button("Acknowledge alert", type="primary", key="dlg_ack"):
                acknowledge_alert()
                st.session_state["show_eval_dialog"] = True
                st.rerun()
    with b2:
        if ev.state in ("yellow", "red") and st.button("Continue to symptom questionnaire", key="dlg_sym"):
            st.session_state["open_questionnaire"] = True
            st.rerun()
    with b3:
        if st.button("Close", key="dlg_close"):
            st.rerun()


@st.dialog("Symptom questionnaire", width="large")
def symptom_dialog():
    if st.session_state.pop("symptoms_saved", False):
        st.rerun()
    st.markdown('<div class="muted">Record symptoms for the flight surgeon. Stored locally and '
                'linked to the latest reading.</div>', unsafe_allow_html=True)
    levels = [lv.capitalize() for lv in get_severity_levels()]
    for group in get_symptom_groups().values():
        st.markdown(f"**{group['label']}**")
        for item in group["items"]:
            st.select_slider(item["label"], options=levels, key=f"sym_{item['id']}")
    st.text_area("Additional notes (optional)", key="sym_notes")
    st.button("Save symptom report", key="sym_save", type="primary", on_click=save_symptoms)


# ── Sidebar ────────────────────────────────────────────────────────────────

with st.sidebar:
    if LOGO.exists():
        st.image(str(LOGO), width=240)
    st.markdown("### StellarHealth")
    st.caption("Astronaut Health Monitoring System")
    st.divider()

    env_label = st.selectbox("Operating environment", ENV_LABELS,
                             index=ENV_IDS.index("iss"))
    env_id = ENV_IDS[ENV_LABELS.index(env_label)]

    if env_id == "habitat":
        st.info("Estimated comm delay: Moon ~1.3 s / Mars 4–22 min. Prioritize local autonomous procedures.")
    elif env_id == "eva":
        st.warning("Suit pressurized at 4.3 psi with 100% O\u2082. HR limits adjusted to % of HR max.")

    ast_filter = st.selectbox("Active crew member", ["All crew"] + CREW_LABELS)

    st.divider()

    # Browsers block audio until the user clicks, so audio is enabled explicitly
    if st.button("Enable audio" if not st.session_state.audio_enabled else "Disable audio"):
        st.session_state.audio_enabled = not st.session_state.audio_enabled
        st.rerun()

    audio_status = "Active" if st.session_state.audio_enabled else "Inactive"
    st.caption(f"Audio alerts: {audio_status}")

    st.divider()
    st.markdown('<span class="pill p-b">LOCAL OFFLINE MODE</span>', unsafe_allow_html=True)
    st.caption("Autonomous operation, no external network required.")

# ── Load data ──────────────────────────────────────────────────────────────

data = get_dashboard_data()
crew_base = data["crew"].copy()
vitals = data["vitals"].copy()
env_data = data["environment"].copy()
demo_alerts = get_alerts_data().copy()
history = get_history_data().copy()

# KPIs come from the latest saved reading per crew member; the provider's fictitious
# reading is kept only for crew members without saved readings.
latest_db = storage.get_latest_per_astronaut()
all_crew = crew_base.copy()
all_crew[VITAL_COLS] = all_crew[VITAL_COLS].astype(float)
all_crew["state"] = all_crew["status"].apply(state_code)
for _, dbr in latest_db.iterrows():
    mask = all_crew.id == dbr["astronaut_id"]
    if mask.any():
        for col in VITAL_COLS:
            all_crew.loc[mask, col] = float(dbr[col])
        all_crew.loc[mask, "state"] = dbr["state"]
all_crew["status"] = [STATE_LABELS.get(s, orig) for s, orig in zip(all_crew["state"], all_crew["status"])]

crew_kpi = all_crew
if ast_filter != "All crew":
    aid_filter = ast_filter.split(" \u00b7 ")[0]
    crew_kpi = all_crew[all_crew.id == aid_filter]
    vitals = vitals[vitals.astronaut_id == aid_filter]

active_alerts = int(crew_kpi["state"].isin(["yellow", "red"]).sum())

# Alert center: saved non-green readings plus demo alerts of crew without saved readings
saved_ids = set(latest_db["astronaut_id"]) if not latest_db.empty else set()
alert_rows = []
for _, r in latest_db.iterrows():
    if r["state"] in ("yellow", "red"):
        mins = THRESHOLDS["next_measurement_minutes"][r["state"]]
        alert_rows.append({
            "timestamp": r["timestamp"], "astronaut": f"{r['astronaut_id']} \u00b7 {r['astronaut_name']}",
            "title": "Reading outside normal range", "level": STATE_LABELS[r["state"]],
            "status": "Under review", "message": r["explanation"],
            "action": f"Repeat measurement in {mins} min",
        })
keep = ~demo_alerts["astronaut"].str.split(" \u00b7 ").str[0].isin(saved_ids)
alerts = pd.concat([pd.DataFrame(alert_rows, columns=demo_alerts.columns), demo_alerts[keep]],
                   ignore_index=True)

# ── Alarm state (red among the latest readings of any crew member) ─────────

red_rows = latest_db[latest_db["state"] == "red"] if not latest_db.empty else latest_db
has_red = not red_rows.empty
alarm_should_play = has_red and not st.session_state["alarm_acknowledged"]

if alarm_should_play:
    names = ", ".join(red_rows["astronaut_id"])
    st.markdown(f'<div class="alarm-banner">CRITICAL STATE: {names}. Alarm active until acknowledged.</div>',
                unsafe_allow_html=True)
    if not st.session_state["audio_enabled"]:
        st.markdown('<div class="alarm-banner">ALARM WITHOUT SOUND: enable audio in the sidebar.</div>',
                    unsafe_allow_html=True)
    st.button("Acknowledge alert", type="primary", key="ack_top", on_click=acknowledge_alert)

if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"))

# ── Top KPIs ───────────────────────────────────────────────────────────────

st.markdown("## Health Monitoring Dashboard")
st.markdown(f'<div class="muted">Environment: {env_label} \u00b7 Updated: {datetime.now():%Y-%m-%d %H:%M:%S}</div>', unsafe_allow_html=True)
st.write("")

k = st.columns(5)
k[0].metric("Crew monitored", f"{len(crew_kpi)}/4")
k[1].metric("Avg SpO\u2082", f"{crew_kpi.spo2.mean():.1f} %")
k[2].metric("Avg HR", f"{crew_kpi.heart_rate.mean():.0f} bpm")
k[3].metric("Avg temperature", f"{crew_kpi.temperature.mean():.1f} \u00b0C")
k[4].metric("Active alerts", str(active_alerts))

st.write("")

# ── Tabs ───────────────────────────────────────────────────────────────────

tab_capture, tab_overview, tab_crew, tab_env, tab_alerts, tab_history = st.tabs([
    "Capture & evaluation", "Mission overview", "Crew", "Cabin environment", "Alert center", "History",
])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: CAPTURE, EVALUATION, TRAFFIC LIGHT, ACTIONS DIALOG, SYMPTOMS
# ═══════════════════════════════════════════════════════════════════════════

with tab_capture:
    st.markdown('<div class="pnl"><b>Vital Signs Capture and Biological Validation</b>'
                '<div class="muted">RF-02 measurement form and RF-03 limit validation.</div></div>',
                unsafe_allow_html=True)
    st.write("")

    col_form, col_result = st.columns([1.2, 1])

    with col_form:
        with st.form("capture_form", clear_on_submit=False):
            st.markdown("**Crew member and context**")
            cf1, cf2 = st.columns(2)
            with cf1:
                sel_ast = st.selectbox("Astronaut", CREW_LABELS, key="f_ast")
            with cf2:
                sel_ctx = st.selectbox("Measurement context", ["rest", "exercise", "EVA"],
                                       index=2 if env_id == "eva" else 0)

            st.markdown("**Vital signs**")
            v1, v2, v3 = st.columns(3)
            with v1:
                val_spo2 = st.number_input("SpO\u2082 (%)", 0.0, 120.0, step=0.5, format="%.1f", key="f_spo2")
                val_hr = st.number_input("Heart rate (bpm)", 0.0, 300.0, step=1.0, format="%.0f", key="f_hr")
            with v2:
                val_sys = st.number_input("Systolic BP (mmHg)", 0.0, 300.0, step=1.0, format="%.0f", key="f_sys")
                val_dia = st.number_input("Diastolic BP (mmHg)", 0.0, 200.0, step=1.0, format="%.0f", key="f_dia")
            with v3:
                val_rr = st.number_input("Respiratory rate (bpm)", 0.0, 80.0, step=1.0, format="%.0f", key="f_rr")
                val_temp = st.number_input("Core temperature (\u00b0C)", 20.0, 45.0, step=0.1, format="%.1f", key="f_temp")

            st.markdown("**Measurement quality**")
            q1, q2 = st.columns(2)
            with q1:
                val_sq = st.slider("Signal quality (sensor)", 0.0, 1.0, step=0.05, key="f_sq")
            with q2:
                val_mov = st.checkbox("Movement or poor sensor contact detected", key="f_mov")

            btn = st.form_submit_button("Evaluate and save")

        if btn:
            aid, aname = sel_ast.split(" \u00b7 ")
            reading = {
                "astronaut_id": aid, "astronaut_name": aname,
                "context": sel_ctx, "environment": env_id,
                "spo2": val_spo2, "heart_rate": val_hr,
                "systolic": val_sys, "diastolic": val_dia,
                "resp_rate": val_rr, "temperature": val_temp,
                "signal_quality": val_sq, "movement_detected": val_mov,
            }
            ok, reason = validate_reading(reading)
            if not ok:
                st.session_state.update(last_invalid=reason, last_eval=None,
                                        last_reading=reading, last_reading_id=None)
            else:
                ev = evaluate_reading(reading, environment=env_id, age=CREW_AGES.get(aid, 40))
                rid = storage.save_reading(reading, ev.state, ev.possible_causes, ev.alert_explanation)
                st.session_state.update(last_eval=ev, last_invalid=None, last_reading=reading,
                                        last_reading_id=rid, show_eval_dialog=True)
                if ev.state == "red":
                    st.session_state["alarm_acknowledged"] = False
                # Rerun so the banner, KPIs and alarm are computed from the saved reading
                st.rerun()

        st.button("Open symptom questionnaire", key="open_sym_btn",
                  on_click=lambda: st.session_state.update(open_questionnaire=True))

    with col_result:
        if st.session_state.get("last_invalid"):
            st.error(f"Reading rejected: {st.session_state['last_invalid']}")
            st.markdown('<div class="muted">Readings outside biological limits or with technical '
                        'faults are rejected and not saved.</div>', unsafe_allow_html=True)
            st.button("Repeat measurement", on_click=reset_form)

        elif st.session_state.get("last_eval"):
            ev: EvaluationResult = st.session_state["last_eval"]
            traffic_light(ev.state)
            st.write("")
            st.markdown(
                f'<div class="pnl">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<b>Evaluation result</b>'
                f'<span class="pill {_pill_cls(ev.state)}">{ev.symbol} {ev.label}</span></div>'
                f'<div class="muted" style="margin-top:8px">{html.escape(ev.alert_explanation)}</div>'
                f'<div style="margin-top:8px"><b>Next measurement:</b> in {ev.next_measurement_minutes} minutes</div>'
                f'</div>', unsafe_allow_html=True)
            st.write("")

            st.markdown("**Indicator breakdown**")
            for k_i, v_i in ev.indicator_states.items():
                val_s = f"{v_i['value']:g}"
                if "hr_pct_max" in v_i:
                    val_s += f" ({v_i['hr_pct_max']}% HR max)"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                    f'border-bottom:1px solid #2A2F3D">'
                    f'<span class="tab-num">{INDICATOR_LABELS.get(k_i, k_i)}: {val_s}</span>'
                    f'<span class="pill {_pill_cls(v_i["state"])}">{STATE_SYMBOLS[v_i["state"]]} '
                    f'{STATE_LABELS[v_i["state"]]}</span></div>', unsafe_allow_html=True)
            st.write("")

            if st.button("Show causes and actions", key="reopen_eval"):
                evaluation_dialog()
            if ev.state in ("yellow", "red") and \
                    st.session_state.get("symptoms_saved_for") != st.session_state.get("last_reading_id"):
                st.warning("Symptom questionnaire pending for this reading.")
        else:
            st.info("Enter the crew member's data in the form and press 'Evaluate and save'.")

# Dialogs open from session flags so they appear after the rerun with fresh data.
# Streamlit allows one dialog at a time, so the questionnaire opens from the evaluation dialog.
if st.session_state.pop("open_questionnaire", False):
    symptom_dialog()
elif st.session_state.pop("show_eval_dialog", False):
    evaluation_dialog()

# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: MISSION OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

with tab_overview:
    left, right = st.columns([1.5, 1])
    with left:
        st.markdown('<div class="pnl"><b>Physiological telemetry time series</b>'
                    '<div class="muted">Crew SpO\u2082 trend</div>', unsafe_allow_html=True)
        if not vitals.empty:
            fig = px.line(vitals, x="timestamp", y="spo2", color="astronaut_name",
                          labels={"timestamp": "Time", "spo2": "SpO\u2082 (%)", "astronaut_name": "Astronaut"})
            fig.update_yaxes(range=[80, 100])
            st.plotly_chart(_chart(fig), width="stretch")
        else:
            st.info("No measurements for selected filter.")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="pnl"><b>Crew status</b>', unsafe_allow_html=True)
        for _, r in crew_kpi.iterrows():
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding:10px 0;'
                f'border-bottom:1px solid #2A2F3D">'
                f'<div><b>{r["name"]}</b><div class="muted">{r["role"]} \u00b7 {r["id"]}</div></div>'
                f'<div style="text-align:right">'
                f'<span class="pill {_pill_cls(r["status"])}">{r["status"]}</span>'
                f'<div class="muted tab-num">SpO\u2082 {r["spo2"]:.0f}% \u00b7 {r["heart_rate"]:.0f} bpm</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    c1, c2, c3 = st.columns(3)
    for col, title, y, lbl in [
        (c1, "SpO\u2082 by crew member", "spo2", "SpO\u2082 (%)"),
        (c2, "Heart rate by crew member", "heart_rate", "BPM"),
        (c3, "Fatigue level", "fatigue", "Scale 0\u201310"),
    ]:
        with col:
            st.markdown(f'<div class="pnl"><b>{title}</b>', unsafe_allow_html=True)
            fig = px.bar(crew_kpi, x="name", y=y, color="status",
                         labels={"name": "Astronaut", y: lbl})
            st.plotly_chart(_chart(fig, 240), width="stretch")
            st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: CREW
# ═══════════════════════════════════════════════════════════════════════════

with tab_crew:
    st.markdown('<div class="pnl"><b>Active crew and physiological parameters</b>', unsafe_allow_html=True)
    st.dataframe(
        crew_kpi[["id", "name", "role", "spo2", "heart_rate", "systolic", "diastolic",
                    "resp_rate", "temperature", "fatigue", "stress", "status"]],
        width="stretch", hide_index=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="pnl"><b>Vital sign trend</b>', unsafe_allow_html=True)
    metric = st.selectbox("Indicator", ["spo2", "heart_rate", "systolic", "diastolic", "resp_rate", "temperature"],
                          format_func=lambda x: {
                              "spo2": "SpO\u2082 (%)", "heart_rate": "Heart rate (bpm)",
                              "systolic": "Systolic BP (mmHg)", "diastolic": "Diastolic BP (mmHg)",
                              "resp_rate": "Respiratory rate (bpm)", "temperature": "Temperature (\u00b0C)",
                          }[x])
    fig = px.line(vitals, x="timestamp", y=metric, color="astronaut_name")
    st.plotly_chart(_chart(fig, 320), width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: CABIN ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════

with tab_env:
    st.markdown('<div class="pnl"><b>Life support and cabin telemetry</b>', unsafe_allow_html=True)
    if not env_data.empty:
        r_e = env_data.iloc[-1]
        ce = st.columns(4)
        ce[0].metric("CO\u2082", f"{r_e.co2:.0f} ppm")
        ce[1].metric("Pressure", f"{r_e.cabin_pressure:.1f} kPa")
        ce[2].metric("Temperature", f"{r_e.cabin_temp:.1f} \u00b0C")
        ce[3].metric("Humidity", f"{r_e.humidity:.0f} %")

        var_e = st.selectbox("Environmental variable", ["co2", "cabin_pressure", "cabin_temp", "humidity"],
                             format_func=lambda x: {"co2": "CO\u2082 (ppm)", "cabin_pressure": "Pressure (kPa)",
                                                    "cabin_temp": "Temperature (\u00b0C)", "humidity": "Humidity (%)"}[x])
        fig = px.line(env_data, x="timestamp", y=var_e)
        st.plotly_chart(_chart(fig, 300), width="stretch")
    else:
        st.info("No environmental telemetry available.")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: ALERT CENTER
# ═══════════════════════════════════════════════════════════════════════════

with tab_alerts:
    st.markdown('<div class="pnl"><b>Alert Center</b><div class="muted">Events generated by the rule engine</div></div>',
                unsafe_allow_html=True)
    st.write("")
    if alerts.empty:
        st.info("No active alerts on record.")
    else:
        for _, r in alerts.iterrows():
            st.markdown(
                f'<div style="padding:12px;margin:8px 0;border:1px solid #2A2F3D;border-radius:6px;background:#181B24">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<b>{r["title"]}</b><span class="pill {_pill_cls(r["level"])}">{r["level"]}</span></div>'
                f'<div class="muted">{r["timestamp"]} \u00b7 {r["astronaut"]} \u00b7 {r["status"]}</div>'
                f'<p style="margin:8px 0">{r["message"]}</p>'
                f'<div class="muted">Action: {r["action"]}</div></div>',
                unsafe_allow_html=True,
            )

# ═══════════════════════════════════════════════════════════════════════════
# TAB 6: HISTORY (SQLite readings with state & causes)
# ═══════════════════════════════════════════════════════════════════════════

with tab_history:
    st.markdown('<div class="pnl"><b>Saved Readings History (SQLite)</b>'
                '<div class="muted">Persistent records in data/astramed.db</div></div>',
                unsafe_allow_html=True)
    st.write("")

    df_local = storage.get_latest_readings(limit=200)
    if df_local.empty:
        st.info("No readings saved in local database yet.")
    else:
        display_cols = ["timestamp", "astronaut_id", "astronaut_name", "environment",
                        "spo2", "heart_rate", "systolic", "diastolic", "resp_rate",
                        "temperature", "state", "causes", "explanation"]
        available = [c for c in display_cols if c in df_local.columns]
        df_show = df_local[available].copy()

        df_show["causes"] = df_show["causes"].apply(
            lambda raw: "; ".join(c["label"] for c in json.loads(raw)) or "None")
        df_show["environment"] = df_show["environment"].map(ENVIRONMENTS).fillna(df_show["environment"])

        # State with symbol
        if "state" in df_show.columns:
            df_show["state"] = df_show["state"].apply(
                lambda s: f"{STATE_SYMBOLS.get(s, '')} {STATE_LABELS.get(s, s)}"
            )

        # Readable column names
        col_labels = {
            "timestamp": "Timestamp", "astronaut_id": "Astronaut ID",
            "astronaut_name": "Name", "environment": "Environment",
            "spo2": "SpO\u2082 (%)", "heart_rate": "HR (bpm)",
            "systolic": "Sys (mmHg)", "diastolic": "Dia (mmHg)",
            "resp_rate": "RR (bpm)", "temperature": "Temp (\u00b0C)",
            "state": "State", "causes": "Causes", "explanation": "Explanation",
        }
        df_show = df_show.rename(columns=col_labels)
        st.dataframe(df_show, width="stretch", hide_index=True)
        csv = df_local[available].to_csv(index=False).encode("utf-8")
        st.download_button("Download readings (CSV)", csv, "astramed_readings.csv", "text/csv")

    st.divider()
    st.markdown('<div class="pnl"><b>Provider telemetry history (data_provider)</b></div>', unsafe_allow_html=True)
    if not history.empty:
        st.dataframe(history, width="stretch", hide_index=True)
        st.download_button("Download provider history (CSV)",
                           history.to_csv(index=False).encode("utf-8"),
                           "provider_history.csv", "text/csv")

# ── Render alarm (must be after all state logic) ───────────────────────────

render_alarm(alarm_should_play, st.session_state.audio_enabled)

# ── Footer ─────────────────────────────────────────────────────────────────

st.divider()
st.markdown('<div class="muted" style="text-align:center;padding:12px">'
            'AstraMed \u00b7 Academic prototype \u00b7 NASA Space Apps Challenge '
            '\u00b7 Demonstration data \u00b7 Does not replace clinical judgment</div>',
            unsafe_allow_html=True)
