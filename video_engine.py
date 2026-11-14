"""
Unknown History - Autonomous Video Engine
=========================================
Pipeline: Groq (ideation + scripting) -> edge-tts (voiceover)
          -> Pixabay (real stock footage) -> MoviePy (render).

Brand: mysterious, educational, deeply human, suspenseful, respectful.
Strictly REAL stock footage - never AI-generated visuals.
"""

import os
import json
import asyncio
import random
from pathlib import Path
from datetime import datetime

import requests
import edge_tts
from groq import Groq
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------- #
# Pillow 10+ compatibility shim for MoviePy 1.0.3
# MoviePy internally calls Image.ANTIALIAS, which Pillow removed in 10.0.0.
# Map it to LANCZOS so MoviePy's resize path keeps working unchanged.
# --------------------------------------------------------------------------- #
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "history_database.txt"
WORK_DIR = BASE_DIR / "work"
WORK_DIR.mkdir(exist_ok=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-120b"
TTS_VOICE = "en-GB-RyanNeural"
TTS_RATE = "-5%"
PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"

FPS = 24
BITRATE = "8000k"

DURATION_PRESETS = {
    "standard": {"label": "Standard documentary (10 min)", "minutes": 10, "scenes": 22},
    "extended": {"label": "Extended documentary (20 min)", "minutes": 20, "scenes": 44},
    "longform": {"label": "Long-form documentary (40 min)", "minutes": 40, "scenes": 88},
}
LONGFORM_CHAPTER_SIZE = 18

OUTRO_NARRATION = "This has been Unknown History. Brought to you by SupremeAmer Tech."
OUTRO_TITLE = "UNKNOWN HISTORY"
OUTRO_BYLINE = "by SupremeAmer Tech"

TOPIC_CATEGORIES = [
    "forgotten tribes and lost peoples",
    "ancient proverbs and their hidden origins",
    "lost rituals and ceremonies",
    "untold cultural histories",
    "human ethics and principles from the past",
    "vanished cities and silent civilisations",
    "unheard voices of ordinary people in history",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def log(cb, msg):
    stamp = datetime.now().strftime("%H:%M:%S")
    if cb:
        cb(f"[{stamp}] {msg}")
    print(f"[{stamp}] {msg}")


def read_database():
    if not DB_FILE.exists():
        return []
    topics = []
    for line in DB_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            topics.append(line.split("|")[0].strip())
    return topics


def append_database(topic, category):
    with open(DB_FILE, "a") as f:
        f.write(f"{topic} | {category} | {datetime.now():%Y-%m-%d}\n")


def groq_client():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return Groq(api_key=GROQ_API_KEY)


def groq_json(client, system, user, temperature=0.9):
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=4000,
    )
    return json.loads(resp.choices[0].message.content)


# --------------------------------------------------------------------------- #
# 1. Ideation
# --------------------------------------------------------------------------- #
def generate_topic(progress_cb=None):
    client = groq_client()
    used = read_database()
    category = random.choice(TOPIC_CATEGORIES)

    system = (
        "You are the ideation brain of 'Unknown History', a documentary studio. "
        "You invent specific, obscure, historically plausible documentary topics. "
        "Tone: mysterious, educational, deeply human, suspenseful, respectful. "
        "Reply ONLY with valid JSON."
    )
    user = (
        f"Pick a topic inside the category: {category}.\n"
        f"Topics already used (never repeat or closely paraphrase these):\n"
        + ("\n".join(f"- {t}" for t in used[-80:]) if used else "(none yet)")
        + "\n\nReturn JSON with keys: "
        '"topic" (a specific, vivid title), "category", "logline" (one sentence hook).'
    )

    log(progress_cb, f"Brainstorming a new topic in category: {category}")
    data = groq_json(client, system, user, temperature=1.0)
    topic = data.get("topic", "").strip()
    if not topic:
        raise RuntimeError(f"Groq returned an unusable topic: {data}")
    append_database(topic, data.get("category", category))
    log(progress_cb, f"New topic locked in: {topic}")
    return data


# --------------------------------------------------------------------------- #
# 2. Scripting
# --------------------------------------------------------------------------- #
def generate_script(topic_info, preset_key, progress_cb=None):
    client = groq_client()
    preset = DURATION_PRESETS[preset_key]
    target = preset["scenes"]
    topic = topic_info["topic"]

    system = (
        "You are an award-winning documentary scriptwriter for 'Unknown History'. "
        "You write cinematic, slow-burn narration: mysterious, educational, deeply "
        "human, suspenseful, respectful. Never invent fake quotes attributed to "
        "real named people; keep claims plausible and hedge when uncertain. "
        "Reply ONLY with valid JSON."
    )

    def scene_block(i):
        return (
            f"{i}. narration: 1-3 short sentences, slow-paced, authoritative, "
            "written to be SPOKEN aloud (no headings, no markdown); "
            "visual_search: exactly 2-3 plain English words for stock-footage "
            "search; mood: one word."
        )

    if preset_key != "longform":
        user = (
            f'Write a {preset["minutes"]}-minute documentary script on: "{topic}". '
            f"Logline: {topic_info.get('logline','')}\n"
            f"Return JSON: {{\"scenes\": [ ... {target} scenes ... ]}} where each scene is:\n"
            + "\n".join(scene_block("i") for _ in range(1))
            + "\nNumber the scenes in order with an 'index' field starting at 1."
        )
        log(progress_cb, f"Scripting {target} scenes with Groq...")
        data = groq_json(client, system, user)
        scenes = data.get("scenes", [])
    else:
        scenes = []
        chapter_n = 0
        total_chapters = -(-target // LONGFORM_CHAPTER_SIZE)
        while len(scenes) < target:
            chapter_n += 1
            need = min(LONGFORM_CHAPTER_SIZE, target - len(scenes))
            user = (
                f'Continue the LONG-FORM ({preset["minutes"]}-minute) documentary on: "{topic}". '
                f"You are writing chapter {chapter_n} of {total_chapters}. "
                f"Scenes already written: {len(scenes)}. Write the next {need} scenes.\n"
                f"Return JSON: {{\"scenes\": [...]}} each with index continuing "
                f"from {len(scenes) + 1}, narration, visual_search, mood."
            )
            log(progress_cb, f"Scripting chapter {chapter_n}/{total_chapters} ({need} scenes)...")
            data = groq_json(client, system, user)
            batch = data.get("scenes", [])
            if not batch:
                break
            scenes.extend(batch)
        scenes = scenes[:target]

    if not scenes:
        raise RuntimeError("Groq returned an empty script.")
    log(progress_cb, f"Script ready: {len(scenes)} scenes.")
    return scenes


# --------------------------------------------------------------------------- #
# 3a. Voiceover
# --------------------------------------------------------------------------- #
async def _tts_save(text, out_path):
    await edge_tts.Communicate(text=text, voice=TTS_VOICE, rate=TTS_RATE).save(str(out_path))


def generate_voiceover(scene, idx, progress_cb=None):
    out = WORK_DIR / f"scene_{idx:03d}.mp3"
    try:
        asyncio.run(_tts_save(scene["narration"], out))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_tts_save(scene["narration"], out))
        loop.close()
    audio = AudioFileClip(str(out))
    log(progress_cb, f"  Scene {idx}: voiceover {audio.duration:.1f}s")
    return out, audio.duration


# --------------------------------------------------------------------------- #
# 3b. Pixabay stock footage
# --------------------------------------------------------------------------- #
def _pick_pixabay_video_file(hit):
    vids = hit.get("videos", {}) or {}
    for key in ("large", "medium", "small", "tiny"):
        rend = vids.get(key) or {}
        url = rend.get("url")
        if url:
            return url
    return None


def search_pixabay_video(query, min_duration, progress_cb=None):
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY is not set.")
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "video_type": "film",
        "safesearch": "true",
        "per_page": 20,
        "order": "popular",
    }
    r = requests.get(PIXABAY_VIDEO_URL, params=params, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])

    for h in hits:
        if h.get("duration", 0) >= min_duration:
            url = _pick_pixabay_video_file(h)
            if url:
                return url

    for h in hits:
        url = _pick_pixabay_video_file(h)
        if url:
            return url
    return None


