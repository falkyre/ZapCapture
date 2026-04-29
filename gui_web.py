import sys

from nicegui import ui, events, run, app
import cv2
import os
import base64
import tempfile
import shutil
import numpy as np
import time

from logging_config import get_logger, setup_logging, parse_verbose_arg
from core import ZapCore, get_available_fonts

logger = get_logger(__name__)

engine = ZapCore()

app_state = {
    'input_folder': './input',
    'output_folder': './output',
    'temp_folder': '',
    'is_previewing': False,
    'gallery_selection': {}
}

mask_clicks = []

class DirectoryPicker(ui.dialog):
    def __init__(self, start_dir: str):
        super().__init__()
        self.current_path = os.path.abspath(start_dir) if os.path.exists(start_dir) else os.path.abspath('.')
        with self, ui.card().classes('w-[500px] max-w-[90vw]'):
            ui.label('Select Directory').classes('text-xl font-bold')
            self.path_label = ui.label(self.current_path).classes('text-sm text-gray-500 break-all')
            self.container = ui.column().classes('w-full h-[50vh] overflow-y-auto overflow-x-hidden border rounded p-1 my-2 block')
            with ui.row().classes('w-full justify-end gap-2 mt-2'):
                ui.button('Cancel', on_click=self.close).props('outline')
                ui.button('Select Current Directory', on_click=lambda: self.submit(self.current_path))
        self.update_view()

    def update_view(self):
        self.path_label.set_text(self.current_path)
        self.container.clear()
        with self.container:
            ui.button('📁 .. (Go Up)', on_click=lambda: self.navigate(os.path.dirname(self.current_path))).classes('w-full text-left bg-gray-200 text-black mb-1 truncate').props('flat no-caps align=left')
            try:
                items = sorted(os.listdir(self.current_path))
            except PermissionError:
                items = []
            for item in items:
                if item.startswith('.'):
                    continue
                full_path = os.path.join(self.current_path, item)
                if os.path.isdir(full_path):
                    with ui.row().classes('w-full items-center no-wrap bg-gray-100 mb-1 rounded p-0'):
                        ui.button(f'📁 {item}', on_click=lambda p=full_path: self.navigate(p)).classes('flex-grow text-left text-black truncate').props('flat no-caps align=left')
                        ui.button('Select', on_click=lambda p=full_path: self.submit(p)).classes('shrink-0 bg-blue-500 text-white mr-1').props('size=sm')

    def navigate(self, path):
        self.current_path = path
        self.update_view()

async def pick_input_dir():
    result = await DirectoryPicker(app_state['input_folder'])
    if result:
        app_state['input_folder'] = result
        lbl_in_dir.set_text(result)
        app_state['output_folder'] = result
        lbl_out_dir.set_text(result)

async def pick_output_dir():
    result = await DirectoryPicker(app_state['output_folder'])
    if result:
        app_state['output_folder'] = result
        lbl_out_dir.set_text(result)

scrubber_dragging = {'active': False}
is_programmatic_update = {'active': False}
last_scrub_time = {'value': 0}

