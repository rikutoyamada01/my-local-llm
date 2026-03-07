import os
import sys
import time
import queue
import wave
import threading
import datetime
import logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import numpy as np
import sounddevice as sd
import keyboard
from faster_whisper import WhisperModel

# --- Configuration & Setup ---
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPTS_DIR = AUDIO_DIR / "transcripts"
CONFIG_PATH = BASE_DIR / "config" / "secrets.yaml"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioUIToggle:
    def __init__(self):
        self.load_config()
        self.sample_rate = 16000  # Required by Whisper
        self.channels = 1
        
        self.is_recording = False
        self.recording_stream = None
        self.frames_to_record = []
        
        # Whisper model loaded lazily
        self.model = None
        
        # TKinter Setup
        self.root = tk.Tk()
        self.root.withdraw() # Hide initially
        self.root.overrideredirect(True) # Borderless
        self.root.attributes("-topmost", True) # Always on top
        self.root.attributes("-alpha", 0.96)
        
        # Color Palette
        self.bg_color = "#121212"
        self.accent_color = "#5c5cff"
        self.text_color = "#e0e0e0"
        self.error_color = "#ff4a4a"
        self.success_color = "#4caf50"
        
        self.root.configure(bg=self.bg_color, padx=10, pady=10)
        
        # Action Queue for Thread Communication
        self.action_queue = queue.Queue()
        
        # Position bottom center
        self.update_geometry(width=450, height=80)
        
        # UI Elements Container (for border styling)
        self.main_frame = tk.Frame(self.root, bg=self.bg_color, highlightbackground="#333333", highlightthickness=1)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="🎤 Ready")
        self.status_label = tk.Label(self.main_frame, textvariable=self.status_var, font=("Segoe UI", 12, "bold"), fg=self.text_color, bg=self.bg_color)
        self.status_label.pack(pady=(15, 5))
        
        # For editing output
        self.text_editor = tk.Text(self.main_frame, height=4, width=50, font=("Segoe UI", 11), bg="#1e1e1e", fg=self.text_color, insertbackground="white", relief=tk.FLAT, padx=10, pady=10)
        
        # Buttons Frame
        self.button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        self.save_btn = tk.Button(self.button_frame, text="Save [Enter]", command=self.save_and_close, bg=self.accent_color, fg="white", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, cursor="hand2", padx=15, pady=5)
        self.save_btn.pack(side=tk.RIGHT, padx=5)
        self.cancel_btn = tk.Button(self.button_frame, text="Delete [Esc]", command=self.cancel_and_close, bg="#444444", fg="white", font=("Segoe UI", 10), relief=tk.FLAT, cursor="hand2", padx=15, pady=5)
        self.cancel_btn.pack(side=tk.RIGHT, padx=5)

        # Bind events
        self.text_editor.bind("<Return>", self.save_and_close)
        self.text_editor.bind("<Escape>", self.cancel_and_close)
        self.text_editor.bind("<KeyPress>", self.reset_timer_on_keypress)
        
        self.text_editor.pack_forget() # Hide editor initially
        self.button_frame.pack_forget()
        
        # Timers and state
        self.close_timer = None
        self.is_saving_locked = False # Prevent double saves

    def load_config(self):
        import yaml
        config = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
                
        audio_cfg = config.get("audio_recording", {})
        self.enabled = audio_cfg.get("enabled", False)
        self.model_size = audio_cfg.get("model", "base")
        self.hotkey = audio_cfg.get("hotkey", "ctrl+shift+r")

    def init_model(self):
        if self.model is None:
            self.update_ui("⏳ Loading AI Model...", height=60, show_editor=False)
            self.root.update()
            
            logger.info(f"Loading Whisper model: {self.model_size} (This may take a moment...)")
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            logger.info("Whisper model loaded.")

    def play_beep(self, start=True):
        try:
            import winsound
            if start:
                winsound.Beep(1000, 200) # High beep
            else:
                winsound.Beep(600, 200) # Low beep
        except Exception:
            pass

    def audio_callback(self, indata, frames, time, status):
        if status:
            logger.warning(status)
        if self.is_recording:
            audio_data = (indata[:, 0] * 32767).astype(np.int16).tobytes()
            self.frames_to_record.append(audio_data)

    def on_hotkey_pressed(self):
        """Thread-safe tk event trigger called by keyboard listener"""
        self.action_queue.put("toggle")

    def process_queue(self):
        """Periodically check the queue from the main TK thread and execute commands"""
        try:
            while True:
                msg = self.action_queue.get_nowait()
                if msg == "toggle":
                    self.toggle_recording()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)

    def update_geometry(self, width=450, height=80):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2) + 200 # slightly below center
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def update_ui(self, message, color=None, height=80, show_editor=False):
        color = color or self.text_color
        self.status_var.set(message)
        self.status_label.config(fg=color)
        
        self.update_geometry(width=480, height=height)
        
        if show_editor:
            self.status_label.pack(pady=(15, 5))
            self.text_editor.pack(pady=5, padx=15, fill=tk.X)
            self.button_frame.pack(pady=5, padx=15, fill=tk.X)
            self.text_editor.focus_set()
        else:
            self.status_label.pack(pady=(15, 5), fill=tk.BOTH, expand=True)
            self.text_editor.pack_forget()
            self.button_frame.pack_forget()

    def toggle_recording(self):
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
            
        if not self.is_recording:
            # Start Recording
            self.is_recording = True
            self.frames_to_record = []
            
            self.is_saving_locked = False
            self.update_ui("🔴 Recording... (Press Ctrl+Shift+R to stop)", color=self.error_color, height=80, show_editor=False)
            self.root.deiconify() # Show window
            self.root.lift() # Bring to front
            
            # Start in new thread to not block UI
            threading.Thread(target=self.play_beep, args=(True,)).start()
            
            self.recording_stream = sd.InputStream(
                samplerate=self.sample_rate, 
                channels=self.channels, 
                callback=self.audio_callback
            )
            self.recording_stream.start()
            logger.info("Recording started.")
            
        else:
            # Stop Recording
            self.is_recording = False
            if self.recording_stream:
                self.recording_stream.stop()
                self.recording_stream.close()
                self.recording_stream = None
                
            threading.Thread(target=self.play_beep, args=(False,)).start()
            self.update_ui("⚙️ Processing Transcription...", color=self.accent_color, height=80, show_editor=False)
            logger.info("Recording stopped. Processing...")
            
            # Process in background thread to unblock UI
            if self.frames_to_record:
                audio_chunk = b"".join(self.frames_to_record)
                self.frames_to_record = []
                threading.Thread(target=self.transcribe_chunk, args=(audio_chunk,)).start()
            else:
                self.schedule_close(1000)

    def transcribe_chunk(self, audio_data: bytes):
        if len(audio_data) < self.sample_rate * 1: # Ignore $< 1 second
            self.root.after(0, lambda: self.update_ui("⚠️ Recording too short. Discarded.", color="#FFCC00"))
            self.root.after(0, lambda: self.schedule_close(2000))
            return
            
        # Init model on block
        self.root.after(0, self.init_model)
        # We need a tiny sleep to allow the UI to update the 'Loading' message before model load blocks the CPU
        if self.model is None:
            time.sleep(0.1) 
            self.init_model() 
            
        try:
            audio_np = np.frombuffer(audio_data, np.int16).astype(np.float32) / 32768.0
            segments, info = self.model.transcribe(audio_np, beam_size=5, language="ja")
            text = " ".join([segment.text for segment in segments]).strip()
            
            if text:
                logger.info(f"Transcript generated: {text[:50]}...")
                self.root.after(0, lambda t=text: self.show_editable_transcript(t))
            else:
                self.root.after(0, lambda: self.update_ui("🔇 No speech detected.", color="#AAAAAA"))
                self.root.after(0, lambda: self.schedule_close(2000))
                
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self.root.after(0, lambda: self.update_ui(f"❌ Error: {str(e)[:30]}", color=self.error_color))
            self.root.after(0, lambda: self.schedule_close(3000))

    def reset_timer_on_keypress(self, event=None):
        """Cancel the auto-save timer if the user starts typing to give them infinite time."""
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
            self.status_var.set("✨ Edit Mode (Press Enter to Save)")

    def show_editable_transcript(self, text: str):
        self.update_ui("✨ Edit & Save (Auto-saves in 10s if untouched)", color=self.success_color, height=180, show_editor=True)
        self.text_editor.delete("1.0", tk.END)
        self.text_editor.insert("1.0", text)
        
        # Auto-save after 10 seconds if user does nothing
        self.schedule_close(10000, save=True)

    def cancel_and_close(self, event=None):
        self.is_saving_locked = True # Prevent normal saving
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
        self.do_close()
        return "break"

    def save_and_close(self, event=None):
        if self.is_saving_locked:
            return "break"
            
        self.is_saving_locked = True
        
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
            
        text = self.text_editor.get("1.0", tk.END).strip()
        if text:
            # Re-update UI rapidly just to show feedback before closing
            self.update_ui("✅ Saved to Daily Log!", color=self.success_color, height=80, show_editor=False)
            self.root.update()
            
            # Execute save
            self.append_to_daily_log(text)
            
            # Close almost immediately
            self.root.after(800, self.do_close)
        else:
            self.do_close()
        return "break" # Prevent default newline in Text widget

    def schedule_close(self, ms, save=False):
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            
        def _close():
            if save:
                self.save_and_close()
            else:
                self.do_close()
                
        self.close_timer = self.root.after(ms, _close)

    def do_close(self):
        self.root.withdraw()
        self.text_editor.pack_forget()
        self.button_frame.pack_forget()
        self.is_saving_locked = False

    def append_to_daily_log(self, text: str):
        jst = datetime.timezone(datetime.timedelta(hours=9))
        now = datetime.datetime.now(jst)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        filepath = TRANSCRIPTS_DIR / f"{date_str}_voice.txt"
        
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"[{time_str}] {text}\n")
            logger.info("Saved to daily log.")
        except Exception as e:
            logger.error(f"Failed to write transcript: {e}")

    def run(self):
        if not self.enabled:
            logger.info("Audio recording disabled in config.")
            return

        logger.info(f"AudioSensor UI started. Press '{self.hotkey}' to toggle recording.")
        try:
            keyboard.add_hotkey(self.hotkey, self.on_hotkey_pressed)
            self.root.after(100, self.process_queue) # Start queue listener poll
            self.root.mainloop() # Blocks here, handling all UI events
        except Exception as e:
            logger.error(f"Failed to run UI: {e}")
        finally:
            self.stop()

if __name__ == "__main__":
    app = AudioUIToggle()
    app.run()
