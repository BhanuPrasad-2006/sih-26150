RECORDER VALIDATION KIT
=======================

What this is: a program that checks whether the SIH DVR/NVR Forensic Tool can recover deleted video from a REAL
recorder's hard disk, and writes a report card. Nothing is uploaded anywhere: it runs on your own computer and only
reads the disk-image files you give it.

You need: Python 3.11+, FFmpeg (on PATH), the disk-image file(s) from the recorder, and the video clip you exported
from the recorder BEFORE deleting it.

STEP 1  Install (once):   Windows: double-click install_kit.bat      Linux/macOS: ./install_kit.sh
STEP 2  Fill in validation_notes_template.json (recorder brand, model, what you did).
STEP 3  Run:
   Windows:      run_kit.bat --after deleted.dd --clip clip.mp4 --before original.dd --notes validation_notes_template.json --out result
   Linux/macOS:  ./run_kit.sh --after deleted.dd --clip clip.mp4 --before original.dd --notes validation_notes_template.json --out result
   (--before is optional but gives extra measurements)
STEP 4  Send back the folder named "result" (it holds validation_report.pdf, validation_report.md, results.json).
        Do NOT send the disk images.

How to record, delete and copy the disk, and what every result means: read GUIDE.md.
Exit codes: 0 finished (read the verdict), 2 a file was missing/wrong, 3 an image changed during the run (stop).
