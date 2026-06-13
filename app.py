#!/usr/bin/env python3
"""
MeTube Podcast Feed - Generates an Apple Podcasts compatible RSS feed for MeTube downloads.
"""

import os
import mimetypes
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from flask import Flask, Response
from mutagen import File as MutagenFile
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

app = Flask(__name__)

# Configuration from environment variables
DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", "/downloads"))
METUBE_URL = os.environ.get("METUBE_URL", "http://localhost:8081")  # MeTube server URL
PODCAST_TITLE = os.environ.get("PODCAST_TITLE", "MeTube Downloads")
PODCAST_DESCRIPTION = os.environ.get("PODCAST_DESCRIPTION", "Audio and video downloads from MeTube")
PODCAST_AUTHOR = os.environ.get("PODCAST_AUTHOR", "MeTube")
PODCAST_EMAIL = os.environ.get("PODCAST_EMAIL", "podcast@example.com")
PODCAST_IMAGE = os.environ.get("PODCAST_IMAGE", "")
PODCAST_LANGUAGE = os.environ.get("PODCAST_LANGUAGE", "en")
PODCAST_CATEGORY = os.environ.get("PODCAST_CATEGORY", "Technology")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")  # This feed's URL
PORT = int(os.environ.get("PORT", "8000"))

# Supported media extensions
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".m4v", ".mov", ".avi"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# Cache for file metadata
file_cache = {}


def get_file_hash(filepath: Path) -> str:
    """Generate a unique ID for a file based on path and mtime."""
    stat = filepath.stat()
    content = f"{filepath}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def get_media_duration(filepath: Path) -> int:
    """Get duration of media file in seconds using mutagen."""
    try:
        audio = MutagenFile(filepath)
        if audio and audio.info:
            return int(audio.info.length)
    except Exception:
        pass
    return 0


def get_mime_type(filepath: Path) -> str:
    """Get MIME type for a file."""
    mime_type, _ = mimetypes.guess_type(str(filepath))
    if mime_type:
        return mime_type
    
    ext = filepath.suffix.lower()
    mime_map = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4v": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
    }
    return mime_map.get(ext, "application/octet-stream")


