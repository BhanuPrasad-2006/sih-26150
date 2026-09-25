# Validation Kit

**Download page:** enable GitHub Pages for this repository (Settings → Pages → Deploy from a branch → `main` → `/docs`) and the kit is published at `https://bhanuprasad-2006.github.io/sih-26150/` with a download button, this guide in plain words, and the file's SHA-256. The package is rebuilt with `python tools/build_kit_package.py` (a test fails if the download is out of date with the code).

A single command that turns real recorder disk images into a finished validation report. It exists because the tool has only been tested on disk images we generated: anyone with a real DVR/NVR can now close that gap in about an hour, without knowing how the tool works inside.

```
python -m backend.validation_kit --after deleted.dd --clip clip.mp4 --before original.dd --notes notes.json --out result
```

## 1. What the person with the recorder does

You need: the recorder (any supported brand, or an unknown one: it still runs), its hard disk, a camera or any video source, a PC, a USB-SATA adapter or dock (a hardware write blocker is better), a second drive with enough space for the images, and a phone or clock to hold in front of the camera.

| Step | Action |
|---|---|
| 1 | Set the recorder's clock and note its time zone. Record a **5-minute** test clip with a clock or phone stopwatch visible. |
| 2 | **Export that same clip** with the recorder's own player or menu to a USB stick (this is the *ground truth*). Do not skip: it is the answer key. |
| 3 | *(Optional but recommended)* Power the recorder off, remove the disk, connect it through the write blocker or dock, and create a raw image **before deleting** (FTK Imager: File → Create Disk Image → Physical Drive → Raw (dd)). Call it `original.dd`. If Windows offers to format/initialise the disk, answer **Cancel**. |
| 4 | Put the disk back. **Delete the recording** through the recorder's menu (do not format, unless you want to test formatting as a separate run). **Power off immediately** so nothing overwrites the footage. |
| 5 | Remove the disk again and image it again the same way: `deleted.dd`. |
| 6 | Copy `notes.json` from [validation_notes_template.json](validation_notes_template.json), fill in the recorder details. |
| 7 | Run the command above (Python 3.11+, FFmpeg on `PATH`, `pip install -r requirements.lock.txt`). |

Large disks make large images. A 500 GB disk is a 500 GB file; use a small or fresh disk if you can. Use a dedicated test disk so private footage is not shared.

## 2. What the kit does

1. Fingerprints every input (SHA-256).
2. Scans `deleted.dd` with the same pipeline as the application: identify the brand, read the recorder's index, carve frames, reconstruct segments.
3. Exports every segment to MP4 and checks that it decodes.
4. Compares the recovered video with your clip: frames recovered, frames that are right, frames in the correct order.
5. If `original.dd` was given: measures how many of the original bytes came back and whether any came from the wrong place.
6. Re-hashes the inputs to prove the run did not change them.
7. Writes the report and a one-line verdict.

## 3. What you get

A folder containing `validation_report.pdf` and `.md` (verdict, test details, evidence hashes, what was detected, per-segment table, all-segments-vs-clip result, byte placement, what was **not** measured, and a row ready to paste into [VALIDATION_REPORT.md](VALIDATION_REPORT.md) §7), `results.json` (every number) and `exports/` (the recovered segments).

| Verdict | Meaning |
|---|---|
| `MATCHES` | Recovered frames equal the clip (recall, precision and order all ≥ 99 %) |
| `COMPLETE_WITH_EXTRAS` | Every clip frame came back plus other footage (expected when the disk holds other recordings) |
| `PARTIAL_MATCH` | Some of the clip came back; the report says how much |
| `NO_MATCH` | Video was recovered but none of it is the clip |
| `NO_DECODABLE_VIDEO` | Data was found but nothing decodes: the carving or container assumptions are probably wrong for this device |
| `NO_VIDEO` | Nothing recoverable was found: footage gone, or the layout is not handled |
| `NOT_MEASURED` | Video recovered but no clip was supplied, so no percentage is given |
| `EVIDENCE_CHANGED` | An input image's hash differs after the run: stop and investigate (exit code 3) |

## 4. Options

| Option | Purpose |
|---|---|
| `--before FILE` | Image taken before deleting; enables byte-placement measurement |
| `--log FILE` | Recording log JSON (see [accuracy_measurement.md](accuracy_measurement.md)); compares times and cameras |
| `--log-clock device\|utc`, `--offset MINUTES` | Clock convention of the log (UTC needs the recorder's offset; never guessed) |
| `--mode exact\|perceptual` | `exact` when the clip is the same stream only re-wrapped; `perceptual` when the vendor player re-encoded it (an upper bound) |
| `--out DIR` | Output folder (default `validation_run`) |

Exit codes: `0` run completed (read the verdict), `2` bad input, `3` an evidence image changed.

## 5. What the kit cannot do

- It measures **one** recovery on **one** device against the ground truth supplied. It never produces a general recovery rate.
- It cannot make the images: that needs a write blocker or imager, and it is the tester's responsibility to keep the recorder powered off after deleting.
- If the clip and the disk are from different recordings, the result says `NO_MATCH`; it cannot know that was a mistake.
- Anything not supplied is reported as *not measured*.

## 6. After the run

1. Send the whole output folder (not the evidence images unless you choose to).
2. Paste the row into the validation report, keeping the verdict and data source.
3. If the verdict is `NO_VIDEO`, `NO_DECODABLE_VIDEO` or `NO_MATCH`, that is a **finding**, not a failure of the test: the parser for that recorder needs correcting, and the trust level of its format in [format_verification.md](format_verification.md) stays below L3 until a run reaches `MATCHES` or a documented `PARTIAL_MATCH`.
