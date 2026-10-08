"""Generate the website's data: themes.json, mp3 previews, raw WAVs and zip downloads.

site/data/themes.json   everything the pages need
site/audio/<hash>.mp3   one preview per unique clip (all themes share the pool)
site/wav/<hash>.wav     the real 16 kHz file (single-file downloads, mix builder)
site/dl/<id>.zip        EdgeTX pack: SOUNDS/en/...
site/dl/<id>-midi.zip   the MIDI sources
site/dl/all-themes.zip  every pack, one folder per theme
"""
import json
import shutil
import subprocess
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from soundgen.roles import EVENTS, GROUPS, max_len
from soundgen.themes import CATEGORIES, REGISTRY

README = """{name} - EdgeTX sound theme
{tagline}

{blurb}

INSTALL
1. Power off the radio and connect it to your computer in USB storage mode
   (or take the SD card out).
2. Copy the SOUNDS folder from this zip onto the root of the SD card and
   allow it to overwrite. Only the {n} files in this pack are replaced; spoken
   numbers, units and everything else keep working.
3. If your radio uses another language, rename SOUNDS/en to your language folder.

All files are 16 kHz, mono, 16-bit PCM WAV, as EdgeTX expects.

Made with Stickbeats: every sound is composed as MIDI and rendered by a
custom chip/FM synth (plus a General MIDI soundfont for some instruments).
Sounds: CC0 1.0 (public domain). Code: MIT.
https://rotordeck.com/stickbeats/
"""


def _zip(path, files):
    """files: list of (arcname, source Path or bytes)."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arc, src in files:
            zi = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, src if isinstance(src, (bytes, str)) else src.read_bytes())
    tmp.replace(path)


def _mp3(args):
    wav, mp3 = args
    if not mp3.exists():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                        "-ac", "1", "-ar", "32000", "-b:a", "64k", str(mp3)], check=True)


def build_site(root: Path, out: Path, ids):
    t0 = time.time()
    site = root / "site"
    for sub in ("data", "audio", "wav", "dl"):
        (site / sub).mkdir(parents=True, exist_ok=True)
    ids = sorted(ids, key=lambda i: ([c for c, _ in CATEGORIES].index(REGISTRY[i].category), REGISTRY[i].name))
    themes, jobs, all_files = [], {}, []
    for tid in ids:
        cls = REGISTRY[tid]
        d = out / tid
        index = json.loads((d / "index.json").read_text())
        clips = {}
        for file, info in index.items():
            h = info["hash"]
            clips[file] = h
            wav = site / "wav" / f"{h}.wav"
            if not wav.exists():
                shutil.copy2(d / "SOUNDS" / "en" / f"{file}.wav", wav)
            jobs[h] = (wav, site / "audio" / f"{h}.mp3")
        meta = cls().meta()
        readme = README.format(n=len(index), **meta)
        pack = [(f"SOUNDS/en/{f}.wav", d / "SOUNDS" / "en" / f"{f}.wav") for f in index]
        _zip(site / "dl" / f"{tid}.zip", pack + [("README.txt", readme)])
        _zip(site / "dl" / f"{tid}-midi.zip",
             [(f"midi/{f}.mid", d / "midi" / f"{f}.mid") for f in index] + [("README.txt", readme)])
        all_files += [(f"{tid}/{a}", s) for a, s in pack] + [(f"{tid}/README.txt", readme)]
        meta.update(
            clips=clips,
            durs={f: i["dur"] for f, i in index.items()},
            unique=len(set(clips.values())),
            zip=(site / "dl" / f"{tid}.zip").stat().st_size,
            midizip=(site / "dl" / f"{tid}-midi.zip").stat().st_size,
        )
        themes.append(meta)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(_mp3, jobs.values()))
    _zip(site / "dl" / "all-themes.zip", all_files)
    live = set(jobs)
    for sub, ext in (("audio", "mp3"), ("wav", "wav")):     # drop clips no theme uses any more
        for p in (site / sub).glob(f"*.{ext}"):
            if p.stem not in live:
                p.unlink()
    data = {
        "generated": time.strftime("%Y-%m-%d"),
        "events": [{"file": f, "role": r, "label": lbl, "recommendedDuration": max_len(r, a)} for f, r, a, lbl in EVENTS],
        "groups": [{"name": g, "files": fs} for g, fs in GROUPS],
        "categories": [{"id": c, "name": n} for c, n in CATEGORIES],
        "themes": themes,
        "allzip": (site / "dl" / "all-themes.zip").stat().st_size,
    }
    (site / "data" / "themes.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"site: {len(themes)} themes, {len(jobs)} unique clips, "
          f"all-themes.zip {data['allzip'] / 1e6:.1f} MB, {time.time() - t0:.1f}s")
