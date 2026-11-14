#!/usr/bin/env python3
"""
mediaorg - organise movies, TV shows, music and videos into a clean library.

Safe by design:
  * Dry run by default. Nothing moves until you add --apply.
  * Never deletes and never overwrites. Duplicates and name clashes go to
    <library>/_Review/ for you to look at.
  * Every move is written to a log, and --undo puts everything back.

Free: Python 3.8+ standard library only. Optional extras:
  * mutagen (pip install mutagen) to read music tags.
  * A free TMDb API key for movie/TV posters and .nfo files.
  * MusicBrainz + Cover Art Archive for album covers (no key needed).

Run  python3 mediaorg.py --help  for usage.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VERSION = "1.0"
VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".webm", ".mpg", ".mpeg", ".flv", ".3gp"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".aiff", ".aif", ".alac"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"}
CAMERA_PREFIX = re.compile(r"^(VID|IMG|PXL|MOV|DSC|DJI|GOPR|GX|GH|MVI|WhatsApp Video)[ _-]?", re.I)
JUNK_WORDS = re.compile(r"\b(2160p|1080p|720p|480p|4k|uhd|hdr|hdr10|dv|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|web|hdtv|dvdrip|remux|x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|ddp?5\.1|5\.1|7\.1|proper|repack|extended|unrated|imax|multi|subs?)\b.*$", re.I)

DEFAULT_CONFIG = {
    "inbox": ["~/Downloads/Media"],
    "library": "~/Media",
    "folders": {"movies": "Movies", "shows": "Shows", "music": "Music", "home": "Home Videos", "videos": "Videos", "review": "_Review"},
    "copy_instead_of_move": False,
    "ignore_smaller_than_mb": 1,
    "tmdb_api_key": "",
    "language": "en-US",
    "musicbrainz_contact": "",
    "jellyfin_url": "",
    "jellyfin_api_key": "",
}


# ---------------------------------------------------------------- helpers
def log(msg=""):
    print(msg, flush=True)


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and Path(path).exists():
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    cfg["tmdb_api_key"] = os.environ.get("TMDB_API_KEY", cfg["tmdb_api_key"])
    cfg["jellyfin_api_key"] = os.environ.get("JELLYFIN_API_KEY", cfg["jellyfin_api_key"])
    if isinstance(cfg["inbox"], str):
        cfg["inbox"] = [cfg["inbox"]]
    cfg["inbox"] = [Path(os.path.expanduser(p)).resolve() for p in cfg["inbox"]]
    cfg["library"] = Path(os.path.expanduser(cfg["library"])).resolve()
    return cfg


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s or "Unknown"


def clean(s):
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)          # [group] tags
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -([")


def title_case(s):
    if s != s.lower():
        return s
    small = {"a", "an", "and", "the", "of", "in", "on", "at", "to", "for", "or"}
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(s.split()))


def file_hash(path, quick=False):
    h = hashlib.sha256()
    size = path.stat().st_size
    with open(path, "rb") as f:
        if quick and size > 4 * 1024 * 1024:
            h.update(f.read(1024 * 1024))
            f.seek(size - 1024 * 1024)
            h.update(f.read(1024 * 1024))
        else:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def same_content(a, b):
    try:
        return a.stat().st_size == b.stat().st_size and file_hash(a, True) == file_hash(b, True) and file_hash(a) == file_hash(b)
    except OSError:
        return False


# ---------------------------------------------------------------- music tags
def read_tags(path):
    try:
        import mutagen  # optional
    except ImportError:
        return {}
    try:
        m = mutagen.File(str(path), easy=True)
        if not m or not m.tags:
            return {}
        g = lambda k: (m.tags.get(k) or [""])[0]
        return {"artist": g("albumartist") or g("artist"), "album": g("album"), "title": g("title"),
                "track": g("tracknumber").split("/")[0], "date": g("date")[:4], "disc": g("discnumber").split("/")[0]}
    except Exception:
        return {}


# ---------------------------------------------------------------- classify
def classify(path, cfg, inbox_root):
    """Return (kind, relative destination path, info dict) or (kind, None, reason)."""
    F = cfg["folders"]
    ext = path.suffix.lower()
    stem = path.stem
    cs = clean(stem)

    if ext in AUDIO_EXT:
        t = read_tags(path)
        rel_parts = path.relative_to(inbox_root).parts[:-1]
        artist, album, title, track = t.get("artist"), t.get("album"), t.get("title"), t.get("track")
        if not title:
            m = re.match(r"^(\d{1,3})[\s.\-_]+(.*)$", cs)
            if m:
                track, rest = m.group(1), m.group(2)
            else:
                rest = cs
            if " - " in rest:
                a, rest = rest.split(" - ", 1)
                artist = artist or a
            title = rest
        if not album and len(rel_parts) >= 1:
            album = clean(rel_parts[-1])
        if not artist and len(rel_parts) >= 2:
            artist = clean(rel_parts[-2])
        if not artist or not album:
            return "music", Path(F["music"]) / "_Unsorted" / safe_name(path.name), {"why": "no artist/album tags"}
        year = t.get("date")
        album_dir = f"{safe_name(album)} ({year})" if year and year.isdigit() else safe_name(album)
        tn = f"{int(track):02d} " if track and track.isdigit() else ""
        if t.get("disc", "").isdigit() and int(t["disc"]) > 1:
            tn = f"{int(t['disc'])}-{tn}"
        return "music", Path(F["music"]) / safe_name(artist) / album_dir / f"{tn}{safe_name(title)}{ext}", \
            {"artist": artist, "album": album, "year": year}

    if ext not in VIDEO_EXT:
        return "other", None, "not a media file"

    if re.search(r"\bsample\b", stem, re.I) and path.stat().st_size < 150 * 1024 * 1024:
        return "skip", None, "looks like a release sample"

    # TV episode: S01E02, S01E02E03, 1x02
    m = re.search(r"^(.*?)[\s._\-]*[Ss](\d{1,2})[\s._]*[Ee](\d{1,3})(?:[\s._\-]*[Ee](\d{1,3}))?", stem) or \
        re.search(r"^(.*?)[\s._\-]+(\d{1,2})x(\d{2,3})\b", stem)
    if m:
        show = clean(m.group(1))
        if not show:  # name only in parent folder
            show = clean(path.parent.name)
            show = re.sub(r"(?i)\bseason\s*\d+\b|\bS\d{1,2}\b", "", show).strip(" -")
        year = None
        y = re.match(r"^(.*?)[\s(]*((?:19|20)\d{2})\)?$", show)
        if y and y.group(1):
            show, year = clean(y.group(1)), y.group(2)
        show = safe_name(title_case(JUNK_WORDS.sub("", show).strip()))
        name = f"{show} ({year})" if year else show
        s, e = int(m.group(2)), int(m.group(3))
        se = f"S{s:02d}E{e:02d}" + (f"-E{int(m.group(4)):02d}" if m.lastindex and m.lastindex >= 4 and m.group(4) else "")
        return "tv", Path(F["shows"]) / name / f"Season {s:02d}" / f"{name} {se}{ext}", {"show": show, "year": year}

    # Camera / phone clip with a date in the name -> home video
    if CAMERA_PREFIX.match(stem):
        d = re.search(r"((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])", stem)
        if d:
            date = f"{d.group(1)}-{d.group(2)}-{d.group(3)}"
        else:
            date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        return "home", Path(F["home"]) / date[:4] / f"{date} {safe_name(stem)}{ext}", {}

    # Movie: Title (Year) or Title.Year.junk
    cs2 = clean(stem)
    mv = re.match(r"^(.*?)\s*[(\[]((?:19|20)\d{2})[)\]]", cs2) or re.match(r"^(.*\S)\s+((?:19|20)\d{2})(?:\s|$)", cs2)
    if mv and mv.group(1):
        title = safe_name(title_case(JUNK_WORDS.sub("", mv.group(1)).strip()))
        year = mv.group(2)
        res = re.search(r"(?i)\b(2160p|1080p|720p|480p|4k)\b", stem)
        tag = f" - {'2160p' if res and res.group(1).lower() == '4k' else res.group(1).lower()}" if res else ""
        name = f"{title} ({year})"
        return "movie", Path(F["movies"]) / name / f"{name}{tag}{ext}", {"title": title, "year": year}

    # Folder named like a movie, file named badly
    pm = re.match(r"^(.*?)\s*[(\[]?((?:19|20)\d{2})[)\]]?$", clean(path.parent.name))
    if pm and pm.group(1) and path.parent != inbox_root:
        title = safe_name(title_case(JUNK_WORDS.sub("", pm.group(1)).strip()))
        name = f"{title} ({pm.group(2)})"
        return "movie", Path(F["movies"]) / name / f"{name}{ext}", {"title": title, "year": pm.group(2)}

    return "video", Path(F["videos"]) / safe_name(path.name), {"why": "no year or episode number found"}


# ---------------------------------------------------------------- planning
def scan(cfg):
    min_bytes = cfg["ignore_smaller_than_mb"] * 1024 * 1024
    lib = cfg["library"]
    for root in cfg["inbox"]:
        if not root.exists():
            log(f"! Inbox folder not found: {root}")
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            if lib in p.parents and cfg["folders"]["review"] in p.parts:
                continue
            ext = p.suffix.lower()
            if ext in VIDEO_EXT and p.stat().st_size < min_bytes:
                continue
            if ext in VIDEO_EXT | AUDIO_EXT | SUB_EXT:
                yield root, p


def plan(cfg):
    moves, skipped, subs = [], [], []
    for root, p in scan(cfg):
        if p.suffix.lower() in SUB_EXT:
            subs.append((root, p))
            continue
        kind, dest, info = classify(p, cfg, root)
        if dest is None:
            skipped.append((p, info))
            continue
        dest = cfg["library"] / dest
        if dest.resolve() == p.resolve():
            continue
        moves.append({"src": p, "dst": dest, "kind": kind, "info": info})

    # Subtitles follow the video with the same base name, keeping language tags (Movie.en.srt)
    by_stem = {m["src"].with_suffix("").as_posix().lower(): m for m in moves if m["kind"] in ("movie", "tv", "home", "video")}
    for root, s in subs:
        base, lang, target = s.with_suffix(""), "", None
        for _ in range(3):  # Movie.srt, Movie.en.srt, Movie.en.forced.srt
            target = by_stem.get(base.as_posix().lower())
            sfx = base.suffix.lower()
            if target or not re.fullmatch(r"\.([a-z]{2,3}|forced|sdh|cc)", sfx):
                break
            lang, base = sfx + lang, base.with_suffix("")
        if target:
            moves.append({"src": s, "dst": target["dst"].with_suffix("").with_name(target["dst"].stem + lang.lower() + s.suffix.lower()), "kind": "subtitle", "info": {}})
        else:
            skipped.append((s, "subtitle without a matching video"))
    return moves, skipped


def resolve_conflicts(moves, cfg):
    """Never overwrite. Same content -> duplicate review; different content -> ' (2)' name."""
    review = cfg["library"] / cfg["folders"]["review"]
    # Identical files inside this batch: keep the best-identified one, send the rest to review
    rank = {"movie": 0, "tv": 0, "music": 0, "home": 1, "video": 2}
    media = [m for m in moves if m["kind"] in rank]
    for group in find_duplicates([m["src"] for m in media]):
        ms = sorted((m for m in media if m["src"] in group), key=lambda m: rank[m["kind"]])
        for m in ms[1:]:
            m["info"] = {"same_as": str(ms[0]["src"])}
            m["dst"], m["kind"] = review / "Duplicates" / m["src"].name, "duplicate"
    taken = set()
    for m in moves:
        dst = m["dst"]
        if dst.exists() and same_content(m["src"], dst):
            m["dst"], m["kind"] = review / "Duplicates" / m["src"].name, "duplicate"
            m["info"] = {"same_as": str(dst)}
            dst = m["dst"]
        n = 2
        base = dst
        while dst.exists() or str(dst).lower() in taken:
            dst = base.with_name(f"{base.stem} ({n}){base.suffix}")
            n += 1
        m["dst"] = dst
        taken.add(str(dst).lower())
    return moves


# ---------------------------------------------------------------- duplicates
def find_duplicates(paths):
    by_size = defaultdict(list)
    for p in paths:
        try:
            by_size[p.stat().st_size].append(p)
        except OSError:
            pass
    groups = []
    for size, ps in by_size.items():
        if len(ps) < 2 or size == 0:
            continue
        quick = defaultdict(list)
        for p in ps:
            quick[file_hash(p, True)].append(p)
        for qs in quick.values():
            if len(qs) < 2:
                continue
            full = defaultdict(list)
            for p in qs:
                full[file_hash(p)].append(p)
            groups += [sorted(g, key=lambda x: (x.stat().st_mtime, str(x))) for g in full.values() if len(g) > 1]
    return groups


def media_files(folder):
    exts = VIDEO_EXT | AUDIO_EXT
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts]


# ---------------------------------------------------------------- applying
def do_moves(moves, cfg, logfile):
    copy = cfg["copy_instead_of_move"]
    done = 0
    with open(logfile, "a", encoding="utf-8") as lf:
        for m in moves:
            src, dst = m["src"], m["dst"]
            if dst.exists():
                log(f"  ! skipped, destination appeared: {dst}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                if copy:
                    shutil.copy2(src, dst)
                else:
                    shutil.move(str(src), str(dst))
            except OSError as e:
                log(f"  ! could not {'copy' if copy else 'move'} {src}: {e}")
                continue
            lf.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "op": "copy" if copy else "move", "src": str(src), "dst": str(dst)}) + "\n")
            done += 1
    return done


def undo(logfile):
    lines = [json.loads(l) for l in Path(os.path.expanduser(logfile)).read_text(encoding="utf-8").splitlines() if l.strip()]
    restored = 0
    for e in reversed(lines):
        src, dst = Path(e["src"]), Path(e["dst"])
        if e["op"] == "copy":
            log(f"  copy left in place (nothing to undo safely): {dst}")
            continue
        if not dst.exists():
            log(f"  ! missing, can't restore: {dst}")
            continue
        if src.exists():
            log(f"  ! original location is occupied, left as is: {src}")
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        restored += 1
    log(f"Restored {restored} file(s). Empty folders created by mediaorg were left in place.")


# ---------------------------------------------------------------- metadata
def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": f"mediaorg/{VERSION}", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def http_save(url, dest, headers=None):
    if dest.exists():
        return False
    req = urllib.request.Request(url, headers={"User-Agent": f"mediaorg/{VERSION}", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    dest.write_bytes(data)
    return True


def xml_escape(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tmdb_metadata(cfg):
    key = cfg["tmdb_api_key"]
    if not key:
        log("Skipping movie/TV metadata: add a free TMDb API key (see README).")
        return
    lib, F = cfg["library"], cfg["folders"]
    jobs = [("movie", d, "movie.nfo") for d in (lib / F["movies"]).glob("*/") if d.is_dir()] + \
           [("tv", d, "tvshow.nfo") for d in (lib / F["shows"]).glob("*/") if d.is_dir()]
    for kind, folder, nfo in jobs:
        if (folder / "poster.jpg").exists() and (folder / nfo).exists():
            continue
        m = re.match(r"^(.*?)(?: \((\d{4})\))?(?: \[tmdbid-(\d+)\])?$", folder.name)
        title, year, tmdb_id = m.group(1), m.group(2), m.group(3)
        try:
            if tmdb_id:
                r = http_json(f"https://api.themoviedb.org/3/{kind}/{tmdb_id}?api_key={key}&language={cfg['language']}")
            else:
                q = {"api_key": key, "query": title, "language": cfg["language"]}
                if year:
                    q["year" if kind == "movie" else "first_air_date_year"] = year
                res = http_json(f"https://api.themoviedb.org/3/search/{kind}?" + urllib.parse.urlencode(q)).get("results") or []
                if not res:
                    log(f"  ? no TMDb match: {folder.name}")
                    continue
                r = res[0]
            name = r.get("title") or r.get("name")
            date = (r.get("release_date") or r.get("first_air_date") or "")[:4]
            tag = "movie" if kind == "movie" else "tvshow"
            if not (folder / nfo).exists():
                (folder / nfo).write_text(
                    f'<?xml version="1.0" encoding="utf-8"?>\n<{tag}>\n  <title>{xml_escape(name)}</title>\n  <year>{date}</year>\n'
                    f'  <plot>{xml_escape(r.get("overview"))}</plot>\n  <uniqueid type="tmdb" default="true">{r.get("id")}</uniqueid>\n</{tag}>\n', encoding="utf-8")
            if r.get("poster_path"):
                http_save(f"https://image.tmdb.org/t/p/original{r['poster_path']}", folder / "poster.jpg")
            if r.get("backdrop_path"):
                http_save(f"https://image.tmdb.org/t/p/original{r['backdrop_path']}", folder / "fanart.jpg")
            log(f"  ✓ {folder.name} → {name} ({date})")
            time.sleep(0.3)
        except Exception as e:
            log(f"  ! TMDb error for {folder.name}: {e}")


def music_covers(cfg):
    contact = cfg["musicbrainz_contact"] or "no-contact-given"
    ua = {"User-Agent": f"mediaorg/{VERSION} ( {contact} )"}
    music = cfg["library"] / cfg["folders"]["music"]
    for album_dir in sorted(music.glob("*/*/")):
        if not album_dir.is_dir() or album_dir.parent.name == "_Unsorted" or (album_dir / "cover.jpg").exists():
            continue
        artist = album_dir.parent.name
        album = re.sub(r" \(\d{4}\)$", "", album_dir.name)
        try:
            q = f'release:"{album}" AND artist:"{artist}"'
            res = http_json("https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode({"query": q, "fmt": "json", "limit": 1}), ua)
            rel = (res.get("releases") or [None])[0]
            time.sleep(1.1)  # MusicBrainz allows about 1 request per second
            if not rel or int(rel.get("score", 0)) < 90:
                log(f"  ? no confident MusicBrainz match: {artist} / {album}")
                continue
            try:
                http_save(f"https://coverartarchive.org/release/{rel['id']}/front-500", album_dir / "cover.jpg", ua)
                log(f"  ✓ cover: {artist} / {album}")
            except urllib.error.HTTPError as e:
                log(f"  ? no cover in Cover Art Archive ({e.code}): {artist} / {album}")
        except Exception as e:
            log(f"  ! MusicBrainz error for {artist} / {album}: {e}")


def jellyfin_refresh(cfg):
    url, key = cfg["jellyfin_url"].rstrip("/"), cfg["jellyfin_api_key"]
    if not url or not key:
        return
    try:
        req = urllib.request.Request(f"{url}/Library/Refresh", method="POST", data=b"",
                                     headers={"X-Emby-Token": key, "Authorization": f'MediaBrowser Token="{key}"'})
        urllib.request.urlopen(req, timeout=15)
        log("Asked Jellyfin to rescan the library.")
    except Exception as e:
        log(f"! Couldn't reach Jellyfin at {url}: {e}")


# ---------------------------------------------------------------- reports
LABEL = {"movie": "Movies", "tv": "TV episodes", "music": "Music", "home": "Home videos", "video": "Other videos", "subtitle": "Subtitles", "duplicate": "Duplicates → _Review"}


def print_plan(moves, skipped, cfg):
    lib = cfg["library"]
    counts = defaultdict(int)
    for m in moves:
        counts[m["kind"]] += 1
    log(f"\nLibrary: {lib}")
    log("Inbox:   " + ", ".join(str(p) for p in cfg["inbox"]))
    log("\nPlan: " + (", ".join(f"{counts[k]} {LABEL[k].lower()}" for k in LABEL if counts[k]) or "nothing to do"))
    for k in LABEL:
        group = [m for m in moves if m["kind"] == k]
        if not group:
            continue
        log(f"\n{LABEL[k]} ({len(group)})")
        for m in group[:200]:
            log(f"  {m['src'].name}\n    → {m['dst'].relative_to(lib)}")
        if len(group) > 200:
            log(f"  … and {len(group) - 200} more")
    if skipped:
        log(f"\nLeft alone ({len(skipped)})")
        for p, why in skipped[:50]:
            log(f"  {p.name}  ({why})")


# ---------------------------------------------------------------- main
def run_once(cfg, apply, with_meta):
    moves, skipped = plan(cfg)
    moves = resolve_conflicts(moves, cfg)
    print_plan(moves, skipped, cfg)
    if not apply:
        log("\nDry run: nothing was changed. Run again with --apply to do it.")
        return 0
    logdir = cfg["library"] / ".mediaorg"
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / f"moves-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    n = do_moves(moves, cfg, logfile) if moves else 0
    if n:
        log(f"\n{'Copied' if cfg['copy_instead_of_move'] else 'Moved'} {n} file(s). Undo with:\n  python3 mediaorg.py --undo \"{logfile}\"")
    if with_meta:
        log("\nFetching metadata and artwork…")
        tmdb_metadata(cfg)
        music_covers(cfg)
    if n or with_meta:
        jellyfin_refresh(cfg)
    return n


def main():
    ap = argparse.ArgumentParser(description="Organise movies, TV, music and videos. Dry run unless you add --apply. Never deletes.")
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.json")), help="settings file (default: config.json next to this script)")
    ap.add_argument("--apply", action="store_true", help="actually move/copy files (otherwise only show the plan)")
    ap.add_argument("--metadata", action="store_true", help="download posters, .nfo files and album covers after organising")
    ap.add_argument("--dupes", metavar="FOLDER", nargs="?", const="__library__", help="report duplicate files in a folder (default: the library)")
    ap.add_argument("--undo", metavar="LOGFILE", help="put files back using a moves log")
    ap.add_argument("--watch", metavar="MINUTES", type=float, help="keep running and organise new files every N minutes (implies --apply)")
    ap.add_argument("--init", action="store_true", help="write a starter config.json")
    a = ap.parse_args()

    if a.init:
        p = Path(a.config)
        if p.exists():
            log(f"{p} already exists; not overwriting it.")
        else:
            p.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
            log(f"Wrote {p}. Edit 'inbox' and 'library', then run: python3 mediaorg.py")
        return
    if a.undo:
        undo(a.undo)
        return
    cfg = load_config(a.config)

    if a.dupes:
        folder = cfg["library"] if a.dupes == "__library__" else Path(os.path.expanduser(a.dupes)).resolve()
        log(f"Checking {folder} for duplicates (size, then SHA-256)…")
        groups = find_duplicates(media_files(folder))
        wasted = sum(g[0].stat().st_size * (len(g) - 1) for g in groups)
        for g in groups:
            log(f"\n{len(g)} identical copies ({g[0].stat().st_size / 1e6:.1f} MB each):")
            for i, p in enumerate(g):
                log(f"  {'keep ' if i == 0 else 'extra'}  {p}")
        log(f"\n{len(groups)} duplicate group(s), {wasted / 1e9:.2f} GB in extra copies.")
        if groups and a.apply:
            review = cfg["library"] / cfg["folders"]["review"] / "Duplicates"
            moves = [{"src": p, "dst": review / p.name, "kind": "duplicate", "info": {}} for g in groups for p in g[1:]]
            moves = resolve_conflicts(moves, {**cfg, "copy_instead_of_move": False})
            logdir = cfg["library"] / ".mediaorg"; logdir.mkdir(parents=True, exist_ok=True)
            logfile = logdir / f"dupes-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
            n = do_moves(moves, {**cfg, "copy_instead_of_move": False}, logfile)
            log(f"Moved {n} extra copies to {review} for you to review. Nothing was deleted.\nUndo with: python3 mediaorg.py --undo \"{logfile}\"")
        elif groups:
            log("Nothing changed. Add --apply to move the extra copies into _Review/Duplicates (never deleted).")
        return

    if a.watch:
        log(f"Watching {', '.join(map(str, cfg['inbox']))} every {a.watch:g} min. Press Ctrl+C to stop.")
        try:
            while True:
                log(f"\n— {datetime.now():%Y-%m-%d %H:%M} —")
                run_once(cfg, True, a.metadata)
                time.sleep(a.watch * 60)
        except KeyboardInterrupt:
            log("\nStopped.")
        return

    run_once(cfg, a.apply, a.metadata)


if __name__ == "__main__":
    sys.exit(main())
