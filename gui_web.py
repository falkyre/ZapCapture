from nicegui import ui, events, run
import cv2
import os
import base64
from core import ZapCore

engine = ZapCore()

app_state = {
    'input_folder': './input',
    'output_folder': './output',
    'is_previewing': False
}

mask_clicks = []

def update_preview():
    if not app_state['is_previewing']:
        return
    frame = engine.get_annotated_preview_frame()
    if frame is not None:
        _, jpeg = cv2.imencode('.jpg', frame)
        b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
        video_preview.set_source(f'data:image/jpeg;base64,{b64}')

def toggle_preview():
    if app_state['is_previewing']:
        preview_timer.deactivate()
        engine.stop_preview()
        app_state['is_previewing'] = False
        preview_btn.set_text('Start Live Preview')
        preview_btn.classes(remove='bg-red-500', add='bg-blue-500')
    else:
        input_dir = app_state['input_folder']
        if os.path.exists(input_dir):
            files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
            if files:
                if engine.start_preview(os.path.join(input_dir, files[0])):
                    app_state['is_previewing'] = True
                    preview_timer.activate()
                    preview_btn.set_text('Stop Live Preview')
                    preview_btn.classes(remove='bg-blue-500', add='bg-red-500')
                    return
        ui.notify("Could not open a video in the input directory.", type='negative')

def handle_image_click(e: events.MouseEventArguments):
    if e.type == 'mousedown':
        mask_clicks.append((int(e.image_x), int(e.image_y)))
        if len(mask_clicks) == 2:
            x1, y1 = mask_clicks[0]
            x2, y2 = mask_clicks[1]
            engine.set_mask(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            mask_clicks.clear()
            ui.notify('Mask set!', type='positive')

async def start_analysis():
    if app_state['is_previewing']:
        toggle_preview()
    analysis_btn.disable()
    ui.notify('Analysis Started...', type='info')
    
    result = await run.io_bound(engine.run_analysis, app_state['input_folder'], app_state['output_folder'])
    
    ui.notify(result, type='positive' if 'Complete' in result else 'warning')
    progress_bar.update()
    analysis_btn.enable()

ui.page_title('ZapCapture-NG Web')

with ui.row().classes('w-full h-screen no-wrap'):
    with ui.column().classes('w-1/3 p-6 bg-gray-100 h-full overflow-y-auto'):
        ui.label('ZapCapture-NG').classes('text-3xl font-bold mb-6')
        ui.input('Input Directory').bind_value(app_state, 'input_folder').classes('w-full')
        ui.input('Output Directory').bind_value(app_state, 'output_folder').classes('w-full')
        ui.input('Watermark Text').bind_value(engine, 'watermark_text').classes('w-full mt-2')
        
        ui.separator().classes('my-4')
        ui.number('Threshold', format='%d').bind_value(engine, 'threshold').classes('w-full')
        ui.number('Buffer Frames', format='%d').bind_value(engine, 'buffer_frames').classes('w-full mb-4')
        
        ui.button('Clear Mask', on_click=lambda: [engine.clear_mask(), mask_clicks.clear()]).classes('w-full bg-gray-500 mb-4')
        preview_btn = ui.button('Start Live Preview', on_click=toggle_preview).classes('w-full bg-blue-500 mb-2')
        analysis_btn = ui.button('Perform Analysis', on_click=start_analysis).classes('w-full bg-green-600')
        
        ui.label('Progress').classes('mt-4 font-bold')
        progress_bar = ui.linear_progress(value=0).bind_value_from(engine, 'progress').classes('w-full')

    with ui.column().classes('w-2/3 h-full flex items-center justify-center bg-black p-4'):
        video_preview = ui.interactive_image(cross=True, on_mouse=handle_image_click).classes('max-w-full max-h-full border border-gray-700')

preview_timer = ui.timer(0.033, update_preview, active=False)
ui.run(host='0.0.0.0', port=8080, title='ZapCapture-NG Web', reload=False)