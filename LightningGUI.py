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
# tkinter required for pyinstaller
import tkinter
from PIL import Image, ImageTk
import cv2
import imageio
from collections import deque
import numpy as np

# imports for gui interface
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
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
    QCheckBox
)
from PySide6.QtGui import (
    QPalette,
    QColor,
    QIntValidator,
    QIcon
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


def count_diff(img1, img2):
    # Finds a difference between a frame and the frame before it.
    small1 = cv2.resize(img1, (0, 0), fx=SCALE, fy=SCALE)
    small2 = cv2.resize(img2, (0, 0), fx=SCALE, fy=SCALE)
    diff = cv2.absdiff(small1, small2)
    diff = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)
    
    global mask_rect
    if mask_rect is not None:
        x, y, w, h = mask_rect
        # Scale mask to match the resized frame
        sx, sy, sw, sh = int(x * SCALE), int(y * SCALE), int(w * SCALE), int(h * SCALE)
        h_img, w_img = diff.shape[:2]
        sx = max(0, min(sx, w_img))
        sy = max(0, min(sy, h_img))
        sw = max(0, min(sw, w_img - sx))
        sh = max(0, min(sh, h_img - sy))
        if sw > 0 and sh > 0:
            # Black out the ignored region so it doesn't trigger differences
            diff[sy:sy+sh, sx:sx+sw] = 0
            
    frame_delta1 = cv2.threshold(diff, NOISE_CUTOFF, 255, 3)[1]
    frame_delta1_color = cv2.cvtColor(frame_delta1, cv2.COLOR_GRAY2RGB)
    delta_count1 = cv2.countNonZero(frame_delta1)

    return delta_count1


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

