from dataclasses import dataclass, field
from typing import Dict, Any, Tuple, List, Optional
from pathlib import Path
import json

CONFIG_DIR = Path(__file__).parent / "config"

# Environment id -> display label mapping
ENVIRONMENTS = {
    "earth":    "Earth, 1 atm",
    "iss":      "ISS cabin",
    "eva":      "EVA suit",
    "habitat":  "Lunar/Martian habitat",
    "altitude": "High altitude",
}

# State code -> display label mapping
STATE_LABELS = {
    "green":  "Normal",
    "yellow": "Caution",
    "red":    "Critical",
}

STATE_SYMBOLS = {"green": "\u25cf", "yellow": "\u25b2", "red": "\u25a0"}  # ● ▲ ■

# English labels first; Spanish values are accepted for backward compatibility
STATE_ALIASES = {
    "green": "green", "normal": "green", "stable": "green", "estable": "green", "verde": "green",
    "yellow": "yellow", "caution": "yellow", "precauci\u00f3n": "yellow", "precaucion": "yellow",
    "atenci\u00f3n": "yellow", "atencion": "yellow", "amarillo": "yellow",
    "red": "red", "critical": "red", "cr\u00edtico": "red", "critico": "red", "rojo": "red",
}


def state_code(label: str) -> str:
    """Map any known state label (English or legacy Spanish) to green/yellow/red; '' if unknown."""
    return STATE_ALIASES.get(str(label).strip().lower(), "")


