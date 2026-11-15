"""
Unknown History - Autonomous Video Engine
=========================================
Pipeline: Groq (ideation + scripting) -> edge-tts (voiceover)
          -> Pixabay (real stock footage) -> MoviePy (render).
Supports serialized (Part 1, Part 2) documentaries.
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

# Pillow 10+ compatibility shim for MoviePy 1.0.3
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

# Adjusted for 5-7 minute parts (15 scenes ≈ 6 minutes)
DURATION_PRESETS = {
    "part_6m": {"label": "Short Part (6 min)", "minutes": 6, "scenes": 15},
    "standard": {"label": "Standard (10 min)", "minutes": 10, "scenes": 22},
}

OUTRO_TITLE = "UNKNOWN HISTORY"
OUTRO_BYLINE = "by SupremeAmer Tech"

TOPIC_CATEGORIES = [
    "forgotten tribes and lost peoples",
    "lost rituals and ceremonies",
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
# 1. Ideation & Scripting
# --------------------------------------------------------------------------- #
def generate_topic(progress_cb=None):
    client = groq_client()
    used = read_database()
    category = random.choice(TOPIC_CATEGORIES)

    system = "You are the ideation brain of 'Unknown History'. Reply ONLY with valid JSON."
    user = (
        f"Pick a topic inside the category: {category}.\n"
        f"Topics already used:\n" + ("\n".join(f"- {t}" for t in used[-50:]) if used else "(none)")
        + '\n\nReturn JSON with keys: "topic", "category", "logline".'
    )

    log(progress_cb, f"Brainstorming a new topic in category: {category}")
    data = groq_json(client, system, user, temperature=1.0)
    topic = data.get("topic", "").strip()
    if not topic:
        raise RuntimeError(f"Groq returned an unusable topic: {data}")
    append_database(topic, data.get("category", category))
    return data

def generate_script(topic_info, preset_key, part_num, total_parts, progress_cb=None):
    client = groq_client()
    preset = DURATION_PRESETS[preset_key]
    target = preset["scenes"]
    topic = topic_info["topic"]

    # Dynamic arc based on total parts
    if total_parts == 1:
        arc = "Structure: cold open hook, rising chapters, a quiet emotional turn, and a reflective ending."
    elif part_num == 1:
        arc = "You are writing PART 1. Focus on the origins, setting, introduction of the people, and the mysterious hook. End on a cliffhanger."
    elif part_num == 2:
        arc = "You are writing PART 2. Focus on the turning point, the conflict, the loss, or the mystery deepening. End on a cliffhanger."
    elif part_num == 3:
        arc = "You are writing PART 3. Focus on the climax, the grand reveal, or the ultimate fate. End on a cliffhanger."
    else:
        arc = "You are writing the FINAL PART. Focus on the legacy, the echoes in modern times, the resolution, and a profound reflective conclusion."

    system = (
        "You are an award-winning documentary scriptwriter. "
        "Write cinematic, slow-burn narration. Reply ONLY with valid JSON."
    )
    user = (
        f'Write Part {part_num} of a documentary titled: "{topic}".\n'
        f"Logline: {topic_info.get('logline','')}\n"
        f"{arc}\n"
        f"Return JSON: {{\"scenes\": [ ... {target} scenes ... ]}} where each scene is:\n"
        '{"narration": "1-3 sentences", "visual_search": "2-3 words", "mood": "one word"}'
    )

    log(progress_cb, f"Scripting Part {part_num} ({target} scenes)...")
    data = groq_json(client, system, user)
    scenes = data.get("scenes", [])
    if not scenes:
        raise RuntimeError("Groq returned an empty script.")
    return scenes


# --------------------------------------------------------------------------- #
# 2. Voiceover & Footage
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
    return out, audio.duration

def _pick_pixabay_video_file(hit):
    vids = hit.get("videos", {}) or {}
    for key in ("large", "medium", "small", "tiny"):
        rend = vids.get(key) or {}
        if rend.get("url"):
            return rend["url"]
    return None

def search_pixabay_video(query, min_duration):
    if not PIXABAY_API_KEY:
        return None
    params = {
        "key": PIXABAY_API_KEY, "q": query, "video_type": "film",
        "safesearch": "true", "per_page": 20, "order": "popular",
    }
    try:
        r = requests.get(PIXABAY_VIDEO_URL, params=params, timeout=30)
        r.raise_for_status()
        hits = r.json().get("hits", [])
        for h in hits:
            if h.get("duration", 0) >= min_duration:
                url = _pick_pixabay_video_file(h)
                if url: return url
        for h in hits:
            url = _pick_pixabay_video_file(h)
            if url: return url
    except Exception:
        pass
    return None

def download_video(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest

def fetch_scene_footage(scene, idx, duration, progress_cb=None):
    query = scene.get("visual_search", "ancient history")
    url = search_pixabay_video(query, min_duration=max(5, int(duration)))
    if not url:
        return make_fallback_card(scene.get("visual_search", "UNKNOWN"), idx, duration)
    dest = WORK_DIR / f"scene_{idx:03d}.mp4"
    download_video(url, dest)
    return str(dest)


# --------------------------------------------------------------------------- #
# 3. Render & Outro Cards
# --------------------------------------------------------------------------- #
def make_fallback_card(title, idx, duration):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 90)
        small = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        font = ImageFont.load_default(); small = font
    draw.text((660, 510), title, fill=(212, 175, 55), font=font)
    p = WORK_DIR / f"card_{idx:03d}.png"
    img.save(p)
    return ImageClip(str(p)).set_duration(duration)

def make_outro_card(duration, part_num, total_parts):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 100)
        mid = ImageFont.truetype("DejaVuSans.ttf", 60)
    except OSError:
        big = mid = ImageFont.load_default()
    
    draw.text((560, 400), OUTRO_TITLE, fill=(212, 175, 55), font=big)
    draw.text((560, 520), OUTRO_BYLINE, fill=(230, 230, 230), font=mid)
    
    # Add the "Watch out for Part X" text if it's a saga
    if total_parts > 1 and part_num < total_parts:
        teaser = f"WATCH OUT FOR PART {part_num + 1}"
        draw.text((560, 700), teaser, fill=(255, 176, 32), font=mid)
        
    png = WORK_DIR / "outro_card.png"
    img.save(png)
    return ImageClip(str(png)).set_duration(duration)

def build_outro(scene_count, part_num, total_parts, progress_cb=None):
    if total_parts > 1 and part_num < total_parts:
        narration = f"This has been Part {part_num} of Unknown History. Watch out for Part {part_num + 1}."
    else:
        narration = "This has been Unknown History. Brought to you by SupremeAmer Tech."
        
    audio_path, dur = generate_voiceover({"narration": narration}, scene_count + 1)
    card = make_outro_card(dur, part_num, total_parts)
    return render_scene({}, scene_count + 1, audio_path, card)


def _fit_clip(clip, duration):
    w, h = clip.size
    target_ratio = 16 / 9
    if w / h > target_ratio:
        nw = int(h * target_ratio); x1 = (w - nw) // 2
        clip = clip.crop(x1=x1, y1=0, x2=x1 + nw, y2=h)
    else:
        nh = int(w / target_ratio); y1 = (h - nh) // 2
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
    vclip = VideoFileClip(footage) if isinstance(footage, str) else footage
    vclip = _fit_clip(vclip, duration)
    vclip = vclip.set_audio(AudioFileClip(str(audio_path)))
    return vclip.fadein(0.6).fadeout(0.8)


# --------------------------------------------------------------------------- #
# 4. Pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(preset_key, part_num=1, total_parts=1, topic_info=None, progress_cb=None, fraction_cb=None):
    def cb(msg, frac=None):
        if msg and progress_cb: progress_cb(msg)
        if frac is not None and fraction_cb: fraction_cb(frac)

    if topic_info is None:
        topic_info = generate_topic(cb)
        
    scenes = generate_script(topic_info, preset_key, part_num, total_parts, cb)
    total = len(scenes)
    clips = []
    
    for i, scene in enumerate(scenes, start=1):
        cb(f"Scene {i}/{total}: {scene.get('visual_search','')}")
        audio_path, dur = generate_voiceover(scene, i, cb)
        footage = fetch_scene_footage(scene, i, dur, cb)
        clips.append(render_scene(scene, i, audio_path, footage))
        cb(None, i / total)

    clips.append(build_outro(total, part_num, total_parts, cb))
    
    cb("Stitching film...")
    final = concatenate_videoclips(clips, method="compose")
    
    safe_title = "".join(c for c in topic_info["topic"] if c.isalnum() or c in " _-")[:30].strip().replace(" ", "_")
    part_suffix = f"_Part{part_num}" if total_parts > 1 else ""
    out = BASE_DIR / f"UnknownHistory_{safe_title}{part_suffix}.mp4"
    
    final.write_videofile(str(out), codec="libx264", audio_codec="aac",
                          bitrate=BITRATE, fps=FPS, preset="medium", threads=4)
    for c in clips: c.close()
    final.close()
    
    # Cleanup memory files for next part
    for file in WORK_DIR.glob("*"):
        try: file.unlink()
        except: pass
        
    return out, topic_info"""
