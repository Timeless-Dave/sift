"""Sift Lab API."""

import os

# Cap decoded image size before OpenCV is imported anywhere (decompression-bomb guard).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(50_000_000))

__version__ = "0.2.0"
