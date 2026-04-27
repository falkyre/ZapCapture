__author__ = "Liam Plybon (blablabliam.github.io)"
__copyright__ = "Copyright 2022, Liam Plybon"
__credits__ = ["Saulius Lukse", "Drake Anthony (Styropyro)", "Stephen C Hummel"]
__license__ = "MIT"
__version__ = "2"
__maintainer__ = "Liam Plybon"
__email__ = "lplybon1@gmail.com"
__status__ = "Prototype"
__date__ = "6-16-2022"

import sys
#import time
import os
import tempfile
import shutil
# tkinter required for pyinstaller
import tkinter
from PIL import Image, ImageTk
import cv2
import imageio
from collections import deque
import numpy as np

# imports for gui interface
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QLineEdit,
    QProgressBar,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QScrollArea,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QTabWidget,
    QSplitter
)
from PySide6.QtGui import (
    QPalette,
    QColor,
    QIntValidator,
    QIcon,
    QPixmap,
    QImage,
    QMovie
)

#global constants
SCALE = 0.5
NOISE_CUTOFF = 5
BLUR_SIZE = 3
END_STRIKE_PERCENTAGE = .9
GIF_FRAMES_LIMIT = 100
# input, output, and threshold are manipulated by the directory select buttons
# this allows them to pass into the worker thread without slots and signals.
# as such they are used as global variables
# for clarity, all globals are redefined as global wherever used.
global input_folder
input_folder = 'No Folder Chosen'
global output_folder
output_folder = 'No Folder Chosen'
global threshold
threshold = '5000000'
# buttonstate determines output file name type.
global buttonState
buttonState = True
global buffer_frames
buffer_frames = '5'
global mask_rect
mask_rect = None