def frame_to_timecode(frame, fps):
    total_secs = frame / max(fps, 1)
    mins = int(total_secs // 60)
    secs = int(total_secs % 60)
    return f'{mins:02d}:{secs:02d}'

def push_frame_to_preview(frame):
    _, jpeg = cv2.imencode('.jpg', frame)
    b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
    video_preview.set_source(f'data:image/jpeg;base64,{b64}')

def update_preview():
    if not app_state['is_previewing']:
        return
    if scrubber_dragging['active']:
        return  # user is scrubbing, don't advance
    frame = engine.get_annotated_preview_frame()
    if frame is not None:
        push_frame_to_preview(frame)
        pos, total, fps = engine.get_preview_info()
        if total > 0:
            current_frame = max(0, pos - 1)
            is_programmatic_update['active'] = True
            scrubber_slider.set_value(current_frame)
            is_programmatic_update['active'] = False
            scrubber_label.set_text(f'{frame_to_timecode(current_frame, fps)}  /  {frame_to_timecode(total, fps)}')

def handle_scrub(e):
    """Called when the user drags the scrubber slider."""
    if is_programmatic_update['active']:
        return
    scrubber_dragging['active'] = True
    
    # Throttle updates to prevent overwhelming the server/browser
    now = time.time()
    if now - last_scrub_time['value'] < 0.1:  # max 10 fps while scrubbing
        return
    last_scrub_time['value'] = now

    frame_num = int(scrubber_slider.value)
    frame = engine.seek_preview(frame_num)
    if frame is not None:
        push_frame_to_preview(frame)
        _, total, fps = engine.get_preview_info()
        scrubber_label.set_text(f'{frame_to_timecode(frame_num, fps)}  /  {frame_to_timecode(total, fps)}')

def handle_scrub_end(e):
    """Resume normal playback after scrubbing."""
    scrubber_dragging['active'] = False
    # Final seek to make sure we're exactly where the user let go
    frame_num = int(scrubber_slider.value)
    engine.seek_preview(frame_num)


def toggle_preview():
    if app_state['is_previewing']:
        preview_timer.deactivate()
        engine.stop_preview()
        app_state['is_previewing'] = False
        preview_btn.set_text('Start Live Preview')
        preview_btn.classes(remove='bg-red-500', add='bg-blue-500')
        scrubber_label.set_text('00:00  /  00:00')
    else:
        input_dir = app_state['input_folder']
        if os.path.exists(input_dir):
            files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv'))]
            if files:
                if engine.start_preview(os.path.join(input_dir, files[0])):
                    _, total, fps = engine.get_preview_info()
                    logger.debug('Video started: %d frames at %.1f FPS', total, fps)
                    scrubber_slider.set_value(0)
                    scrubber_slider.props(f'max={total}')
                    scrubber_label.set_text(f'00:00  /  {frame_to_timecode(total, fps)}')
                    app_state['is_previewing'] = True
                    preview_timer.activate()
                    preview_btn.set_text('Stop Live Preview')
                    preview_btn.classes(remove='bg-blue-500', add='bg-red-500')
                    return
        ui.notify("Could not open a video in the input directory.", type='negative')

def force_preview_frame_update():
    if not app_state['is_previewing']:
        input_dir = app_state['input_folder']
        if os.path.exists(input_dir):
            files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv'))]
            if files:
                engine.start_preview(os.path.join(input_dir, files[0]))
                frame = engine.get_annotated_preview_frame()
                engine.stop_preview()
                if frame is not None:
                    push_frame_to_preview(frame)

drag_state = {'is_dragging': False, 'start_x': 0, 'start_y': 0}

def handle_image_click(e: events.MouseEventArguments):
    if e.type == 'mousedown':
        drag_state['is_dragging'] = True
        drag_state['start_x'] = int(e.image_x)
        drag_state['start_y'] = int(e.image_y)
    elif e.type == 'mousemove' and drag_state['is_dragging']:
        x1, y1 = drag_state['start_x'], drag_state['start_y']
        x2, y2 = int(e.image_x), int(e.image_y)
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        video_preview.content = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="rgba(255, 0, 0, 0.4)" stroke="red" stroke-width="2"/>'
    elif e.type == 'mouseup' and drag_state['is_dragging']:
        drag_state['is_dragging'] = False
        video_preview.content = ''
        x1, y1 = drag_state['start_x'], drag_state['start_y']
        x2, y2 = int(e.image_x), int(e.image_y)
        if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
            engine.set_mask(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            force_preview_frame_update()
            ui.notify('Mask set! Highlighted area will be ignored.', type='positive')

def clear_mask():
    engine.clear_mask()
    mask_clicks.clear()
    force_preview_frame_update()
    ui.notify('Mask cleared!', type='info')

def calc_thresh_task(input_dir):
    first_video = None
    if not os.path.exists(input_dir): return None
    for f in os.listdir(input_dir):
        if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
            first_video = os.path.join(input_dir, f)
            break
    if not first_video: return None
    cap = cv2.VideoCapture(first_video)
    ret, frame0 = cap.read()
    if not ret:
        cap.release()
        return None
    diffs = []
    for i in range(1500):
        ret, frame1 = cap.read()
        if not ret: break
        diffs.append(engine._count_diff(frame0, frame1))
        frame0 = frame1
    cap.release()
    if diffs:
        suggested = int(np.percentile(np.array(diffs), 99))
        return max(suggested, 1000)
    return None

async def calculate_suggested_threshold():
    calc_btn.disable()
    ui.notify('Calculating suggested threshold...', type='info')
    res = await run.io_bound(calc_thresh_task, app_state['input_folder'])
    calc_btn.enable()
    if res:
        engine.threshold = res
        ui.notify(f'Suggested threshold: {res}', type='positive')
        thresh_input.update()
    else:
        ui.notify('Could not calculate threshold.', type='negative')

STATUS_ICONS = {'pending': '⏳', 'processing': '▶️', 'done': '✅', 'skipped': '⏭️'}

async def start_analysis():
    if app_state['is_previewing']:
        toggle_preview()
    analysis_btn.disable()
    ui.notify('Analysis Started...', type='info')
    
    # Pre-populate the queue list with files from the input dir
    input_dir = app_state['input_folder']
    queue_list.clear()
    queue_labels = {}
    files = sorted([f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4','.avi','.mov','.mkv'))])
    with queue_list:
        for f in files:
            queue_labels[f] = ui.label(f'⏳ {f}').classes('text-sm font-mono')

    current_file_label.set_text('Starting...')
    analysis_dialog.open()

    def refresh_queue():
        for fname, lbl in queue_labels.items():
            status = engine.queue_status.get(fname, 'pending')
            icon = STATUS_ICONS.get(status, '⏳')
            lbl.set_text(f'{icon} {fname}')
        current_file_label.set_text(f'Now processing: {engine.current_file}' if engine.current_file else '')

    refresh_timer = ui.timer(0.5, refresh_queue)

    app_state['temp_folder'] = tempfile.mkdtemp(prefix="zapcapture_")
    result = await run.io_bound(engine.run_analysis, app_state['input_folder'], app_state['temp_folder'])

    refresh_timer.cancel()
    refresh_queue()  # Final update

    ui.notify(result, type='positive' if 'Complete' in result else 'warning')
    analysis_btn.enable()
    analysis_dialog.close()
    
    # Copy CSV files automatically to output
    final_out = app_state['output_folder']
    os.makedirs(final_out, exist_ok=True)
    temp = app_state['temp_folder']
    for f in os.listdir(temp):
        if f.endswith('.csv'):
            shutil.copy2(os.path.join(temp, f), final_out)
            
    load_gallery()
    tabs_panel.set_value('Analysis Results')

def load_gallery():
    gallery_container.clear()
    app_state['gallery_selection'] = {}
    
    if not app_state['temp_folder'] or not os.path.exists(app_state['temp_folder']):
        return
        
    app.add_static_files('/temp_gallery', app_state['temp_folder'])
    
    files = sorted([f for f in os.listdir(app_state['temp_folder']) if f.endswith('.png')])
    with gallery_container:
        with ui.grid(columns=4).classes('w-full gap-4'):
            for f in files:
                filepath = os.path.join(app_state['temp_folder'], f)
                gif_filename = f.replace('.png', '.gif')
                
                with ui.card().classes('p-2 items-center'):
                    img_url = f'/temp_gallery/{f}'
                    gif_url = f'/temp_gallery/{gif_filename}'
                    
                    img = ui.image(img_url).classes('w-48 h-48 object-contain cursor-pointer')
                    img.on('mouseenter', lambda e, g=gif_url, i=img: i.set_source(g))
                    img.on('mouseleave', lambda e, p=img_url, i=img: i.set_source(p))
                    
                    cb = ui.checkbox(f, value=True)
                    app_state['gallery_selection'][filepath] = cb

def save_selected():
    final_out = app_state['output_folder']
    out_frames = os.path.join(final_out, 'frames')
    out_gifs = os.path.join(final_out, 'gifs')
    out_mp4s = os.path.join(final_out, 'mp4s')
    
    os.makedirs(out_frames, exist_ok=True)
    os.makedirs(out_gifs, exist_ok=True)
    os.makedirs(out_mp4s, exist_ok=True)
    
    temp_dir = app_state['temp_folder']
    copied_mp4s = set()
    
    for filepath, cb in app_state['gallery_selection'].items():
        if cb.value:
            filename = os.path.basename(filepath)
            shutil.copy2(filepath, os.path.join(out_frames, filename))
            
            gif_filename = filename.replace('.png', '.gif')
            gif_path = os.path.join(temp_dir, gif_filename)
            if os.path.exists(gif_path):
                shutil.copy2(gif_path, os.path.join(out_gifs, gif_filename))

            # Use the engine's png_to_mp4 map for exact match
            mp4_src = engine.png_to_mp4.get(filepath)
            if mp4_src and os.path.exists(mp4_src) and mp4_src not in copied_mp4s:
                shutil.copy2(mp4_src, os.path.join(out_mp4s, os.path.basename(mp4_src)))
                copied_mp4s.add(mp4_src)
                
    gallery_container.clear()
    shutil.rmtree(temp_dir, ignore_errors=True)
    ui.notify('Selected files saved to frames/, gifs/, and mp4s/!', type='positive')
    tabs_panel.set_value('Live Preview')

def select_all():
    for cb in app_state['gallery_selection'].values():
        cb.value = True

def deselect_all():
    for cb in app_state['gallery_selection'].values():
        cb.value = False

def discard_all():
    gallery_container.clear()
    temp_dir = app_state['temp_folder']
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    tabs_panel.set_value('Live Preview')

ui.page_title('ZapCapture-NG Web')
dark_mode = ui.dark_mode(value=None)

with ui.dialog().props('persistent') as analysis_dialog:
    with ui.card().classes('flex flex-col items-center p-8 bg-gray-800 text-white rounded-lg shadow-2xl min-w-96'):
        ui.spinner('dots', size='3em', color='green').classes('mb-4')
        ui.label('Analyzing Videos...').classes('text-2xl font-bold mb-1')
        current_file_label = ui.label('').classes('text-gray-400 mb-4')
        queue_list = ui.column().classes('w-full gap-1 mb-6')
        with ui.row().classes('gap-4'):
            ui.button('Skip Current File', icon='skip_next',
                      on_click=lambda: setattr(engine, 'skip_current', True)).classes('bg-yellow-600 text-white')
            ui.button('Cancel All', icon='stop',
                      on_click=lambda: setattr(engine, 'cancel_analysis', True)).classes('bg-red-600 text-white')

with ui.row().classes('w-full h-screen no-wrap'):
    with ui.column().classes('w-1/3 p-6 h-full overflow-y-auto'):
        with ui.row().classes('w-full items-center justify-between mb-6'):
            ui.label('ZapCapture-NG').classes('text-3xl font-bold')
            ui.select({'light': 'Light', 'dark': 'Dark', 'auto': 'Auto'}, value='auto', 
                      on_change=lambda e: dark_mode.set_value(None if e.value == 'auto' else e.value == 'dark')).classes('w-24')
        
        ui.button('Select Input Dir', on_click=pick_input_dir).classes('w-full bg-gray-300 text-black')
        lbl_in_dir = ui.label(app_state['input_folder']).classes('text-sm text-gray-500 mb-4 break-all text-left')
        
        ui.button('Select Output Dir', on_click=pick_output_dir).classes('w-full bg-gray-300 text-black')
        lbl_out_dir = ui.label(app_state['output_folder']).classes('text-sm text-gray-500 mb-4 break-all text-left')
        
        ui.label('Output Filenames').classes('font-bold mt-2')
        ui.radio({'frame': 'Frame Number', 'timestamp': 'Timestamp'}, value=engine.output_format).bind_value(engine, 'output_format').classes('w-full mb-4')
        
        ui.label('Detection Mode').classes('font-bold')
        ui.select({
            'standard': 'Standard (Intensity Difference)',
            'canny': 'Canny Edge Density',
            'hybrid': 'Hybrid (Intensity + Edge Count)'
        }, value=engine.detection_mode).bind_value(engine, 'detection_mode').classes('w-full mb-4')
        
        calc_btn = ui.button('Calculate Suggested Threshold', on_click=calculate_suggested_threshold).classes('w-full bg-purple-500 mb-4')
        

        
        thresh_input = ui.number('Threshold', format='%d').bind_value(engine, 'threshold').classes('w-full mb-2')
        ui.number('Buffer Frames', format='%d').bind_value(engine, 'buffer_frames').classes('w-full mb-4')
        
        with ui.card().classes('w-full bg-blue-100 border border-blue-500 p-2 mb-2'):
            with ui.row().classes('items-center no-wrap mb-1'):
                ui.icon('crop_free', size='sm').classes('text-blue-700 mr-2 shrink-0')
                ui.label('Masking: Click and drag on the Live Preview to draw an area to ignore.').classes('text-sm text-blue-900 font-bold')
            with ui.row().classes('items-start no-wrap mt-1'):
                ui.icon('warning', size='sm').classes('text-orange-600 mr-2 shrink-0')
                ui.label('Remember to Calculate Suggested Threshold again after setting or clearing a mask!').classes('text-xs text-orange-800 font-bold')
        ui.button('Clear Mask', on_click=clear_mask).classes('w-full bg-gray-500 mb-4')
        
        preview_btn = ui.button('Start Live Preview', on_click=toggle_preview).classes('w-full bg-blue-500 mb-4')
        
        with ui.card().classes('w-full bg-blue-100 border border-blue-500 p-2 mb-2'):
            with ui.row().classes('items-center no-wrap'):
                ui.icon('info', size='sm').classes('text-blue-700 mr-2 shrink-0')
                ui.label('Watermark text is burned into frames during analysis. Must be set before running!').classes('text-sm text-blue-900 font-bold')
        
        ui.label('Watermark Configuration:').classes('font-bold mb-2')
        font_preview_img = ui.interactive_image(cross=False).classes('w-full h-16 bg-gray-900 border border-gray-700 mb-2')
        
        def update_font_preview(e=None):
            frame = engine.generate_font_preview()
            _, jpeg = cv2.imencode('.jpg', frame)
            b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
            font_preview_img.set_source(f'data:image/jpeg;base64,{b64}')

        ui.input('Watermark Text', placeholder='Enter text...').bind_value(engine, 'watermark_text').on_value_change(update_font_preview).classes('w-full mb-2')
        
        with ui.row().classes('w-full mb-4 no-wrap gap-2'):
            available_fonts = get_available_fonts()
            default_font = engine.watermark_font if engine.watermark_font in available_fonts else list(available_fonts.keys())[0]
            ui.select(available_fonts, value=default_font, label='Font Style').bind_value(engine, 'watermark_font').on_value_change(update_font_preview).classes('flex-grow')
            
            ui.number('Size Multiplier', value=1.0, format='%.1f', min=0.1, max=5.0, step=0.1).bind_value(engine, 'watermark_size').on_value_change(update_font_preview).classes('w-32')
            
        update_font_preview()
        
        ui.label('Export Settings').classes('font-bold mb-2')
        with ui.row().classes('w-full mb-4 no-wrap gap-2'):
            ui.select({'gif': 'GIF only', 'mp4': 'MP4 only', 'both': 'GIF + MP4'},
                      value='gif', label='Export Format').bind_value(engine, 'export_format').classes('flex-grow')
            ui.select({'None': 'Original', '1:1': 'Square (1:1)', '9:16': 'Portrait (9:16)'},
                      value='None', label='Crop Ratio').bind_value(engine, 'crop_aspect_ratio').classes('flex-grow')
        
        analysis_btn = ui.button('Perform Analysis', on_click=start_analysis).classes('w-full bg-green-600')

    with ui.column().classes('w-2/3 h-full bg-black flex-1 relative'):
        with ui.tabs().classes('w-full text-white bg-gray-800') as tabs:
            ui.tab('Live Preview')
            ui.tab('Analysis Results')
            ui.tab('Help & Guide')
            
        with ui.tab_panels(tabs, value='Live Preview').classes('w-full h-full bg-black p-4') as tabs_panel:
            with ui.tab_panel('Live Preview').classes('w-full h-full flex flex-col items-center justify-center bg-black gap-2'):
                video_preview = ui.interactive_image(cross=True, on_mouse=handle_image_click, events=['mousedown', 'mousemove', 'mouseup']).classes('max-w-full max-h-[85%] border border-gray-700 flex-shrink')
                with ui.column().classes('w-full px-4 gap-1'):
                    scrubber_slider = ui.slider(min=0, max=100000, value=0, step=1
                        ).classes('w-full').on_value_change(handle_scrub).on('change', handle_scrub_end)
                    scrubber_label = ui.label('00:00  /  00:00').classes('text-white text-lg font-bold text-center w-full')
                
            with ui.tab_panel('Analysis Results').classes('p-0 bg-gray-900 w-full h-full'):
                with ui.column().classes('w-full h-full no-wrap justify-between'):
                    gallery_container = ui.column().classes('w-full flex-grow overflow-y-auto p-4')
                    
                    with ui.row().classes('w-full justify-center gap-4 p-4 bg-gray-800 shrink-0'):
                        ui.button('Select All', on_click=select_all).classes('bg-blue-600')
                        ui.button('Deselect All', on_click=deselect_all).classes('bg-gray-600')
                        ui.button('Save Selected', on_click=save_selected).classes('bg-green-600')
                        ui.button('Discard All', on_click=discard_all).classes('bg-red-600')

            with ui.tab_panel('Help & Guide').classes('w-full h-full bg-gray-900 text-white overflow-y-auto p-8'):
                guide_path = os.path.join(os.path.dirname(__file__), 'assets', 'USER_GUIDE.md')
                if os.path.exists(guide_path):
                    with open(guide_path, 'r', encoding='utf-8') as f:
                        ui.markdown(f.read()).classes('text-lg')
                else:
                    ui.label("User guide not found.").classes('text-red-500')

preview_timer = ui.timer(0.033, update_preview, active=False)

verbose = parse_verbose_arg()
setup_logging(verbose=verbose)
logger.info('ZapCapture-NG Web starting on 0.0.0.0:8080 (verbose=%s)', verbose)

ui.run(host='0.0.0.0', port=8080, title='ZapCapture-NG Web', reload=False)