def download_video(url, dest, progress_cb=None):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def make_fallback_card(title, idx, duration):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 90)
        small = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
        small = font
    draw.line([(660, 470), (1260, 470)], fill=(212, 175, 55), width=4)
    draw.line([(660, 640), (1260, 640)], fill=(212, 175, 55), width=4)
    w = draw.textlength(title, font=font)
    draw.text(((1920 - w) / 2, 510), title, fill=(212, 175, 55), font=font)
    t = "UNKNOWN HISTORY"
    wt = draw.textlength(t, font=small)
    draw.text(((1920 - wt) / 2, 380), t, fill=(230, 230, 230), font=small)
    by = "SUPREMEAMER TECH"
    wb = draw.textlength(by, font=small)
    draw.text(((1920 - wb) / 2, 980), by, fill=(160, 160, 160), font=small)
    p = WORK_DIR / f"card_{idx:03d}.png"
    img.save(p)
    return ImageClip(str(p)).set_duration(duration)


def make_outro_card(duration):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 120)
        mid = ImageFont.truetype("DejaVuSans.ttf", 64)
        small = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        big = mid = small = ImageFont.load_default()
    draw.line([(560, 420), (1360, 420)], fill=(212, 175, 55), width=4)
    draw.line([(560, 700), (1360, 700)], fill=(212, 175, 55), width=4)
    wt = draw.textlength(OUTRO_TITLE, font=big)
    draw.text(((1920 - wt) / 2, 490), OUTRO_TITLE, fill=(212, 175, 55), font=big)
    wb = draw.textlength(OUTRO_BYLINE, font=mid)
    draw.text(((1920 - wb) / 2, 640), OUTRO_BYLINE, fill=(230, 230, 230), font=mid)
    tag = "SUPREMEAMER TECH"
    wg = draw.textlength(tag, font=small)
    draw.text(((1920 - wg) / 2, 980), tag, fill=(150, 150, 150), font=small)
    png = WORK_DIR / "outro_card.png"
    img.save(png)
    return ImageClip(str(png)).set_duration(duration)


