# main.py — @new200013
# Sound Booster MAX
# CREDIT: Dev Coding Knowledge Forever
#         Dev Poltu Bag from Ambika Kalna

import os, json, time, threading, traceback
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.gridlayout import GridLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.graphics import Color, Rectangle
from kivy.clock import Clock
from kivy.core.window import Window

BRAND = "@new200013"
REQ_CODE = 20013
SR = 44100
BUF_BYTES = 16384
TAPS = 63

USAGE_MEDIA = 1
USAGE_GAME = 14
USAGE_UNKNOWN = 0
USAGE_ASSISTANCE_ACCESSIBILITY = 11
CONTENT_TYPE_MUSIC = 2

PRESET_FILE = "/sdcard/boost_preset.json"


def log(x):
    try:
        print(f"{BRAND} — {x}")
    except Exception:
        pass


def _act():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def request_all_perms():
    try:
        from android.permissions import request_permissions, Permission
        perms = [Permission.RECORD_AUDIO]
        try: perms.append(Permission.MODIFY_AUDIO_SETTINGS)
        except Exception: pass
        try: perms.append(Permission.POST_NOTIFICATIONS)
        except Exception: pass
        request_permissions(perms)
    except Exception as e:
        log(f"perm fail: {e}")


def has_rec_perm():
    try:
        from android.permissions import check_permission, Permission
        return check_permission(Permission.RECORD_AUDIO)
    except Exception:
        return False


_wl = None


def wakelock_on():
    global _wl
    try:
        from jnius import autoclass, cast
        act = _act()
        Context = autoclass("android.content.Context")
        PM = autoclass("android.os.PowerManager")
        pm = cast(PM, act.getSystemService(Context.POWER_SERVICE))
        _wl = pm.newWakeLock(
            PM.PARTIAL_WAKE_LOCK | PM.SCREEN_BRIGHT_WAKE_LOCK
            | PM.ON_AFTER_RELEASE, "@new200013:boost")
        _wl.acquire(12 * 60 * 60 * 1000)
    except Exception as e:
        log(f"wakelock: {e}")


def wakelock_off():
    global _wl
    try:
        if _wl is not None:
            _wl.release()
            _wl = None
    except Exception:
        pass


def keep_screen(on):
    try:
        from jnius import autoclass
        LP = autoclass("android.view.WindowManager$LayoutParams")
        act = _act()
        if on:
            act.getWindow().addFlags(LP.FLAG_KEEP_SCREEN_ON)
        else:
            act.getWindow().clearFlags(LP.FLAG_KEEP_SCREEN_ON)
    except Exception:
        pass


def _lowpass_fir(cutoff, sr, taps=TAPS):
    n = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(2 * cutoff / sr * n) * (2 * cutoff / sr)
    w = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(taps) / (taps - 1))
    h = h * w
    h = h / np.sum(h)
    return h.astype(np.float32)


