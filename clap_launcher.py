#!/usr/bin/env python3
"""
Wake Up - Clap-Activated App Launcher
Control your computer with voice and claps!

Say a wake word to activate, then use clap patterns to launch apps.
Uses Porcupine for fast, offline wake word detection.

GitHub: https://github.com/tpateeq/wake-up
"""

import pyaudio
import numpy as np
import subprocess
import time
import sys
import os
import platform
from collections import deque
import struct
import signal
import threading

try:
    import pvporcupine
except ImportError:
    print("❌ Porcupine not installed!")
    print("\nInstall it with:")
    print("  pip install pvporcupine")
    sys.exit(1)

# Your Porcupine API key - Get free key from https://console.picovoice.ai/
PORCUPINE_ACCESS_KEY = "DSPgLEwQdE9s1uhDuTpbFy3Ui41YZKeBol0Yx8eLyjaq4xpm2530SQ=="


class UnifiedLauncher:
    """Unified wake word and clap detection with single audio stream"""
    
    def __init__(self, wake_word="serena", clap_threshold=1800, debug=False):
        self.wake_word = wake_word.lower()
        self.clap_threshold = clap_threshold
        self.debug = debug
        
        # Detect operating system
        self.os_type = platform.system()  # Returns 'Darwin' (macOS), 'Windows', or 'Linux'
        print(f"🖥️  Detected OS: {self.os_type}")
        
        # State management
        self.is_active = False
        self.activation_time = 0
        self.active_duration = 5
        self.running = True
        
        # Clap detection state
        self.clap_times = []
        self.last_clap_time = 0
        self.clap_interval = 0.7
        self.previous_amplitude = 0
        self.amplitude_history = deque(maxlen=10)

        # Keyboard fallback: set to True when user presses Enter or Space (instead of double clap)
        self.keyboard_triggered = False
        # Global bypass: type apostrophe + Enter to launch immediately
        self.instant_launch_triggered = False
        self._keyboard_thread = None
        
        # Initialize Porcupine wake word detection
        builtin_keywords = pvporcupine.KEYWORDS
        print(f"📋 Available wake words: {', '.join(builtin_keywords)}")
        
        if self.wake_word not in builtin_keywords:
            print(f"⚠️  '{self.wake_word}' not available in Porcupine built-ins, using 'jarvis' instead")
            self.wake_word = "jarvis"
        
        try:
            self.porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=[self.wake_word]
            )
            print(f"✅ Wake word '{self.wake_word}' loaded successfully!")
            print("💡 This runs 100% locally - no internet needed!\n")
        except Exception as e:
            print(f"❌ Error initializing Porcupine: {e}")
            print("\n💡 Make sure you've added your API key at line 32")
            print("💡 Get a free key at: https://console.picovoice.ai/")
            sys.exit(1)
        
        # Audio setup - use Porcupine's requirements
        self.sample_rate = self.porcupine.sample_rate
        self.frame_length = self.porcupine.frame_length
        
        # PyAudio
        self.pa = pyaudio.PyAudio()
        self.audio_stream = None
        
        # Setup signal handler for clean exit
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, sig, frame):
        """Handle Ctrl+C gracefully"""
        print("\n\n👋 Shutting down...")
        self.running = False
    
    def start_audio_stream(self):
        """Start the unified audio stream"""
        try:
            self.audio_stream = self.pa.open(
                rate=self.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.frame_length
            )
            print(f"🎧 Listening for '{self.wake_word}'...")
            print("💡 Say the wake word to start clap detection\n")
        except Exception as e:
            print(f"❌ Error opening audio stream: {e}")
            sys.exit(1)
    
    def detect_wake_word(self, pcm):
        """Detect wake word from audio data"""
        try:
            keyword_index = self.porcupine.process(pcm)
            return keyword_index >= 0
        except Exception as e:
            if self.debug:
                print(f"Wake word error: {e}")
            return False
    
    def detect_clap(self, pcm):
        """Detect clap from audio data"""
        try:
            # Convert to numpy array and get amplitude
            audio_data = np.array(pcm, dtype=np.int16)
            amplitude = np.abs(audio_data).max()
            
            self.amplitude_history.append(amplitude)
            current_time = time.time()
            
            if self.debug and amplitude > 500:
                print(f"Amplitude: {amplitude} (threshold: {self.clap_threshold})")
            
            # Check for sharp sound (clap characteristics)
            amplitude_jump = amplitude - self.previous_amplitude
            sharp_attack = amplitude_jump > (self.clap_threshold * 0.4)
            loud_enough = amplitude > self.clap_threshold
            
            if len(self.amplitude_history) >= 3:
                avg_recent = sum(self.amplitude_history) / len(self.amplitude_history)
                not_sustained = avg_recent < (self.clap_threshold * 0.5)
            else:
                not_sustained = True
            
            is_clap = loud_enough and (sharp_attack or not_sustained)
            
            if is_clap and current_time - self.last_clap_time > 0.1:
                self.clap_times.append(current_time)
                self.last_clap_time = current_time
                print(f"👏 Clap #{len(self.clap_times)} detected!")
                
                # Clean up old claps
                self.clap_times = [t for t in self.clap_times 
                                  if current_time - t < self.clap_interval * 2.5]
                
                # Check for double clap
                if len(self.clap_times) >= 2:
                    time_span = self.clap_times[-1] - self.clap_times[-2]
                    if time_span < self.clap_interval:
                        self.clap_times.clear()
                        return 2
            
            self.previous_amplitude = amplitude
            
            # Clean up old claps periodically
            if len(self.clap_times) > 0 and current_time - self.clap_times[-1] > self.clap_interval * 2:
                self.clap_times.clear()
            
            return 0
            
        except Exception as e:
            if self.debug:
                print(f"Clap detection error: {e}")
            return 0
    
    def activate(self):
        """Activate clap listening mode"""
        self.is_active = True
        self.activation_time = time.time()
        print("\n" + "="*60)
        print(f"✨ '{self.wake_word.upper()}' DETECTED! Listening for claps...")
        print("👏👏  Double clap = Launch apps + enable triple clap mode")
        print("⌨️   Or press Enter / Space to trigger instead of clapping")
        print(f"⏱️  You have {self.active_duration} seconds...")
        print("="*60 + "\n")
    
    def deactivate(self):
        """Deactivate clap listening mode"""
        self.is_active = False
        print(f"\n⏰ Time's up! Say '{self.wake_word}' to try again.\n")
    
    def is_still_active(self):
        """Check if still in active listening window"""
        if not self.is_active:
            return False
        
        elapsed = time.time() - self.activation_time
        if elapsed > self.active_duration:
            self.deactivate()
            return False
            
        return True

    def _keyboard_listener_loop(self):
        """Background thread: set keyboard_triggered when user presses Enter or Space (only when active)."""
        if platform.system() == "Windows":
            try:
                import msvcrt
                line_buffer = []
                while self.running:
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key in (b"\r", b"\n"):
                            typed = b"".join(line_buffer).decode(errors="ignore").strip()
                            if typed == "'":
                                self.instant_launch_triggered = True
                            line_buffer.clear()
                        elif key == b"\x08":  # Backspace
                            if line_buffer:
                                line_buffer.pop()
                        elif key not in (b"\x00", b"\xe0"):  # Ignore special key prefixes
                            line_buffer.append(key)

                        if key in (b"\r", b"\n", b" ") and self.is_active:
                            self.keyboard_triggered = True
                    time.sleep(0.05)
            except Exception:
                pass
        else:
            # Mac/Linux: line input; apostrophe + Enter triggers instant launch.
            # Enter during active window still works as keyboard fallback.
            try:
                while self.running:
                    try:
                        typed = input().strip()
                        if typed == "'":
                            self.instant_launch_triggered = True
                        elif self.is_active:
                            self.keyboard_triggered = True
                    except (EOFError, OSError):
                        break
            except Exception:
                pass

    def _trigger_launch_and_exit(self, reason_text):
        """Run shared launch sequence and stop the app."""
        print(reason_text)
        self.play_jarvis_startup()
        self.launch_all_apps()
        if self.is_active:
            self.deactivate()
        time.sleep(1)
        self.running = False

    def _launch_app_macos(self, app_name, path=None, args=None):
        """Launch an app on macOS"""
        cmd = ["open", "-a", app_name]
        if path:
            cmd.append(path)
        if args:
            cmd.extend(["--args"] + args)
        subprocess.Popen(cmd)
    
    def _launch_app_windows(self, app_command, args=None):
        """Launch an app on Windows without leaving a CMD window open"""
        try:
            if args:
                # Launch executable directly with arguments
                subprocess.Popen([app_command] + args)
            else:
                # Launch executable directly
                subprocess.Popen([app_command])
        except FileNotFoundError:
            # As a fallback, try using os.startfile (works for paths/URLs)
            try:
                os.startfile(app_command)
            except Exception as e:
                print(f"⚠️ Failed to launch '{app_command}': {e}")
    
    def _launch_app_linux(self, app_command, args=None):
        """Launch an app on Linux"""
        if args:
            subprocess.Popen([app_command] + args)
        else:
            subprocess.Popen([app_command])
    
    def launch_all_apps(self):
        """
        Launch all configured apps - automatically detects OS
        
        Customize the apps for each platform below!
        """
        print("\n🚀 DOUBLE CLAP DETECTED! Launching apps...\n")
        
        if self.os_type == "Darwin":  # macOS
            # VS Code with specific folder
            tbt_path = os.path.expanduser("~/code/tbt")
            self._launch_app_macos("Visual Studio Code", path=tbt_path)
            print(f"✅ Launched VS Code with folder: {tbt_path}")
            time.sleep(0.5)
            
            # Chrome with specific URL
            self._launch_app_macos("Google Chrome", args=["--new-window", "https://claude.ai"])
            print("✅ Launched Chrome with https://claude.ai")
            time.sleep(0.5)
            
            # # Discord
            # self._launch_app_macos("Discord")
            # print("✅ Launched Discord")
            # time.sleep(0.5)
            
        elif self.os_type == "Windows":
            # Cursor IDE via Start Menu shortcut (.lnk) to avoid extra CMD windows
            try:
                cursor_shortcut = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Cursor\Cursor.lnk"
                os.startfile(cursor_shortcut)
                print("✅ Launched Cursor")
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️ Could not launch Cursor: {e}")

            # Prefer classic Opera (not Opera GX) by checking its default install path.
            user_profile = os.getenv("USERPROFILE", "C:\\Users\\L")
            opera_path = os.path.join(
                user_profile,
                "AppData",
                "Local",
                "Programs",
                "Opera",
                "opera.exe",
            )
            has_opera = os.path.exists(opera_path)

            # Always open a fresh Opera window if available
            if has_opera:
                try:
                    subprocess.Popen([opera_path])
                    print("✅ Launched Opera")
                    time.sleep(0.5)
                except Exception as e:
                    print(f"⚠️ Could not launch Opera: {e}")

            # ChatGPT native app via URI; fall back to Opera, then default browser
            try:
                os.startfile("chatgpt:")
                print("✅ Launched ChatGPT app")
            except Exception:
                try:
                    if has_opera:
                        subprocess.Popen([opera_path, "https://chatgpt.com"])
                        print("✅ Launched Opera with ChatGPT")
                    else:
                        raise FileNotFoundError("Opera not found at expected path")
                except Exception:
                    try:
                        os.startfile("https://chatgpt.com")
                        print("✅ Launched default browser with ChatGPT")
                    except Exception as e:
                        print(f"❌ Failed to open ChatGPT: {e}")
            time.sleep(0.5)

            # WhatsApp native app via URI; fall back to Opera, then default browser
            try:
                os.startfile("whatsapp:")
                print("✅ Launched WhatsApp app")
            except Exception:
                try:
                    if has_opera:
                        subprocess.Popen([opera_path, "https://web.whatsapp.com"])
                        print("✅ Launched Opera with WhatsApp Web")
                    else:
                        raise FileNotFoundError("Opera not found at expected path")
                except Exception:
                    try:
                        os.startfile("https://web.whatsapp.com")
                        print("✅ Launched default browser with WhatsApp Web")
                    except Exception as e:
                        print(f"❌ Failed to open WhatsApp Web: {e}")
            time.sleep(0.5)
            
        elif self.os_type == "Linux":
            # VS Code
            self._launch_app_linux("code")
            print("✅ Launched VS Code")
            time.sleep(0.5)
            
            # Chrome/Chromium with URL
            try:
                self._launch_app_linux("google-chrome", args=["https://claude.ai"])
                print("✅ Launched Chrome with https://claude.ai")
            except:
                self._launch_app_linux("chromium-browser", args=["https://claude.ai"])
                print("✅ Launched Chromium with https://claude.ai")
            time.sleep(0.5)
            
            # Discord
            # self._launch_app_linux("discord")
            # print("✅ Launched Discord")
            # time.sleep(0.5)
        
        print("\n✨ All apps launched!\n")

    def play_jarvis_startup(self):
        """
        Play the first 3 seconds of the futuristic UI sound when activation is triggered.
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        wav_file = os.path.join(
            script_dir,
            "UI Sounds_ Futuristic sound effects example.wav",
        )

        try:
            import pygame

            pygame.mixer.init()
            sound = pygame.mixer.Sound(wav_file)
            sound.play()

            # Stop playback after 3 seconds without blocking the main loop
            def stop_sound():
                try:
                    pygame.mixer.stop()
                    pygame.mixer.quit()
                except Exception:
                    pass

            timer = threading.Timer(3.0, stop_sound)
            timer.daemon = True
            timer.start()

            print("🎵 Playing futuristic UI sound (first 3 seconds).")
        except Exception as e:
            print(f"⚠️ Could not play JARVIS startup sound: {e}")
    
    def run(self):
        """Main run loop"""
        self.start_audio_stream()

        # Start keyboard listener so Enter/Space can trigger instead of double clap
        self._keyboard_thread = threading.Thread(target=self._keyboard_listener_loop, daemon=True)
        self._keyboard_thread.start()
        
        try:
            while self.running:
                # Read audio frame
                pcm_bytes = self.audio_stream.read(self.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self.frame_length, pcm_bytes)
                
                # Check for wake word when not active
                if not self.is_active:
                    # Optional global bypass: type apostrophe then Enter to launch immediately
                    if self.instant_launch_triggered:
                        self.instant_launch_triggered = False
                        self._trigger_launch_and_exit("⌨️  Instant bypass detected (apostrophe + Enter) – launching apps...")
                        break

                    if self.detect_wake_word(pcm):
                        self.activate()
                
                # Check for claps or keyboard when active (initial 5 second window)
                elif self.is_still_active():
                    # Keyboard fallback: Enter or Space = same as double clap
                    if self.keyboard_triggered:
                        self.keyboard_triggered = False
                        self._trigger_launch_and_exit("⌨️  Enter/Space pressed – launching apps...")
                        break

                    clap_type = self.detect_clap(pcm)
                    
                    if clap_type == 2:  # Double clap
                        # Play UI sound immediately on successful double clap
                        self._trigger_launch_and_exit("👏👏 Double clap detected – launching apps...")
                        break
                        
        except KeyboardInterrupt:
            print("\n\n👋 Shutting down...")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        print("Cleaning up...")
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pa:
            self.pa.terminate()
        if self.porcupine:
            self.porcupine.delete()
        print("Goodbye!")


def _close_console_if_windows():
    """On Windows, close the console window so the CMD terminal doesn't stay open."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass


def main():
    print("=" * 70)
    print("  👏 WAKE UP - Clap Launcher")
    print("=" * 70)
    print("\n🚀 100% LOCAL - No internet needed!")
    print("🗣️  Say wake word → 👏👏 Double clap (or Enter/Space) → Launch apps + startup sound")
    print("⚡ Optional bypass: type ' then press Enter to launch immediately")
    print("\nPress Ctrl+C to exit\n")
    
    debug_mode = "--debug" in sys.argv
    
    # Get wake word from command line or use default
    wake_word = "serena"
    for i, arg in enumerate(sys.argv):
        if arg == "--wake" and i + 1 < len(sys.argv):
            wake_word = sys.argv[i + 1]
    
    if not debug_mode:
        print("💡 Tip: Run with '--debug' to see amplitude levels")
        print("💡 Tip: Run with '--wake computer' to change wake word\n")
    
    launcher = UnifiedLauncher(wake_word=wake_word, clap_threshold=1800, debug=debug_mode)
    launcher.run()
    _close_console_if_windows()


if __name__ == "__main__":
    main()