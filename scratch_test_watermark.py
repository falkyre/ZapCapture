import cv2
import numpy as np
import core

engine = core.ZapCore()
engine.watermark_text = "Test Watermark"
frame = np.zeros((1000, 1920, 3), dtype=np.uint8)
frame.fill(128)

res = engine._apply_watermark(frame)
cv2.imwrite("test_watermark.png", res)
