# inputs.py
import pygame
import config

class InputManager:
    def __init__(self):
        pygame.init()
        pygame.joystick.init()
        self.joysticks = []
        self.scan_joysticks()
        
        # Zmienne klawiatury
        self.key_throttle = 0.0
        self.key_max_limit = 10.0
        
        # Nowa zmienna: zapamiętuje limit ustawiony przez strzałki na padzie
        self.pad_max_limit = 10.0

    def scan_joysticks(self):
        self.joysticks = []
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        count = pygame.joystick.get_count()
        self.joysticks = [pygame.joystick.Joystick(i) for i in range(count)]
        for joy in self.joysticks:
            if not joy.get_init():
                joy.init()
        return self.joysticks

    def handle_keyboard(self, event_type, key_code):
        """Metoda wywoływana z GUI przy zdarzeniach klawiatury"""
        k = key_code.lower()
        
        if event_type == 'press':
            if k == 'w': self.key_throttle = 1.0
            elif k == 's': self.key_throttle = -1.0
            elif k == 'r': self.key_max_limit = min(config.ABSOLUTE_MAX_LIMIT, self.key_max_limit + 1.0)
            elif k == 'f': self.key_max_limit = max(1.0, self.key_max_limit - 1.0)
            
        elif event_type == 'release':
            if k in ['w', 's']: self.key_throttle = 0.0
            
    def update(self, app_state):
        """Oblicza sterowanie i aktualizuje AppState"""
        try:
            events = pygame.event.get()
        except KeyError:
            events = []
        for event in events:
            if event.type == pygame.JOYHATMOTION:
                if event.value[1] == 1:
                    self.pad_max_limit = min(config.ABSOLUTE_MAX_LIMIT, self.pad_max_limit + 1.0)
                elif event.value[1] == -1:
                    self.pad_max_limit = max(1.0, self.pad_max_limit - 1.0)
            
            elif event.type == pygame.JOYBUTTONDOWN:
                # Blokada przycisków pod R3 (zazwyczaj przycisk nr 9 w Pygame dla pada Xbox/SteamDeck)
                if event.button == 9: 
                    app_state.buttons_locked = not app_state.buttons_locked
                    stan_txt = "WŁĄCZONA" if app_state.buttons_locked else "WYŁĄCZONA"
                    app_state.log(f"[Bezpieczeństwo] Blokada przycisków: {stan_txt}")
                
                # Uruchomienie sekwencji pod 'X' (zazwyczaj przycisk nr 2)
                elif event.button == 2:
                    if not app_state.buttons_locked:
                        app_state.trigger_full_start = True
                    else:
                        app_state.log("!! ODRZUCONO: Przyciski zablokowane. Wciśnij prawą gałkę (R3), aby odblokować.")

        joy_throttle = 0.0
        joy_active = False
        steering = 0.0
        
        # Obsługa Joysticka
        if self.joysticks:
            try:
                joy = self.joysticks[0]
                
                # Przekazujemy nasz zaktualizowany strzałkami limit do stanu aplikacji
                app_state.current_speed_limit = self.pad_max_limit
                
                # Gaz/Hamulec - Lewa gałka pionowo (Zazwyczaj Axis 1)
                # Wychylenie w górę daje wartości ujemne, dlatego dajemy minus przed joy.get_axis
                axis1 = -joy.get_axis(1)
                if abs(axis1) > config.JOYSTICK_DEADZONE:
                    joy_throttle = axis1 * app_state.current_speed_limit
                    joy_active = True
                
                # Skręt - Prawa gałka poziomo (Zazwyczaj Axis 3 lub 2)
                if joy.get_numaxes() > 3:
                    steering = joy.get_axis(3)
                elif joy.get_numaxes() > 2:
                    steering = joy.get_axis(2)
                    
            except Exception:
                pass
        else:
            app_state.current_speed_limit = self.key_max_limit

        # Wybór (Joystick vs Klawiatura)
        if joy_active:
            app_state.target_rps = joy_throttle
        else:
            app_state.target_rps = self.key_throttle * app_state.current_speed_limit
            
        app_state.steering_val = steering