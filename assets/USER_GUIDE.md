# ZapCapture-NG User Guide

Welcome to ZapCapture-NG! This tool is designed to scan batches of video files and automatically extract lightning strikes as high-quality images and animated GIFs.

## Getting Started
1. **Input Directory**: Select the folder containing your raw video files (`.mp4`, `.mov`, etc.).
2. **Output Directory**: Select where you want the final extracted frames, GIFs, and the CSV summary report to be saved.

---

## 1. Detection Modes
ZapCapture provides three distinct computer vision algorithms to detect strikes:

* **Standard (Intensity Difference):** The fastest and most common method. It compares the overall brightness of the current frame against previous frames. Best for night-time lightning where strikes cause massive flashes of light.
* **Canny Edge Density:** Uses OpenCV's Canny edge detector to count the number of sharp edges in the sky. Excellent for daytime lightning where the sky might already be bright, but the sudden appearance of a jagged bolt introduces new hard edges.
* **Hybrid (Intensity + Edge Count):** The most accurate, but computationally heavier. It combines both brightness detection and edge detection.

---

## 2. Setting the Threshold
The **Threshold** is the mathematical trigger point. If the difference between two frames exceeds this number, the engine considers it a lightning strike.
1. Click **Start Preview** to run a live test on a video file.
2. Click **Calculate Suggested Threshold**. The system will monitor the live video for a few seconds and determine the baseline background noise level.
3. The Threshold will automatically update to a value safely above the baseline noise.

---

## 3. The Masking Tool
Often, videos contain moving elements on the ground (cars, swaying trees, blinking lights) that can trigger false positives. 
1. Click **Set Mask** and click-and-drag a rectangle over the lower portion of the preview video to cover the moving elements.
2. A red box will appear. The detection engine will now completely ignore anything happening inside this red box.
3. **CRITICAL:** Because you have changed the total number of pixels the engine is analyzing, you *must* click **Calculate Suggested Threshold** again after creating or clearing a mask!

---

## 4. Custom Watermarks
You can "burn" text into the bottom right corner of your exported images and GIFs to protect your copyright.
* **Text**: Type your desired watermark (e.g., `© 2026 StormChaser`).
* **Font**: ZapCapture-NG automatically discovers TrueType fonts (`.ttf` or `.otf`) located in the `assets/fonts/` folder. Select your preferred style.
* **Size Multiplier**: Because videos vary drastically in resolution (1080p vs 4K), setting a raw font size doesn't work. Instead, use the multiplier to scale the font up or down relative to the size of the video.
