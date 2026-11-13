"""
Unknown History - Streamlit control room.
Dark cinematic theme: Gold #d4af37 on Black #0e1117.
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import video_engine as ve

st.set_page_config(
    page_title="Unknown History Studio",
    page_icon="🏺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Cinematic dark theme
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      .stApp { background-color: #0e1117; color: #e8e8e8; }
      h1, h2, h3 { color: #d4af37; font-family: Georgia, serif; letter-spacing: 1px; }
      .gold-line { border: none; border-top: 1px solid #d4af37; opacity: .5; }
      .stButton>button {
          background-color: #d4af37; color: #0e1117; font-weight: bold;
          border: none; border-radius: 6px; padding: .6rem 1.6rem;
          font-size: 1.05rem; letter-spacing: .5px;
      }
      .stButton>button:hover { background-color: #f0d060; color: #0e1117; }
      .card {
          background: #161a23; border: 1px solid #2a2f3a; border-radius: 12px;
          padding: 1rem 1.2rem; margin-bottom: .8rem;
      }
      .agent-chip {
          display: inline-block; background: #1f2430; border: 1px solid #d4af37;
          color: #d4af37; border-radius: 999px; padding: .15rem .8rem;
          margin: .15rem .25rem .15rem 0; font-size: .85rem;
      }
      .warn { color: #ffb020; }
      footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🏺 Unknown History — Autonomous AI Video Studio")
st.markdown('<hr class="gold-line">', unsafe_allow_html=True)
st.caption(
    "One click: research a forgotten story → write the script → narrate → "
    "fetch real 4K stock footage → render a cinematic documentary."
)
st.markdown(
    '<span class="agent-chip">🧠 Ideation Agent</span>'
    '<span class="agent-chip">✍️ Scriptwriter AI</span>'
    '<span class="agent-chip">🎙️ Voice AI</span>'
    '<span class="agent-chip">🎬 Video Production AI</span>'
    '<span class="agent-chip">🖼️ Thumbnail AI</span>'
    '<span class="agent-chip">📈 Analytics & Growth Agent</span>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="gold-line">', unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Sidebar — video production settings
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("🎛️ Video production settings")
    duration_label = st.selectbox(
        "Documentary length",
        options=list(ve.DURATION_PRESETS.keys()),
        format_func=lambda k: ve.DURATION_PRESETS[k]["label"],
        index=0,
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
            '<p class="warn">⚠️ 40-minute videos require much more research, '
            "production time and quality control.</p>",
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="gold-line">', unsafe_allow_html=True)
    st.header("🗂️ Memory")
    if st.button("Show topic history"):
        used = ve.read_database()
        if used:
            for t in reversed(used[-30:]):
                st.write("•", t)
        else:
            st.write("No topics yet.")
    st.caption(f"Database: `{ve.DB_FILE.name}` — topics never repeat.")

# --------------------------------------------------------------------------- #
# Main — generate
# --------------------------------------------------------------------------- #
col1, col2 = st.columns([2, 1])
with col1:
    generate = st.button("▶ GENERATE DOCUMENTARY", use_container_width=True)
with col2:
    st.metric("Target runtime", f"{preset['minutes']} min")
    st.metric("Planned scenes", preset["scenes"])

if generate:
    if not os.getenv("GROQ_API_KEY") or not os.getenv("PIXABAY_API_KEY"):
        st.error(
            "Missing API keys. Copy `.env.example` to `.env` and set "
            "GROQ_API_KEY and PIXABAY_API_KEY, then restart the app."
        )
        st.stop()
    log_box = st.empty()
    bar = st.progress(0)
    logs = []

    def progress_cb(msg):
        logs.append(msg)
        log_box.code("\n".join(logs[-14:]), language=None)

    def fraction_cb(frac):
        bar.progress(min(1.0, max(0.0, frac)))

    try:
        with st.spinner("The studio is working..."):
            out_path, topic_info = ve.run_pipeline(
                duration_label, progress_cb=progress_cb, fraction_cb=fraction_cb
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
        st.warning(
            "After uploading to YouTube, tick the **'Altered Content'** label "
            "(AI-generated disclosure)."
        )
    except Exception as e:
        st.error(f"Pipeline failed: {e}")
        with st.expander("Full log"):
            st.code("\n".join(logs))

else:
    st.info("Click **GENERATE DOCUMENTARY** to let the studio work. "
            "Every run picks a topic never told before.")
