# mediaorg – automatic media library organiser

Sorts your movies, TV shows, music and videos into a clean library that Jellyfin, Kodi, Plex and Navidrome read perfectly. It renames files, finds duplicates, downloads posters and album covers from official sources, and can keep running to sort new downloads automatically.

**It never deletes anything.**
- It only shows a plan until you add `--apply`.
- It never overwrites a file. Name clashes get ` (2)`, and identical copies go to `_Review/Duplicates/` for you to decide.
- Every run writes a log, and `--undo` puts everything back where it was.

## What it does

| Detects | From | Goes to |
|---|---|---|
| Movie | `The.Matrix.1999.1080p.BluRay.x264.mkv` | `Movies/The Matrix (1999)/The Matrix (1999) - 1080p.mkv` |
| TV episode | `bluey 2018 s02e01 dance mode.mp4` | `Shows/Bluey (2018)/Season 02/Bluey (2018) S02E01.mp4` |
| Subtitle | `The.Matrix.1999…x264.en.srt` | follows its video: `… - 1080p.en.srt` |
| Music | tags, or `Artist/Album/01 - Song.mp3` | `Music/Artist/Album (Year)/01 Song.mp3` |
| Phone/camera clip | `VID_20230714_181205.mp4` | `Home Videos/2023/2023-07-14 VID_20230714_181205.mp4` |
| Anything else | `Grandma 80th birthday.mov` | `Videos/Grandma 80th birthday.mov` |
| Exact duplicate | same bytes as another file | `_Review/Duplicates/` |

Files it can't identify (music without tags, subtitles with no matching video) are listed and left where they are. Release "sample" files are skipped.

## Install (5 minutes, all free)

1. Install **Python 3** if you don't have it: python.org/downloads. On Windows, tick "Add python.exe to PATH". Mac and Linux usually have it already.
2. Optional, to read music tags (artist, album, track number):
   ```bash
   pip install mutagen
   ```
3. In this folder, copy `config.example.json` to `config.json` (or run `python3 mediaorg.py --init` to create a fresh one).

## Set up

Open `config.json` in any text editor:

```json
{
  "inbox": ["~/Downloads/Media"],
  "library": "~/Media",
  "copy_instead_of_move": false,
  "tmdb_api_key": "",
  "musicbrainz_contact": "",
  "jellyfin_url": "",
  "jellyfin_api_key": ""
}
```

- **inbox**: one or more folders where new files land. You can list your existing messy folders here too.
- **library**: where the organised library lives. Point Jellyfin's libraries at its `Movies`, `Shows`, `Music` and `Home Videos` folders.
- **copy_instead_of_move**: set to `true` to leave the originals untouched and build the library as copies. This needs twice the disk space.
- On Windows, write paths like `"C:/Users/You/Downloads/Media"` with forward slashes.

## Use

Each command runs from the folder holding `mediaorg.py`.

**1. See the plan (changes nothing):**
```bash
python3 mediaorg.py
```

**2. Do it:**
```bash
python3 mediaorg.py --apply
```

**3. Changed your mind? Undo using the log path it printed:**
```bash
python3 mediaorg.py --undo "~/Media/.mediaorg/moves-20261114-203714.jsonl"
```

**Find duplicates already in your library (report only):**
```bash
python3 mediaorg.py --dupes
```

Add `--apply` to move the extra copies into `_Review/Duplicates/`. They are not deleted. Duplicates are matched by size and SHA-256 hash, so only byte-identical files count.

On Windows, type `python` instead of `python3`.

## Posters, plots and album covers (from official, authorised sources)

```bash
python3 mediaorg.py --apply --metadata
```

- **Movies and TV:** from **TMDb** (The Movie Database). Get a free API key at themoviedb.org → Settings → API (free for personal use; TMDb asks you to credit them). Put the key in `tmdb_api_key`. Each film and show folder gets `poster.jpg`, `fanart.jpg` and a `movie.nfo` or `tvshow.nfo` with title, year, plot and TMDb ID, which Jellyfin and Kodi read.
- **Music:** from **MusicBrainz** and the **Cover Art Archive**. No key needed. Put an email or website in `musicbrainz_contact`, because MusicBrainz asks apps to identify themselves. Each album folder gets `cover.jpg`. It waits 1 second between requests, as MusicBrainz requires.
- **Wrong match?** Add the TMDb ID to the folder name, for example `The Matrix (1999) [tmdbid-603]`, and run again. Existing images and .nfo files are never overwritten.

Jellyfin can also download metadata itself. Running `--metadata` keeps a local copy next to your files, so it survives reinstalls and works in other players too.

## Keep the library updated automatically

**Option A – leave it running.** This sorts new files every 15 minutes:
```bash
python3 mediaorg.py --watch 15 --metadata
```

**Option B – schedule it (recommended):**
- **Windows:** Task Scheduler → Create Basic Task → Daily, repeat every 1 hour. Action: start `python`, with arguments `C:\path\to\mediaorg.py --apply --metadata`.
- **Mac/Linux:** run `crontab -e` and add this line to run at minute 5 of every hour:
  ```
  5 * * * * /usr/bin/python3 /path/to/mediaorg.py --apply --metadata >> /path/to/mediaorg.log 2>&1
  ```

**Tell Jellyfin to rescan after each run.** In Jellyfin, go to Dashboard → API Keys → + and create a key. Then fill in `jellyfin_url` (for example `http://localhost:8096`) and `jellyfin_api_key`. Or turn on "real-time monitoring" in each Jellyfin library and skip this.

## Tips

- Run a dry run after every config change and read the plan.
- For music with bad tags, fix the tags first with **MusicBrainz Picard** (free). mediaorg then sorts it correctly.
- Wanted a file somewhere else? Move it by hand. mediaorg only touches the inbox folders, plus `_Review` when you run `--dupes --apply`.