def _highpass_fir(cutoff, sr, taps=TAPS):
    lp = _lowpass_fir(cutoff, sr, taps)
    hp = -lp.copy()
    hp[(taps - 1) // 2] += 1.0
    return hp.astype(np.float32)


BASS_FIR = _lowpass_fir(300, SR)
TREB_FIR = _highpass_fir(3000, SR)

PRESETS = {
    "Flat":    {"bass": 1.0, "mid": 1.0, "treb": 1.0, "widen": 1.0, "gain": 1.5},
    "Bass":    {"bass": 2.5, "mid": 0.9, "treb": 1.1, "widen": 1.2, "gain": 2.0},
    "Vocal":   {"bass": 0.7, "mid": 1.8, "treb": 1.4, "widen": 0.9, "gain": 1.8},
    "Concert": {"bass": 1.6, "mid": 1.0, "treb": 1.3, "widen": 1.6, "gain": 2.0},
    "Night":   {"bass": 1.2, "mid": 1.1, "treb": 1.0, "widen": 1.0, "gain": 2.5},
    "EDM":     {"bass": 2.2, "mid": 0.9, "treb": 1.4, "widen": 1.8, "gain": 2.2},
    "Pop":     {"bass": 1.4, "mid": 1.2, "treb": 1.3, "widen": 1.3, "gain": 2.0},
}


class Pipeline:
    def __init__(self):
        self.record = None
        self.track = None
        self.projection = None
        self.running = False
        self.thread = None
        self.orig_music_vol = None
        self.auto_restart = True
        self.last_code = None
        self.last_data = None
        self.bass = 1.5
        self.mid = 1.0
        self.treb = 1.2
        self.widen = 1.3
        self.gain = 2.0
        self.bypass = False
        self.peak = 0.0

    def set_params(self, **kw):
        for k, v in kw.items():
            if hasattr(self, k):
                setattr(self, k, float(v))

    def start(self, result_code, data):
        self.stop()
        self.last_code = result_code
        self.last_data = data
        try:
            from jnius import autoclass
            from android import mActivity
            Context = autoclass("android.content.Context")
            AM = autoclass("android.media.AudioManager")
            am = mActivity.getSystemService(Context.AUDIO_SERVICE)
            try:
                self.orig_music_vol = am.getStreamVolume(AM.STREAM_MUSIC)
                am.setStreamVolume(AM.STREAM_MUSIC, 0, 0)
            except Exception:
                self.orig_music_vol = None
            MPM = autoclass("android.media.projection.MediaProjectionManager")
            mgr = mActivity.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
            self.projection = mgr.getMediaProjection(result_code, data)
            AA = autoclass("android.media.AudioAttributes")
            APCC = autoclass("android.media.AudioPlaybackCaptureConfiguration")
            b = APCC.Builder(self.projection)
            for u in (USAGE_MEDIA, USAGE_GAME, USAGE_UNKNOWN,
                      USAGE_ASSISTANCE_ACCESSIBILITY):
                try:
                    b.addMatchingUsage(u)
                except Exception:
                    pass
            apcc = b.build()
            AudioFormat = autoclass("android.media.AudioFormat")
            afb = AudioFormat.Builder()
            afb.setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            afb.setSampleRate(SR)
            afb.setChannelMask(AudioFormat.CHANNEL_IN_STEREO)
            af = afb.build()
            AR = autoclass("android.media.AudioRecord")
            arb = AR.Builder()
            arb.setAudioFormat(af)
            arb.setBufferSizeInBytes(BUF_BYTES)
            arb.setAudioPlaybackCaptureConfig(apcc)
            self.record = arb.build()
            AT = autoclass("android.media.AudioTrack")
            aab = AA.Builder()
            aab.setUsage(USAGE_ASSISTANCE_ACCESSIBILITY)
            aab.setContentType(CONTENT_TYPE_MUSIC)
            aa = aab.build()
            atb = AT.Builder()
            atb.setAudioAttributes(aa)
            atb.setAudioFormat(af)
            atb.setBufferSizeInBytes(BUF_BYTES)
            atb.setTransferMode(AT.MODE_STREAM)
            self.track = atb.build()
            self.record.startRecording()
            self.track.play()
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            log("pipeline started")
            return True
        except Exception as e:
            log(f"start fail: {e}")
            self.stop()
            return False

    def _loop(self):
        try:
            from jnius import autoclass
            AR = autoclass("android.media.AudioRecord")
            rb = AR.READ_BLOCKING
        except Exception:
            rb = 0
        buf = bytearray(BUF_BYTES)
        while self.running:
            try:
                n = self.record.read(buf, 0, BUF_BYTES, rb)
                if n <= 0:
                    time.sleep(0.005)
                    continue
                raw = bytes(buf[:n])
                out = self._process(raw)
                self.track.write(out, 0, len(out))
            except Exception as e:
                log(f"loop: {e}")
                time.sleep(0.05)

    def _process(self, raw):
        arr = np.frombuffer(raw, dtype=np.int16)
        if arr.size % 2 != 0:
            arr = arr[:-1]
        arr = arr.reshape(-1, 2).astype(np.float32)
        L = arr[:, 0]; R = arr[:, 1]
        if self.bypass:
            self.peak = float(np.max(np.abs(arr))) / 32768.0
            return arr.astype(np.int16).tobytes()
        L_low = np.convolve(L, BASS_FIR, "same")
        L_hi = np.convolve(L, TREB_FIR, "same")
        L_mid = L - L_low - L_hi
        R_low = np.convolve(R, BASS_FIR, "same")
        R_hi = np.convolve(R, TREB_FIR, "same")
        R_mid = R - R_low - R_hi
        L_out = L_low * self.bass + L_mid * self.mid + L_hi * self.treb
        R_out = R_low * self.bass + R_mid * self.mid + R_hi * self.treb
        mid = (L_out + R_out) * 0.5
        side = (L_out - R_out) * 0.5 * self.widen
        L_out = mid + side
        R_out = mid - side
        L_out *= self.gain
        R_out *= self.gain
        out = np.stack([L_out, R_out], axis=1).reshape(-1)
        out = np.tanh(out / 32768.0) * 32768.0 * 0.95
        self.peak = float(np.max(np.abs(out))) / 32768.0
        return out.astype(np.int16).tobytes()

    def stop(self):
        self.running = False
        for obj in (self.record, self.track):
            try:
                if obj is not None:
                    try: obj.stop()
                    except Exception: pass
                    obj.release()
            except Exception:
                pass
        self.record = None
        self.track = None
        try:
            if self.projection is not None:
                self.projection.stop()
                self.projection = None
        except Exception:
            pass
        try:
            if self.orig_music_vol is not None:
                from jnius import autoclass
                from android import mActivity
                Context = autoclass("android.content.Context")
                AM = autoclass("android.media.AudioManager")
                am = mActivity.getSystemService(Context.AUDIO_SERVICE)
                am.setStreamVolume(AM.STREAM_MUSIC, self.orig_music_vol, 0)
        except Exception:
            pass


_pipe = Pipeline()


def ask_projection():
    try:
        from jnius import autoclass
        from android import mActivity
        Context = autoclass("android.content.Context")
        mgr = mActivity.getSystemService(Context.MEDIA_PROJECTION_SERVICE)
        intent = mgr.createScreenCaptureIntent()
        mActivity.startActivityForResult(intent, REQ_CODE)
    except Exception as e:
        log(f"ask fail: {e}")


def bind_result(cb):
    try:
        from android import activity
        activity.bind(on_activity_result=cb)
    except Exception as e:
        log(f"bind: {e}")


def on_result(request_code, result_code, intent):
    if request_code != REQ_CODE:
        return
    if result_code != -1:
        log("denied")
        return
    threading.Thread(target=_pipe.start,
                     args=(result_code, intent), daemon=True).start()


def auto_restart_loop():
    while True:
        time.sleep(6)
        try:
            if _pipe.auto_restart and _pipe.last_code is not None:
                if not _pipe.running or _pipe.record is None:
                    _pipe.start(_pipe.last_code, _pipe.last_data)
        except Exception:
            pass


def save_preset():
    try:
        data = {"bass": _pipe.bass, "mid": _pipe.mid,
                "treb": _pipe.treb, "widen": _pipe.widen,
                "gain": _pipe.gain}
        with open(PRESET_FILE, "w") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False


def load_preset():
    try:
        with open(PRESET_FILE, "r") as f:
            data = json.load(f)
        _pipe.set_params(**data)
        return data
    except Exception:
        return None


class Root(FloatLayout):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(0.03, 0.05, 0.03, 1)
            self.bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._r, size=self.size)

        main = BoxLayout(orientation="vertical", padding=10, spacing=6)
        main.add_widget(Label(
            text="@new200013  BOOST MAX",
            font_size="20sp", bold=True,
            color=(0.4, 1.0, 0.5, 1),
            size_hint=(1, None), height=42))
        self.status = Label(
            text="press START", font_size="12sp",
            color=(0.9, 1.0, 0.9, 1),
            size_hint=(1, None), height=60,
            halign="center", valign="middle",
            text_size=(Window.width - 24, None))
        main.add_widget(self.status)
        self.vu = Label(
            text="", font_size="10sp",
            color=(0.4, 1.0, 0.5, 1),
            size_hint=(1, None), height=22)
        main.add_widget(self.vu)

        self.sliders = {}
        for key, label, lo, hi, val in (
            ("gain",  "Gain",        1.0, 5.0, 2.0),
            ("bass",  "Bass",        0.0, 4.0, 1.5),
            ("mid",   "Mid",         0.0, 3.0, 1.0),
            ("treb",  "Treble",      0.0, 4.0, 1.2),
            ("widen", "Stereo Wide", 0.0, 3.0, 1.3),
        ):
            row = BoxLayout(size_hint=(1, None), height=42)
            row.add_widget(Label(text=label, font_size="13sp",
                                 color=(0.7, 1.0, 0.7, 1),
                                 size_hint=(0.3, 1)))
            s = Slider(min=lo, max=hi, value=val, size_hint=(0.7, 1))
            row.add_widget(s)
            lbl = Label(text=f"{val:.1f}", font_size="13sp", bold=True,
                        color=(0.4, 1.0, 0.5, 1),
                        size_hint=(None, 1), width=44)
            row.add_widget(lbl)
            self.sliders[key] = (s, lbl)
            s.bind(value=lambda _, v, k=key: self._on_slider(k, v))
            main.add_widget(row)

        grid = GridLayout(cols=4, spacing=4,
                          size_hint=(1, None), height=110)
        for name in PRESETS.keys():
            b = Button(text=name, font_size="11sp",
                       background_normal="",
                       background_color=(0.05, 0.15, 0.07, 1),
                       color=(0.4, 1.0, 0.5, 1))
            b.bind(on_release=lambda _, n=name: self._preset(n))
            grid.add_widget(b)
        main.add_widget(grid)

        row = BoxLayout(size_hint=(1, None), height=60, spacing=6)

        def mk(txt, cb, bg=(0.05, 0.20, 0.07, 1), col=(0.4, 1.0, 0.5, 1)):
            b = Button(text=txt, font_size="14sp", bold=True,
                       background_normal="",
                       background_color=bg, color=col)
            b.bind(on_release=lambda *_: cb())
            return b

        row.add_widget(mk("START", self._start,
                          (0.05, 0.25, 0.08, 1), (0.4, 1.0, 0.5, 1)))
        row.add_widget(mk("STOP", self._stop,
                          (0.25, 0.05, 0.05, 1), (1.0, 0.4, 0.4, 1)))
        row.add_widget(mk("SAVE", self._save))
        row.add_widget(mk("LOAD", self._load))
        row.add_widget(mk("BYPASS", self._bypass))
        main.add_widget(row)

        main.add_widget(Label(
            text="Dev Coding Knowledge Forever\nDev Poltu Bag from Ambika Kalna",
            font_size="11sp", color=(1.0, 0.6, 0.2, 1),
            size_hint=(1, None), height=36,
            halign="center"))

        self.add_widget(main)
        bind_result(on_result)
        Clock.schedule_once(lambda dt: request_all_perms(), 1.0)
        Clock.schedule_interval(lambda dt: self._refresh(), 1.0)
        threading.Thread(target=auto_restart_loop, daemon=True).start()
        self._bypass_state = False

    def _r(self, *a):
        self.bg.pos = self.pos
        self.bg.size = self.size

    def _on_slider(self, key, v):
        s, lbl = self.sliders[key]
        lbl.text = f"{v:.1f}"
        _pipe.set_params(**{key: v})

    def _preset(self, name):
        p = PRESETS[name]
        for k, v in p.items():
            if k in self.sliders:
                self.sliders[k][0].value = v
            _pipe.set_params(**{k: v})
        self.status.text = f"preset: {name}"

    def _start(self):
        wakelock_on()
        keep_screen(True)
        if not has_rec_perm():
            request_all_perms()
            Clock.schedule_once(lambda dt: ask_projection(), 1.5)
        else:
            ask_projection()
        self.status.text = "opening projection dialog…"

    def _stop(self):
        _pipe.auto_restart = False
        _pipe.stop()
        keep_screen(False)
        wakelock_off()
        self.status.text = "stopped"

    def _save(self):
        if save_preset():
            self.status.text = "saved"
        else:
            self.status.text = "save fail"

    def _load(self):
        d = load_preset()
        if not d:
            self.status.text = "no preset"
            return
        for k, v in d.items():
            if k in self.sliders:
                self.sliders[k][0].value = v
        self.status.text = "loaded"

    def _bypass(self):
        self._bypass_state = not self._bypass_state
        _pipe.bypass = self._bypass_state
        self.status.text = "bypass " + ("ON" if self._bypass_state else "OFF")

    def _refresh(self):
        try:
            peak = _pipe.peak
            bars = int(peak * 30)
            self.vu.text = "▮" * bars + "▯" * (30 - bars)
        except Exception:
            pass
        if _pipe.running:
            self.status.text = f"RUNNING · gain {_pipe.gain:.1f}x"


class BoostApp(App):
    def build(self):
        Window.clearcolor = (0.03, 0.05, 0.03, 1)
        return Root()


if __name__ == "__main__":
    BoostApp().run()
