import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time
from collections import deque
import subprocess
import platform

import config

from comms import MqttManager
from inputs import InputManager
from utils import AppState


class DashboardGUI:
    def __init__(self, root, app_state, input_manager, mqtt_manager):
        self.root = root
        self.state : AppState = app_state
        self.input_manager : InputManager = input_manager
        self.mqtt_manager : MqttManager = mqtt_manager
        
        # --- DODANE ZMIENNE ---
        self._last_locked_state = None
        self._is_full_start_running = False
        # ----------------------

        self.start_time = time.time()
        self.setup_ui()
        self._start_network_monitor()


    def _ping_host(self, ip):
        """Pomocnicza funkcja pingująca dany adres IP (nieblokująca)"""
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
        timeout_val = '500' if platform.system().lower() == 'windows' else '1' # 500ms dla Win, 1s dla Linux
        
        try:
            # Pingujemy 1 pakiet z krótkim timeoutem
            command = ['ping', param, '5', timeout_param, timeout_val, ip]
            # Używamy subprocess.call z ukryciem wyjścia (stdout=DEVNULL)
            response = subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return response == 0
        except Exception:
            return False

    def _check_connection(self, host, port=None):
        """
        Uniwersalna funkcja sprawdzająca połączenie.
        Dla Brokera (port podany) -> Używa szybkiego testu TCP (socket).
        Dla Routera (brak portu) -> Używa systemowego PING.
        """
        try:
            if port:
                # METODA 1: Test TCP (Socket) - Idealna dla MQTT
                # Działa natychmiastowo i sprawdza czy usługa faktycznie działa
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5) # Max 500ms czekania
                result = sock.connect_ex((host, port))
                sock.close()
                return result == 0 # 0 oznacza sukces (połączono)
            
            else:
                # METODA 2: Systemowy Ping (ICMP) - Dla Routera
                param = '-n' if platform.system().lower() == 'windows' else '-c'
                timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
                # Windows: timeout w ms (500), Linux: timeout w s (1)
                timeout_val = '500' if platform.system().lower() == 'windows' else '1'
                
                cmd = ['ping', param, '1', timeout_param, timeout_val, host]
                
                # Ukrycie mrugającego okna konsoli na Windows
                startupinfo = None
                if platform.system().lower() == 'windows':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                # stdout=subprocess.DEVNULL ucisza wyjście w konsoli
                response = subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
                return response == 0
                
        except Exception as e:
            print(f"Błąd sprawdzania sieci: {e}")
            return False

    def reconnect_mqtt(self):
        """Obsługa przycisku Reconnect w osobnym wątku"""
        def _worker():
            self.state.log(">> [GUI] Próba ręcznego reconnectu...")
            try:
                # Jeśli klient już istnieje, próbujemy funkcji reconnect() z biblioteki paho
                if self.mqtt_manager.client:
                    self.mqtt_manager.client.reconnect()
                    self.state.log(">> [GUI] Wysłano żądanie reconnect().")
                else:
                    # Jeśli klient nie istnieje (np. błąd przy starcie), inicjalizujemy od nowa
                    self.mqtt_manager.connect()
            except Exception as e:
                self.state.log(f"!! Błąd reconnect: {e}")
                # Fallback: próba pełnej reinicjalizacji
                try:
                    self.mqtt_manager.connect()
                except Exception as e2:
                    self.state.log(f"!! Błąd fatalny reconnect: {e2}")
        # Uruchomienie w tle, aby nie blokować GUI
        threading.Thread(target=_worker, daemon=True).start()

    def _start_network_monitor(self):
        """Uruchamia wątek sprawdzający połączenie w tle"""
        def monitor_loop():
            print(">> [System] Start monitorowania sieci (Ping/Socket)...")
            while True:
                # 1. Sprawdzenie Brokera (192.168.1.1 na porcie 1883)
                # To wykryje odłączenie kabla znacznie szybciej niż ping
                self.state.ping_broker_ok = self._check_connection("192.168.1.1", 1883)
                
                # 2. Sprawdzenie Routera (192.168.1.102, 192.168.1.101 przez PING)
                self.state.ping_router_ok = self._check_connection("192.168.1.102", 443)
                self.state.ping_ground_ok = self._check_connection("192.168.1.101", 443)
                # Opcjonalnie: Debug w konsoli (odkomentuj, jeśli nadal będą problemy)
                # print(f"[NetCheck] Broker: {self.state.ping_broker_ok}, Router: {self.state.ping_router_ok}")
                
                time.sleep(1) # Sprawdzaj co 1 sekundę

        threading.Thread(target=monitor_loop, daemon=True).start()
        
    def setup_ui(self):
        self.root.configure(bg=config.BG_COLOR)
        # Layout Frames
        self.main_frame = tk.Frame(self.root, bg=config.BG_COLOR)
        self.main_frame.pack(fill="both", expand=True)

        # Lewy panel węższy (bez wykresu)
        self.left_frame = tk.Frame(self.main_frame, bg=config.BG_COLOR, width=300)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)
        self.left_frame.pack_propagate(False)

        # Środkowy panel dostaje więcej miejsca na płytki informacji
        self.center_frame = tk.Frame(self.main_frame, bg=config.BG_COLOR)
        self.center_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        # Prawy panel dopasowany do szerokości Decka
        self.right_frame = tk.Frame(self.main_frame, bg=config.BG_COLOR, width=350)
        self.right_frame.pack(side="left", fill="y", padx=10, pady=10)
        self.right_frame.pack_propagate(False)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    def _build_left_panel(self):
        # Joysticki
        self.joy_container = tk.Frame(self.left_frame, bg=config.BG_COLOR)
        self.joy_container.pack(side="top", fill="x")
        self.joystick_list_frame = tk.Frame(self.joy_container, bg=config.BG_COLOR)
        
        tk.Button(self.joy_container, text="  RESET JOYSTICK", command=self.refresh_joysticks, 
                  bg=config.BTN_RESET_COLOR, fg="white", font=("Arial", 10, "bold")).pack(fill="x", pady=(0,10))
        self.joystick_list_frame.pack(fill="both", expand=True)

        # Instrukcja
        instr = tk.LabelFrame(self.left_frame, text="Klawiatura", bg=config.BG_COLOR, fg="#ccc")
        instr.pack(fill="x", pady=10)
        tk.Label(instr, text="[W]/[S] - Przód/Tył | [R]/[F] - Limit", bg=config.BG_COLOR, fg="white", font=("Arial", 10, "bold")).pack()
        tk.Label(instr, text="[ESC] - Zamknij fullscreen", bg=config.BG_COLOR, fg="#888").pack()

    def _build_center_panel(self):
        # Gauge (Zegary)
