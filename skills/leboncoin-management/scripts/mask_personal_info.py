#!/usr/bin/env python3
"""Natural masking of personal info in photos using OpenCV seamless clone.

Handles login screens, avatars, usernames, serial numbers with textured backgrounds.
Usage:
  python3 mask_personal_info.py <src.jpg> <x0,y0,x1,y1> <dx,dy> <out.jpg>

Args:
  src.jpg:      Input image file
  x0,y0,x1,y1:  Bounding box of the region to mask (pixels)
  dx,dy:        Offset to clone source (in pixels, relative to top-left of box)
  out.jpg:      Output file

Example (macOS login screen — clone sky over the avatar):
  python3 mask_personal_info.py screen.jpg 588,596,694,674 -118,0 screen_masked.jpg

Will create a 2x zoomed preview in the same directory as a '_preview.jpg' for QA.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

if len(sys.argv) < 5:
    print(__doc__)
    sys.exit(1)

src_file = Path(sys.argv[1])
box_str = sys.argv[2]
off_str = sys.argv[3]
out_file = Path(sys.argv[4])

x0, y0, x1, y1 = map(int, box_str.split(','))
dx, dy = map(int, off_str.split(','))

img = cv2.imread(str(src_file))
if img is None:
    print(f"Error: could not read {src_file}")
    sys.exit(1)

w, h = x1 - x0, y1 - y0

# Clone source: extract the background region offset from the box
src = img[y0 + dy : y1 + dy, x0 + dx : x1 + dx].copy()

# Mask: ellipse for smooth edges (not rectangular)
mask = np.zeros((h, w), np.uint8)
cy, cx = h // 2, w // 2
rx, ry = w // 2 - 2, h // 2 - 2
cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)

# Seamless clone into the target region
center = (x0 + cx, y0 + cy)
result = cv2.seamlessClone(src, img, mask, center, cv2.NORMAL_CLONE)

# Write output
cv2.imwrite(str(out_file), result, [cv2.IMWRITE_JPEG_QUALITY, 92])

# QA preview: 2x zoomed region around the masked area
zoom = result[max(0, y0 - 120) : y1 + 120, max(0, x0 - 200) : x1 + 200]
zoom_2x = cv2.resize(zoom, None, fx=2, fy=2)
prev_file = out_file.parent / f"{out_file.stem}_preview.jpg"
cv2.imwrite(str(prev_file), zoom_2x, [cv2.IMWRITE_JPEG_QUALITY, 92])

print(f"✓ {out_file.name}")
print(f"  Preview: {prev_file.name} (2x zoomed)")
