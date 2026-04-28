import cv2
import os
import imageio
import shutil
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def get_available_fonts():
    fonts_dir = os.path.join(os.path.dirname(__file__), 'assets', 'fonts')
    if not os.path.exists(fonts_dir):
        return {'Arial.ttf': 'Arial'}
    fonts = {}
    for f in sorted(os.listdir(fonts_dir)):
        if f.lower().endswith(('.ttf', '.otf')):
            fonts[f] = os.path.splitext(f)[0]
    return fonts if fonts else {'Arial.ttf': 'Arial'}

class ZapCore:
    def __init__(self):
        # Configuration
        self.scale = 0.5
        self.noise_cutoff = 5
        self.threshold = 5000000
        self.detection_mode = 'standard'
        self.buffer_frames = 5
        self.output_format = 'frame'
        self.export_format = 'gif'        # 'gif', 'mp4', or 'both'
        self.crop_aspect_ratio = 'None'   # 'None', '1:1', '9:16'
        self.mask_rect = None
        self.watermark_text = ""
        self.watermark_font = "Arial.ttf"
        self.watermark_size = 1.0
        
        # State
        self.progress = 0.0
        self.is_analyzing = False
        self.skip_current = False
        self.cancel_analysis = False
        self.current_file = ""
        self.queue_status = {}  # filename -> 'pending'|'processing'|'done'|'skipped'
        self.png_to_mp4 = {}   # png_path -> mp4_path, for selective save
        self.cap = None
        self.frame0 = None
        self.strike_display_frames = 0

    def set_mask(self, x, y, w, h):
        self.mask_rect = (x, y, w, h)

    def clear_mask(self):
        self.mask_rect = None

    def _apply_crop(self, frame):
        """Center-crops the frame to the selected aspect ratio."""
        if self.crop_aspect_ratio == 'None':
            return frame
        h, w = frame.shape[:2]
        if self.crop_aspect_ratio == '1:1':
            target_w, target_h = min(h, w), min(h, w)
        elif self.crop_aspect_ratio == '9:16':
            # Pillarbox: crop width to match 9:16 portrait ratio
            target_h = h
            target_w = int(h * 9 / 16)
            if target_w > w:
                target_w = w
                target_h = int(w * 16 / 9)
        else:
            return frame
        x_start = (w - target_w) // 2
        y_start = (h - target_h) // 2
        return frame[y_start:y_start + target_h, x_start:x_start + target_w]

    def _apply_watermark(self, frame):
        """Burns a text watermark into the bottom right corner of the frame."""
        if not self.watermark_text:
            return frame
            
        font_filename = self.watermark_font
        font_path = os.path.join(os.path.dirname(__file__), 'assets', 'fonts', font_filename)
        
        h, w = frame.shape[:2]
        font_size = int(max(10, h / 20) * self.watermark_size)
        
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            
        img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        bbox = draw.textbbox((0, 0), self.watermark_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        text_x = w - text_w - 20
        text_y = h - text_h - 20
        
        shadow_offset = max(2, int(font_size / 20))
        draw.text((text_x + shadow_offset, text_y + shadow_offset), self.watermark_text, font=font, fill=(0, 0, 0))
        draw.text((text_x, text_y), self.watermark_text, font=font, fill=(255, 255, 255))
        
        return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    def generate_font_preview(self):
        """Generates a small image showing what the current watermark configuration looks like."""
        h, w = 100, 400
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[:] = (40, 40, 40)
        
        text = self.watermark_text if self.watermark_text else "Preview ©"
        
        font_filename = self.watermark_font
        font_path = os.path.join(os.path.dirname(__file__), 'assets', 'fonts', font_filename)
        
        font_size = int(30 * self.watermark_size)
        
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            
        img_pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        text_x = int((w - text_w) / 2)
        text_y = int((h - text_h) / 2)
        
        shadow_offset = max(1, int(font_size / 20))
        draw.text((text_x + shadow_offset, text_y + shadow_offset), text, font=font, fill=(0, 0, 0))
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))
        
        return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

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

    def get_preview_info(self):
        """Returns (current_frame, total_frames, fps) for scrubber UI."""
        if not self.cap:
            return 0, 0, 30
        pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        return pos, total, fps

    def seek_preview(self, frame_num):
        """Seek the preview capture to a specific frame and return an annotated frame."""
        if not self.cap:
            return None
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_num))
        ret, frame1 = self.cap.read()
        if not ret:
            return None
        self.frame0 = frame1
        self.strike_display_frames = 0  # clear strike banner on seek
        return self.get_annotated_preview_frame()

    def get_annotated_preview_frame(self):
        if not self.cap:
            return None

        ret, frame1 = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame1 = self.cap.read()
            if not ret:
                return None
            self.frame0 = frame1

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
        """Heavy background analysis loop with queue management."""
        self.is_analyzing = True
        self.progress = 0.0
        self.cancel_analysis = False
        self.skip_current = False
        self.png_to_mp4 = {}

        if not os.path.exists(input_dir) or not os.path.exists(output_dir):
            self.is_analyzing = False
            return "Input or Output directory does not exist."

        files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        if not files:
            self.is_analyzing = False
            return "No video files found."

        total_files = len(files)
        self.queue_status = {f: 'pending' for f in files}

        for file_idx, filename in enumerate(files):
            if self.cancel_analysis:
                break

            self.skip_current = False
            self.current_file = filename
            self.queue_status[filename] = 'processing'

            video_path = os.path.join(input_dir, filename)
            video = cv2.VideoCapture(video_path)
            fps = video.get(cv2.CAP_PROP_FPS)
            nframes = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            orig_w = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if nframes == 0:
                self.queue_status[filename] = 'skipped'
                continue

            ret, prev_frame = video.read()
            if not ret:
                self.queue_status[filename] = 'skipped'
                continue

            # Determine output frame dimensions after cropping
            sample_crop = self._apply_crop(prev_frame)
            crop_h, crop_w = sample_crop.shape[:2]

            frame_buffer = deque(maxlen=self.buffer_frames)
            gif_frames = []
            gif_png_names = []
            mp4_frames = []   # Collected separately for imageio MP4 export
            mp4name_to_save = None
            deadzone = 0
            file_strikes = 0
            filename_clean = os.path.splitext(filename)[0]

            csv_path = os.path.join(output_dir, f"{filename_clean}.csv")
            csv_file = open(csv_path, 'w')

            for i in range(1, nframes):
                if self.skip_current or self.cancel_analysis:
                    break

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
                    mp4name = os.path.join(output_dir, f"{filename_clean}_{timestamp}.mp4")
                else:
                    imname = os.path.join(output_dir, f"{filename_clean}_{i:06d}.png")
                    gifname = os.path.join(output_dir, f"{filename_clean}_{i:06d}.gif")
                    mp4name = os.path.join(output_dir, f"{filename_clean}_{i:06d}.mp4")

                cropped_frame = self._apply_crop(frame1)
                save_frame = self._apply_watermark(cropped_frame.copy())

                if is_strike:
                    file_strikes += 1

                if deadzone == 0 and file_strikes > 1:
                    # Finalize previous strike clip
                    if len(gif_frames) > 0:
                        if self.export_format in ('gif', 'both'):
                            rgb_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in gif_frames]
                            try:
                                imageio.mimsave(gif_name_to_save, rgb_frames, fps=10, loop=0)
                                for png_path in gif_png_names:
                                    expected_gif = png_path.replace('.png', '.gif')
                                    if expected_gif != gif_name_to_save:
                                        shutil.copy2(gif_name_to_save, expected_gif)
                            except:
                                pass
                        if self.export_format in ('mp4', 'both') and mp4frames_to_save and mp4name_to_save:
                            try:
                                rgb = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in mp4frames_to_save]
                                imageio.mimsave(mp4name_to_save, rgb, fps=10, macro_block_size=1)
                            except Exception as e:
                                print(f'[MP4] Mid-stream export error: {e}')
                    gif_frames = []
                    gif_png_names = []
                    mp4_frames = []
                    mp4name_to_save = None
                    file_strikes = 0

                if is_strike:
                    # Initialize MP4 reference FIRST so buffer frames are registered
                    if self.export_format in ('mp4', 'both'):
                        mp4name_to_save = mp4name
                        mp4frames_to_save = mp4_frames  # reference

                    while len(frame_buffer) > 0:
                        buf_frame, _, buf_imname = frame_buffer.popleft()
                        cv2.imwrite(buf_imname, buf_frame)
                        gif_frames.append(buf_frame)
                        gif_png_names.append(buf_imname)
                        if self.export_format in ('mp4', 'both'):
                            mp4_frames.append(buf_frame)
                            self.png_to_mp4[buf_imname] = mp4name_to_save
                    deadzone = self.buffer_frames
                    gif_name_to_save = gifname

                if deadzone > 0:
                    cv2.imwrite(imname, save_frame)
                    gif_frames.append(save_frame)
                    gif_png_names.append(imname)
                    if self.export_format in ('mp4', 'both'):
                        mp4_frames.append(save_frame)
                        self.png_to_mp4[imname] = mp4name_to_save
                    deadzone -= 1
                else:
                    if self.buffer_frames > 0:
                        frame_buffer.append((save_frame, i, imname))

                prev_frame = frame1

            # Finalize any remaining MP4 frames
            if self.export_format in ('mp4', 'both') and mp4_frames and mp4name_to_save:
                print(f'[MP4] Writing {len(mp4_frames)} frames to: {mp4name_to_save}')
                try:
                    rgb = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in mp4_frames]
                    imageio.mimsave(mp4name_to_save, rgb, fps=10, macro_block_size=1)
                    print(f'[MP4] Write complete: {mp4name_to_save}')
                except Exception as e:
                    print(f'[MP4] Export error: {e}')
            elif self.export_format in ('mp4', 'both'):
                print(f'[MP4] Skipped finalize — mp4_frames={len(mp4_frames)}, mp4name_to_save={mp4name_to_save}')

            csv_file.close()
            video.release()

            if self.skip_current:
                self.queue_status[filename] = 'skipped'
            else:
                self.queue_status[filename] = 'done'

        self.progress = 1.0
        self.is_analyzing = False
        self.current_file = ""
        return "Analysis Complete!"