def format_duration(seconds: int) -> str:
    """Format duration as HH:MM:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def get_metube_download_url(filename: str, is_video: bool) -> str:
    """Generate the MeTube download URL for a file."""
    # MeTube uses /audio_download/ or /download/ endpoints
    endpoint = "download" if is_video else "audio_download"
    encoded_name = quote(filename)
    return f"{METUBE_URL.rstrip('/')}/{endpoint}/{encoded_name}"


def scan_downloads() -> list[dict]:
    """Scan downloads directory for media files."""
    media_files = []
    
    if not DOWNLOADS_DIR.exists():
        return media_files
    
    for filepath in DOWNLOADS_DIR.rglob("*"):
        if not filepath.is_file():
            continue
        
        if filepath.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        
        # Skip hidden files and temp files
        if filepath.name.startswith(".") or filepath.name.endswith(".part"):
            continue
        
        file_hash = get_file_hash(filepath)
        
        # Use cached metadata if available and file hasn't changed
        if file_hash in file_cache:
            media_files.append(file_cache[file_hash])
            continue
        
        stat = filepath.stat()
        is_video = filepath.suffix.lower() in VIDEO_EXTENSIONS
        
        # Get duration
        duration = get_media_duration(filepath)
        
        file_info = {
            "path": filepath,
            "filename": filepath.name,
            "name": filepath.stem,
            "extension": filepath.suffix.lower(),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            "duration": duration,
            "duration_formatted": format_duration(duration),
            "mime_type": get_mime_type(filepath),
            "guid": file_hash,
            "is_video": is_video,
            "download_url": get_metube_download_url(filepath.name, is_video),
        }
        
        file_cache[file_hash] = file_info
        media_files.append(file_info)
    
    # Sort by modification time, newest first
    media_files.sort(key=lambda x: x["mtime"], reverse=True)
    return media_files


def generate_rss_feed() -> str:
    """Generate Apple Podcasts compatible RSS feed."""
    media_files = scan_downloads()
    
    # Create RSS root with namespaces
    rss = Element("rss")
    rss.set("version", "2.0")
    rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    
    channel = SubElement(rss, "channel")
    
    # Required channel elements
    SubElement(channel, "title").text = PODCAST_TITLE
    SubElement(channel, "description").text = PODCAST_DESCRIPTION
    SubElement(channel, "language").text = PODCAST_LANGUAGE
    SubElement(channel, "link").text = METUBE_URL
    
    # Atom self-link (recommended)
    atom_link = SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", f"{BASE_URL}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    
    # iTunes specific elements
    SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}author").text = PODCAST_AUTHOR
    SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary").text = PODCAST_DESCRIPTION
    SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"
    
    # Owner info
    owner = SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}owner")
    SubElement(owner, "{http://www.itunes.com/dtds/podcast-1.0.dtd}name").text = PODCAST_AUTHOR
    SubElement(owner, "{http://www.itunes.com/dtds/podcast-1.0.dtd}email").text = PODCAST_EMAIL
    
    # Category
    category = SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}category")
    category.set("text", PODCAST_CATEGORY)
    
    # Podcast image
    if PODCAST_IMAGE:
        image_url = PODCAST_IMAGE
    else:
        image_url = f"{BASE_URL}/cover.jpg"
    
    image = SubElement(channel, "image")
    SubElement(image, "url").text = image_url
    SubElement(image, "title").text = PODCAST_TITLE
    SubElement(image, "link").text = METUBE_URL
    
    itunes_image = SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
    itunes_image.set("href", image_url)
    
    # Last build date
    if media_files:
        last_build = media_files[0]["mtime"]
    else:
        last_build = datetime.now(timezone.utc)
    SubElement(channel, "lastBuildDate").text = last_build.strftime("%a, %d %b %Y %H:%M:%S %z")
    
    # Add items for each media file
    for media in media_files:
        item = SubElement(channel, "item")
        
        SubElement(item, "title").text = media["name"]
        SubElement(item, "description").text = f"Downloaded: {media['mtime'].strftime('%Y-%m-%d %H:%M')}"
        SubElement(item, "link").text = media["download_url"]
        SubElement(item, "guid").text = media["guid"]
        SubElement(item, "pubDate").text = media["mtime"].strftime("%a, %d %b %Y %H:%M:%S %z")
        
        # Enclosure (required for podcast) - points to MeTube's download URL
        enclosure = SubElement(item, "enclosure")
        enclosure.set("url", media["download_url"])
        enclosure.set("length", str(media["size"]))
        enclosure.set("type", media["mime_type"])
        
        # iTunes specific item elements
        if media["duration"]:
            SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration").text = media["duration_formatted"]
        
        SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}author").text = PODCAST_AUTHOR
        SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary").text = f"Downloaded: {media['mtime'].strftime('%Y-%m-%d %H:%M')}"
        SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "false"
        
        # Mark video content
        if media["is_video"]:
            SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType").text = "full"
    
    # Pretty print XML
    xml_str = tostring(rss, encoding="unicode")
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


class DownloadEventHandler(FileSystemEventHandler):
    """Handle file system events to invalidate cache."""
    
    def on_any_event(self, event):
        # Clear cache on any file system change
        file_cache.clear()


@app.route("/")
def index():
    """Simple index page."""
    media_files = scan_downloads()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{PODCAST_TITLE}</title>
    <style>
        :root {{
            --bg: #0a0a0f;
            --surface: #12121a;
            --accent: #ff6b35;
            --accent-dim: #cc5629;
            --text: #e8e6e3;
            --text-dim: #9ca3af;
            --border: #2a2a3a;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at 20% 0%, rgba(255, 107, 53, 0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 100%, rgba(255, 107, 53, 0.05) 0%, transparent 50%);
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 3rem 2rem;
        }}
        header {{
            text-align: center;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border);
        }}
        h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent) 0%, #ff9f6b 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
        }}
        .subtitle {{
            color: var(--text-dim);
            font-size: 0.9rem;
        }}
        .feed-link {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 1.5rem;
            padding: 0.75rem 1.5rem;
            background: var(--accent);
            color: var(--bg);
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .feed-link:hover {{
            background: var(--accent-dim);
            transform: translateY(-2px);
        }}
        .stats {{
            display: flex;
            gap: 2rem;
            justify-content: center;
            margin-top: 1.5rem;
            color: var(--text-dim);
            font-size: 0.85rem;
        }}
        .stat {{ display: flex; align-items: center; gap: 0.5rem; }}
        .episodes {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        .episode {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
            transition: all 0.2s;
        }}
        .episode:hover {{
            border-color: var(--accent);
            transform: translateX(4px);
        }}
        .episode-title {{
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: var(--text);
        }}
        .episode-meta {{
            display: flex;
            gap: 1.5rem;
            font-size: 0.8rem;
            color: var(--text-dim);
        }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.5rem;
            background: var(--accent);
            color: var(--bg);
            border-radius: 3px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .empty {{
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-dim);
        }}
        .empty-icon {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}
        a {{ color: var(--accent); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <div class="container">
        <header>
            <h1>📻 {PODCAST_TITLE}</h1>
            <p class="subtitle">{PODCAST_DESCRIPTION}</p>
            <a href="/feed.xml" class="feed-link">
                <span>🎙️</span> Subscribe to RSS Feed
            </a>
            <div class="stats">
                <span class="stat">📁 {len(media_files)} episodes</span>
                <span class="stat">🔗 <a href="{METUBE_URL}">{METUBE_URL}</a></span>
            </div>
        </header>
        
        <div class="episodes">
"""
    
    if not media_files:
        html += """
            <div class="empty">
                <div class="empty-icon">📭</div>
                <p>No media files found yet.</p>
                <p>Download something with MeTube!</p>
            </div>
"""
    else:
        for media in media_files:
            badge = "VIDEO" if media["is_video"] else "AUDIO"
            html += f"""
            <div class="episode">
                <div class="episode-title">
                    <span class="badge">{badge}</span>
                    <a href="{media['download_url']}">{media['name']}</a>
                </div>
                <div class="episode-meta">
                    <span>⏱️ {media['duration_formatted']}</span>
                    <span>📅 {media['mtime'].strftime('%Y-%m-%d %H:%M')}</span>
                    <span>💾 {media['size'] / (1024*1024):.1f} MB</span>
                </div>
            </div>
"""
    
    html += """
        </div>
    </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/feed.xml")
@app.route("/feed")
@app.route("/rss")
@app.route("/podcast.xml")
def feed():
    """Serve the RSS feed."""
    rss_content = generate_rss_feed()
    return Response(rss_content, mimetype="application/rss+xml")


@app.route("/cover.jpg")
def default_cover():
    """Serve a default cover image (simple SVG)."""
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="1400" height="1400" viewBox="0 0 1400 1400" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1a1a2e"/>
      <stop offset="100%" style="stop-color:#0a0a14"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#ff6b35"/>
      <stop offset="100%" style="stop-color:#ff9f6b"/>
    </linearGradient>
  </defs>
  <rect width="1400" height="1400" fill="url(#bg)"/>
  <circle cx="700" cy="650" r="300" fill="none" stroke="url(#accent)" stroke-width="40"/>
  <circle cx="700" cy="650" r="120" fill="url(#accent)"/>
  <rect x="600" y="1000" width="200" height="80" rx="10" fill="url(#accent)"/>
  <rect x="660" y="950" width="80" height="60" fill="url(#accent)"/>
  <text x="700" y="1200" font-family="sans-serif" font-size="60" font-weight="bold" 
        fill="white" text-anchor="middle">MeTube Podcast</text>
</svg>"""
    return Response(svg, mimetype="image/svg+xml")


@app.route("/rescan", methods=["GET", "POST"])
def rescan():
    """Clear cache and rescan downloads directory."""
    file_cache.clear()
    media_files = scan_downloads()
    return {
        "status": "ok",
        "message": "Rescan complete",
        "episodes": len(media_files)
    }


@app.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "episodes": len(scan_downloads())}


# For running directly (development)
if __name__ == "__main__":
    # Set up file watcher to invalidate cache on changes
    event_handler = DownloadEventHandler()
    observer = Observer()
    
    if DOWNLOADS_DIR.exists():
        observer.schedule(event_handler, str(DOWNLOADS_DIR), recursive=True)
        observer.start()
    
    print(f"🎙️ MeTube Podcast Feed")
    print(f"📁 Watching: {DOWNLOADS_DIR}")
    print(f"🔗 MeTube URL: {METUBE_URL}")
    print(f"🌐 Feed URL: {BASE_URL}")
    print(f"📻 RSS Feed: {BASE_URL}/feed.xml")
    print(f"🚀 Starting server on port {PORT}...")
    
    try:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
    finally:
        observer.stop()
        observer.join()

