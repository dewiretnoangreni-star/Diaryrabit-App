"""
Rabit Notes - aplikasi catatan harian (Kivy, tampilan HP Android)
Jalankan:  python main.py      (file rabitnotes.kv harus satu folder dengan main.py)
"""
import os
import re
import json
import uuid
import hashlib
from datetime import datetime, date, timedelta
from time import monotonic

from kivy.config import Config

# jendela berbentuk HP (portrait) saat dijalankan di komputer
Config.set("graphics", "width", "360")
Config.set("graphics", "height", "700")
Config.set("graphics", "resizable", "0")

import traceback

from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import (StringProperty, BooleanProperty, ListProperty,
                             NumericProperty, ObjectProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex, platform, escape_markup

APP_NAME = "Rabit Notes"

BG = get_color_from_hex("#FDE7F3")
PINK = get_color_from_hex("#F472B6")
PINK_D = get_color_from_hex("#DB2777")
VIOLET = get_color_from_hex("#8B5CF6")
PURPLE = get_color_from_hex("#6D28D9")
BLUSH = get_color_from_hex("#FBCFE8")
TEXT = get_color_from_hex("#4C1D95")
WHITE = [1, 1, 1, 1]

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
         "Agustus", "September", "Oktober", "November", "Desember"]

Window.clearcolor = BG
Window.softinput_mode = "below_target"  # keyboard HP tidak menutupi kolom tulis


def fmt_date(d):
    return "%s, %d %s %d" % (HARI[d.weekday()], d.day, BULAN[d.month - 1], d.year)


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100000).hex()


# ------------------------------------------------------------------ penyimpanan
class Storage:
    def __init__(self, path):
        self.path = path
        self.data = {"users": {}, "last_email": ""}
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            try:  # file rusak -> dicadangkan, tidak dihapus
                os.replace(self.path, self.path + ".rusak.bak")
            except OSError:
                pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # tulis aman: data lama tidak rusak


# ------------------------------------------------------------------ widget kecil
class RoundButton(Button):
    btn_color = ListProperty(PINK)


class TopBar(BoxLayout):
    title = StringProperty("")
    show_back = BooleanProperty(True)


class DayButton(Button):
    bg = ListProperty(WHITE)
    fg = ListProperty(TEXT)
    has_note = BooleanProperty(False)


class DiaryRow(Button):
    pass


class SchedRow(BoxLayout):
    time = StringProperty("")
    activity = StringProperty("")
    index = NumericProperty(0)
    delete_cb = ObjectProperty(None)


# ------------------------------------------------------------------ dasar layar
class BaseScreen(Screen):
    pass


class AutoScreen(BaseScreen):
    """Layar dengan simpan otomatis (0.5 detik setelah berhenti mengetik)."""
    loaded = False
    _job = None

    def schedule_save(self):
        if self._job:
            self._job.cancel()
        self._job = Clock.schedule_once(lambda dt: self.save_now(), 0.5)

    def save_now(self):
        if self._job:
            self._job.cancel()
            self._job = None
        self.do_save()

    def do_save(self):
        pass

    def on_pre_leave(self, *args):
        self.save_now()
        self.loaded = False