def count_diff(img1, img2, mode='standard'):
    # Finds a difference between a frame and the frame before it.
    small1 = cv2.resize(img1, (0, 0), fx=SCALE, fy=SCALE)
    small2 = cv2.resize(img2, (0, 0), fx=SCALE, fy=SCALE)
    
    global mask_rect
    if mask_rect is not None:
        x, y, w, h = mask_rect
        # Scale mask to match the resized frame
        sx, sy, sw, sh = int(x * SCALE), int(y * SCALE), int(w * SCALE), int(h * SCALE)
        h_img, w_img = small1.shape[:2]
        sx = max(0, min(sx, w_img))
        sy = max(0, min(sy, h_img))
        sw = max(0, min(sw, w_img - sx))
        sh = max(0, min(sh, h_img - sy))
        if sw > 0 and sh > 0:
            # Black out the ignored region so it doesn't trigger differences
            small1[sy:sy+sh, sx:sx+sw] = 0
            small2[sy:sy+sh, sx:sx+sw] = 0

    if mode == 'standard':
        diff = cv2.absdiff(small1, small2)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        frame_delta = cv2.threshold(diff_gray, NOISE_CUTOFF, 255, cv2.THRESH_BINARY)[1]
        return cv2.countNonZero(frame_delta)

    elif mode == 'canny':
        # Option 1: Canny Edge Density
        # Convert to gray for edge detection
        gray1 = cv2.cvtColor(small1, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(small2, cv2.COLOR_RGB2GRAY)
        
        # Apply Canny to both frames
        edges1 = cv2.Canny(gray1, 100, 200)
        edges2 = cv2.Canny(gray2, 100, 200)
        
        # Find the difference between edge maps
        edge_diff = cv2.absdiff(edges1, edges2)
        return cv2.countNonZero(edge_diff)

    elif mode == 'hybrid':
        # Option 3: Hybrid Intensity + Edge Count
        diff = cv2.absdiff(small1, small2)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
        
        # 1. Find high intensity areas (the "candidate" pixels)
        _, mask = cv2.threshold(diff_gray, NOISE_CUTOFF, 255, cv2.THRESH_BINARY)
        
        # 2. Find edges in the original frames
        gray1 = cv2.cvtColor(small1, cv2.COLOR_RGB2GRAY)
        gray2 = cv2.cvtColor(small2, cv2.COLOR_RGB2GRAY)
        edges1 = cv2.Canny(gray1, 100, 200)
        edges2 = cv2.Canny(gray2, 100, 200)
        edges_diff = cv2.absdiff(edges1, edges2)
        
        # 3. Intersect: Count edge changes only within the high-intensity mask
        hybrid_diff = cv2.bitwise_and(edges_diff, mask)
        return cv2.countNonZero(hybrid_diff)

    return 0


def error_popup(message):
    '''Might cause a crash, but since it is for errors I am less inclined to worry.'''
    print(message)
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setText("Error")
    msg.setInformativeText(str(message))
    msg.setWindowTitle("Lightning Analysis Error")
    # prevents crash after closing message box
    msg.setAttribute(Qt.WA_DeleteOnClose)
    msg.exec()

# Popup for info after analysis. Caused crashes when started from
# the analysis thread rather than the main thread.
# Might reintroduce one day, since it provides nice information.

# def info_popup(message):
#     msg = QMessageBox()
#     msg.setIcon(QMessageBox.Information)
#     msg.setText("Analysis Complete!")
#     msg.setInformativeText(str(message))
#     msg.setWindowTitle("Lightning Analysis Complete")
#     # prevents crash after closing message box
#     msg.setAttribute(Qt.WA_DeleteOnClose)
#     msg.exec_()

class HyperlinkLable(QLabel):
    def __init__(self, parent=None):
        super().__init__()
        #self.setStyleSheet('font-size: 35px')
        self.setOpenExternalLinks(True)
        self.setParent(parent)

class HoverImageLabel(QLabel):
    def __init__(self, static_pixmap, gif_path, parent=None):
        super().__init__(parent)
        self.static_pixmap = static_pixmap
        self.gif_path = gif_path
        
        self.setPixmap(self.static_pixmap)
        
        if os.path.exists(self.gif_path):
            self.movie = QMovie(self.gif_path)
            self.movie.setParent(self)
            self.movie.setScaledSize(self.static_pixmap.size())
        else:
            self.movie = None

    def enterEvent(self, event):
        if self.movie is not None:
            self.setMovie(self.movie)
            self.movie.jumpToFrame(0)
            self.movie.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.movie is not None:
            self.movie.stop()
            self.setPixmap(self.static_pixmap)
        super().leaveEvent(event)

class PreviewGallery(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.temp_dir = ""
        self.final_out_dir = ""
        self.selected_files = []
        
        self.layout = QVBoxLayout(self)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)
        
        self.btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.save_btn = QPushButton("Save Selected")
        self.save_btn.clicked.connect(self.save_selected)
        self.cancel_btn = QPushButton("Discard All")
        self.cancel_btn.clicked.connect(self.clear_gallery)
        
        self.btn_layout.addWidget(self.select_all_btn)
        self.btn_layout.addWidget(self.deselect_all_btn)
        self.btn_layout.addWidget(self.save_btn)
        self.btn_layout.addWidget(self.cancel_btn)
        self.layout.addLayout(self.btn_layout)
        self.checkboxes = []
        
    def load_images(self, temp_dir, final_out_dir):
        self.temp_dir = temp_dir
        self.final_out_dir = final_out_dir
        
        # Clear existing layout
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        frames_dir = os.path.join(self.temp_dir, 'frames')
        if not os.path.exists(frames_dir):
            return
            
        row = 0
        col = 0
        self.checkboxes = []
        for filename in sorted(os.listdir(frames_dir)):
            if filename.endswith(".png"):
                filepath = os.path.join(frames_dir, filename)
                gif_filename = filename.replace(".png", ".gif")
                gif_path = os.path.join(self.temp_dir, 'gifs', gif_filename)
                
                item_widget = QWidget()
                item_layout = QVBoxLayout(item_widget)
                item_layout.setAlignment(Qt.AlignCenter)
                
                pixmap = QPixmap(filepath)
                pixmap = pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl = HoverImageLabel(pixmap, gif_path)
                
                cb = QCheckBox(filename)
                cb.setChecked(True)
                
                self.checkboxes.append((cb, filepath))
                
                item_layout.addWidget(lbl)
                item_layout.addWidget(cb)
                
                self.grid_layout.addWidget(item_widget, row, col)
                
                col += 1
                if col > 3:
                    col = 0
                    row += 1

    def select_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(True)

    def deselect_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(False)

    def save_selected(self):
        out_frames_dir = os.path.join(self.final_out_dir, 'frames')
        out_gifs_dir = os.path.join(self.final_out_dir, 'gifs')
        if not os.path.exists(out_frames_dir):
            os.makedirs(out_frames_dir)
        if not os.path.exists(out_gifs_dir):
            os.makedirs(out_gifs_dir)
            
        for cb, filepath in self.checkboxes:
            if cb.isChecked():
                filename = os.path.basename(filepath)
                dest = os.path.join(out_frames_dir, filename)
                import shutil
                shutil.copy2(filepath, dest)
                
                gif_filename = filename.replace(".png", ".gif")
                gif_path = os.path.join(self.temp_dir, 'gifs', gif_filename)
                if os.path.exists(gif_path):
                    gif_dest = os.path.join(out_gifs_dir, gif_filename)
                    shutil.copy2(gif_path, gif_dest)
        
        for f in os.listdir(self.temp_dir):
            if f.endswith('.csv'):
                import shutil
                shutil.copy2(os.path.join(self.temp_dir, f), os.path.join(self.final_out_dir, f))

        self.clear_gallery()

    def clear_gallery(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.checkboxes = []
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                import shutil
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Error cleaning up temp dir: {e}")

class Worker(QObject):
    # worker thread for the analysis.
    finished = Signal()
    threadProgress = Signal(int)
    analysisComplete = Signal(str, str) # temp_dir, out_dir

    def __init__(self, mode='standard'):
        super().__init__()
        self.mode = mode

    def run(self):
        """Analyzes lightning. """
        print('Started Analysis!')
        global input_folder
        global output_folder
        global threshold
        global buttonState
        global buffer_frames
        
        in_folder = input_folder
        actual_out_folder = output_folder
        
        # Create temporary directory
        temp_folder = tempfile.mkdtemp(prefix="zapcapture_")
        
        out_folder = temp_folder
        
        threshold_integer = int(threshold)
        buffer_frames_integer = int(buffer_frames)
        self.threadProgress.emit(10)
        
        if not os.path.isdir(in_folder):
            error_popup('Input folder not valid. Select a valid folder.')
            self.threadProgress.emit(0)
            self.finished.emit()
            return
            
        if not os.path.isdir(actual_out_folder):
            error_popup('Output folder not valid. Select a valid folder.')
            self.threadProgress.emit(0)
            self.finished.emit()
            return
            
        impath = os.path.join(out_folder, 'frames/')
        gifpath = os.path.join(out_folder, 'gifs/')
        os.makedirs(impath, exist_ok=True)
        os.makedirs(gifpath, exist_ok=True)
        
        files = [f for f in os.listdir(in_folder) if not f.startswith('.')]
        filecount = len(files)
        if filecount == 0:
            self.threadProgress.emit(100)
            self.finished.emit()
            return
            
        per_file = 90 / filecount
        
        for index, filename in enumerate(files):
            print('Processing ' + filename)
            file_base = 10 + index * per_file
            self.threadProgress.emit(file_base)
            
            f_in = os.path.join(in_folder, filename)
            f_out = os.path.join(out_folder, filename)
            
            video = cv2.VideoCapture(f_in)
            if not video.isOpened():
                continue
                
            nframes = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = int(video.get(cv2.CAP_PROP_FPS))
            
            if fps == 0 or nframes <= 1:
                video.release()
                continue
                
            fff = open(f_out + ".csv", 'w')
            flag, frame0 = video.read()
            if not flag:
                fff.close()
                video.release()
                continue
                
            deadzone = 0
            gif_frames = []
            gif_png_names = []
            gif_name = ''
            file_strikes = 0
            frame_buffer = deque(maxlen=buffer_frames_integer) if buffer_frames_integer > 0 else deque()
            
            filename_clean = filename.replace('.', '_')
            
            for i in range(nframes - 1):
                file_cap = (i / nframes) * per_file
                self.threadProgress.emit(file_base + file_cap)
                
                flag, frame1 = video.read()
                if not flag: break
                
                diff1 = count_diff(frame0, frame1, mode=self.mode)
                
                if not buttonState and isinstance(fps, int) and fps > 0:
                    timestamp = str(round(i / fps, 2)).replace('.', '-')
                    imname = impath + str(filename_clean) + timestamp + '.png'
                    gifname = gifpath + str(filename_clean) + timestamp + '.gif'
                else:
                    imname = impath + str(filename_clean) + "_%06d.png" % i
                    gifname = gifpath + str(filename_clean) + "_%06d.gif" % i
                    
                if len(gif_frames) >= GIF_FRAMES_LIMIT:
                    deadzone = 0
                
                is_strike = diff1 > threshold_integer
                if is_strike:
                    file_strikes += 1
                    
                    if deadzone == 0 and file_strikes > 1:
                        if len(gif_frames) > 0:
                            gif_frames.pop(0)
                            if len(gif_png_names) > 0:
                                gif_png_names.pop(0)
                            rgb_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in gif_frames]
                            if len(rgb_frames) > 0:
                                try:
                                    imageio.mimsave(gif_name, rgb_frames, fps=10, loop=0)
                                    import shutil
                                    for png_path in gif_png_names:
                                        target_gif = os.path.join(gifpath, os.path.basename(png_path).replace('.png', '.gif'))
                                        if target_gif != gif_name and not os.path.exists(target_gif):
                                            shutil.copy2(gif_name, target_gif)
                                except Exception as e:
                                    print(f"Error saving GIF {gif_name}: {e}")
                            gif_frames = []
                            gif_png_names = []
                            
                    while len(frame_buffer) > 0:
                        buf_frame, buf_i, buf_imname = frame_buffer.popleft()
                        cv2.imwrite(buf_imname, buf_frame)
                        gif_frames.append(buf_frame)
                        gif_png_names.append(buf_imname)
                        
                    deadzone = buffer_frames_integer
                    gif_name = gifname
                    
                if deadzone > 0:
                    cv2.imwrite(imname, frame1)
                    gif_frames.append(frame1)
                    gif_png_names.append(imname)
                    deadzone -= 1
                else:
                    if buffer_frames_integer > 0:
                        frame_buffer.append((frame1, i, imname))
                        
                fff.write(f"{f_out}, {diff1}\n")
                frame0 = frame1
                
                if i == nframes - 2 and len(gif_frames) > 0:
                    gif_frames.pop(0)
                    if len(gif_png_names) > 0:
                        gif_png_names.pop(0)
                    rgb_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in gif_frames]
                    try:
                        imageio.mimsave(gif_name, rgb_frames, fps=10, loop=0)
                        import shutil
                        for png_path in gif_png_names:
                            target_gif = os.path.join(gifpath, os.path.basename(png_path).replace('.png', '.gif'))
                            if target_gif != gif_name and not os.path.exists(target_gif):
                                shutil.copy2(gif_name, target_gif)
                    except Exception as e:
                        print(f"Error saving GIF {gif_name}: {e}")
                    gif_frames = []
                    gif_png_names = []
                    deadzone = 0
                    
            fff.close()
            video.release()
            
        self.threadProgress.emit(100)
        print('analysis complete!')
        self.analysisComplete.emit(temp_folder, actual_out_folder)
        self.finished.emit()

class LivePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.video_label)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.cap = None
        self.frame0 = None
        self.threshold_val = 5000000
        self.detection_mode = 'standard'
        self.strike_display_frames = 0
        
    def start_preview(self, video_path, threshold_val, detection_mode):
        self.threshold_val = threshold_val
        self.detection_mode = detection_mode
        self.strike_display_frames = 0
        
        if self.cap:
            self.cap.release()
            
        self.cap = cv2.VideoCapture(video_path)
        ret, self.frame0 = self.cap.read()
        if not ret:
            print("Could not read the first video for preview.")
            self.cap.release()
            self.cap = None
            return
            
        self.timer.start(30) # ~30fps
        
    def stop_preview(self):
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_label.clear()
        
    def update_frame(self):
        if not self.cap:
            return
            
        ret, frame1 = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, self.frame0 = self.cap.read()
            if not ret:
                self.stop_preview()
                return
            return

        diff1 = count_diff(self.frame0, frame1, mode=self.detection_mode)
        is_strike = diff1 > self.threshold_val

        if is_strike:
            self.strike_display_frames = 15

        display_frame = frame1.copy()

        # Draw mask
        global mask_rect
        if mask_rect is not None:
            rx, ry, rw, rh = mask_rect
            overlay = display_frame.copy()
            cv2.rectangle(overlay, (rx, ry), (rx+rw, ry+rh), (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.3, display_frame, 0.7, 0, display_frame)
            cv2.rectangle(display_frame, (rx, ry), (rx+rw, ry+rh), (0, 0, 255), 2)
            cv2.putText(display_frame, "IGNORED (MASK)", (rx, ry - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        info_text = f"Diff: {diff1} | Thresh: {int(self.threshold_val)}"
        cv2.putText(display_frame, info_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        if self.strike_display_frames > 0:
            cv2.putText(display_frame, "STRIKE DETECTED!", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
            self.strike_display_frames -= 1

        self.frame0 = frame1
        
        # Convert to QPixmap
        h, w, ch = display_frame.shape
        bytes_per_line = ch * w
        display_frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        qt_img = QImage(display_frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img)
        
        # Scale
        lbl_size = self.video_label.size()
        pixmap = pixmap.scaled(lbl_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video_label.setPixmap(pixmap)


class Window(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi()

    def setupUi(self):
        self.setWindowTitle("ZapCapture")
        self.resize(1000, 700)
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        
        # Splitter for left and right panels
        main_layout = QHBoxLayout(self.centralWidget)
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)
        
        # Left Panel (Controls)
        self.controls_widget = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_widget)
        
        self.inputFileDirectoryButton = QPushButton("Select Input Directory", self)
        self.inputFileDirectoryButton.clicked.connect(self.pick_new_input)
        self.inputFileDirectoryLabel = QLabel(input_folder)
        self.inputFileDirectoryLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.outputFileDirectoryButton = QPushButton("Select Output Directory", self)
        self.outputFileDirectoryButton.clicked.connect(self.pick_new_output)
        self.outputFileDirectoryLabel = QLabel(output_folder)
        self.outputFileDirectoryLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        
        self.setMaskButton = QPushButton("Select Area to Ignore (Mask)", self)
        self.setMaskButton.clicked.connect(self.define_mask)
        self.setMaskButton.setToolTip("Draw a box over an area of the video to ignore during analysis (e.g., ground or moving trees).")
        
        self.clearMaskButton = QPushButton("Clear Mask", self)
        self.clearMaskButton.clicked.connect(self.clear_mask)
        self.clearMaskButton.setToolTip("Clear the currently selected mask.")
        
        self.outputFilenameLabel = QLabel('Output File Name (❓)')
        self.outputFilenameLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.outputFilenameLabel.setToolTip(
            'Output File Name determines the standard used to give a file name. Frame number will output files as an integer, while timestamp will output files as a timestamp.')
        self.outputFrameNumButton = QRadioButton("Frame Number")
        self.outputFrameNumButton.setChecked(True)
        self.outputFrameNumButton.toggled.connect(lambda: self.btnstate(self.outputFrameNumButton))
        self.outputTimestampButton = QRadioButton("Timestamp")
        self.outputTimestampButton.setChecked(False)
        self.outputTimestampButton.toggled.connect(
            lambda: self.btnstate(self.outputTimestampButton))
        
        self.detectionModeLabel = QLabel("Detection Mode", self)
        self.detectionModeLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.detectionModeLabel.setToolTip("Select the algorithm used to detect lightning strikes.")
        self.detectionModeCombo = QComboBox(self)
        self.detectionModeCombo.addItem("Standard (Intensity Difference)", "standard")
        self.detectionModeCombo.addItem("Canny Edge Density", "canny")
        self.detectionModeCombo.addItem("Hybrid (Intensity + Edge Count)", "hybrid")
        
        self.calcThresholdButton = QPushButton("Calculate Suggested Threshold", self)
        self.calcThresholdButton.clicked.connect(self.calculate_suggested_threshold)
        self.calcThresholdButton.setToolTip("Skims the first video to automatically calculate and fill in a suggested threshold.")
        
        self.thresholdLabel = QLabel("Threshold (❓)", self)
        self.thresholdLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.thresholdLabel.setToolTip('Threshold determines the sensitivity of the computer vision algorithm...')
        self.thresholdEntry = QLineEdit(threshold)
        self.onlyInt = QIntValidator()
        self.thresholdEntry.setValidator(self.onlyInt)
        
        self.bufferFramesLabel = QLabel("Buffer Frames Before & After (❓)", self)
        self.bufferFramesLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.bufferFramesLabel.setToolTip("Number of frames to save immediately before and after the detected strike.")
        self.bufferFramesEntry = QLineEdit(buffer_frames)
        self.bufferFramesEntry.setValidator(self.onlyInt)
        
        self.previewButton = QPushButton('Start Live Preview', self)
        self.previewButton.setToolTip('Play a clip from the input folder to see if your threshold and mask settings are detecting strikes correctly.')
        self.previewButton.clicked.connect(self.toggle_preview)
        self.is_previewing = False
        
        self.analysisButton = QPushButton('Perform Analysis', self)
        self.analysisButton.clicked.connect(self.runLongTask)
        self.progressBar = QProgressBar(self)
        self.progressBar.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.progressBar.setValue(0)
        
        linkTemplate = '<a href={0}>{1}</a>'
        self.starvationButton = HyperlinkLable(self)
        starvationMessage = '''Like ZapCapture? Consider buying me a coffee!'''
        self.starvationButton.setText(linkTemplate.format('https://www.buymeacoffee.com/Blablabliam', starvationMessage))

        self.controls_layout.addWidget(self.inputFileDirectoryButton)
        self.controls_layout.addWidget(self.inputFileDirectoryLabel)
        self.controls_layout.addWidget(self.outputFileDirectoryButton)
        self.controls_layout.addWidget(self.outputFileDirectoryLabel)
        self.controls_layout.addWidget(self.setMaskButton)
        self.controls_layout.addWidget(self.clearMaskButton)
        self.controls_layout.addWidget(self.outputFilenameLabel)
        self.controls_layout.addWidget(self.outputFrameNumButton)
        self.controls_layout.addWidget(self.outputTimestampButton)
        self.controls_layout.addWidget(self.detectionModeLabel)
        self.controls_layout.addWidget(self.detectionModeCombo)
        self.controls_layout.addWidget(self.calcThresholdButton)
        self.controls_layout.addWidget(self.thresholdLabel)
        self.controls_layout.addWidget(self.thresholdEntry)
        self.controls_layout.addWidget(self.bufferFramesLabel)
        self.controls_layout.addWidget(self.bufferFramesEntry)
        self.controls_layout.addWidget(self.previewButton)
        self.controls_layout.addWidget(self.analysisButton)
        self.controls_layout.addWidget(self.progressBar)
        self.controls_layout.addWidget(self.starvationButton)
        self.controls_layout.addStretch()
        
        # Right Panel (Tabs)
        self.tabs = QTabWidget()
        self.live_preview_tab = LivePreviewWidget()
        self.gallery_tab = PreviewGallery()
        
        self.tabs.addTab(self.live_preview_tab, "Live Preview")
        self.tabs.addTab(self.gallery_tab, "Analysis Results")
        
        self.splitter.addWidget(self.controls_widget)
        self.splitter.addWidget(self.tabs)
        
        self.splitter.setSizes([300, 700])

    def pick_new_input(self):
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Input Folder")
        global input_folder
        input_folder = str(folder_path)
        self.inputFileDirectoryLabel.setText(str(folder_path))
        self.progressBar.setValue(0)
        self.analysisButton.setEnabled(True)

    def pick_new_output(self):
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Output Folder")
        global output_folder
        output_folder = str(folder_path)
        self.outputFileDirectoryLabel.setText(str(folder_path))
        self.progressBar.setValue(0)
        self.analysisButton.setEnabled(True)

    def btnstate(self, b):
        global buttonState
        if b.text() == "Frame Number":
            if b.isChecked() == True:
                buttonState = True
            else:
                buttonState = False
                
    def define_mask(self):
        global input_folder
        global mask_rect
        if input_folder == 'No Folder Chosen' or not os.path.isdir(input_folder):
            error_popup("Please select a valid input folder first.")
            return

        first_video = None
        for f in os.listdir(input_folder):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                first_video = os.path.join(input_folder, f)
                break

        if not first_video:
            error_popup("No video files found in the selected input folder.")
            return

        cap = cv2.VideoCapture(first_video)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            error_popup("Could not read the first video to define a mask.")
            return

        h, w = frame.shape[:2]
        max_height = 800
        if h > max_height:
            scale_display = max_height / h
            display_frame = cv2.resize(frame, (int(w * scale_display), max_height))
        else:
            scale_display = 1.0
            display_frame = frame

        window_name = "Draw Box over Area to IGNORE (Press Space to confirm)"
        roi = cv2.selectROI(window_name, display_frame, showCrosshair=True, fromCenter=False)
        cv2.destroyWindow(window_name)
        cv2.waitKey(1)

        if roi[2] > 0 and roi[3] > 0:
            real_x = int(roi[0] / scale_display)
            real_y = int(roi[1] / scale_display)
            real_w = int(roi[2] / scale_display)
            real_h = int(roi[3] / scale_display)
            
            mask_rect = (real_x, real_y, real_w, real_h)
            self.setMaskButton.setText("Area to Ignore: Custom Mask Applied")
        else:
            mask_rect = None
            self.setMaskButton.setText("Select Area to Ignore (Mask)")
            
    def clear_mask(self):
        global mask_rect
        mask_rect = None
        self.setMaskButton.setText("Select Area to Ignore (Mask)")
                
    def calculate_suggested_threshold(self):
        global input_folder
        if input_folder == 'No Folder Chosen' or not os.path.isdir(input_folder):
            error_popup("Please select a valid input folder first.")
            return

        first_video = None
        for f in os.listdir(input_folder):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                first_video = os.path.join(input_folder, f)
                break

        if not first_video:
            error_popup("No video files found in the selected input folder.")
            return

        self.calcThresholdButton.setText("Calculating... Please wait")
        self.calcThresholdButton.setEnabled(False)
        QApplication.processEvents()

        cap = cv2.VideoCapture(first_video)
        ret, frame0 = cap.read()
        if not ret:
            error_popup("Could not read the first video.")
            cap.release()
            self.calcThresholdButton.setText("Calculate Suggested Threshold")
            self.calcThresholdButton.setEnabled(True)
            return

        diffs = []
        for i in range(1500):
            ret, frame1 = cap.read()
            if not ret: break
            diffs.append(count_diff(frame0, frame1, mode=self.detectionModeCombo.currentData()))
            frame0 = frame1
            if i % 50 == 0: QApplication.processEvents()
        cap.release()

        if diffs:
            diffs_arr = np.array(diffs)
            suggested = int(np.percentile(diffs_arr, 99))
            suggested = max(suggested, 1000)
            self.thresholdEntry.setText(str(suggested))
        
        self.calcThresholdButton.setText("Calculate Suggested Threshold")
        self.calcThresholdButton.setEnabled(True)
            
    def toggle_preview(self):
        if self.is_previewing:
            self.live_preview_tab.stop_preview()
            self.previewButton.setText('Start Live Preview')
            self.is_previewing = False
        else:
            global input_folder
            if input_folder == 'No Folder Chosen' or not os.path.isdir(input_folder):
                error_popup("Please select a valid input folder first.")
                return

            first_video = None
            for f in os.listdir(input_folder):
                if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                    first_video = os.path.join(input_folder, f)
                    break

            if not first_video:
                error_popup("No video files found in the selected input folder.")
                return

            try:
                threshold_val = int(self.thresholdEntry.text())
            except ValueError:
                threshold_val = 5000000

            self.tabs.setCurrentWidget(self.live_preview_tab)
            self.live_preview_tab.start_preview(first_video, threshold_val, self.detectionModeCombo.currentData())
            self.previewButton.setText('Stop Live Preview')
            self.is_previewing = True

    def runLongTask(self):
        if self.is_previewing:
            self.toggle_preview()
            
        global threshold
        global buffer_frames
        threshold = self.thresholdEntry.text()
        buffer_frames = self.bufferFramesEntry.text()
        self.thread = QThread()
        mode = self.detectionModeCombo.currentData()
        self.worker = Worker(mode=mode)
        self.worker.moveToThread(self.thread)
        self.worker.threadProgress.connect(self.onCountChanged)
        self.thread.started.connect(self.worker.run)
        self.worker.analysisComplete.connect(self.show_preview_gallery)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

        self.analysisButton.setEnabled(False)
        self.thread.finished.connect(self.enableAnalysisButton)

    def show_preview_gallery(self, temp_dir, actual_out_dir):
        self.gallery_tab.load_images(temp_dir, actual_out_dir)
        self.tabs.setCurrentWidget(self.gallery_tab)

    def onCountChanged(self, value):
        self.progressBar.setValue(value)

    def enableAnalysisButton(self):
        self.analysisButton.setEnabled(True)


app = QApplication(sys.argv)
app.setStyle("Fusion")
palette = QPalette()
palette.setColor(QPalette.Window, QColor(53, 53, 53))
palette.setColor(QPalette.WindowText, Qt.white)
palette.setColor(QPalette.Base, QColor(25, 25, 25))
palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
palette.setColor(QPalette.ToolTipBase, Qt.black)
palette.setColor(QPalette.ToolTipText, Qt.white)
palette.setColor(QPalette.Text, Qt.white)
palette.setColor(QPalette.Button, QColor(53, 53, 53))
palette.setColor(QPalette.ButtonText, Qt.white)
palette.setColor(QPalette.BrightText, Qt.red)
palette.setColor(QPalette.Link, QColor(42, 130, 218))
palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
palette.setColor(QPalette.HighlightedText, Qt.black)
app.setPalette(palette)
win = Window()
win.show()
sys.exit(app.exec())
