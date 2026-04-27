import sys
import os
import cv2
import shutil
import tempfile
import numpy as np
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QMovie
from PySide6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                               QWidget, QPushButton, QLineEdit, QHBoxLayout, QFileDialog,
                               QTabWidget, QScrollArea, QGridLayout, QCheckBox, QComboBox, QMessageBox, QProgressBar, QRadioButton, QButtonGroup)
from core import ZapCore

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
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
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
                
        if not os.path.exists(self.temp_dir):
            return
            
        row = 0
        col = 0
        self.checkboxes = []
        
        for filename in sorted(os.listdir(self.temp_dir)):
            if filename.endswith(".png"):
                filepath = os.path.join(self.temp_dir, filename)
                gif_filename = filename.replace(".png", ".gif")
                gif_path = os.path.join(self.temp_dir, gif_filename)
                
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
        out_frames_dir = os.path.join(self.final_out_dir, "frames")
        out_gifs_dir = os.path.join(self.final_out_dir, "gifs")
        
        if not os.path.exists(out_frames_dir):
            os.makedirs(out_frames_dir)
        if not os.path.exists(out_gifs_dir):
            os.makedirs(out_gifs_dir)
            
        for cb, filepath in self.checkboxes:
            if cb.isChecked():
                filename = os.path.basename(filepath)
                dest = os.path.join(out_frames_dir, filename)
                shutil.copy2(filepath, dest)
                
                gif_filename = filename.replace(".png", ".gif")
                gif_path = os.path.join(self.temp_dir, gif_filename)
                if os.path.exists(gif_path):
                    gif_dest = os.path.join(out_gifs_dir, gif_filename)
                    shutil.copy2(gif_path, gif_dest)
        
        self.clear_gallery()

    def clear_gallery(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.checkboxes = []
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Error cleaning up temp dir: {e}")

class AnalysisThread(QThread):
    finished = Signal(str, str, str)
    
    def __init__(self, engine, in_dir, out_dir):
        super().__init__()
        self.engine = engine
        self.in_dir = in_dir
        self.out_dir = out_dir
        
    def run(self):
        temp_folder = tempfile.mkdtemp(prefix="zapcapture_")
        result = self.engine.run_analysis(self.in_dir, temp_folder)
        self.finished.emit(result, temp_folder, self.out_dir)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = ZapCore()
        self.setWindowTitle("ZapCapture-NG Desktop")
        self.resize(1000, 700)
        
        self.input_dir = "./input"
        self.output_dir = "./output"
        
        main_layout = QHBoxLayout()
        controls_layout = QVBoxLayout()
        
        self.btn_in = QPushButton("Select Input Dir")
        self.lbl_in_dir = QLabel(self.input_dir)
        self.btn_in.clicked.connect(self.select_input)
        self.btn_out = QPushButton("Select Output Dir")
        self.lbl_out_dir = QLabel(self.output_dir)
        self.btn_out.clicked.connect(self.select_output)
        
        self.outputFilenameLabel = QLabel("Output Filenames:")
        self.outputFrameNumButton = QRadioButton("Frame Number (e.g. VID_0123.png)")
        self.outputTimestampButton = QRadioButton("Timestamp (e.g. VID_0-12s.png)")
        if self.engine.output_format == 'timestamp':
            self.outputTimestampButton.setChecked(True)
        else:
            self.outputFrameNumButton.setChecked(True)
        self.btn_group_output = QButtonGroup(self)
        self.btn_group_output.addButton(self.outputFrameNumButton)
        self.btn_group_output.addButton(self.outputTimestampButton)
        self.outputFrameNumButton.toggled.connect(self.update_output_format)
        self.outputTimestampButton.toggled.connect(self.update_output_format)
        
        self.btn_set_mask = QPushButton("Select Area to Ignore (Mask)")
        self.btn_set_mask.clicked.connect(self.define_mask)
        self.btn_clear_mask = QPushButton("Clear Mask")
        self.btn_clear_mask.clicked.connect(self.clear_mask)
        
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Standard (Intensity Difference)", "standard")
        self.combo_mode.addItem("Canny Edge Density", "canny")
        self.combo_mode.addItem("Hybrid (Intensity + Edge Count)", "hybrid")
        self.combo_mode.currentIndexChanged.connect(self.update_mode)
        
        self.btn_calc_thresh = QPushButton("Calculate Suggested Threshold")
        self.btn_calc_thresh.clicked.connect(self.calculate_suggested_threshold)
        
        self.watermark_label = QLabel("Watermark:")
        self.watermark_label.setToolTip("Watermark text is burned into the frames during analysis. Must be set before running analysis.")
        self.watermark_input = QLineEdit()
        self.watermark_input.setPlaceholderText("Enter watermark text...")
        self.watermark_input.textChanged.connect(self.update_watermark)
        
        self.thresh_input = QLineEdit(str(self.engine.threshold))
        self.thresh_input.textChanged.connect(self.update_thresh)
        
        self.btn_preview = QPushButton("Start Preview")
        self.btn_preview.clicked.connect(self.toggle_preview)
        
        self.btn_analyze = QPushButton("Run Analysis")
        self.btn_analyze.clicked.connect(self.start_analysis)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                background-color: #111;
                text-align: center;
                color: #00ff00;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00ff00;
                width: 15px;
                margin: 1px;
            }
        """)
        
        controls_layout.addWidget(self.btn_in)
        controls_layout.addWidget(self.lbl_in_dir)
        controls_layout.addWidget(self.btn_out)
        controls_layout.addWidget(self.lbl_out_dir)
        controls_layout.addWidget(self.outputFilenameLabel)
        controls_layout.addWidget(self.outputFrameNumButton)
        controls_layout.addWidget(self.outputTimestampButton)
        controls_layout.addWidget(self.btn_set_mask)
        controls_layout.addWidget(self.btn_clear_mask)
        controls_layout.addWidget(QLabel("Detection Mode:"))
        controls_layout.addWidget(self.combo_mode)
        controls_layout.addWidget(self.btn_calc_thresh)
        controls_layout.addWidget(QLabel("Threshold:"))
        controls_layout.addWidget(self.thresh_input)
        controls_layout.addWidget(self.btn_preview)
        controls_layout.addWidget(self.watermark_label)
        controls_layout.addWidget(self.watermark_input)
        controls_layout.addWidget(self.btn_analyze)
        controls_layout.addWidget(self.progress_bar)
        controls_layout.addStretch()
        
        self.tabs = QTabWidget()
        
        # Live Preview Tab
        self.preview_widget = QWidget()
        preview_layout = QVBoxLayout(self.preview_widget)
        self.video_label = QLabel("Preview Area")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        preview_layout.addWidget(self.video_label)
        
        self.gallery_tab = PreviewGallery(self.engine)
        
        self.tabs.addTab(self.preview_widget, "Live Preview")
        self.tabs.addTab(self.gallery_tab, "Analysis Results")
        
        main_layout.addLayout(controls_layout, 1)
        main_layout.addWidget(self.tabs, 2)
        
        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_preview)
        self.is_previewing = False
        
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        
    def select_input(self):
        self.input_dir = QFileDialog.getExistingDirectory(self, "Select Input")
        self.lbl_in_dir.setText(self.input_dir)
        
    def select_output(self):
        self.output_dir = QFileDialog.getExistingDirectory(self, "Select Output")
        self.lbl_out_dir.setText(self.output_dir)

    def update_watermark(self, text):
        self.engine.watermark_text = text

    def update_output_format(self):
        if self.outputTimestampButton.isChecked():
            self.engine.output_format = 'timestamp'
        else:
            self.engine.output_format = 'frame'

    def update_thresh(self, text):
        if text.isdigit():
            self.engine.threshold = int(text)

    def update_mode(self):
        self.engine.detection_mode = self.combo_mode.currentData()

    def define_mask(self):
        if not os.path.isdir(self.input_dir):
            QMessageBox.warning(self, "Error", "Please select a valid input folder first.")
            return

        first_video = None
        for f in os.listdir(self.input_dir):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                first_video = os.path.join(self.input_dir, f)
                break

        if not first_video:
            QMessageBox.warning(self, "Error", "No video files found in the selected input folder.")
            return

        cap = cv2.VideoCapture(first_video)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            QMessageBox.warning(self, "Error", "Could not read the first video to define a mask.")
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
            
            self.engine.set_mask(real_x, real_y, real_w, real_h)
            self.btn_set_mask.setText("Area to Ignore: Custom Mask Applied")
        else:
            self.engine.clear_mask()
            self.btn_set_mask.setText("Select Area to Ignore (Mask)")

    def clear_mask(self):
        self.engine.clear_mask()
        self.btn_set_mask.setText("Select Area to Ignore (Mask)")

    def calculate_suggested_threshold(self):
        if not os.path.isdir(self.input_dir):
            QMessageBox.warning(self, "Error", "Please select a valid input folder first.")
            return

        first_video = None
        for f in os.listdir(self.input_dir):
            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
                first_video = os.path.join(self.input_dir, f)
                break

        if not first_video:
            QMessageBox.warning(self, "Error", "No video files found in the selected input folder.")
            return

        self.btn_calc_thresh.setText("Calculating... Please wait")
        self.btn_calc_thresh.setEnabled(False)
        QApplication.processEvents()

        cap = cv2.VideoCapture(first_video)
        ret, frame0 = cap.read()
        if not ret:
            QMessageBox.warning(self, "Error", "Could not read the first video.")
            cap.release()
            self.btn_calc_thresh.setText("Calculate Suggested Threshold")
            self.btn_calc_thresh.setEnabled(True)
            return

        diffs = []
        for i in range(1500):
            ret, frame1 = cap.read()
            if not ret: break
            diffs.append(self.engine._count_diff(frame0, frame1))
            frame0 = frame1
            if i % 50 == 0: QApplication.processEvents()
        cap.release()

        if diffs:
            diffs_arr = np.array(diffs)
            suggested = int(np.percentile(diffs_arr, 99))
            suggested = max(suggested, 1000)
            self.thresh_input.setText(str(suggested))
            self.engine.threshold = suggested
        
        self.btn_calc_thresh.setText("Calculate Suggested Threshold")
        self.btn_calc_thresh.setEnabled(True)

    def toggle_preview(self):
        if self.is_previewing:
            self.timer.stop()
            self.engine.stop_preview()
            self.btn_preview.setText("Start Preview")
            self.is_previewing = False
            self.video_label.clear()
        else:
            files = [f for f in os.listdir(self.input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv'))]
            if files:
                if self.engine.start_preview(os.path.join(self.input_dir, files[0])):
                    self.timer.start(30)
                    self.btn_preview.setText("Stop Preview")
                    self.is_previewing = True

    def update_preview(self):
        frame = self.engine.get_annotated_preview_frame()
        if frame is not None:
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qt_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_img).scaled(self.video_label.size(), Qt.KeepAspectRatio)
            self.video_label.setPixmap(pixmap)

    def update_progress(self):
        self.progress_bar.setValue(int(self.engine.progress * 100))

    def start_analysis(self):
        self.btn_analyze.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_timer.start(100)
        self.thread = AnalysisThread(self.engine, self.input_dir, self.output_dir)
        self.thread.finished.connect(self.analysis_done)
        self.thread.start()

    def analysis_done(self, result, temp_folder, actual_out_dir):
        self.progress_timer.stop()
        self.progress_bar.setValue(100)
        self.btn_analyze.setEnabled(True)
        print(result)
        
        if not os.path.exists(actual_out_dir):
            os.makedirs(actual_out_dir)
            
        for f in os.listdir(temp_folder):
            if f.endswith('.csv'):
                shutil.copy2(os.path.join(temp_folder, f), actual_out_dir)
                
        self.gallery_tab.load_images(temp_folder, actual_out_dir)
        self.tabs.setCurrentWidget(self.gallery_tab)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())