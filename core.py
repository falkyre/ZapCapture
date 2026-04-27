import cv2
import os
import imageio
import shutil
from collections import deque
import numpy as np

class ZapCore:
    def __init__(self):
        # Configuration
        self.scale = 0.5
        self.noise_cutoff = 5
        self.threshold = 5000000
        self.detection_mode = 'standard'
        self.buffer_frames = 5
        self.output_format = 'frame'
        self.mask_rect = None
        self.watermark_text = ""
        
        # State
        self.progress = 0.0
        self.is_analyzing = False
        self.cap = None
        self.frame0 = None
        self.strike_display_frames = 0

    def set_mask(self, x, y, w, h):
        self.mask_rect = (x, y, w, h)

    def clear_mask(self):
        self.mask_rect = None

    def _apply_watermark(self, frame):
        """Burns a text watermark into the bottom right corner of the frame."""
        if not self.watermark_text:
            return frame
            
        font = cv2.FONT_HERSHEY_SIMPLEX
        h, w = frame.shape[:2]
        font_scale = max(1.0, h / 500.0)
        thickness = max(2, int(font_scale * 2))
        
        text_size = cv2.getTextSize(self.watermark_text, font, font_scale, thickness)[0]
        text_x = int(w - text_size[0] - 20)
        text_y = int(h - 20)
        
        # Draw a black drop shadow first, then the white text over it
        cv2.putText(frame, self.watermark_text, (text_x + 2, text_y + 2), font, font_scale, (0, 0, 0), thickness + 1)
        cv2.putText(frame, self.watermark_text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness)
        
        return frame

    def _count_diff(self, img1, img2):
        small1 = cv2.resize(img1, (0, 0), fx=self.scale, fy=self.scale)
        small2 = cv2.resize(img2, (0, 0), fx=self.scale, fy=self.scale)
        
        if self.mask_rect is not None:
            x, y, w, h = self.mask_rect
            sx, sy = int(x * self.scale), int(y * self.scale)
            sw, sh = int(w * self.scale), int(h * self.scale)
            h_img, w_img = small1.shape[:2]
            
            sx, sy = max(0, min(sx, w_img)), max(0, min(sy, h_img))
            sw, sh = max(0, min(sw, w_img - sx)), max(0, min(sh, h_img - sy))
            
            if sw > 0 and sh > 0:
                small1[sy:sy+sh, sx:sx+sw] = 0
                small2[sy:sy+sh, sx:sx+sw] = 0

        if self.detection_mode == 'standard':
            diff = cv2.absdiff(small1, small2)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
            frame_delta = cv2.threshold(diff_gray, self.noise_cutoff, 255, cv2.THRESH_BINARY)[1]
            return cv2.countNonZero(frame_delta)
        elif self.detection_mode == 'canny':
            gray1 = cv2.cvtColor(small1, cv2.COLOR_RGB2GRAY)
            gray2 = cv2.cvtColor(small2, cv2.COLOR_RGB2GRAY)
            edges1 = cv2.Canny(gray1, 100, 200)
            edges2 = cv2.Canny(gray2, 100, 200)
            diff = cv2.absdiff(edges1, edges2)
            return cv2.countNonZero(diff)
        elif self.detection_mode == 'hybrid':
            diff = cv2.absdiff(small1, small2)
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
            
            _, mask = cv2.threshold(diff_gray, self.noise_cutoff, 255, cv2.THRESH_BINARY)
            
            gray1 = cv2.cvtColor(small1, cv2.COLOR_RGB2GRAY)
            gray2 = cv2.cvtColor(small2, cv2.COLOR_RGB2GRAY)
            edges1 = cv2.Canny(gray1, 100, 200)
            edges2 = cv2.Canny(gray2, 100, 200)
            edges_diff = cv2.absdiff(edges1, edges2)
            
            hybrid_diff = cv2.bitwise_and(edges_diff, mask)
            return cv2.countNonZero(hybrid_diff)
        return 0

    def start_preview(self, video_path):
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(video_path)
        ret, self.frame0 = self.cap.read()
        return ret

    def stop_preview(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_annotated_preview_frame(self):
        if not self.cap:
            return None

        ret, frame1 = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, self.frame0 = self.cap.read()
            if not ret:
                return None

        diff1 = self._count_diff(self.frame0, frame1)
        is_strike = diff1 > self.threshold

        if is_strike:
            self.strike_display_frames = 15

        display_frame = frame1.copy()

        if self.mask_rect is not None:
            rx, ry, rw, rh = self.mask_rect
            overlay = display_frame.copy()
            cv2.rectangle(overlay, (rx, ry), (rx+rw, ry+rh), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.3, display_frame, 0.7, 0, display_frame)
            cv2.rectangle(display_frame, (rx, ry), (rx+rw, ry+rh), (0, 0, 255), 2)
            cv2.putText(display_frame, "IGNORED (MASK)", (rx, ry - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        info_text = f"Diff: {diff1} | Thresh: {int(self.threshold)}"
        cv2.putText(display_frame, info_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        if self.strike_display_frames > 0:
            cv2.putText(display_frame, "STRIKE DETECTED!", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
            self.strike_display_frames -= 1

        self.frame0 = frame1
        display_frame = self._apply_watermark(display_frame)
        return display_frame

    def run_analysis(self, input_dir, output_dir):
        """Heavy background analysis loop."""
        self.is_analyzing = True
        self.progress = 0.0

        if not os.path.exists(input_dir) or not os.path.exists(output_dir):
            self.is_analyzing = False
            return "Input or Output directory does not exist."

        files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        if not files:
            self.is_analyzing = False
            return "No video files found."

        total_files = len(files)

        for file_idx, filename in enumerate(files):
            video_path = os.path.join(input_dir, filename)
            video = cv2.VideoCapture(video_path)
            fps = video.get(cv2.CAP_PROP_FPS)
            nframes = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if nframes == 0:
                continue

            ret, prev_frame = video.read()
            if not ret:
                continue

            frame_buffer = deque(maxlen=self.buffer_frames)
            gif_frames = []
            gif_png_names = []
            deadzone = 0
            file_strikes = 0
            filename_clean = os.path.splitext(filename)[0]
            
            csv_path = os.path.join(output_dir, f"{filename_clean}.csv")
            csv_file = open(csv_path, 'w')

            for i in range(1, nframes):
                ret, frame1 = video.read()
                if not ret:
                    break

                self.progress = ((file_idx / total_files) + ((i / nframes) / total_files))

                diff1 = self._count_diff(prev_frame, frame1)
                is_strike = diff1 > self.threshold
                csv_file.write(f"{video_path}, {diff1}\n")

                if self.output_format == 'timestamp' and fps > 0:
                    timestamp = str(round(i / fps, 2)).replace('.', '-')
                    imname = os.path.join(output_dir, f"{filename_clean}_{timestamp}.png")
                    gifname = os.path.join(output_dir, f"{filename_clean}_{timestamp}.gif")
                else:
                    imname = os.path.join(output_dir, f"{filename_clean}_{i:06d}.png")
                    gifname = os.path.join(output_dir, f"{filename_clean}_{i:06d}.gif")

                save_frame = self._apply_watermark(frame1.copy())

                if is_strike:
                    file_strikes += 1

                if deadzone == 0 and file_strikes > 1:
                    if len(gif_frames) > 0:
                        rgb_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in gif_frames]
                        try:
                            imageio.mimsave(gif_name_to_save, rgb_frames, fps=10, loop=0)
                            for png_path in gif_png_names:
                                expected_gif = png_path.replace('.png', '.gif')
                                if expected_gif != gif_name_to_save:
                                    shutil.copy2(gif_name_to_save, expected_gif)
                        except:
                            pass
                    gif_frames = []
                    gif_png_names = []
                    file_strikes = 0

                if is_strike:
                    while len(frame_buffer) > 0:
                        buf_frame, _, buf_imname = frame_buffer.popleft()
                        cv2.imwrite(buf_imname, buf_frame)
                        gif_frames.append(buf_frame)
                        gif_png_names.append(buf_imname)
                    deadzone = self.buffer_frames
                    gif_name_to_save = gifname

                if deadzone > 0:
                    cv2.imwrite(imname, save_frame)
                    gif_frames.append(save_frame)
                    gif_png_names.append(imname)
                    deadzone -= 1
                else:
                    if self.buffer_frames > 0:
                        frame_buffer.append((save_frame, i, imname))

                prev_frame = frame1
            csv_file.close()
            video.release()

        self.progress = 1.0
        self.is_analyzing = False
        return "Analysis Complete!"