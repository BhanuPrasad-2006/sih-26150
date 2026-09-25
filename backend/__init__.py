"""backend package"""
import os as _os

# OpenCV decodes exported / ground-truth video through its bundled FFmpeg. Allow only local files there too,
# so a crafted playlist inside a video cannot make it open URLs or other files (see backend/sandbox.py).
# Must be set before cv2 is imported anywhere.
_os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "protocol_whitelist;file")
