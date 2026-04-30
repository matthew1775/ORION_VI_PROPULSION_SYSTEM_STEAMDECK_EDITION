# comms.py
from numpy import int8, isin
import paho.mqtt.client as mqtt
import json
import time
import config
from utils import AppState

class MqttManager:
    def __init__(self, app_state):
        self.client = None
        self.state:AppState = app_state

    def connect(self):
        self.state.log("--- Inicjalizacja MQTT ---")
        try:
            # Używamy dokładnie tej samej wersji API co w Twoim pliku (limited)
            #self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)

            self.client = mqtt.Client()
            
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            
            self.state.log(f"Łączenie z {config.BROKER_ADDRESS}...")
            self.client.connect(config.BROKER_ADDRESS, config.BROKER_PORT)
            self.client.loop_start()
            
        except Exception as e:
            self.state.mqtt_status_text = "MQTT: Błąd"
            self.state.log(f"Błąd krytyczny połączenia: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.state.mqtt_connected = True
            self.state.mqtt_status_text = "MQTT: POŁĄCZONO"
            client.subscribe(config.TOPIC_FEEDBACK)
            self.state.log(">> Połączono z brokerem (RC=0).")
        else:
            self.state.mqtt_status_text = f"MQTT: Błąd {rc}"
            self.state.log(f"Błąd połączenia, kod: {rc}")

    #feedback message:
    #[
    #   0: side (0- left|1- right)
    #   1: measured velocity of the front ODrive
    #   2: measured position of the front ODrive
    #   3: measured velocity of the rear ODrive
    #   4: measured position of the rear ODrive
    #]
    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            if "error" in payload:
                if "odrive_id" in payload:
                    self.state.log(f"!! ERROR: {payload['error']} (odrive_id: {payload['odrive_id']})")
                self.state.log(f"!! ERROR: {payload['error']} (odrive_id: -)")
                return
            
            if isinstance(payload, dict) and "error" in payload:
                oid = payload.get("odrive_id", "-")
                self.state.log(f"!! ODRIVE ERROR: {payload['error']} (ID: {oid})")
                return # Exit here

            if not isinstance(payload, list) or len(payload) != 5:
                self.state.log(f"!! ERROR: feedback data is of a wrong format: {payload}")
                return

            side:int8 = payload[0]
            estimate_lag_sum:float = 0

            for i in range(2):
                self.state.o_drives[str(i) + str(side)].measured_velocity = payload[i * 2 + 1]
                self.state.o_drives[str(i) + str(side)].measured_position = payload[i * 2 + 2]
                self.state.o_drives[str(i) + str(side)].last_feedback_time = time.time()
                estimate_lag_sum += self.state.o_drives[str(i) + str(side)].measured_velocity

            # TODO: separate lag calculation and storage for both sides. 
            # Now, it pushes latency only for one side read at a time, calculating the mean value
            # Lag estimator (jeśli używasz utils.py z poprzedniej wersji)
            self.state.latency_estimator.estimate_lag(estimate_lag_sum / 2)
            
            
        except json.JSONDecodeError:
            raw = msg.payload.decode()
            self.state.log(f"[JSON DECODE ERROR] MSG (RAW): {raw}")
        except Exception as e:
            # Ciche ignorowanie błędów parsowania, żeby nie spamować konsoli
            pass

    def send_drive_command(self):
            """Wysyła ramkę sterującą JSON: velocity + steering"""
            if self.client and self.state.mqtt_connected:
                payload = {
                    "velocity": round(self.state.target_rps, 3),
                    "steering": round(self.state.steering_val, 3)
                }
                try:
                    # Generujemy JSONa raz
                    payload_json = json.dumps(payload)
                    
                    # Publikacja na oryginalny temat
                    self.client.publish(config.TOPIC_SET_VELOCITY, payload_json)
                    
                    # Publikacja zduplikowana na prawą stronę
                    self.client.publish(f"{config.TOPIC_SET_VELOCITY}_right", payload_json)
                    
                    self.state.latency_estimator.push_target(self.state.target_rps)
                except Exception as e:
                    self.state.log(f"Błąd wysyłania: {e}")

    def send_cmd(self, cmd, target="a"):
            """
            target:
                "a" -> override
                "l" -> LF+LR
                "r" -> RF+RR
                "lf", "lr", "rf", "rr" -> single wheel
            """
            if not (self.client and self.state.mqtt_connected):
                return

            #   command:
            #   0 - no command,
            #   1 - calibrate,
            #   2 - closed_loop,
            #   3 - set_vel_mode,
            #   4 - set_ramp_mode,
            #   5 - dump_errors,
            #   6 - reboot_odrive
            
            if cmd not in config.CMD_MAP:
                self.state.log(f"[MQTT] Unknown cmd: {cmd}")
                return

            payload = [0, 0, 0, 0, 0]  # LF, LR, RF, RR, OVERRIDE
            val = config.CMD_MAP[cmd]

            if target == "a":
                payload[4] = val
            elif target == "l":
                payload[0] = payload[1] = val
            elif target == "r":
                payload[2] = payload[3] = val
            elif target == "lf":
                payload[0] = val
            elif target == "lr":
                payload[1] = val
            elif target == "rf":
                payload[2] = val
            elif target == "rr":
                payload[3] = val

            try:
                # Generujemy JSONa raz
                payload_json = json.dumps(payload)
                
                # Publikacja na oryginalny temat
                self.client.publish(config.TOPIC_CMD, payload_json)
                
                # Publikacja zduplikowana na prawą stronę
                self.client.publish(f"{config.TOPIC_CMD}_right", payload_json)
                
                self.state.log(f">> CMD: {cmd} ({target}) -> {payload}")
            except Exception as e:
                self.state.log(f"[MQTT] Send error: {e}")