# ------------------------------------------------------------------ LOGIN
class LoginScreen(BaseScreen):
    msg = StringProperty("")

    def prefill(self):
        # saat kv baru dibangun, ids belum tersedia -> lewati (diisi lagi di on_start)
        if "email_in" not in self.ids:
            return
        app = App.get_running_app()
        self.ids.email_in.text = app.store.data.get("last_email", "")
        self.ids.pw_in.text = ""
        self.msg = ""

    def on_pre_enter(self, *args):
        self.prefill()

    def do_login(self):
        app = App.get_running_app()
        mail = self.ids.email_in.text.strip().lower()
        pw = self.ids.pw_in.text
        if not re.fullmatch(r"[a-z0-9._%+-]+@gmail\.com", mail):
            self.msg = "Masukkan Gmail yang benar, contoh: nama@gmail.com"
            return
        if len(pw) < 6:
            self.msg = "Password minimal 6 karakter."
            return
        users = app.store.data["users"]
        home = app.root.get_screen("home")
        if mail in users:
            if hash_pw(pw, users[mail]["salt"]) != users[mail]["hash"]:
                self.msg = "Password salah, coba lagi ya."
                return
            home.notice = ""
        else:  # akun baru dibuat otomatis
            salt = os.urandom(16).hex()
            users[mail] = {"salt": salt, "hash": hash_pw(pw, salt),
                           "journal": {}, "diary": [], "timetable": {}, "study": {}}
            home.notice = "Akun baru berhasil dibuat. Selamat datang!"
            Clock.schedule_once(lambda dt: setattr(home, "notice", ""), 5)
        app.store.data["last_email"] = mail
        app.store.save()
        app.email = mail
        self.msg = ""
        app.go("home")


# ------------------------------------------------------------------ BERANDA
class HomeScreen(BaseScreen):
    initial = StringProperty("")
    name_text = StringProperty("")
    email_text = StringProperty("")
    date_text = StringProperty("")
    time_text = StringProperty("")
    notice = StringProperty("")
    _ev = None

    def on_pre_enter(self, *args):
        app = App.get_running_app()
        if app.email:
            self.initial = app.email[0].upper()
            self.name_text = app.email.split("@")[0]
            self.email_text = app.email
        self.tick()
        self._ev = Clock.schedule_interval(self.tick, 1)

    def on_leave(self, *args):
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def tick(self, *args):
        now = datetime.now()
        self.date_text = fmt_date(now.date())  # tanggal real time
        self.time_text = now.strftime("%H:%M:%S")


# ------------------------------------------------------------------ JURNAL RABIT
class JournalScreen(AutoScreen):
    date_text = StringProperty("")
    status = StringProperty("")
    today_text = StringProperty("")
    is_today = BooleanProperty(True)
    back_to = StringProperty("home")
    cur = ObjectProperty(None)

    def on_pre_enter(self, *args):
        if "txt" not in self.ids:
            return
        if self.cur is None:
            self.cur = date.today()
        self.load()

    def load(self):
        app = App.get_running_app()
        d = self.cur
        self.date_text = fmt_date(d)
        self.is_today = (d == date.today())
        self.today_text = "hari ini" if self.is_today else "Kembali ke hari ini"
        self.loaded = False
        self.ids.txt.text = app.user["journal"].get(d.isoformat(), "")
        self.loaded = True
        self.status = "Tulis ceritamu, tersimpan otomatis"

    def shift(self, n):
        self.save_now()
        self.cur = self.cur + timedelta(days=n)
        self.load()

    def go_today(self):
        self.save_now()
        self.cur = date.today()
        self.load()

    def on_change(self):
        if self.loaded:
            self.status = "Menyimpan..."
            self.schedule_save()

    def do_save(self):
        if not self.loaded or self.cur is None:
            return
        app = App.get_running_app()
        text = self.ids.txt.text
        key = self.cur.isoformat()
        if text.strip():
            app.user["journal"][key] = text
        else:
            app.user["journal"].pop(key, None)
        app.store.save()
        self.status = "Tersimpan " + datetime.now().strftime("%H:%M:%S")


# ------------------------------------------------------------------ DIARY
class DiaryListScreen(BaseScreen):
    def on_pre_enter(self, *args):
        if "list" not in self.ids:
            return
        app = App.get_running_app()
        box = self.ids.list
        box.clear_widgets()
        entries = sorted(app.user["diary"], key=lambda e: e["updated"], reverse=True)
        if not entries:
            box.add_widget(Label(text="Belum ada diary.\nYuk tulis cerita pertamamu!",
                                 color=get_color_from_hex("#A78BFA"), halign="center",
                                 size_hint_y=None, height=dp(120)))
            return
        for e in entries:
            dt = datetime.strptime(e["created"], "%Y-%m-%d %H:%M")
            title = e["title"] or (e["text"].strip().split("\n")[0][:28] or "(tanpa judul)")
            row = DiaryRow(text="[b]%s[/b]\n[size=12sp]%s  -  %s[/size]" % (
                escape_markup(title), fmt_date(dt.date()), dt.strftime("%H:%M")))
            row.bind(on_release=lambda w, eid=e["id"]: app.open_diary(eid))
            box.add_widget(row)


