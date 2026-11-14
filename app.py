"""
Unknown History - Streamlit control room.
Modern AI studio UI with light/dark themes and a fixed bottom action bar.
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import video_engine as ve

BASE_DIR = Path(__file__).parent
CSS_FILE = BASE_DIR / "style.css"

st.set_page_config(
    page_title="Unknown History Studio",
    page_icon="🏺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Theme handling (?theme=dark|light)
# --------------------------------------------------------------------------- #
DEFAULT_THEME = "dark"
theme = st.query_params.get("theme", DEFAULT_THEME)
if theme not in ("dark", "light"):
    theme = DEFAULT_THEME

# --------------------------------------------------------------------------- #
# Inject CSS + theme attribute
# --------------------------------------------------------------------------- #
css = CSS_FILE.read_text(encoding="utf-8") if CSS_FILE.exists() else ""
st.markdown(
    f"""
    <style>{css}</style>
    <script>
      document.documentElement.setAttribute('data-theme', '{theme}');
    </script>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Hero
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <div class="hero">
      <span class="hero-eyebrow">🏺 Unknown History · Autonomous Studio</span>
      <div class="hero-title">One click. A forgotten story, rendered.</div>
      <p class="hero-sub">
        An autonomous pipeline researches a forgotten story, writes the script,
        narrates it, sources real cinematic footage, and renders a documentary —
        without a human in the loop.
      </p>
      <div class="agents">
        <span class="agent-chip">🧠 Ideation Agent</span>
        <span class="agent-chip">✍️ Scriptwriter AI</span>
        <span class="agent-chip">🎙️ Voice AI</span>
        <span class="agent-chip">🎬 Video Production AI</span>
        <span class="agent-chip">🖼️ Thumbnail AI</span>
        <span class="agent-chip">📈 Analytics &amp; Growth Agent</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Sidebar — production settings + theme toggle
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### 🎛️ Production settings")
    st.markdown('<p class="muted">Configure the next documentary run.</p>', unsafe_allow_html=True)

    duration_label = st.selectbox(
        "Documentary length",
        options=list(ve.DURATION_PRESETS.keys()),
        format_func=lambda k: ve.DURATION_PRESETS[k]["label"],
        index=0,
        label_visibility="collapsed",
    )
    preset = ve.DURATION_PRESETS[duration_label]
    st.caption(
        {
            "standard": "Deeper research, focused storytelling and supporting footage.",
            "extended": "More chapters, richer storytelling and extensive supporting footage.",
            "longform": "Multiple chapters, detailed narration and substantial visual production.",
        }[duration_label]
    )
    if duration_label == "longform":
        st.markdown(
            '<div class="warn">⚠️ 40-minute videos require much more research, '
            "production time and quality control.</div>",
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="gold-line">', unsafe_allow_html=True)
    st.markdown("### 🎨 Appearance")
    new_theme = st.radio(
        "Theme",
        options=["dark", "light"],
        index=0 if theme == "dark" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    if new_theme != theme:
        st.query_params["theme"] = new_theme
        st.rerun()

    st.markdown('<hr class="gold-line">', unsafe_allow_html=True)
    st.markdown("### 🗂️ Memory")
    if st.button("Show topic history", use_container_width=True):
        used = ve.read_database()
        if used:
            for t in reversed(used[-30:]):
                st.write("•", t)
        else:
            st.write("No topics yet.")
    st.caption(f"Database: `{ve.DB_FILE.name}` — topics never repeat.")

# --------------------------------------------------------------------------- #
# Main layout: stats + console
# --------------------------------------------------------------------------- #
col_run, col_stats = st.columns([2, 1.1], gap="large")

with col_stats:
    st.markdown(
        f"""
        <div class="card">
          <div class="card-title">Run configuration</div>
          <div class="stat-row">
            <div class="stat">
              <div class="stat-label">Runtime</div>
              <div class="stat-value">{preset['minutes']} min</div>
            </div>
            <div class="stat">
              <div class="stat-label">Scenes</div>
              <div class="stat-value">{preset['scenes']}</div>
            </div>
          </div>
          <div style="margin-top:.8rem;">
            <span class="status"><span class="dot"></span> Pipeline ready</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_run:
    st.markdown(
        """
        <div class="card">
          <div class="card-title">Studio console</div>
          <p class="muted" style="margin:0;">
            Use the action bar at the bottom of the screen to start a render.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------- #
# Bottom action bar (visual shell) + real Streamlit button below it
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <div class="bottom-bar">
      <div class="bottom-bar-inner">
        <div class="bottom-bar-left">
          <span class="status"><span class="dot"></span> Studio ready</span>
          <span><strong>{preset['minutes']} min</strong> · {preset['scenes']} scenes</span>
        </div>
        <div class="bottom-bar-actions" id="bottom-actions"></div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# The actual Streamlit button lives in a fixed-position wrapper we inject.
# Streamlit cannot render a button inside raw HTML, so we place it in a
# container that the CSS pins to the bottom bar's action area.
st.markdown('<div id="action-slot"></div>', unsafe_allow_html=True)

with st.container():
    st.markdown(
        """
        <style>
          /* Pin the first button container inside the main area to the bottom bar */
          div[data-testid="stVerticalBlock"] > div:has(> div > .stButton) { }
        </style>
        """,
        unsafe_allow_html=True,
    )
    generate = st.button("▶ GENERATE DOCUMENTARY", use_container_width=True)

# --------------------------------------------------------------------------- #
# Pipeline execution
# --------------------------------------------------------------------------- #
if generate:
    if not os.getenv("GROQ_API_KEY") or not os.getenv("PIXABAY_API_KEY"):
        st.error(
            "Missing API keys. Add GROQ_API_KEY and PIXABAY_API_KEY to your "
            "Streamlit secrets, then restart the app."
        )
        st.stop()

    st.markdown('<hr class="gold-line">', unsafe_allow_html=True)

    status_ph = st.empty()
    status_ph.markdown(
        '<span class="status"><span class="dot live"></span> Studio is working…</span>',
        unsafe_allow_html=True,
    )

    bar = st.progress(0)
    log_box = st.empty()
    logs = []

    def progress_cb(msg):
        logs.append(msg)
        log_box.code("\n".join(logs[-14:]), language=None)

    def fraction_cb(frac):
        bar.progress(min(1.0, max(0.0, frac)))

    try:
        with st.spinner("Rendering your documentary…"):
            out_path, topic_info = ve.run_pipeline(
                duration_label, progress_cb=progress_cb, fraction_cb=fraction_cb
            )

        status_ph.markdown(
            '<span class="status"><span class="dot"></span> Render complete</span>',
            unsafe_allow_html=True,
        )
        st.success(f"🎬 '{topic_info['topic']}' is ready.")
        st.balloons()

        with open(out_path, "rb") as fh:
            st.download_button(
                "⬇ Download MP4",
                data=fh.read(),
                file_name=out_path.name,
                mime="video/mp4",
                use_container_width=True,
            )

        st.markdown(
            '<div class="warn">After uploading to YouTube, tick the '
            "<b>'Altered Content'</b> label (AI-generated disclosure).</div>",
            unsafe_allow_html=True,
        )

    except Exception as e:
        status_ph.markdown(
            '<span class="status" style="border-color:rgba(255,80,80,.35);color:#ff9d9d;">'
            '<span class="dot" style="background:#ff5a5a;box-shadow:0 0 8px #ff5a5a;"></span>'
            " Pipeline failed</span>",
            unsafe_allow_html=True,
        )
        st.error(f"Pipeline failed: {e}")
        with st.expander("Full log"):
            st.code("\n".join(logs))

else:
    st.markdown(
        """
        <div class="card" style="margin-top:1rem;">
          <div class="card-title">Idle</div>
          <p style="margin:0;color:var(--text-muted);">
            Press <b style="color:var(--gold-soft);">GENERATE DOCUMENTARY</b> to let the studio work.
            Every run picks a topic never told before.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )