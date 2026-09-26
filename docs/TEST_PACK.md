# Test pack

A folder of generated disk images, reference photos and ground-truth clips you can load into the tool and check against
**known answers**. It exists because no physical recorder disk is available: it lets you exercise every screen and see that
what the tool reports matches what was put in.

```bash
python tools/make_test_pack.py "C:/path/to/sih-test-pack"
```

Takes about two minutes: it renders the video, builds the disks, then runs the tool over them and writes `START_HERE.md`
(what to click and what you should see, with the numbers the tool really produced) and `expected_results.json`.

| Option | Meaning |
|---|---|
| `--photo-a me.jpg --photo-b friend.jpg` | Use your own photos (with consent) instead of the cartoon avatars. Both must contain one clear, front-facing face, and the two people must not look alike to the face model. |
| `--seconds N` | Length of each camera's video (default 12). |
| `--quick` | 4-second version (used by the automated tests). |
| `--no-verify` | Skip running the tool over the pack (no `START_HERE.md`). |

## What is in it

- **Two people** in one camera's video (they walk in, stand side by side, leave) and one of them alone in a second camera's video,
  the two cameras overlapping in time. The people are **cartoon avatars** drawn by `tools/testpack/personas.py`: not photographs,
  not real people.
- **Dahua-style disks**: intact; deleted (index wiped, video left); partly overwritten (gaps); and a deliberately hard "tiny
  clusters" image where the tool finds frames that are wrong (the accuracy check exposes it).
- **CP Plus-style** and **TP-Link-style** disks with the video left on them. CP Plus goes through the Dahua engine (an unverified
  assumption); TP-Link has no parser, so only generic carving applies: one segment, no times.
- **Ground truth**: the original camera clips and the reference photos, for the accuracy test and face search.

## What it can and cannot show

It shows that the tool's steps work and that its results match the input, including where the tool loses frames. It does **not**
show that a real recorder's disk decodes: every layout is built by us from the public specifications the tool implements, and the
face test is easy because the avatars render identically in every frame. Real validation needs a real disk: see
[VALIDATION_KIT.md](VALIDATION_KIT.md).