class DiaryEditScreen(AutoScreen):
    entry = ObjectProperty(None, allownone=True)
    back_to = StringProperty("diary")
    date_text = StringProperty("")
    status = StringProperty("")

    def on_pre_enter(self, *args):
        e = self.entry
        if not e or "title_in" not in self.ids:
            return
        dt = datetime.strptime(e["created"], "%Y-%m-%d %H:%M")
        self.date_text = "%s  -  %s" % (fmt_date(dt.date()), dt.strftime("%H:%M"))
        self.loaded = False
        self.ids.title_in.text = e["title"]
        self.ids.body_in.text = e["text"]
        self.loaded = True
        self.status = "Tersimpan otomatis"

    def on_change(self):
        if self.loaded:
            self.status = "Menyimpan..."
            self.schedule_save()

    def do_save(self):
        e = self.entry
        if not self.loaded or not e:
            return
        e["title"] = self.ids.title_in.text.strip()
        e["text"] = self.ids.body_in.text
        e["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        App.get_running_app().store.save()
        self.status = "Tersimpan " + datetime.now().strftime("%H:%M:%S")

    def on_pre_leave(self, *args):
        AutoScreen.on_pre_leave(self)
        e = self.entry
        app = App.get_running_app()
        # diary kosong tidak disimpan
        if e and not e["title"] and not e["text"].strip() and e in app.user["diary"]:
            app.user["diary"].remove(e)
            app.store.save()

    def delete(self):
        app = App.get_running_app()

        def yes():
            e = self.entry
            self.loaded = False
            if e in app.user["diary"]:
                app.user["diary"].remove(e)
            self.entry = None
            app.store.save()
            app.go("diary", "right")

        app.confirm("Hapus diary ini?", yes, "Hapus")


# ------------------------------------------------------------------ JADWAL PELAJARAN
HARI_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
TIME_RE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def norm_time(t):
    m = TIME_RE.fullmatch(t.strip())
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else None


def fmt_minutes(sec):
    m = int(round(sec / 60.0))
    if m < 60:
        return "%d menit" % m
    h, m = divmod(m, 60)
    return "%d jam %d menit" % (h, m) if m else "%d jam" % h


class LessonRow(BoxLayout):
    time_text = StringProperty("")
    subject = StringProperty("")
    item_id = StringProperty("")
    edit_cb = ObjectProperty(None)
    delete_cb = ObjectProperty(None)


class TimetableScreen(BaseScreen):
    day = NumericProperty(0)
    day_text = StringProperty("")
    form_title = StringProperty("Tambah pelajaran")
    form_btn = StringProperty("Tambah")
    editing = BooleanProperty(False)
    edit_id = None

    def start(self):
        self.day = date.today().weekday()
        self.reset_form()

    def day_items(self, day=None, create=False):
        u = App.get_running_app().user
        tt = u.setdefault("timetable", {})
        key = str(int(self.day if day is None else day))
        return tt.setdefault(key, []) if create else tt.get(key, [])

    def on_pre_enter(self, *args):
        if "lessons" not in self.ids:
            return
        self.refresh()

    def refresh(self):
        today = date.today().weekday()
        tabs = self.ids.days
        tabs.clear_widgets()
        for i, name in enumerate(HARI_SHORT):
            has = bool(self.day_items(i))
            bg, fg = WHITE, TEXT
            if has:
                bg = BLUSH
            if i == today:
                bg, fg = PINK, WHITE
            if i == int(self.day):
                bg, fg = VIOLET, WHITE
            b = DayButton(text=name, bg=bg, fg=fg, has_note=has)
            b.bind(on_release=lambda w, i=i: self.select_day(i))
            tabs.add_widget(b)

        items = sorted(self.day_items(), key=lambda x: (x["start"], x["end"]))
        self.day_text = "Jadwal hari %s  (%d pelajaran)" % (HARI[int(self.day)], len(items))
        box = self.ids.lessons
        box.clear_widgets()
        if not items:
            box.add_widget(Label(text="Belum ada pelajaran di hari ini.\nTambahkan lewat form di bawah.",
                                 color=get_color_from_hex("#A78BFA"), halign="center",
                                 size_hint_y=None, height=dp(90)))
        for it in items:
            box.add_widget(LessonRow(time_text="%s - %s" % (it["start"], it["end"]),
                                     subject=it["subject"], item_id=it["id"],
                                     edit_cb=self.start_edit, delete_cb=self.delete_item))

    def select_day(self, i):
        self.day = i
        self.reset_form()
        self.refresh()

    # ---- form tambah / ubah
    def reset_form(self):
        self.editing = False
        self.edit_id = None
        self.form_title = "Tambah pelajaran"
        self.form_btn = "Tambah"
        if "start_in" in self.ids:
            self.ids.start_in.text = ""
            self.ids.end_in.text = ""
            self.ids.sub_in.text = ""

    def start_edit(self, item_id):
        for it in self.day_items():
            if it["id"] == item_id:
                self.edit_id = item_id
                self.editing = True
                self.form_title = "Ubah pelajaran (ketuk Simpan)"
                self.form_btn = "Simpan"
                self.ids.start_in.text = it["start"]
                self.ids.end_in.text = it["end"]
                self.ids.sub_in.text = it["subject"]
                return

    def cancel_edit(self):
        self.reset_form()

    def submit(self):
        app = App.get_running_app()
        st = norm_time(self.ids.start_in.text)
        en = norm_time(self.ids.end_in.text)
        sub = self.ids.sub_in.text.strip()
        if not st or not en:
            return app.info("Format jam harus HH:MM\ncontoh 07:30")
        if en <= st:
            return app.info("Jam selesai harus setelah jam mulai.")
        if not sub:
            return app.info("Isi nama mata pelajarannya dulu ya.")
        lst = self.day_items(create=True)
        if self.editing:
            for it in lst:
                if it["id"] == self.edit_id:
                    it["start"], it["end"], it["subject"] = st, en, sub
            self.reset_form()
        else:
            lst.append({"id": uuid.uuid4().hex, "start": st, "end": en, "subject": sub})
            self.ids.start_in.text = en  # praktis: jam mulai berikutnya = jam selesai tadi
            self.ids.end_in.text = ""
            self.ids.sub_in.text = ""
        app.store.save()
        self.refresh()

    def delete_item(self, item_id):
        app = App.get_running_app()

        def yes():
            lst = self.day_items(create=True)
            lst[:] = [x for x in lst if x["id"] != item_id]
            if self.edit_id == item_id:
                self.reset_form()
            app.store.save()
            self.refresh()

        app.confirm("Hapus pelajaran ini?", yes, "Hapus")


# ------------------------------------------------------------------ STOPWATCH BELAJAR
class StopwatchScreen(BaseScreen):
    clock_text = StringProperty("00:00:00")
    status = StringProperty("Siap belajar")
    toggle_text = StringProperty("Mulai")
    total_text = StringProperty("")
    owner = None
    acc = 0.0
    t0 = None
    running = False
    _ev = None

    def elapsed(self):
        return self.acc + ((monotonic() - self.t0) if (self.running and self.t0) else 0.0)

    def tick(self, *args):
        s = int(self.elapsed())
        self.clock_text = "%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)

    def stop_timer(self):
        if self._ev:
            self._ev.cancel()
            self._ev = None
        self.running = False
        self.t0 = None

    def sync_labels(self):
        if self.running:
            self.toggle_text, self.status = "Jeda", "Sedang belajar..."
        elif self.acc > 0:
            self.toggle_text, self.status = "Lanjut", "Dijeda - lanjutkan atau simpan sesi"
        else:
            self.toggle_text, self.status = "Mulai", "Siap belajar"

    def on_pre_enter(self, *args):
        if "subj_in" not in self.ids:
            return
        app = App.get_running_app()
        if self.owner != app.email:  # ganti akun -> muat stopwatch milik akun ini
            self.stop_timer()
            self.acc = 0.0
            self.owner = app.email
            st = app.user.get("stopwatch")
            if st:
                self.acc = float(st.get("acc", 0))
                self.ids.subj_in.text = st.get("subject", "")
            else:
                self.ids.subj_in.text = ""
        self.sync_labels()
        self.tick()
        self.refresh_list()

    def toggle(self):
        if self.running:
            self.acc = self.elapsed()
            self.stop_timer()
        else:
            self.t0 = monotonic()
            self.running = True
            self._ev = Clock.schedule_interval(self.tick, 0.2)
        self.sync_labels()
        self.tick()
        self.persist()

    def reset(self):
        self.stop_timer()
        self.acc = 0.0
        self.sync_labels()
        self.tick()
        self.persist()

    def save_session(self):
        app = App.get_running_app()
        sec = int(self.elapsed())
        if sec < 5:
            return app.info("Stopwatch belum berjalan.\nMulai belajar dulu ya!")
        subj = self.ids.subj_in.text.strip() or "Belajar"
        day = date.today().isoformat()
        app.user.setdefault("study", {}).setdefault(day, []).append(
            {"subject": subj, "seconds": sec, "at": datetime.now().strftime("%H:%M")})
        self.stop_timer()
        self.acc = 0.0
        self.sync_labels()
        self.tick()
        self.persist()
        app.store.save()
        self.refresh_list()
        app.info("Sesi tersimpan!\n%s - %s" % (subj, fmt_minutes(sec)))

    def persist(self):
        """Simpan kondisi stopwatch supaya tidak hilang saat aplikasi ditutup."""
        app = App.get_running_app()
        if not app.email or self.owner != app.email or "subj_in" not in self.ids:
            return
        el = self.elapsed()
        if el > 0:
            app.user["stopwatch"] = {"acc": el, "subject": self.ids.subj_in.text}
        else:
            app.user.pop("stopwatch", None)
        app.store.save()

    def refresh_list(self):
        app = App.get_running_app()
        items = app.user.get("study", {}).get(date.today().isoformat(), [])
        self.total_text = "Total belajar hari ini: " + fmt_minutes(sum(x["seconds"] for x in items))
        box = self.ids.sessions
        box.clear_widgets()
        if not items:
            box.add_widget(Label(text="Belum ada sesi belajar hari ini.",
                                 color=get_color_from_hex("#A78BFA"), font_size="12sp",
                                 size_hint_y=None, height=dp(50)))
        for i, x in enumerate(items):
            box.add_widget(SchedRow(time="%d mnt" % max(1, int(round(x["seconds"] / 60.0))),
                                    activity="%s  (%s)" % (x["subject"], x["at"]),
                                    index=i, delete_cb=self.delete_session))

    def delete_session(self, index):
        app = App.get_running_app()

        def yes():
            items = app.user.get("study", {}).get(date.today().isoformat(), [])
            if 0 <= index < len(items):
                items.pop(index)
                app.store.save()
            self.refresh_list()

        app.confirm("Hapus sesi belajar ini?", yes, "Hapus")


# ------------------------------------------------------------------ PENGAMAN ERROR
class SafeHandler(ExceptionHandler):
    """Kalau ada error di satu halaman, aplikasi TIDAK tertutup:
    error dicatat ke rabit_error.log dan ditampilkan lewat popup."""

    def handle_exception(self, inst):
        if isinstance(inst, (KeyboardInterrupt, SystemExit)):
            return ExceptionManager.RAISE
        err = "".join(traceback.format_exception(type(inst), inst, inst.__traceback__))
        print(err)
        app = App.get_running_app()
        if app is not None:
            try:
                with open(app.log_path, "a", encoding="utf-8") as f:
                    f.write("[%s]\n%s\n" % (datetime.now().isoformat(timespec="seconds"), err))
            except Exception:
                pass
            Clock.schedule_once(lambda dt: app.show_error(inst), 0)
        return ExceptionManager.PASS


ExceptionManager.add_handler(SafeHandler())


# ------------------------------------------------------------------ APLIKASI
class RabitNotesApp(App):
    title = APP_NAME
    email = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if platform == "android":
            folder = self.user_data_dir
        else:
            folder = os.path.dirname(os.path.abspath(__file__))
        self.store = Storage(os.path.join(folder, "rabit_notes_data.json"))
        self.log_path = os.path.join(folder, "rabit_error.log")
        self._err_open = False

    @property
    def user(self):
        return self.store.data["users"][self.email]

    def on_start(self):
        Window.bind(on_keyboard=self.on_key)
        self.root.get_screen("login").prefill()

    # ---- navigasi
    def go(self, name, direction="left"):
        self.root.transition.direction = direction
        self.root.current = name

    def go_back(self):
        back = getattr(self.root.current_screen, "back_to", None)
        self.go(back or "home", "right")

    def on_key(self, window, key, *args):
        if key == 27:  # tombol back Android
            if self.root.current in ("login", "home"):
                return False
            self.go_back()
            return True
        return False

    def logout(self):
        self.flush()
        self.email = None
        self.go("login", "right")

    def open_journal(self, d=None, back_to="home"):
        scr = self.root.get_screen("journal")
        scr.cur = d or date.today()
        scr.back_to = back_to
        self.go("journal")

    def open_timetable(self):
        self.root.get_screen("timetable").start()
        self.go("timetable")

    def new_diary(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        e = {"id": uuid.uuid4().hex, "title": "", "text": "", "created": now, "updated": now}
        self.user["diary"].append(e)
        self.root.get_screen("diary_edit").entry = e
        self.go("diary_edit")

    def open_diary(self, entry_id):
        for e in self.user["diary"]:
            if e["id"] == entry_id:
                self.root.get_screen("diary_edit").entry = e
                self.go("diary_edit")
                return

    # ---- popup
    def _popup(self, text, buttons, height=190):
        pop = Popup(title=APP_NAME, size_hint=(0.86, None), height=dp(height),
                    auto_dismiss=False, separator_color=VIOLET)
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(12))
        box.add_widget(Label(text=text, halign="center"))
        row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(46))
        for label, color, action in buttons:
            b = RoundButton(text=label, btn_color=color, height=dp(46))
            b.bind(on_release=lambda w, a=action: (pop.dismiss(), a() if a else None))
            row.add_widget(b)
        box.add_widget(row)
        pop.content = box
        pop.open()

    def show_error(self, exc):
        if self._err_open:
            return
        self._err_open = True
        msg = "%s: %s" % (type(exc).__name__, exc)
        self._popup("Ups, ada error kecil:\n%s\n(detail ada di rabit_error.log)" % msg[:160],
                    [("OK", PINK, lambda: setattr(self, "_err_open", False))], 230)

    def info(self, text):
        self._popup(text, [("OK", PINK, None)], 170)

    def confirm(self, text, on_yes, yes_text="Ya"):
        self._popup(text, [("Batal", VIOLET, None), (yes_text, PINK, on_yes)])

    # ---- pastikan semua tersimpan saat aplikasi ditutup / ke background
    def flush(self):
        try:
            scr = self.root.current_screen
            if hasattr(scr, "save_now"):
                scr.save_now()
        except Exception:
            pass
        try:
            self.root.get_screen("stopwatch").persist()
        except Exception:
            pass
        try:
            self.store.save()
        except Exception:
            pass


    def on_pause(self):
        self.flush()
        return True
  
    def on_stop(self):
        self.flush()


if __name__ == "__main__":
    RabitNotesApp().run()