Unknown History - Autonomous Video Engine
=========================================
Pipeline: Groq (ideation + scripting) -> edge-tts (voiceover)
          -> Pixabay (real stock footage) -> MoviePy (render).
Supports serialized (Part 1, Part 2) documentaries.
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

# Pillow 10+ compatibility shim for MoviePy 1.0.3
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

# Adjusted for 5-7 minute parts (15 scenes ≈ 6 minutes)
DURATION_PRESETS = {
    "part_6m": {"label": "Short Part (6 min)", "minutes": 6, "scenes": 15},
    "standard": {"label": "Standard (10 min)", "minutes": 10, "scenes": 22},
}

OUTRO_TITLE = "UNKNOWN HISTORY"
OUTRO_BYLINE = "by SupremeAmer Tech"

TOPIC_CATEGORIES = [
    "forgotten tribes and lost peoples",
    "lost rituals and ceremonies",
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
# 1. Ideation & Scripting
# --------------------------------------------------------------------------- #
def generate_topic(progress_cb=None):
    client = groq_client()
    used = read_database()
    category = random.choice(TOPIC_CATEGORIES)

    system = "You are the ideation brain of 'Unknown History'. Reply ONLY with valid JSON."
    user = (
        f"Pick a topic inside the category: {category}.\n"
        f"Topics already used:\n" + ("\n".join(f"- {t}" for t in used[-50:]) if used else "(none)")
        + '\n\nReturn JSON with keys: "topic", "category", "logline".'
    )

    log(progress_cb, f"Brainstorming a new topic in category: {category}")
    data = groq_json(client, system, user, temperature=1.0)
    topic = data.get("topic", "").strip()
    if not topic:
        raise RuntimeError(f"Groq returned an unusable topic: {data}")
    append_database(topic, data.get("category", category))
    return data

def generate_script(topic_info, preset_key, part_num, total_parts, progress_cb=None):
    client = groq_client()
    preset = DURATION_PRESETS[preset_key]
    target = preset["scenes"]
    topic = topic_info["topic"]

    # Dynamic arc based on total parts
    if total_parts == 1:
        arc = "Structure: cold open hook, rising chapters, a quiet emotional turn, and a reflective ending."
    elif part_num == 1:
        arc = "You are writing PART 1. Focus on the origins, setting, introduction of the people, and the mysterious hook. End on a cliffhanger."
    elif part_num == 2:
        arc = "You are writing PART 2. Focus on the turning point, the conflict, the loss, or the mystery deepening. End on a cliffhanger."
    elif part_num == 3:
        arc = "You are writing PART 3. Focus on the climax, the grand reveal, or the ultimate fate. End on a cliffhanger."
    else:
        arc = "You are writing the FINAL PART. Focus on the legacy, the echoes in modern times, the resolution, and a profound reflective conclusion."

    system = (
        "You are an award-winning documentary scriptwriter. "
        "Write cinematic, slow-burn narration. Reply ONLY with valid JSON."
    )
    user = (
        f'Write Part {part_num} of a documentary titled: "{topic}".\n'
        f"Logline: {topic_info.get('logline','')}\n"
        f"{arc}\n"
        f"Return JSON: {{\"scenes\": [ ... {target} scenes ... ]}} where each scene is:\n"
        '{"narration": "1-3 sentences", "visual_search": "2-3 words", "mood": "one word"}'
    )

    log(progress_cb, f"Scripting Part {part_num} ({target} scenes)...")
    data = groq_json(client, system, user)
    scenes = data.get("scenes", [])
    if not scenes:
        raise RuntimeError("Groq returned an empty script.")
    return scenes


# --------------------------------------------------------------------------- #
# 2. Voiceover & Footage
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
    return out, audio.duration

def _pick_pixabay_video_file(hit):
    vids = hit.get("videos", {}) or {}
    for key in ("large", "medium", "small", "tiny"):
        rend = vids.get(key) or {}
        if rend.get("url"):
            return rend["url"]
    return None

def search_pixabay_video(query, min_duration):
    if not PIXABAY_API_KEY:
        return None
    params = {
        "key": PIXABAY_API_KEY, "q": query, "video_type": "film",
        "safesearch": "true", "per_page": 20, "order": "popular",
    }
    try:
        r = requests.get(PIXABAY_VIDEO_URL, params=params, timeout=30)
        r.raise_for_status()
        hits = r.json().get("hits", [])
        for h in hits:
            if h.get("duration", 0) >= min_duration:
                url = _pick_pixabay_video_file(h)
                if url: return url
        for h in hits:
            url = _pick_pixabay_video_file(h)
            if url: return url
    except Exception:
        pass
    return None

def download_video(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest

def fetch_scene_footage(scene, idx, duration, progress_cb=None):
    query = scene.get("visual_search", "ancient history")
    url = search_pixabay_video(query, min_duration=max(5, int(duration)))
    if not url:
        return make_fallback_card(scene.get("visual_search", "UNKNOWN"), idx, duration)
    dest = WORK_DIR / f"scene_{idx:03d}.mp4"
    download_video(url, dest)
    return str(dest)


# --------------------------------------------------------------------------- #
# 3. Render & Outro Cards
# --------------------------------------------------------------------------- #
def make_fallback_card(title, idx, duration):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 90)
        small = ImageFont.truetype("DejaVuSans.ttf", 44)
    except OSError:
        font = ImageFont.load_default(); small = font
    draw.text((660, 510), title, fill=(212, 175, 55), font=font)
    p = WORK_DIR / f"card_{idx:03d}.png"
    img.save(p)
    return ImageClip(str(p)).set_duration(duration)

def make_outro_card(duration, part_num, total_parts):
    img = Image.new("RGB", (1920, 1080), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 100)
        mid = ImageFont.truetype("DejaVuSans.ttf", 60)
    except OSError:
        big = mid = ImageFont.load_default()
    
    draw.text((560, 400), OUTRO_TITLE, fill=(212, 175, 55), font=big)
    draw.text((560, 520), OUTRO_BYLINE, fill=(230, 230, 230), font=mid)
    
    # Add the "Watch out for Part X" text if it's a saga
    if total_parts > 1 and part_num < total_parts:
        teaser = f"WATCH OUT FOR PART {part_num + 1}"
        draw.text((560, 700), teaser, fill=(255, 176, 32), font=mid)
        
    png = WORK_DIR / "outro_card.png"
    img.save(png)
    return ImageClip(str(png)).set_duration(duration)

def build_outro(scene_count, part_num, total_parts, progress_cb=None):
    if total_parts > 1 and part_num < total_parts:
        narration = f"This has been Part {part_num} of Unknown History. Watch out for Part {part_num + 1}."
    else:
        narration = "This has been Unknown History. Brought to you by SupremeAmer Tech."
        
    audio_path, dur = generate_voiceover({"narration": narration}, scene_count + 1)
    card = make_outro_card(dur, part_num, total_parts)
    return render_scene({}, scene_count + 1, audio_path, card)


def _fit_clip(clip, duration):
    w, h = clip.size
    target_ratio = 16 / 9
    if w / h > target_ratio:
        nw = int(h * target_ratio); x1 = (w - nw) // 2
        clip = clip.crop(x1=x1, y1=0, x2=x1 + nw, y2=h)
    else:
        nh = int(w / target_ratio); y1 = (h - nh) // 2
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
    vclip = VideoFileClip(footage) if isinstance(footage, str) else footage
    vclip = _fit_clip(vclip, duration)
    vclip = vclip.set_audio(AudioFileClip(str(audio_path)))
    return vclip.fadein(0.6).fadeout(0.8)


# --------------------------------------------------------------------------- #
# 4. Pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(preset_key, part_num=1, total_parts=1, topic_info=None, progress_cb=None, fraction_cb=None):
    def cb(msg, frac=None):
        if msg and progress_cb: progress_cb(msg)
        if frac is not None and fraction_cb: fraction_cb(frac)

    if topic_info is None:
        topic_info = generate_topic(cb)
        
    scenes = generate_script(topic_info, preset_key, part_num, total_parts, cb)
    total = len(scenes)
    clips = []
    
    for i, scene in enumerate(scenes, start=1):
        cb(f"Scene {i}/{total}: {scene.get('visual_search','')}")
        audio_path, dur = generate_voiceover(scene, i, cb)
        footage = fetch_scene_footage(scene, i, dur, cb)
        clips.append(render_scene(scene, i, audio_path, footage))
        cb(None, i / total)

    clips.append(build_outro(total, part_num, total_parts, cb))
    
    cb("Stitching film...")
    final = concatenate_videoclips(clips, method="compose")
    
    safe_title = "".join(c for c in topic_info["topic"] if c.isalnum() or c in " _-")[:30].strip().replace(" ", "_")
    part_suffix = f"_Part{part_num}" if total_parts > 1 else ""
    out = BASE_DIR / f"UnknownHistory_{safe_title}{part_suffix}.mp4"
    
    final.write_videofile(str(out), codec="libx264", audio_codec="aac",
                          bitrate=BITRATE, fps=FPS, preset="medium", threads=4)
    for c in clips: c.close()
    final.close()
    
    # Cleanup memory files for next part
    for file in WORK_DIR.glob("*"):
        try: file.unlink()
        except: pass
        
    return out, topic_info
