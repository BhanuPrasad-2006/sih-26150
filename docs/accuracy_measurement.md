# Measuring recovery accuracy against ground truth

The tool never states a recovery percentage on its own: it cannot know how much footage there should have been.
A percentage exists only when you supply **ground truth**. The **Accuracy Against Ground Truth** card on the
Recordings screen (and `POST /api/cases/{id}/accuracy`) computes it; results are saved with the case, written to the
hash-chained audit log, and included in the PDF report. Anything not supplied is reported as **not measured**.

## What you can supply

| Ground truth | Gives you | Needs |
|---|---|---|
| A known-good **video** (e.g. exported by the recorder's own player) | Frame recall / precision / order; byte-identical yes/no | The segment exported first |
| A **recording log** (JSON) | Time coverage and start/end offsets per logged recording, by camera | Log times in the recorder's clock, or UTC + the evidence's clock offset |
| The **original disk image from before the deletion** | Byte recall and placement precision by disk offset | Both images from the same disk geometry |

Log format: `{"recordings":[{"name":"front door","camera":1,"start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}]}`

## What each number means

- **Frames recovered (recall):** share of ground-truth frames found in the recovered video. Frames are matched by decoded
  pixels (`exact`) or by a tolerant 8x8 hash (`perceptual`, for when the vendor player re-encoded; an upper bound).
  Each truth frame can be matched once, so repeated frames in a static scene are not double-counted.
- **Frames that are right (precision):** share of recovered frames that are in the ground truth. Extra or wrong frames lower it.
- **In correct order:** share of matched frames whose order agrees with the ground truth (a longest-increasing-subsequence
  test). A wrong fragment order shows up here even when recall is 100%.
- **Byte-identical file:** the recovered export equals the ground-truth file byte for byte. A re-wrapped copy of the same
  video normally is not identical but can still have 100% frame recall.
- **Original bytes recovered / Bytes from the right place:** computed from disk offsets. Recall is the share of the original
  recordings' bytes that recovered segments cover; placement precision is the share of recovered bytes that lie inside an
  original recording's location. They check WHERE bytes came from, not what the video shows.
  - Dahua DHFS 4.1: the reference is the **original disk's own index** (independent of our carving).
  - Every other format: the reference is **our carver run on the original image**, so it measures what deletion cost, not
    whether the carver is right. The result states which one was used.

## Limits

- One segment, one disk, one deletion. Not a general recovery rate; the result says so.
- Frame checks need FFmpeg; the perceptual mode needs OpenCV.
- Time coverage uses device-clock times as recorded; a log in UTC needs the evidence's clock offset (never guessed).
- Nothing here validates a format on real hardware by itself: it measures a specific real test against known truth.

## Example finding

Running the placement check on a synthetic fragmented Dahua disk after wiping its index showed that only 21 of 40
frames were carved (byte recall 86.5 %). The cause was `DHAV_MIN_FRAME_BYTES = 100`, which rejected the
tiny P-frames of a quiet camera. At 40 all 40 frames are carved (byte recall 92.1 %, placement precision 100 %). This is the kind of loss only a ground-truth comparison reveals.