class Worker(QObject):
    # worker thread for the analysis.
    finished = Signal()
    threadProgress = Signal(int)

    def run(self):
        """Analyzes lightning. """
        # Launches analysis of the videos in the in directory.
        print('Started Analysis!')
        global input_folder
        global output_folder
        global threshold
        global buttonState
        global buffer_frames
        in_folder = input_folder
        out_folder = output_folder
        threshold_integer = int(threshold)
        buffer_frames_integer = int(buffer_frames)
        # set framecount, strike counter to zero before looping all frames
        frame_count = 0
        strikes = 0
        # set progress bar to 10 so people know it is working
        self.threadProgress.emit(10)
        try:
            # error if the folder is invalid. Check folder for verification.
            path, dirs, files = next(os.walk(in_folder))
            filecount = len(files)
        except:
            error_popup('Input folder not valid. Select a valid folder.')
            self.threadProgress.emit(0)
            self.finished.emit()
            return
        try:
            # determine if the output folder is valid
            path, dirs, files = next(os.walk(out_folder))
            outfilecount = len(files)
        except:
            error_popup('Output folder not valid. Select a valid folder.')
            self.threadProgress.emit(0)
            self.finished.emit()
            return
        # create frame and gif directories after checking for existence
        impath = os.path.join(out_folder, 'frames/')
        gifpath = os.path.join(out_folder, 'gifs/')
        if not os.path.isdir(impath):
            os.mkdir(impath)
        if not os.path.isdir(gifpath):
            os.mkdir(gifpath)
        # get the current directory files count. If the outfolder is the same
        # as the infolder, this might have changed after creating the output
        # folders above.
        path, dirs, files = next(os.walk(in_folder))
        filecount = len(files)+len(dirs)
        # set per file progress bar quantity
        per_file = 90/(filecount)
        for index, filename in enumerate(os.listdir(in_folder)):
            # itterates over files in directory
            # f_in and f_out control input and destination targets
            print('Processing ' + filename)
            try:
                file_base = 10 + index*per_file
                completion = file_base
            except:
                self.threadProgress.emit(0)
                self.finished.emit()
                return
            self.threadProgress.emit(completion)
            f_in = os.path.join(in_folder, filename)
            f_out = os.path.join(out_folder, filename)
            try:
                video = cv2.VideoCapture(f_in)
            except:
                print('video lib error?')
                return
            # gets statistics on current video
            nframes = (int)(video.get(cv2.CAP_PROP_FRAME_COUNT))
            width = (int)(video.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = (int)(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = (int)(video.get(cv2.CAP_PROP_FPS))
            #print('FPS is '+ str(fps))
            # video diagnostics printout for user ease.
            # Might incorporate into visible log at later date
            frame_size = "Frame size: " + str(width) + str(height) + '\n'
            total_frames = "Total frames: " + str(nframes) + '\n'
            video_fps = "Fps: " + str(fps) + '\n'
            # print(frame_size)
            # print(total_frames)
            # print(video_fps)
            # checks if input is an actual video before opening csv.
            # opens csv for statistics- might want to disable for production.
            if fps == 0 or nframes == 1:
                print('zerofps or image!')
                continue
            fff = open(f_out+".csv", 'w')
            # reads the video out to give a frame and flag
            flag, frame0 = video.read()
            # Set video codec.
            print("setting codec mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            print("codec successful!")
            
            # savestate for using the deadzone.
            deadzone = 0
            # creates list for gif frames
            gif_frames = []
            gif_name = ''
            # strike counter independent for file. Helps with writing gifs.
            file_strikes = 0
            frame_buffer = deque(maxlen=buffer_frames_integer) if buffer_frames_integer > 0 else deque()
            # remove filename period, so that the output files don't confuse anything.
            filename = filename.replace('.', '_')
            for i in range(nframes-1):
                # loops through all of the frames, looking for strikes.
                # itterate progress bar
                file_cap = (i/(nframes+1))*per_file
                file_completion = file_base + file_cap
                self.threadProgress.emit(file_completion)
                # process the video
                flag, frame1 = video.read()
                if not flag: break
                
                diff1 = count_diff(frame0, frame1)
                # checks for file output name system
                # names files and gifs respectively.
                if not buttonState and type(fps) == int:
                    timestamp = str(round(int(i)/int(fps), 2)).replace('.', '-')
                    imname = impath + '/' + str(filename) + str(timestamp) + '.png'
                    gifname = gifpath + '/' + str(filename) + str(timestamp) + '.mp4'
                else:
                    imname = impath + str(filename) + "_%06d.png" % i
                    gifname = gifpath + str(filename) + "_%06d.mp4" % i
                if len(gif_frames) == GIF_FRAMES_LIMIT:
                    # end a gif if the clip gets large to prevent computer issues.
                    # massive gifs can cause lag and other problems.
                    deadzone = 0
                
                is_strike = diff1 > threshold_integer
                if is_strike:
                    # pass condition to save a frame and start a save state
                    strikes = strikes + 1
                    file_strikes = file_strikes + 1
                    gif_name = gifname
                    # write previous gif list to a gif if not the second frame
                    # and the deadzone is already zero (ie lightning has already
                    # struck and the gif buffer contains frames).
                    if deadzone == 0 and file_strikes > 1:
                        if len(gif_frames) > 0:
                            gif_start_frame = gif_frames[0]
                            gif_frames.pop(0)
                            print('setting writer')
                            out = cv2.VideoWriter(gif_name, fourcc, 4.0, (width,height))
                            for idx, frame in enumerate(gif_frames):
                                print('writing frame')
                                out.write(frame)
                                print('wrote frame')
                            out.release()
                            gif_frames = []
                    
                    # Process any buffered 'before' frames
                    while len(frame_buffer) > 0:
                        buf_frame, buf_i, buf_imname = frame_buffer.popleft()
                        cv2.imwrite(buf_imname, buf_frame)
                        gif_frames.append(buf_frame)
                        
                    deadzone = buffer_frames_integer
                    gif_name = gifname

                if deadzone > 0:
                    # save frame for passing the deadzone condition.
                    cv2.imwrite(imname, frame1)
                    # save frame to list for writing to gif
                    gif_frames.append(frame1)
                    deadzone -= 1
                else:
                    # Not currently saving a strike, buffer frames for next potential strike
                    if buffer_frames_integer > 0:
                        frame_buffer.append((frame1, i, imname))

                text = str(f_out)+', '+str(diff1)
                # write threshold data to csv
                fff.write(text + '\n')
                fff.flush()
                # pass frame forward
                frame0 = frame1
                if i == nframes-1 and len(gif_frames) > 0:
                    # saves a gif at the end of a file
                    gif_start_frame = gif_frames[0]
                    gif_frames.pop(0)
                    print('setting writer')
                    out = cv2.VideoWriter(gif_name, fourcc, 4.0, (width,height))
                    for idx, frame in enumerate(gif_frames):
                        print('writing frame')
                        out.write(frame)
                        print('wrote frame')
                    out.release()
                    gif_frames = []
                    deadzone = 0
        self.threadProgress.emit(100)
        fff.close()
        print('analysis complete!')
        # statistics for nerds!
        # video_strikes = 'Strikes: ' + str(strikes) + '\n'
        # elapsed_time = 'Process Time: ' + str(int(time.time() - start)) + ' s\n'
        # print(video_strikes)
        # print(elapsed_time)
        # info = video_strikes+elapsed_time
        # looks like calling popups from this thread can cause crashes.
        # For stability, I am removing the info popup. Error popups will be left
        # for now, but need to be fixed.

        # info_popup(info)
        # sends finished signal. Essentially terminates the thread.
        self.finished.emit()


class Window(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi()

    def setupUi(self):
        # sets up the gui layout itself
        self.setWindowTitle("ZapCapture")
        self.resize(300, 150)
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        # Create and connect widgets
        # directory widgets
        self.inputFileDirectoryButton = QPushButton("Select Input Directory", self)
        self.inputFileDirectoryButton.clicked.connect(self.pick_new_input)
        self.inputFileDirectoryLabel = QLabel(input_folder)
        self.inputFileDirectoryLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.outputFileDirectoryButton = QPushButton("Select Output Directory", self)
        self.outputFileDirectoryButton.clicked.connect(self.pick_new_output)
        self.outputFileDirectoryLabel = QLabel(output_folder)
        self.outputFileDirectoryLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        
        # mask widget
        self.setMaskButton = QPushButton("Select Area to Ignore (Mask)", self)
        self.setMaskButton.clicked.connect(self.define_mask)
        self.setMaskButton.setToolTip("Draw a box over an area of the video to ignore during analysis (e.g., ground or moving trees).")
        
        self.clearMaskButton = QPushButton("Clear Mask", self)
        self.clearMaskButton.clicked.connect(self.clear_mask)
        self.clearMaskButton.setToolTip("Clear the currently selected mask.")
        
        # file name widgets
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
        
        # calculate threshold widget
        self.calcThresholdButton = QPushButton("Calculate Suggested Threshold", self)
        self.calcThresholdButton.clicked.connect(self.calculate_suggested_threshold)
        self.calcThresholdButton.setToolTip("Skims the first video to automatically calculate and fill in a suggested threshold.")
        
        # threshold widget
        self.thresholdLabel = QLabel("Threshold (❓)", self)
        self.thresholdLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.thresholdLabel.setToolTip('Threshold determines the sensitivity of the computer vision algorithm. High thresholds will execute quickly with few output images, while low thresholds will potentially detect every frame of the video as a lightning event. Each video in your folder may need an individually tuned threshold; in this case, make subfolders for videos from the same camera and event. For example, separate your dash-cam footage and stationary camera footage. Nighttime footage can require thresholds aroung 10 million, while daytime footage can be as low as 10 thousand.')
        self.thresholdEntry = QLineEdit(threshold)
        # restricts the threshold to be numbers only
        self.onlyInt = QIntValidator()
        self.thresholdEntry.setValidator(self.onlyInt)
        
        # buffer frames widget
        self.bufferFramesLabel = QLabel("Buffer Frames Before & After (❓)", self)
        self.bufferFramesLabel.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.bufferFramesLabel.setToolTip("Number of frames to save immediately before and after the detected strike.")
        self.bufferFramesEntry = QLineEdit(buffer_frames)
        self.bufferFramesEntry.setValidator(self.onlyInt)
        
        self.previewButton = QPushButton('Live Preview Settings', self)
        self.previewButton.setToolTip('Play a clip from the input folder to see if your threshold and mask settings are detecting strikes correctly.')
        self.previewButton.clicked.connect(self.preview_settings)
        
        self.analysisButton = QPushButton('Perform Analysis', self)
        # self.analysisButton.clicked.connect(self.analysis)
        self.analysisButton.clicked.connect(self.runLongTask)
        self.progressBar = QProgressBar(self)
        self.progressBar.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        #self.progressBar.setGeometry(200, 80, 250, 20)
        self.progressBar.setValue(0)
        # monetization to prevent starvation
        linkTemplate = '<a href={0}>{1}</a>'
        self.starvationButton = HyperlinkLable(self)
        starvationMessage = '''Like ZapCapture? Consider buying me a coffee!'''
        self.starvationButton.setText(linkTemplate.format('https://www.buymeacoffee.com/Blablabliam', starvationMessage))

        # Set the layout
        layout = QVBoxLayout()
        layout.addWidget(self.inputFileDirectoryButton)
        layout.addWidget(self.inputFileDirectoryLabel)
        layout.addWidget(self.outputFileDirectoryButton)
        layout.addWidget(self.outputFileDirectoryLabel)
        layout.addWidget(self.setMaskButton)
        layout.addWidget(self.clearMaskButton)
        layout.addWidget(self.outputFilenameLabel)
        layout.addWidget(self.outputFrameNumButton)
        layout.addWidget(self.outputTimestampButton)
        layout.addWidget(self.calcThresholdButton)
        layout.addWidget(self.thresholdLabel)
        layout.addWidget(self.thresholdEntry)
        layout.addWidget(self.bufferFramesLabel)
        layout.addWidget(self.bufferFramesEntry)
        layout.addWidget(self.previewButton)
        layout.addWidget(self.analysisButton)
        layout.addWidget(self.progressBar)
        layout.addWidget(self.starvationButton)
        self.centralWidget.setLayout(layout)

    def pick_new_input(self):
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Input Folder")
        global input_folder
        input_folder = str(folder_path)
        self.inputFileDirectoryLabel.setText(str(folder_path))
        # reset the progress bar to 0
        self.progressBar.setValue(0)
        self.analysisButton.setEnabled(True)

    def pick_new_output(self):
        dialog = QFileDialog()
        folder_path = dialog.getExistingDirectory(None, "Select Output Folder")
        global output_folder
        output_folder = str(folder_path)
        self.outputFileDirectoryLabel.setText(str(folder_path))
        # reset the progress bar to 0
        self.progressBar.setValue(0)
        self.analysisButton.setEnabled(True)

    def btnstate(self, b):
        global buttonState
        if b.text() == "Frame Number":
            if b.isChecked() == True:
                buttonState = True
                print(b.text()+" is selected")
            else:
                buttonState = False
                print(b.text()+" is deselected")
                
    def define_mask(self):
        global input_folder
        global mask_rect
        if input_folder == 'No Folder Chosen' or not os.path.isdir(input_folder):
            error_popup("Please select a valid input folder first.")
            return

        # Find first video
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

        # Scale down for display if the video is huge
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
        cv2.waitKey(1)  # Important for macOS to flush the close event immediately

        if roi[2] > 0 and roi[3] > 0:
            real_x = int(roi[0] / scale_display)
            real_y = int(roi[1] / scale_display)
            real_w = int(roi[2] / scale_display)
            real_h = int(roi[3] / scale_display)
            
            mask_rect = (real_x, real_y, real_w, real_h)
            print(f"Mask defined: {mask_rect}")
            self.setMaskButton.setText("Area to Ignore: Custom Mask Applied")
        else:
            mask_rect = None
            print("Mask cancelled. Using full frame.")
            self.setMaskButton.setText("Select Area to Ignore (Mask)")
            
    def clear_mask(self):
        global mask_rect
        mask_rect = None
        print("Mask cleared.")
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
        QApplication.processEvents()  # Keeps GUI responsive

        cap = cv2.VideoCapture(first_video)
        ret, frame0 = cap.read()
        if not ret:
            error_popup("Could not read the first video.")
            cap.release()
            self.calcThresholdButton.setText("Calculate Suggested Threshold")
            self.calcThresholdButton.setEnabled(True)
            return

        diffs = []
        # Read a healthy sample of frames (~50 seconds) to find the noise baseline
        for i in range(1500):
            ret, frame1 = cap.read()
            if not ret: break
            diffs.append(count_diff(frame0, frame1))
            frame0 = frame1
            if i % 50 == 0: QApplication.processEvents()
        cap.release()

        if diffs:
            diffs_arr = np.array(diffs)
            suggested = int(np.mean(diffs_arr) + 5 * np.std(diffs_arr))
            suggested = max(suggested, 1000)
            self.thresholdEntry.setText(str(suggested))
            print(f"Suggested threshold calculated: {suggested}")
        
        self.calcThresholdButton.setText("Calculate Suggested Threshold")
        self.calcThresholdButton.setEnabled(True)
            
    def preview_settings(self):
        global input_folder
        global mask_rect
        if input_folder == 'No Folder Chosen' or not os.path.isdir(input_folder):
            error_popup("Please select a valid input folder first.")
            return

        # Find first video
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

        cap = cv2.VideoCapture(first_video)
        ret, frame0 = cap.read()
        if not ret:
            error_popup("Could not read the first video for preview.")
            cap.release()
            return

        h, w = frame0.shape[:2]
        window_name = "Preview (Press 'q' or 'ESC' to exit)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, min(w, 1280), min(h, 720))

        while True:
            ret, frame1 = cap.read()
            if not ret:
                break  # End of video

            # calculate diff
            diff1 = count_diff(frame0, frame1)
            
            current_threshold = threshold_val
            is_strike = diff1 > threshold_val

            display_frame = frame1.copy()

            # Draw mask
            if mask_rect is not None:
                rx, ry, rw, rh = mask_rect
                cv2.rectangle(display_frame, (rx, ry), (rx+rw, ry+rh), (0, 0, 255), 2)
                cv2.putText(display_frame, "IGNORED (MASK)", (rx, ry - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # Draw info
            info_text = f"Diff: {diff1} | Thresh: {int(current_threshold)}"
            cv2.putText(display_frame, info_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            if is_strike:
                cv2.putText(display_frame, "STRIKE DETECTED!", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)

            cv2.imshow(window_name, display_frame)
            frame0 = frame1

            key = cv2.waitKey(30) & 0xFF
            if key == ord('q') or key == 27: # q or ESC
                break

            # check if window was closed via the "X" button
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except:
                pass

        cap.release()
        cv2.destroyWindow(window_name)
        cv2.waitKey(1)

    def runLongTask(self):
        # set the threshold
        global threshold
        global buffer_frames
        threshold = self.thresholdEntry.text()
        buffer_frames = self.bufferFramesEntry.text()
        # Step 2: Create a QThread object
        self.thread = QThread()
        # Step 3: Create a worker object
        self.worker = Worker()
        # Step 4: Move worker to the thread
        self.worker.moveToThread(self.thread)
        # setup progress bar signal
        self.worker.threadProgress.connect(self.onCountChanged)
        # Step 5: Connect signals and slots
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        # self.worker.progress.connect(self.reportProgress)
        # Step 6: Start the thread
        self.thread.start()

        # Final resets
        self.analysisButton.setEnabled(False)
        self.thread.finished.connect(self.enableAnalysisButton)
        # self.thread.finished.connect(
        #     lambda: self.analysisButton.setEnabled(True)
        # )

    def onCountChanged(self, value):
        self.progressBar.setValue(value)

    def enableAnalysisButton(self):
        self.analysisButton.setEnabled(True)


app = QApplication(sys.argv)

# Dark Mode code
# Force the style to be the same on all OSs:
app.setStyle("Fusion")

# Now use a palette to switch to dark colors:
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

# finish building window
win = Window()
win.show()
sys.exit(app.exec())