def _load_json(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return json.load(f)

THRESHOLDS = _load_json("thresholds.json")
ACTIONS = _load_json("actions.json")
CONDITIONS = _load_json("conditions.json")


@dataclass
class EvaluationResult:
    state: str                                  # "green", "yellow", "red"
    indicator_states: Dict[str, Dict[str, Any]]
    possible_causes: List[Dict[str, str]]
    actions: List[str]
    next_measurement_minutes: int
    alert_explanation: str
    is_valid: bool = True
    invalid_reason: str = ""

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    @property
    def symbol(self) -> str:
        return STATE_SYMBOLS.get(self.state, "")


def validate_reading(reading: Dict[str, Any]) -> Tuple[bool, str]:
    limits = THRESHOLDS.get("biological_limits", {})

    if reading.get("movement_detected"):
        return False, "Excessive movement or poor sensor contact detected during measurement."

    try:
        sq = float(reading.get("signal_quality", 1.0))
    except (ValueError, TypeError):
        return False, "Non-numeric signal quality value."
    if sq < limits.get("signal_quality_min", 0.6):
        return False, f"Insufficient signal quality ({sq:.2f} < 0.60)."

    fields = [
        ("spo2",        "SpO\u2082",              limits.get("spo2",        {"min": 50,   "max": 100})),
        ("heart_rate",  "Heart rate",             limits.get("heart_rate",  {"min": 20,   "max": 250})),
        ("systolic",    "Systolic BP",            limits.get("systolic",    {"min": 60,   "max": 260})),
        ("diastolic",   "Diastolic BP",           limits.get("diastolic",   {"min": 30,   "max": 150})),
        ("resp_rate",   "Respiratory rate",       limits.get("resp_rate",   {"min": 4,    "max": 60})),
        ("temperature", "Core body temperature",  limits.get("temperature", {"min": 33.0, "max": 42.0})),
    ]

    for key, label, lim in fields:
        val = reading.get(key)
        if val is None:
            return False, f"Missing indicator: {label}."
        try:
            v = float(val)
        except (ValueError, TypeError):
            return False, f"Non-numeric value for {label}."
        if v < lim["min"] or v > lim["max"]:
            return False, f"{label} ({v}) outside biological limits ({lim['min']}–{lim['max']})."

    if float(reading["diastolic"]) >= float(reading["systolic"]):
        return False, (
            f"Diastolic BP ({float(reading['diastolic']):.0f} mmHg) "
            f"cannot be equal to or greater than systolic BP ({float(reading['systolic']):.0f} mmHg)."
        )

    return True, ""


def _evaluate_base(value: float, cfg: dict) -> Tuple[str, str]:
    lo, hi = cfg["green"]
    if lo <= value <= hi:
        return "green", f"Within normal range ({lo}\u2013{hi})"

    if "yellow" in cfg:
        a, b = cfg["yellow"]
        if a <= value <= b:
            return "yellow", f"Caution range ({a}\u2013{b})"

    if "yellow_low" in cfg:
        a, b = cfg["yellow_low"]
        if a <= value <= b:
            return "yellow", f"Below normal ({a}\u2013{b})"

    if "yellow_high" in cfg:
        a, b = cfg["yellow_high"]
        if a <= value <= b:
            return "yellow", f"Above normal ({a}\u2013{b})"

    return "red", "Outside safe limits (critical range)"


def evaluate_reading(
    reading: Dict[str, Any],
    environment: str = "iss",
    symptoms: Optional[Dict[str, Any]] = None,
    age: int = 40,
    mission_day: int = 14,
) -> EvaluationResult:

    valid, reason = validate_reading(reading)
    if not valid:
        return EvaluationResult(
            state="invalid",
            indicator_states={},
            possible_causes=[],
            actions=["Repeat measurement after verifying rest and sensor placement."],
            next_measurement_minutes=0,
            alert_explanation=f"Reading rejected: {reason}",
            is_valid=False,
            invalid_reason=reason,
        )

    base = THRESHOLDS["base_thresholds"]
    ind: Dict[str, Dict[str, Any]] = {}
    reasons: List[str] = []

    # --- SpO2 ---
    spo2 = float(reading["spo2"])
    if environment == "altitude":
        cfg_a = THRESHOLDS["environment_adjustments"]["altitude"]["spo2"]
        if spo2 >= cfg_a["green"][0]:
            st_spo2, mot = "green", f"Normal for high altitude (\u2265 {cfg_a['green'][0]}%)"
        elif spo2 >= cfg_a["yellow"][0]:
            st_spo2, mot = "yellow", f"Caution for high altitude ({cfg_a['yellow'][0]}\u2013{cfg_a['yellow'][1]}%)"
        else:
            st_spo2, mot = "red", f"Critical for high altitude (< {cfg_a['red_low']}%)"
    else:
        st_spo2, mot = _evaluate_base(spo2, base["spo2"])
    ind["spo2"] = {"value": spo2, "state": st_spo2, "reason": mot}
    if st_spo2 != "green":
        reasons.append(f"SpO\u2082 {spo2:.1f}% ({mot})")

    # --- Heart rate ---
    hr = float(reading["heart_rate"])
    if environment == "eva":
        hr_max = 208.0 - 0.7 * float(age)
        hr_pct = (hr / hr_max) * 100.0 if hr_max > 0 else 100.0
        ecfg = THRESHOLDS["environment_adjustments"]["eva"]["fc_max_pct"]
        if hr_pct <= ecfg["green_max"]:
            st_hr, mot = "green", f"Safe cardiovascular load ({hr_pct:.1f}% of HR max)"
        elif hr_pct <= ecfg["yellow_max"]:
            st_hr, mot = "yellow", f"Moderate EVA strain ({hr_pct:.1f}% of HR max)"
        else:
            st_hr, mot = "red", f"Critical EVA strain ({hr_pct:.1f}% of HR max)"
        ind["heart_rate"] = {"value": hr, "hr_pct_max": round(hr_pct, 1), "state": st_hr, "reason": mot}
    else:
        st_hr, mot = _evaluate_base(hr, base["heart_rate"])
        ind["heart_rate"] = {"value": hr, "state": st_hr, "reason": mot}
    if st_hr != "green":
        reasons.append(f"HR {hr:.0f} bpm ({mot})")

    # --- Systolic BP ---
    sys_p = float(reading["systolic"])
    if environment == "eva":
        ecfg = THRESHOLDS["environment_adjustments"]["eva"]["systolic"]
        if ecfg["green"][0] <= sys_p <= ecfg["green"][1]:
            st_sys, mot = "green", f"Acceptable for EVA exertion (\u2264 {ecfg['green'][1]} mmHg)"
        elif sys_p <= ecfg["yellow"][1]:
            st_sys, mot = "yellow", f"Elevated for EVA ({ecfg['yellow'][0]}\u2013{ecfg['yellow'][1]} mmHg)"
        else:
            st_sys, mot = "red", f"Critical for EVA (> {ecfg['red_high']} mmHg)"
    else:
        st_sys, mot = _evaluate_base(sys_p, base["systolic"])
    ind["systolic"] = {"value": sys_p, "state": st_sys, "reason": mot}
    if st_sys != "green":
        reasons.append(f"Systolic {sys_p:.0f} mmHg ({mot})")

    # --- Diastolic BP ---
    dia_p = float(reading["diastolic"])
    st_dia, mot = _evaluate_base(dia_p, base["diastolic"])
    ind["diastolic"] = {"value": dia_p, "state": st_dia, "reason": mot}
    if st_dia != "green":
        reasons.append(f"Diastolic {dia_p:.0f} mmHg ({mot})")

    # --- Respiratory rate ---
    rr = float(reading["resp_rate"])
    if environment == "eva":
        ecfg = THRESHOLDS["environment_adjustments"]["eva"]["resp_rate"]
        if ecfg["green"][0] <= rr <= ecfg["green"][1]:
            st_rr, mot = "green", f"Acceptable for EVA (\u2264 {ecfg['green'][1]} bpm)"
        elif rr <= ecfg["yellow"][1]:
            st_rr, mot = "yellow", f"Moderate tachypnea in EVA ({ecfg['yellow'][0]}\u2013{ecfg['yellow'][1]} bpm)"
        else:
            st_rr, mot = "red", f"Critical tachypnea in EVA (> {ecfg['red_high']} bpm)"
    else:
        st_rr, mot = _evaluate_base(rr, base["resp_rate"])
    ind["resp_rate"] = {"value": rr, "state": st_rr, "reason": mot}
    if st_rr != "green":
        reasons.append(f"RR {rr:.0f} bpm ({mot})")

    # --- Temperature ---
    temp = float(reading["temperature"])
    st_temp, mot = _evaluate_base(temp, base["temperature"])
    ind["temperature"] = {"value": temp, "state": st_temp, "reason": mot}
    if st_temp != "green":
        reasons.append(f"Temperature {temp:.1f} \u00b0C ({mot})")

    # --- Worst state ---
    all_states = [st_spo2, st_hr, st_sys, st_dia, st_rr, st_temp]
    if "red" in all_states:
        state = "red"
    elif "yellow" in all_states:
        state = "yellow"
    else:
        state = "green"

    # --- Symptom escalation (severe symptom escalates one level) ---
    severe_symptoms: List[str] = []
    if symptoms and isinstance(symptoms, dict):
        for sid, sval in symptoms.items():
            if str(sval).strip().lower() == "severe":
                severe_symptoms.append(sid)
    if severe_symptoms:
        if state == "green":
            state = "yellow"
            reasons.append(f"Escalated to Caution due to severe symptom ({', '.join(severe_symptoms)})")
        elif state == "yellow":
            state = "red"
            reasons.append(f"Escalated to Critical due to severe symptom ({', '.join(severe_symptoms)})")

    # --- Possible causes to rule out (decision support, not diagnosis) ---
    causes: List[Dict[str, str]] = []

    spo2_threshold = 90.0 if environment == "altitude" else 95.0
    has_dyspnea = False
    if symptoms and isinstance(symptoms, dict):
        has_dyspnea = any(symptoms.get(k) in ("moderate", "severe") for k in ("dyspnea_rest", "suffocation"))
    if spo2 < spo2_threshold or has_dyspnea:
        why = f"SpO\u2082 reading of {spo2:.1f}% below normal threshold of {spo2_threshold}%"
        if has_dyspnea:
            why += " with reported dyspnea/suffocation."
        else:
            why += "."
        causes.append({"id": "hypoxia", "label": "Hypoxia or asphyxia risk from depressurization / O\u2082 supply failure", "why": why})

    if environment == "eva":
        hr_max_v = 208.0 - 0.7 * float(age)
        pct = (hr / hr_max_v) * 100.0 if hr_max_v > 0 else 0
        if pct > 80.0 or rr > 30:
            causes.append({"id": "eva_strain", "label": "Cardiovascular strain and metabolic fatigue during EVA", "why": f"In EVA suit HR reached {hr:.0f} bpm ({pct:.1f}% of HR max) or RR exceeded 30 bpm."})

    has_headache = False
    if symptoms and isinstance(symptoms, dict):
        has_headache = symptoms.get("frontal_headache") in ("mild", "moderate", "severe")
    if mission_day <= 3 and has_headache and environment in ("iss", "earth"):
        causes.append({"id": "fluid_shift", "label": "Cephalad fluid shift (Space adaptation syndrome)", "why": f"Mission day {mission_day} in microgravity with reported cephalad congestion (note: validate with HRP sources)."})

    has_presyncope = False
    if symptoms and isinstance(symptoms, dict):
        has_presyncope = symptoms.get("presyncope") in ("moderate", "severe")
    if sys_p < 95 or dia_p < 60 or has_presyncope:
        causes.append({"id": "orthostatic_intolerance", "label": "Orthostatic intolerance from spaceflight hypovolemia", "why": f"Blood pressure {sys_p:.0f}/{dia_p:.0f} mmHg below euvolemic range."})

    if temp > 37.5:
        causes.append({"id": "hyperthermia_fever", "label": "Hyperthermia or active infectious process", "why": f"Core temperature {temp:.1f} \u00b0C above 37.5 \u00b0C."})

    if sys_p >= 136 or dia_p >= 89:
        causes.append({"id": "reactive_hypertension", "label": "Reactive blood pressure elevation or hemodynamic overload", "why": f"Blood pressure {sys_p:.0f}/{dia_p:.0f} mmHg above expected baseline."})

    # --- Actions ---
    actions: List[str] = []
    env_actions = ACTIONS.get("environment_actions", {})
    if environment in env_actions and state in env_actions[environment]:
        actions.extend(env_actions[environment][state])
    else:
        actions.extend(ACTIONS.get("base_actions", {}).get(state, []))

    cause_actions = ACTIONS.get("cause_actions", {})
    for c in causes:
        ckey = c["id"]
        if ckey in cause_actions:
            for a in cause_actions[ckey]:
                if a not in actions:
                    actions.append(a)

    # --- Next measurement ---
    nm = THRESHOLDS.get("next_measurement_minutes", {"green": 180, "yellow": 20, "red": 5})
    next_min = nm.get(state, 60)

    explanation = "; ".join(reasons) if reasons else "All vital signs within standard physiological ranges."

    return EvaluationResult(
        state=state,
        indicator_states=ind,
        possible_causes=causes,
        actions=actions,
        next_measurement_minutes=next_min,
        alert_explanation=explanation,
    )
