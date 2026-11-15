"""
UI components: traffic light, Web Audio API alarm, symptom questionnaire.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

import streamlit as st
import streamlit.components.v1 as stc

CONFIG_DIR = Path(__file__).parent / "config"
SYMPTOMS_CFG = json.loads((CONFIG_DIR / "symptoms.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Traffic light  (● ▲ ■)
# ---------------------------------------------------------------------------

_LIGHT_CSS = """
<div style="display:flex;gap:12px;align-items:center;padding:12px 16px;
            background:#181B24;border:1px solid #2A2F3D;border-radius:6px">
  <div style="width:32px;height:32px;border-radius:50%;
              background:{bg_g};border:2px solid #3DDC84;
              display:flex;align-items:center;justify-content:center;
              font-size:18px;color:{fg_g}">{sym_g}</div>
  <div style="width:32px;height:32px;border-radius:6px;
              background:{bg_y};border:2px solid #FFC533;
              display:flex;align-items:center;justify-content:center;
              font-size:16px;color:{fg_y}">{sym_y}</div>
  <div style="width:32px;height:32px;border-radius:4px;
              background:{bg_r};border:2px solid #FF5D5D;
              display:flex;align-items:center;justify-content:center;
              font-size:16px;color:{fg_r}">{sym_r}</div>
  <span style="margin-left:8px;font-size:14px;font-weight:600;color:{lbl_color}">
    {sym_active} {label}
  </span>
</div>
"""


def traffic_light(state: str) -> None:
    """Render a 3-bulb traffic light with the active state lit."""
    s = state.lower()
    bg_g = "#3DDC84" if s == "green"  else "#1a2a20"
    bg_y = "#FFC533" if s == "yellow" else "#2a2512"
    bg_r = "#FF5D5D" if s == "red"    else "#331518"
    fg_g = "#0F1117" if s == "green"  else "#3DDC8440"
    fg_y = "#0F1117" if s == "yellow" else "#FFC53340"
    fg_r = "#0F1117" if s == "red"    else "#FF5D5D40"

    labels = {"green": "Normal", "yellow": "Caution", "red": "Critical"}
    symbols = {"green": "\u25cf", "yellow": "\u25b2", "red": "\u25a0"}
    colors  = {"green": "#3DDC84", "yellow": "#FFC533", "red": "#FF5D5D"}

    html = _LIGHT_CSS.format(
        bg_g=bg_g, fg_g=fg_g, sym_g="\u25cf",
        bg_y=bg_y, fg_y=fg_y, sym_y="\u25b2",
        bg_r=bg_r, fg_r=fg_r, sym_r="\u25a0",
        sym_active=symbols.get(s, ""),
        label=labels.get(s, state),
        lbl_color=colors.get(s, "#E8EAF0"),
    )
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Web Audio API alarm (900 Hz / 450 Hz alternating every 0.5 s)
# ---------------------------------------------------------------------------
# st.components.v1.html recreates its iframe on reruns, so the AudioContext and the
# timer live on the parent window (window.parent). A flag there prevents a second
# oscillator and keeps the tone from restarting when Streamlit reruns.

_ALARM_START_HTML = """
<script>
(function() {
  var p = window.parent;
  if (p._astramed_alarm) return;
  var AC = p.AudioContext || p.webkitAudioContext;
  if (!AC) return;
  var ctx = new AC();
  var gain = ctx.createGain();
  gain.gain.value = 0.25;
  gain.connect(ctx.destination);
  var osc = ctx.createOscillator();
  osc.type = 'square';
  osc.frequency.value = 900;
  osc.connect(gain);
  osc.start();
  var high = true;
  var iv = p.setInterval(function() {
    high = !high;
    osc.frequency.value = high ? 900 : 450;
    if (ctx.state === 'suspended') ctx.resume();
  }, 500);
  if (ctx.state === 'suspended') ctx.resume();
  p._astramed_alarm = {
    stop: function() {
      p.clearInterval(iv);
      try { osc.stop(); } catch (e) {}
      try { ctx.close(); } catch (e) {}
      p._astramed_alarm = null;
    }
  };
})();
</script>
"""

_ALARM_STOP_HTML = """
<script>
(function() {
  var p = window.parent;
  if (p._astramed_alarm) p._astramed_alarm.stop();
})();
</script>
"""


def _embed_script(code: str) -> None:
    # st.components.v1.html is deprecated in recent Streamlit; st.iframe replaces it
    if hasattr(st, "iframe"):
        st.iframe(code, height=1)
    else:
        stc.html(code, height=0)


def render_alarm(should_play: bool, audio_enabled: bool) -> None:
    """Render (or stop) the continuous alarm via Web Audio API.

    - should_play: True when state is red AND alarm not yet acknowledged.
    - audio_enabled: True when user clicked 'Enable audio'.
    """
    if should_play and audio_enabled:
        _embed_script(_ALARM_START_HTML)
    else:
        _embed_script(_ALARM_STOP_HTML)


# ---------------------------------------------------------------------------
# Symptom questionnaire helpers
# ---------------------------------------------------------------------------

def get_symptom_groups() -> dict:
    """Return the symptom catalogue from config/symptoms.json."""
    return SYMPTOMS_CFG["groups"]


def get_severity_levels() -> list:
    return SYMPTOMS_CFG.get("severity_levels", ["none", "mild", "moderate", "severe"])