# Gauge (Zegary) - Wersja kompaktowa
        gauge_frame = tk.LabelFrame(self.center_frame, text="Wskaźniki", bg=config.BG_COLOR, fg=config.FG_COLOR)
        gauge_frame.pack(pady=5, fill="both") # Mniejszy margines
        
        # Znacznie mniejszy Canvas
        self.gauge_canvas = tk.Canvas(gauge_frame, width=240, height=140, bg=config.BG_COLOR, highlightthickness=0)
        self.gauge_canvas.pack(pady=5)
        
        # Mniejsze czcionki dla etykiet
        self.lbl_target = tk.Label(gauge_frame, text="Target: 0.0 RPS", bg=config.BG_COLOR, fg="white", font=("Arial", 16, "bold"))
        self.lbl_target.pack()
        self.lbl_steering = tk.Label(gauge_frame, text="Steering: 0.00", bg=config.BG_COLOR, fg="#FFAA00", font=("Arial", 12))
        self.lbl_steering.pack(pady=(0, 5))

        self.odrive_widgets = {}

        container = tk.Frame(self.center_frame, bg=config.BG_COLOR)
        container.pack(fill="both", expand=True)

        ids = ["00", "10", "01", "11"]

        for i, odrive_id in enumerate(ids):
            frame, odrive_widget = self._build_odrive_panel(container, odrive_id)

            row = i // 2
            col = i % 2

            frame.grid(row = row, column= col, sticky="nsew", padx=5, pady=5)

            self.odrive_widgets[odrive_id] = odrive_widget

        for i in range(2):
            container.grid_rowconfigure(i, weight=1)
            container.grid_columnconfigure(i, weight=1)

        # Feedback Frame
        fb_frame = tk.LabelFrame(self.center_frame, text="Feedback & Diagnostyka", bg=config.BG_COLOR, fg="#00ff00")
        fb_frame.pack(pady=20, fill="x", padx=10)
        
        # 1. RPS (Dodano)
        self.lbl_meas_vel = tk.Label(fb_frame, text="RPS: 0.00", bg=config.BG_COLOR, fg="#00ff00", font=("Consolas", 18))
        self.lbl_meas_vel.pack(anchor="w", padx=10, pady=2)

        # 2. Kontener prędkości (km/h i m/s obok siebie)
        speed_container = tk.Frame(fb_frame, bg=config.BG_COLOR)
        speed_container.pack(anchor="w", padx=10, pady=2)
        
        self.lbl_kmh = tk.Label(speed_container, text="0.0 km/h", bg=config.BG_COLOR, fg="#ff00ff", font=("Consolas", 20, "bold"))
        self.lbl_kmh.pack(side="left", padx=(0, 20))
        
        self.lbl_ms = tk.Label(speed_container, text="0.00 m/s", bg=config.BG_COLOR, fg="#ff88ff", font=("Consolas", 14))
        self.lbl_ms.pack(side="left")

        # 3. Pozycja
        self.lbl_pos = tk.Label(fb_frame, text="Pozycja: 0.00 obr", bg=config.BG_COLOR, fg="#00ccff", font=("Consolas", 18))
        self.lbl_pos.pack(anchor="w", padx=10, pady=5)
        
        # 4. Dystans i Reset
        dist_container = tk.Frame(fb_frame, bg=config.BG_COLOR)
        dist_container.pack(anchor="w", padx=10, pady=5)
        
        self.lbl_dist = tk.Label(dist_container, text="Dystans: 0.00 m", bg=config.BG_COLOR, fg="white", font=("Consolas", 18))
        self.lbl_dist.pack(side="left")
        
        #tk.Button(dist_container, text="[RESET]", command=lambda : self.reset_trip(), bg="#444", fg="white", font=("Arial", 10)).pack(side="left", padx=10)
        
        tk.Frame(fb_frame, height=1, bg="#444").pack(fill="x", padx=5, pady=5)
        
        # 5. Diagnostyka (Packet Age + Lag)
        self.lbl_packet_age = tk.Label(fb_frame, text="Sieć (Packet Age): -- ms", bg=config.BG_COLOR, fg="#aaaaaa", font=("Consolas", 11))
        self.lbl_packet_age.pack(anchor="w", padx=10)

        self.lbl_lag = tk.Label(fb_frame, text="Lag: -- ms", bg=config.BG_COLOR, fg="#aaaaaa", font=("Consolas", 16, "bold"))
        self.lbl_lag.pack(anchor="w", padx=10, pady=(5,10))

    def _build_odrive_panel(self, parent, odrive_id):
        frame = tk.LabelFrame(parent, text=f"ODrive {odrive_id}", bg=config.BG_COLOR, fg="#00ff00")
        frame.grid_propagate(False)

        widgets = {}

        # --- RPS ---
        widgets["lbl_rps"] = tk.Label(
            frame, text="RPS: 0.00",
            bg=config.BG_COLOR, fg="#00ff00",
            font=("Consolas", 16)
        )
        widgets["lbl_rps"].pack(anchor="w", padx=10, pady=2)

        # --- Speed container ---
        speed_container = tk.Frame(frame, bg=config.BG_COLOR)
        speed_container.pack(anchor="w", padx=10, pady=2)

        widgets["lbl_kmh"] = tk.Label(
            speed_container, text="0.0 km/h",
            bg=config.BG_COLOR, fg="#ff00ff",
            font=("Consolas", 16, "bold")
        )
        widgets["lbl_kmh"].pack(side="left", padx=(0, 15))

        widgets["lbl_ms"] = tk.Label(
            speed_container, text="0.00 m/s",
            bg=config.BG_COLOR, fg="#ff88ff",
            font=("Consolas", 12)
        )
        widgets["lbl_ms"].pack(side="left")

        # --- Position ---
        widgets["lbl_pos"] = tk.Label(
            frame, text="Pozycja: 0.00 obr",
            bg=config.BG_COLOR, fg="#00ccff",
            font=("Consolas", 14)
        )
        widgets["lbl_pos"].pack(anchor="w", padx=10, pady=5)

        # --- Distance + Reset ---
        dist_container = tk.Frame(frame, bg=config.BG_COLOR)
        dist_container.pack(anchor="w", padx=10, pady=5)

        widgets["lbl_dist"] = tk.Label(
            dist_container, text="Dystans: 0.00 m",
            bg=config.BG_COLOR, fg="white",
            font=("Consolas", 14)
        )
        widgets["lbl_dist"].pack(side="left")

        # IMPORTANT: bind odrive_id
        widgets["btn_reset"] = tk.Button(
            dist_container,
            text="[RESET]",
            command=lambda oid=odrive_id: self.reset_trip([oid]),
            bg="#444", fg="white",
            font=("Arial", 9)
        )
        widgets["btn_reset"].pack(side="left", padx=10)

        # --- Separator ---
        tk.Frame(frame, height=1, bg="#444").pack(fill="x", padx=5, pady=5)

        # --- Packet Age ---
        widgets["lbl_packet_age"] = tk.Label(
            frame,
            text="Sieć (Packet Age): -- ms",
            bg=config.BG_COLOR,
            fg="#aaaaaa",
            font=("Consolas", 10)
        )
        widgets["lbl_packet_age"].pack(anchor="w", padx=10)

        # --- Lag ---
        widgets["lbl_lag"] = tk.Label(
            frame,
            text="Lag: -- ms",
            bg=config.BG_COLOR,
            fg="#aaaaaa",
            font=("Consolas", 12, "bold")
        )
        widgets["lbl_lag"].pack(anchor="w", padx=10, pady=(5, 10))

        return frame, widgets

    def _build_right_panel(self):
        # --- ZMIANA START: Pasek nagłówka z przyciskiem Reconnect ---
        header_frame = tk.Frame(self.right_frame, bg=config.BG_COLOR)
        header_frame.pack(fill="x", side="top", pady=(0, 5))

        # 1. Lewa strona nagłówka: Status tekstowy MQTT
        status_col = tk.Frame(header_frame, bg=config.BG_COLOR)
        status_col.pack(side="left")
        self.lbl_mqtt_status = tk.Label(status_col, text="MQTT: --", 
                                      bg=config.BG_COLOR, fg=config.FG_COLOR, font=("Arial", 10))
        self.lbl_mqtt_status.pack(anchor="w")

        # 2. Prawa strona nagłówka: Diody PING + Przycisk Reconnect
        controls_col = tk.Frame(header_frame, bg=config.BG_COLOR)
        controls_col.pack(side="right")

        # --- SEKCJA DIOD (Zaktualizowana) ---
        # Zwiększamy szerokość width=200, żeby zmieścić 3 diody
        self.led_canvas = tk.Canvas(controls_col, width=200, height=25, bg=config.BG_COLOR, highlightthickness=0)
        self.led_canvas.pack(side="top", pady=(0, 5))

        # 1. Ground (.101) - Pierwsze ogniwo (Ty)
        self.led_ground = self.led_canvas.create_oval(5, 5, 20, 20, fill="grey", outline="white")
        self.led_canvas.create_text(25, 12, text="Gnd", fill="white", anchor="w", font=("Arial", 8))

        # 2. Rover (.100) - Drugie ogniwo (Most)
        self.led_router = self.led_canvas.create_oval(65, 5, 80, 20, fill="grey", outline="white")
        self.led_canvas.create_text(85, 12, text="Rover", fill="white", anchor="w", font=("Arial", 8))

        # 3. Broker (.1) - Cel (Mózg)
        self.led_broker = self.led_canvas.create_oval(130, 5, 145, 20, fill="grey", outline="white")
        self.led_canvas.create_text(150, 12, text="MQTT", fill="white", anchor="w", font=("Arial", 8))

        # Przycisk Reconnect (z poprzedniego zadania)
        self.btn_reconnect = tk.Button(controls_col, text="Reconnect MQTT", command=self.reconnect_mqtt, 
                                     bg="#d9534f", fg="white", font=("Arial", 8, "bold"), width=15)
        self.btn_reconnect.pack(side="top")

        # ... (Dalsza część metody bez zmian: console, cmd_frame itp.) ...
        self.console = scrolledtext.ScrolledText(self.right_frame, bg="#222", fg="#0f0", height=15, font=("Consolas", 10))
        self.console.pack(fill="both", expand=True, pady=5)
        
        # ... (reszta przycisków cmd_frame bez zmian) ...
        cmd_frame = tk.LabelFrame(self.right_frame, text="Polecenia ODrive", bg=config.BG_COLOR, fg=config.FG_COLOR)
        cmd_frame.pack(fill="x", side="bottom", pady=20)
        
        # ... (pozostałe przyciski: btn_full_start itp.) ...
        self.btn_full_start = tk.Button(cmd_frame, text="★ FULL START (AUTO) ★", command=self.run_full_start, 
                                        bg=config.BTN_FULL_START_COLOR, fg="white", height=2, font=("Arial", 11, "bold"))
        self.btn_full_start.pack(fill="x", padx=10, pady=(10, 20))
        
        # (Tutaj powinna być reszta Twoich przycisków z oryginalnego pliku)
        self.btn_calib = tk.Button(cmd_frame, text="1. KALIBRACJA", command=lambda: self.mqtt_manager.send_cmd("calibrate"), 
                  bg="#AA8800", fg="white", height=1)
        
        self.btn_calib.pack(fill="x", padx=10, pady=2)
                  
        self.btn_closed_loop = tk.Button(cmd_frame, text="2. CLOSED LOOP", command=lambda: self.mqtt_manager.send_cmd("closed_loop"), 
                  bg="#006600", fg="white", height=1)
        self.btn_closed_loop.pack(fill="x", padx=10, pady=2)
                  
        self.btn_vel_mode = tk.Button(cmd_frame, text="3. TRYB VELOCITY", command=lambda: self.mqtt_manager.send_cmd("set_vel_mode"), 
                  bg="#004488", fg="white", height=1)
        self.btn_vel_mode.pack(fill="x", padx=10, pady=2)
                  
        self.btn_ramp_mode = tk.Button(cmd_frame, text="4. RAMP MODE", command=lambda: self.mqtt_manager.send_cmd("set_ramp_mode"), 
                  bg="#550088", fg="white", height=1)
        self.btn_ramp_mode.pack(fill="x", padx=10, pady=2)

        self.btn_dump_errors = tk.Button(cmd_frame, text="DUMP ERRORS (odrv0)", command=lambda: self.mqtt_manager.send_cmd("dump_errors"), 
                  bg=config.BTN_DUMP_COLOR, fg="white", height=1, font=("Arial", 10, "bold"))
        self.btn_dump_errors.pack(fill="x", padx=10, pady=(10, 2))
        
        self.btn_reboot_odrive = tk.Button(cmd_frame, text="⚠ REBOOT ODRIVE", command=lambda: self.mqtt_manager.send_cmd("reboot_odrive"), 
                  bg=config.BTN_REBOOT_COLOR, fg="white", height=1, font=("Arial", 10, "bold"))
        self.btn_reboot_odrive.pack(fill="x", padx=10, pady=(10, 2))

    def refresh_joysticks(self):
        joysticks = self.input_manager.scan_joysticks()
        for widget in self.joystick_list_frame.winfo_children():
            widget.destroy()
        if not joysticks:
            tk.Label(self.joystick_list_frame, text="BRAK JOYSTICKA (Użyj Klawiatury)", bg=config.BG_COLOR, fg="yellow").pack()
        for i, joy in enumerate(joysticks):
            joy_name = joy.get_name()[:15]
            tk.Label(self.joystick_list_frame, text=f"Joy {i}: {joy_name}", bg=config.BG_COLOR, fg="white").pack(anchor="w")

    def reset_trip(self, ids: list[str]):
        for id in ids:
            if (not id in ['00', '10', '01', '11']):
                print("Unknown id! Expected id = '00' | '10' | '01' | '11', instead got {id}")
                return
            self.state.o_drives[id].start_position_offset = self.state.o_drives[id].measured_position
            self.lbl_dist.config(text="Dystans: 0.00 m")

    def run_full_start(self):
        self._is_full_start_running = True  # <-- DODANE
        threading.Thread(target=self._full_start_thread, daemon=True).start()

    def _full_start_thread(self):
        self.state.log("\n=== FULL START SEQUENCE ===")
        self.mqtt_manager.send_cmd("calibrate")

        self.btn_full_start.config(state="disabled", bg="#555555")

        self.btn_calib.config(state="disabled", bg="#555555")
        self.btn_closed_loop.config(state="disabled", bg="#555555")
        self.btn_dump_errors.config(state="disabled", bg="#555555")
        self.btn_ramp_mode.config(state="disabled", bg="#555555")
        self.btn_reboot_odrive.config(state="disabled", bg="#555555")
        self.btn_vel_mode.config(state="disabled", bg="#555555")
        
        for i in range(10, 0, -1):
            self.root.after(0, lambda t=i: self.btn_full_start.config(text=f"CZEKAJ: {t}s..."))
            time.sleep(1)
        
        self.root.after(0, lambda: self.btn_full_start.config(text="KONFIGURACJA..."))
        self.mqtt_manager.send_cmd("closed_loop")
        time.sleep(0.1)
        self.mqtt_manager.send_cmd("set_vel_mode")
        time.sleep(0.1)
        self.mqtt_manager.send_cmd("set_ramp_mode")
        
        self.state.log("=== FULL START ZAKOŃCZONY ===\n")

        def enable_buttons():
            self.btn_full_start.config(text="★ FULL START (AUTO) ★", state="normal", bg=config.BTN_FULL_START_COLOR)
            self.btn_calib.config(state="normal", bg="#AA8800")
            self.btn_closed_loop.config(state="normal", bg="#006600")

            self.btn_vel_mode.config(state="normal", bg="#004488")

            self.btn_ramp_mode.config(state="normal", bg="#550088")

            self.btn_dump_errors.config(state="normal", bg=config.BTN_DUMP_COLOR)
            self.btn_reboot_odrive.config(state="normal", bg=config.BTN_REBOOT_COLOR)
            # --- DODANE ---
            self._is_full_start_running = False
            self._last_locked_state = None  # Wymusza odświeżenie kolorów w GUI
            # --------------n  
        
        self.root.after(0, enable_buttons)

    def update_interface(self):
        self.lbl_target.config(text=f"Target: {self.state.target_rps:.2f} RPS")
        self.lbl_steering.config(text=f"Steering: {self.state.steering_val:.2f}")
        self.lbl_mqtt_status.config(text=self.state.mqtt_status_text)

        # --- NOWY KOD: Obsługa blokady przycisków na czarno ---
        if not self._is_full_start_running:
            if self.state.buttons_locked != self._last_locked_state:
                self._last_locked_state = self.state.buttons_locked
                if self.state.buttons_locked:
                    # Blokujemy i zmieniamy kolory na czarny
                    bg_locked = "black"
                    fg_locked = "#444444" # Ciemnoszary, ledwo widoczny tekst
                    self.btn_full_start.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_calib.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_closed_loop.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_vel_mode.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_ramp_mode.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_dump_errors.config(state="disabled", bg=bg_locked, fg=fg_locked)
                    self.btn_reboot_odrive.config(state="disabled", bg=bg_locked, fg=fg_locked)
                else:
                    # Odblokowujemy i przywracamy oryginalne kolory
                    self.btn_full_start.config(state="normal", bg=config.BTN_FULL_START_COLOR, fg="white")
                    self.btn_calib.config(state="normal", bg="#AA8800", fg="white")
                    self.btn_closed_loop.config(state="normal", bg="#006600", fg="white")
                    self.btn_vel_mode.config(state="normal", bg="#004488", fg="white")
                    self.btn_ramp_mode.config(state="normal", bg="#550088", fg="white")
                    self.btn_dump_errors.config(state="normal", bg=config.BTN_DUMP_COLOR, fg="white")
                    self.btn_reboot_odrive.config(state="normal", bg=config.BTN_REBOOT_COLOR, fg="white")
        # ----------------------------------------------------

        for odrive_id, odrv in self.state.o_drives.items():
            widgets = self.odrive_widgets.get(odrive_id)
            if not widgets:
                continue

            meas_rps = odrv.measured_velocity
            speed_ms = meas_rps * config.DISTANCE_PER_MOTOR_REV
            speed_kmh = speed_ms * 3.6

            widgets["lbl_rps"].config(text=f"RPS: {meas_rps:.2f}")
            widgets["lbl_kmh"].config(text=f"{speed_kmh:.1f} km/h")
            widgets["lbl_ms"].config(text=f"{speed_ms:.2f} m/s")

            widgets["lbl_pos"].config(text=f"Pozycja: {odrv.measured_position:.2f} obr")

            trip_turns = odrv.measured_position - odrv.start_position_offset
            trip_distance = trip_turns * config.DISTANCE_PER_MOTOR_REV
            widgets["lbl_dist"].config(text=f"Dystans: {trip_distance:.2f} m")

            # Packet Age
            if odrv.last_feedback_time > 0:
                diff_ms = (time.time() - odrv.last_feedback_time) * 1000.0
                widgets["lbl_packet_age"].config(text=f"Packet Age: {int(diff_ms)} ms")

                if diff_ms < 200:
                    widgets["lbl_packet_age"].config(fg="#88ff88")
                elif diff_ms < 500:
                    widgets["lbl_packet_age"].config(fg="orange")
                else:
                    widgets["lbl_packet_age"].config(fg="red")
            else:
                widgets["lbl_packet_age"].config(text="Brak danych", fg="grey")

            # Lag (optional: per-module or global)
            lag = self.state.latency_estimator.estimate_lag(meas_rps)
            if lag is not None:
                widgets["lbl_lag"].config(text=f"Lag: {int(lag)} ms")

                if lag < 300:
                    widgets["lbl_lag"].config(fg="#00ff00")
                elif lag < 600:
                    widgets["lbl_lag"].config(fg="orange")
                else:
                    widgets["lbl_lag"].config(fg="red")

        # --- AKTUALIZACJA 3 DIOD SIECIOWYCH ---
        color_ground = "#00ff00" if self.state.ping_ground_ok else "#444"
        color_router = "#00ff00" if self.state.ping_router_ok else "#444"
        color_broker = "#00ff00" if self.state.ping_broker_ok else "#444"
        
        # Ostrzeżenie: Jeśli mamy połączenie MQTT, a system twierdzi że brak sieci, dajemy żółty
        if self.state.mqtt_connected and not self.state.ping_broker_ok:
             color_broker = "orange"

        self.led_canvas.itemconfig(self.led_ground, fill=color_ground)
        self.led_canvas.itemconfig(self.led_router, fill=color_router)
        self.led_canvas.itemconfig(self.led_broker, fill=color_broker)

        # Console logs
        while self.state.logs:
            msg = self.state.logs.pop(0)
            self.console.insert(tk.END, msg + "\n")
            self.console.see(tk.END)

        # Draw Gauge
        self._draw_gauge(self.state.target_rps)


    def _draw_gauge(self, val):
        self.gauge_canvas.delete("all")
        
        # Nowe, mniejsze współrzędne środka (cx, cy) i promień (r)
        cx, cy, r = 120, 110, 90 
        max_v = config.ABSOLUTE_MAX_LIMIT
        
        # Cieńszy pasek (width=15 zamiast 25)
        self.gauge_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=0, extent=180, style="arc", outline="#333", width=15)
        
        limit_angle = (self.state.current_speed_limit / max_v) * 180
        self.gauge_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=180, extent=-limit_angle, style="arc", outline="#665500", width=15)
        
        val_clamped = max(-max_v, min(max_v, val))
        draw_angle = (val_clamped / max_v) * 90 
        
        color = "#00ff00" if val >= 0 else "#ff5500"
        self.gauge_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=90, extent=-draw_angle, style="arc", outline=color, width=15)
        
        # Pomniejszone czcionki i przesunięte teksty na środku zegara
        self.gauge_canvas.create_text(cx, cy-15, text=f"{val:.1f}", fill="white", font=("Arial", 24, "bold"))
        self.gauge_canvas.create_text(cx, cy+20, text=f"Max: {self.state.current_speed_limit:.1f} RPS", fill="#888", font=("Arial", 10))