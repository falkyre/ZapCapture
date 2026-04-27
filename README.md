# ZapCapture-NG

ZapCapture-NG is a Python-based computer vision tool designed to analyze video files and automatically detect, extract, and generate GIFs of lightning strikes. 

This project uses a Model-View-Controller (MVC) architecture to run the exact same core detection engine across two entirely different interfaces: a native **Desktop App** (PySide6) and a headless **Web App** (NiceGUI) optimized for Docker deployments.

This project was built upon the orginal ZapCapture code base and significantly improved. The original codebase can be found here: https://github.com/blablabliam/ZapCapture

## Features
* **Multi-Algorithm Detection:** Choose between Standard (intensity difference), Canny Edge Density, and Hybrid (Intensity plus Edge Count) algorithms)
* **Live Video Preview:** Test your threshold and mask settings in real-time before processing large batches of video.
* **Interactive Masking:** Draw a rectangle directly on the live preview to ignore moving trees, cars, or ground elements.  This is typically used to mask out the bottom portions of a landscape.
* **Custom Watermarking:** Burn custom text with a drop shadow into your final images and GIFs.
* **Automated GIF Generation:** Automatically buffers frames before and after a strike to generate a seamless animated GIF.

## Project Structure
```text
zapcapture/
├── pyproject.toml    # Dependency & environment management via `uv`
├── core.py           # The UI-agnostic computer vision engine
├── gui_desktop.py    # Native PySide6 interface
├── gui_web.py        # NiceGUI web interface
└── Dockerfile        # Container definition for the web interface