def build_outro(scene_count, progress_cb=None):
    log(progress_cb, "Outro: 'Unknown History by SupremeAmer Tech'")
    audio_path, dur = generate_voiceover(
        {"narration": OUTRO_NARRATION}, scene_count + 1, progress_cb
    )
    card = make_outro_card(dur)
    return render_scene({}, scene_count + 1, audio_path, card, progress_cb)


def fetch_scene_footage(scene, idx, duration, progress_cb=None):
    query = scene.get("visual_search", "ancient history")
    log(progress_cb, f"  Scene {idx}: searching Pixabay for '{query}'")
    url = search_pixabay_video(query, min_duration=max(5, int(duration)))
    if not url:
        log(progress_cb, f"  Scene {idx}: no footage found - cinematic title card fallback")
        return make_fallback_card(scene.get("visual_search", "UNKNOWN"), idx, duration)
    dest = WORK_DIR / f"scene_{idx:03d}.mp4"
    download_video(url, dest)
    return str(dest)


# --------------------------------------------------------------------------- #
# 4. Render
# --------------------------------------------------------------------------- #
def _fit_clip(clip, duration):
    w, h = clip.size
    target_ratio = 16 / 9
    if w / h > target_ratio:
        nw = int(h * target_ratio)
        x1 = (w - nw) // 2
        clip = clip.crop(x1=x1, y1=0, x2=x1 + nw, y2=h)
    else:
        nh = int(w / target_ratio)
        y1 = (h - nh) // 2
        clip = clip.crop(x1=0, y1=y1, x2=w, y2=y1 + nh)
    clip = clip.resize(newsize=(1920, 1080))
    if clip.duration > duration:
        clip = clip.subclip(0, duration)
    elif clip.duration < duration and clip.duration > 0:
        n = int(duration / clip.duration) + 1
        from moviepy.editor import concatenate_videoclips as _cat
        clip = _cat([clip] * n).subclip(0, duration)
    return clip.set_duration(duration)


def render_scene(scene, idx, audio_path, footage, progress_cb=None):
    duration = AudioFileClip(str(audio_path)).duration
    if isinstance(footage, str):
        vclip = VideoFileClip(footage)
    else:
        vclip = footage
    vclip = _fit_clip(vclip, duration)
    vclip = vclip.set_audio(AudioFileClip(str(audio_path)))
    vclip = vclip.fadein(0.6).fadeout(0.8)
    return vclip


def run_pipeline(preset_key, progress_cb=None, fraction_cb=None):
    def cb(msg, frac=None):
        if msg:
            progress_cb and progress_cb(msg)
        if frac is not None and fraction_cb:
            fraction_cb(frac)

    topic_info = generate_topic(cb)
    scenes = generate_script(topic_info, preset_key, cb)

    def render_cb(msg):
        if msg:
            cb(msg)

    preset = DURATION_PRESETS[preset_key]
    total = len(scenes)
    clips = []
    for i, scene in enumerate(scenes, start=1):
        render_cb(f"Scene {i}/{total}: {scene.get('visual_search','')}")
        audio_path, dur = generate_voiceover(scene, i, render_cb)
        footage = fetch_scene_footage(scene, i, dur, render_cb)
        clips.append(render_scene(scene, i, audio_path, footage, render_cb))
        cb(None, i / total)

    clips.append(build_outro(total, render_cb))
    cb(None, 1.0)

    render_cb("Stitching scenes into the final film...")
    final = concatenate_videoclips(clips, method="compose")
    safe = "".join(c for c in topic_info["topic"] if c.isalnum() or c in " _-")[:40].strip().replace(" ", "_")
    out = BASE_DIR / f"UnknownHistory_{safe}.mp4"
    final.write_videofile(str(out), codec="libx264", audio_codec="aac",
                          bitrate=BITRATE, fps=FPS, preset="medium", threads=4)
    for c in clips:
        c.close()
    final.close()
    render_cb(f"Done -> {out.name}")
    return out, topic_info