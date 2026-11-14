# Media Hub

A free, legal, personal media center in one place. Open `index.html` and pick a section from the menu.

| # | Section | What it does | File |
|---|---|---|---|
| 1 | **Launcher** | 45 free, legal streaming sources (movies, TV, music, podcasts, documentaries) plus links to your own servers | `apps/launcher.html` |
| 2 | **Jellyfin setup** | Step-by-step guide to your own movie and TV server, with a filename renamer and checklist | `apps/jellyfin-library.html` |
| 3 | **Music (Crate)** | Music player for your own files: playlists, favorites, shuffle, history, artists and albums, plus a Navidrome guide | `apps/music.html` |
| 4 | **Free TV & movies** | Official free platforms by country (Kosovo, Spain, UK, US, Germany, France, Italy) with sign-up and limits | `apps/free-tv.html` |
| 5 | **Media player** | Local video and audio player: subtitles (SRT/VTT), playlists, fullscreen, picture-in-picture, resume playback | `apps/player.html` |
| 6 | **Learn (Open Shelf)** | 44 free documentaries, lectures, courses and public-domain films, filterable, with favorites | `apps/learn.html` |
| 7 | **Auto-organiser** | Python script that sorts, renames and de-duplicates your media and downloads artwork, without ever deleting | `tools/mediaorg/` |

Everything is plain HTML, CSS and JavaScript with no build step and no dependencies. Your media files never leave your computer. Favorites, playlists, history and resume positions are stored in your browser only.

## Use it

**Online:** if GitHub Pages is turned on for this repository, open `https://<your-username>.github.io/media-hub/`.

**On your laptop:**
1. Download the repository (green **Code** button → **Download ZIP**) and unzip it, or clone it:
   ```bash
   git clone https://github.com/<your-username>/media-hub.git
   ```
2. Double-click `index.html`.

The sections open inside the hub. If your browser blocks a section when you open it this way, start a small local server in the folder instead (Python 3):

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080. To reach it from a TV or phone on the same Wi-Fi, use `http://<laptop-ip>:8080`.

## Turn on GitHub Pages (free hosting)

On GitHub, go to the repository's **Settings → Pages**. Under "Build and deployment", choose **Deploy from a branch**, select branch `main` and folder `/ (root)`, then **Save**. After a minute the site is live at `https://<your-username>.github.io/media-hub/`. Pages on a free account needs a public repository.

## The auto-organiser

See [`tools/mediaorg/README.md`](tools/mediaorg/README.md). In short:

```bash
cd tools/mediaorg
```

```bash
cp config.example.json config.json
```

Edit `inbox` and `library` in `config.json`, then preview the plan:

```bash
python3 mediaorg.py
```

When the plan looks right, apply it:

```bash
python3 mediaorg.py --apply
```

## Legal

Every source linked here is official and free, from public broadcasters, libraries, universities, the rights holders or the public domain. Use the players and organiser only with media you own or have the rights to play.
