import sys
import os
import json
import shutil
import random
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QMessageBox, QGridLayout, QCheckBox, QComboBox, QSpinBox,
    QHBoxLayout, QSizePolicy, QMainWindow, QStackedWidget, QWidget, QPushButton,
    QVBoxLayout, QLabel, QScrollArea, QFrame, QProgressBar, QFileDialog, QLineEdit,
    QDoubleSpinBox
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QTextOption, QIcon
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QParallelAnimationGroup, QPoint, QEasingCurve, QRect

import time

try:
    from logic import (
        filterDataFrame,
        getRandomSample,
        getRandomRows,
        getMaxCount,
        getRow
    )
except Exception as e:
    raise ImportError(f"Failed to import required functions from logic.py: {e}")


# ---------------- Helpers for resources & user data ----------------
def resource_path(relative_path: str) -> str:
    """
    Return a path to a resource that works both bundled by PyInstaller (onefile)
    and in development.
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)


def user_data_dir(app_name: str = "KanjiDriller") -> str:
    """
    Return a persistent per-user data directory for the app and ensure it exists.
    - Windows: %APPDATA%\<app_name>
    - macOS: ~/Library/Application Support/<app_name>
    - Linux: ~/.local/share/<app_name>
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")

    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path


# Small button that wraps long text
class WrapButton(QPushButton):
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__("", parent)
        self._wrap_text = str(text)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setText(text)

    def setText(self, text: str):
        self._wrap_text = str(text)
        super().setText(self._wrap_text)

    def paintEvent(self, event):
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        opt.setAlignment(Qt.AlignCenter)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect()
        # draw background
        painter.fillRect(r, self.palette().button())

        painter.setPen(self.palette().buttonText().color())
        painter.setFont(self.font())

        pad = 8
        text_rect = QRect(r.left() + pad, r.top() + pad, r.width() - pad * 2, r.height() - pad * 2)

        painter.drawText(text_rect, self._wrap_text, opt)

        if self.underMouse():
            painter.setPen(self.palette().mid().color())
            painter.drawRect(r.adjusted(0, 0, -1, -1))

        painter.end()


# Clickable label for profile picture
class ClickableLabel(QLabel):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._on_click = None

    def set_on_click(self, fn):
        self._on_click = fn

    def mousePressEvent(self, event):
        if callable(self._on_click):
            self._on_click()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # persistent files now in user data dir
        appdata = user_data_dir("KanjiDriller")
        self.stats_path = os.path.join(appdata, "kanji_stats.json")
        self.profile_path = os.path.join(appdata, "profile.json")
        self.appdata = appdata  # keep for easy reference

        # default filters - ensure count default is 4
        self.drillFilters = {
            "system": "JLPT",
            "drill": "Meaning",
            "jlpt_levels": [5],
            "wanikani_levels": [],
            "count": 4,
            "max_count": 79,
            "prioritize_weakness": True
        }


        self.reading_type = "kunyomi"
        self.meaning_mode = "multiple_choice"
        

        # load/create persistence first so profile_data exists
        self.kanji_stats = {}
        self.profile_data = {}
        self._results_page = None
        self._profile_page = None
        self.load_or_create_stats()
        self.load_or_create_profile()

        # initial dataframe sample
        self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        self.currentSample = getRandomSample(self.df_f, self.drillFilters["count"])

        self.currentRow = None
        self.currentQuestionBatch = None
        self.currentAnswer = None

        self.currentQuestionIndex = 0
        self.totalQuestions = 0

        self.popup_seconds = 1.5
        self._session_start_avg_prof = None

        # session tracking
        self.session_results = []  # list of dicts {kanji, given, expected, correct}
        self.session_xp = {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}

        self.setWindowTitle("Kanji Driller")
        self.setFixedSize(500, 600)

        # compute button min width based on window width (nearly full width)
        # NOTE: keep this as an upper-bound used below to compute a centered block width
        self._button_min_width = max(300, self.width() - 40)

        # SlideStack class that animates page transitions
        class SlideStack(QStackedWidget):
            def slide_to(self, index, direction="left"):
                if index == self.currentIndex():
                    return
                current = self.currentWidget()
                next_w = self.widget(index)
                w = self.width()
                h = self.height()
                if direction == "left":
                    next_start = QPoint(w, 0)
                    current_end = QPoint(-w, 0)
                else:
                    next_start = QPoint(-w, 0)
                    current_end = QPoint(w, 0)
                next_w.setGeometry(0, 0, w, h)
                next_w.move(next_start)
                next_w.show()
                anim_cur = QPropertyAnimation(current, b"pos")
                anim_cur.setEndValue(current_end)
                anim_cur.setDuration(300)
                anim_cur.setEasingCurve(QEasingCurve.OutCubic)
                anim_next = QPropertyAnimation(next_w, b"pos")
                anim_next.setStartValue(next_start)
                anim_next.setEndValue(QPoint(0, 0))
                anim_next.setDuration(300)
                anim_next.setEasingCurve(QEasingCurve.OutCubic)
                group = QParallelAnimationGroup(self)
                group.addAnimation(anim_cur)
                group.addAnimation(anim_next)

                def finish():
                    self.setCurrentWidget(next_w)
                    current.move(0, 0)
                    next_w.move(0, 0)
                    group.deleteLater()

                group.finished.connect(finish)
                group.start()

        self.stack = SlideStack()

        self.stack.currentChanged.connect(self._on_stack_changed)

        # --- Main Menu page ---
        mainMenuLayout = QVBoxLayout()
        # align items toward top so buttons don't sit at the bottom
        mainMenuLayout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mainMenuLayout.setContentsMargins(24, 16, 24, 16)
        mainMenuLayout.setSpacing(12)

        mainMenuTitle = QLabel("Kanji Driller")
        mainMenuTitle.setSizePolicy(mainMenuTitle.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        mainMenuTitle.setFont(QFont(mainMenuTitle.font().family(), 42))
        mainMenuLayout.addWidget(mainMenuTitle, alignment=Qt.AlignmentFlag.AlignHCenter)

        # username above PFP (centered)
        profile_col = QVBoxLayout()
        profile_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        profile_col.setSpacing(8)

        self.mainMenuUsername = QLabel(self.profile_data.get("username", "User"))
        self.mainMenuUsername.setFont(QFont(mainMenuTitle.font().family(), 18))
        self.mainMenuUsername.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mainMenuPFP = ClickableLabel()
        # load PFP from profile_data (should be absolute path in user data dir)
        main_pix_path = self.profile_data.get("pfp_path", resource_path("pfp.png"))
        try:
            mainPix = QPixmap(main_pix_path)
            if mainPix.isNull():
                # fallback to bundled resource
                mainPix = QPixmap(resource_path("pfp.jpg"))
        except Exception:
            mainPix = QPixmap(resource_path("pfp.jpg"))
        # reduced pfp: max height 215
        mainPix = mainPix.scaledToHeight(215, Qt.SmoothTransformation)
        self.mainMenuPFP.setPixmap(mainPix)
        self.mainMenuPFP.setFixedSize(mainPix.width(), mainPix.height())
        self.mainMenuPFP.set_on_click(lambda: (self.build_profile_page(), self.stack.slide_to(self.profile_index(), "left")))

        profile_col.addWidget(self.mainMenuUsername)
        profile_col.addWidget(self.mainMenuPFP)
        mainMenuLayout.addLayout(profile_col)

        # add spacing between the PFP and the buttons
        mainMenuLayout.addSpacing(12)

        # make Drill/Profile buttons large but ensure they are centered correctly
        buttons_box = QVBoxLayout()
        buttons_box.setSpacing(14)
        # remove internal margins so centering is accurate
        buttons_box.setContentsMargins(0, 0, 0, 0)

        # choose a sensible target width for the centered button block:
        # - don't force minimum width larger than available area
        # - keep a comfortable side padding (80px) so it doesn't touch edges
        available_width = max(0, self.width() - (mainMenuLayout.contentsMargins().left() + mainMenuLayout.contentsMargins().right()))
        target_block_width = min(self._button_min_width, max(300, available_width - 80))

        mainMenuDrillButton = QPushButton("Drill")
        # prefer fixed width for consistent centering; let vertical height remain fixed
        mainMenuDrillButton.setFixedWidth(target_block_width)
        mainMenuDrillButton.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Fixed)
        mainMenuDrillButton.setFixedHeight(88)  # taller
        mainMenuDrillButton.clicked.connect(lambda: self.stack.slide_to(1, "left"))

        mainMenuProfileButton = QPushButton("Profile")
        mainMenuProfileButton.setFixedWidth(target_block_width)
        mainMenuProfileButton.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Fixed)
        mainMenuProfileButton.setFixedHeight(88)
        mainMenuProfileButton.clicked.connect(lambda: (self.build_profile_page(), self.stack.slide_to(self.profile_index(), "left")))

        buttons_box.addWidget(mainMenuDrillButton, alignment=Qt.AlignmentFlag.AlignHCenter)
        buttons_box.addWidget(mainMenuProfileButton, alignment=Qt.AlignmentFlag.AlignHCenter)

        # center the whole vertical buttons block by placing it inside a horizontal layout with stretches
        buttons_container_h = QHBoxLayout()
        buttons_container_h.setContentsMargins(0, 0, 0, 0)
        buttons_container_h.addStretch()
        buttons_container_h.addLayout(buttons_box)
        buttons_container_h.addStretch()

        mainMenuLayout.addLayout(buttons_container_h)
        mainMenuLayout.addStretch()

        mainMenuPage = QWidget()
        mainMenuPage.setLayout(mainMenuLayout)

        # --- Drill Menu page ---
        DrillMenuLayout = QVBoxLayout()

        DrillMenuBackLayout = QHBoxLayout()
        DrillMenuBack = QPushButton("← Back")
        DrillMenuBack.setFixedSize(80, 28)
        DrillMenuBack.clicked.connect(lambda: self.stack.slide_to(0, "right"))
        DrillMenuBackLayout.addWidget(DrillMenuBack, alignment=Qt.AlignmentFlag.AlignLeft)
        DrillMenuBackLayout.addStretch()
        DrillMenuLayout.addLayout(DrillMenuBackLayout)

        DrillMenuSystemCombo = QComboBox()
        DrillMenuSystemCombo.addItems(["JLPT", "WaniKani"])
        DrillMenuSystemCombo.currentTextChanged.connect(self.filtersystem_changed)
        DrillMenuLayout.addWidget(DrillMenuSystemCombo)

        DrillMenuDrillCombo = QComboBox()
        DrillMenuDrillCombo.addItems(["Meaning", "Reading"])
        DrillMenuDrillCombo.currentTextChanged.connect(self.filterdrill_changed)
        DrillMenuLayout.addWidget(DrillMenuDrillCombo)

        self.DrillMenuMeaningModeCombo = QComboBox()
        self.DrillMenuMeaningModeCombo.addItems(["Multiple Choice", "Writing"])
        self.DrillMenuMeaningModeCombo.setCurrentIndex(0)
        self.DrillMenuMeaningModeCombo.currentTextChanged.connect(self.meaningmode_changed)
        DrillMenuLayout.addWidget(self.DrillMenuMeaningModeCombo)

        # hide initially unless we are in Meaning drill
        if self.drillFilters.get("drill", "Meaning") != "Meaning":
            self.DrillMenuMeaningModeCombo.hide()

        self.DrillMenuReadingTypeCombo = QComboBox()
        self.DrillMenuReadingTypeCombo.addItems(["Kunyomi", "Onyomi"])
        # default to Kunyomi
        # internal value mapping: "Kunyomi" -> "kunyomi", "Onyomi" -> "onyomi"
        self.DrillMenuReadingTypeCombo.setCurrentIndex(0)
        self.DrillMenuReadingTypeCombo.currentTextChanged.connect(self.readingtype_changed)
        DrillMenuLayout.addWidget(self.DrillMenuReadingTypeCombo)
        # hide initially unless we are in Reading drill
        if self.drillFilters.get("drill", "Meaning") != "Reading":
            self.DrillMenuReadingTypeCombo.hide()

        DrillMenuCountLayout = QHBoxLayout()
        self.DrillMenuCountLabel = QLabel("Count: (total: " + str(self.drillFilters["max_count"]) + ")")
        self.DrillMenuCountLabel.setToolTip("Average mastery across all kanji in the current filter and mode. Shown to 3 decimal places.")
        self.DrillMenuCountSpin = QSpinBox()
        self.DrillMenuCountSpin.setRange(4, max(4, self.drillFilters["max_count"]))
        self.DrillMenuCountSpin.setValue(4)
        self.DrillMenuCountSpin.valueChanged.connect(self.filtercount_changed)

        DrillMenuCountLayout.addWidget(self.DrillMenuCountLabel)
        DrillMenuCountLayout.addWidget(self.DrillMenuCountSpin)
        DrillMenuLayout.addLayout(DrillMenuCountLayout)

        self.DrillMenuPrioritizeWeaknessCB = QCheckBox("Prioritize weakness")
        self.DrillMenuPrioritizeWeaknessCB.setChecked(bool(self.drillFilters.get("prioritize_weakness", True)))
        self.DrillMenuPrioritizeWeaknessCB.stateChanged.connect(self.prioritizeweakness_changed)
        DrillMenuLayout.addWidget(self.DrillMenuPrioritizeWeaknessCB)

        popup_row = QHBoxLayout()
        popup_row.setContentsMargins(0, 0, 0, 0)
        popup_row.setSpacing(6)

        popup_label = QLabel("Popup (s):")
        popup_spin = QDoubleSpinBox()
        popup_spin.setRange(0.0, 10.0)
        popup_spin.setSingleStep(0.1)
        popup_spin.setDecimals(1)
        popup_spin.setValue(float(self.popup_seconds))
        popup_spin.setToolTip("Set how long the answer popup shows (0 = no popup).")

        # store widget ref
        self.DrillMenuPopupSpin = popup_spin
        popup_spin.valueChanged.connect(lambda v: setattr(self, "popup_seconds", float(v)))

        popup_row.addWidget(popup_label)
        popup_row.addWidget(popup_spin)
        # place it under the checkbox visually (or next to it if you prefer)
        DrillMenuLayout.addLayout(popup_row)

        # JLPT levels row
        self.DrillMenuJLPTSection = QWidget()
        DrillMenuJLPTLayout = QHBoxLayout(self.DrillMenuJLPTSection)

        DrillMenuJLPTLevelLabel = QLabel("Level: ")
        DrillMenuJLPTLevelN5 = QCheckBox("N5")
        DrillMenuJLPTLevelN4 = QCheckBox("N4")
        DrillMenuJLPTLevelN3 = QCheckBox("N3")
        DrillMenuJLPTLevelN2 = QCheckBox("N2")
        DrillMenuJLPTLevelN1 = QCheckBox("N1")

        DrillMenuJLPTLevelN5.setChecked(5 in self.drillFilters["jlpt_levels"])
        DrillMenuJLPTLevelN4.setChecked(4 in self.drillFilters["jlpt_levels"])
        DrillMenuJLPTLevelN3.setChecked(3 in self.drillFilters["jlpt_levels"])
        DrillMenuJLPTLevelN2.setChecked(2 in self.drillFilters["jlpt_levels"])
        DrillMenuJLPTLevelN1.setChecked(1 in self.drillFilters["jlpt_levels"])

        for cb in (DrillMenuJLPTLevelN5, DrillMenuJLPTLevelN4, DrillMenuJLPTLevelN3, DrillMenuJLPTLevelN2, DrillMenuJLPTLevelN1):
            cb.stateChanged.connect(self.level_filter)

        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelLabel)
        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelN5)
        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelN4)
        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelN3)
        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelN2)
        DrillMenuJLPTLayout.addWidget(DrillMenuJLPTLevelN1)

        DrillMenuLayout.addWidget(self.DrillMenuJLPTSection)

        # WaniKani grid
        self.DrillMenuWaniKaniSection = QWidget()
        DrillMenuWaniKaniLayout = QGridLayout(self.DrillMenuWaniKaniSection)
        DrillMenuWaniKaniLayout.setSpacing(6)
        DrillMenuWaniKaniLayout.setContentsMargins(0, 0, 0, 0)

        DrillMenuWaniKaniLevelLabel = QLabel("Level:")
        DrillMenuWaniKaniLayout.addWidget(DrillMenuWaniKaniLevelLabel, 0, 0, 1, 1, Qt.AlignmentFlag.AlignLeft)

        columns = 9
        start_col = 1
        for i in range(1, 61):
            checkbox = QCheckBox(str(i))
            checkbox.stateChanged.connect(self.level_filter)
            index = i - 1
            row = index // columns
            col = start_col + (index % columns)
            DrillMenuWaniKaniLayout.addWidget(checkbox, row, col)

        DrillMenuLayout.addWidget(self.DrillMenuWaniKaniSection)
        self.DrillMenuWaniKaniSection.hide()

        mainMenuDrillButton = QPushButton("Drill")
        mainMenuDrillButton.clicked.connect(lambda: self.DrillStart())
        DrillMenuLayout.addWidget(mainMenuDrillButton)

        DrillMenuPage = QWidget()
        DrillMenuPage.setLayout(DrillMenuLayout)

        # --- Train page ---
        TrainLayout = QVBoxLayout()
        TrainBackLayout = QHBoxLayout()
        TrainBack = QPushButton("← Back")
        TrainBack.setFixedSize(80, 28)
        TrainBack.clicked.connect(lambda: self.stack.slide_to(1, "right"))
        TrainBackLayout.addWidget(TrainBack, alignment=Qt.AlignmentFlag.AlignLeft)
        TrainBackLayout.addStretch()
        TrainLayout.addLayout(TrainBackLayout)

        self.TrainMainWidget = QWidget()
        self.TrainMainLayout = QVBoxLayout(self.TrainMainWidget)
        self.TrainMainLayout.setContentsMargins(8, 8, 8, 8)
        self.TrainMainLayout.setSpacing(8)
        TrainLayout.addWidget(self.TrainMainWidget)

        TrainPage = QWidget()
        TrainPage.setLayout(TrainLayout)

        # Add pages to stack
        self.stack.addWidget(mainMenuPage)    # index 0
        self.stack.addWidget(DrillMenuPage)   # index 1
        self.stack.addWidget(TrainPage)       # index 2

        self.setCentralWidget(self.stack)

        # init UI labels / ranges
        self.update_count_label()

    # ---------------- persistence helpers ----------------
    def load_or_create_stats(self):
        if os.path.exists(self.stats_path):
            try:
                with open(self.stats_path, "r", encoding="utf-8") as f:
                    self.kanji_stats = json.load(f)
            except Exception:
                self.kanji_stats = {}
        else:
            self.kanji_stats = {}
            self.save_stats()

        # normalize schema (adds pw_* keys to old stats files)
        try:
            for k in list(self.kanji_stats.keys()):
                self.ensure_kanji_entry(k)
            self.save_stats()
        except Exception:
            pass

    def save_stats(self):
        try:
            with open(self.stats_path, "w", encoding="utf-8") as f:
                json.dump(self.kanji_stats, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_or_create_profile(self):
        """
        Ensure profile.json exists in user data dir and profile_data keys are present.
        Also ensure a PFP file exists in user data dir and profile_data['pfp_path'] points to it.
        """
        default_profile = {
            "username": "User",
            "pfp_path": os.path.join(self.appdata, "pfp.png"),
            "xp": {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}
        }

        # If profile file exists in user data dir, load it
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    self.profile_data = json.load(f)
            except Exception:
                self.profile_data = default_profile.copy()
        else:
            # Create profile file in user data dir, but ensure PFP exists there first
            # Copy bundled pfp.jpg to appdata if not already present
            # find a bundled default pfp with any common extension
            bundled_pfp = None
            for ext in ("jpg", "png", "jpeg", "webp"):
                candidate = resource_path(f"pfp.{ext}")
                if os.path.exists(candidate):
                    bundled_pfp = candidate
                    break

            if bundled_pfp:
                target_pfp = os.path.join(self.appdata, os.path.basename(bundled_pfp))
                try:
                    if not os.path.exists(target_pfp):
                        shutil.copyfile(bundled_pfp, target_pfp)
                    self.profile_data["pfp_path"] = target_pfp
                except Exception:
                    self.profile_data["pfp_path"] = bundled_pfp
            else:
                # absolute last-resort fallback
                self.profile_data["pfp_path"] = resource_path("pfp.jpg")

            try:
                if not os.path.exists(target_pfp):
                    shutil.copyfile(bundled_pfp, target_pfp)
            except Exception:
                # best effort copy; if it fails we'll still use the bundled resource at runtime
                pass
            self.profile_data = default_profile.copy()
            self.save_profile()

        # Normalize keys and ensure absolute pfp path
        self.profile_data.setdefault("username", "User")
        # If pfp_path is relative or missing, point it to appdata/pfp.jpg (copy if needed)
        pfp_path = self.profile_data.get("pfp_path")
        if not pfp_path:
            pfp_path = os.path.join(self.appdata, "pfp.jpg")
            self.profile_data["pfp_path"] = pfp_path

        # If the profile's pfp_path doesn't exist but a bundled file exists, copy bundled file
        if not os.path.exists(pfp_path):
            bundled = resource_path("pfp.jpg")
            try:
                shutil.copyfile(bundled, os.path.join(self.appdata, "pfp.jpg"))
                self.profile_data["pfp_path"] = os.path.join(self.appdata, "pfp.jpg")
            except Exception:
                # as last resort, keep profile['pfp_path'] pointing to the bundled resource
                self.profile_data["pfp_path"] = bundled

        # ensure xp structure
        self.profile_data.setdefault("xp", {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}})
        for sysn in ("JLPT", "WaniKani"):
            self.profile_data["xp"].setdefault(sysn, {})
            for dr in ("Meaning", "Reading"):
                self.profile_data["xp"][sysn].setdefault(dr, 0)
        # finally save normalized profile (may rewrite paths to absolute appdata)
        self.profile_data.setdefault("pw_question_counter", 0)
        self.profile_data.setdefault("pw_session_counter", 0)
        self.save_profile()

    def save_profile(self):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- XP math ----------------
    def xp_per_correct(self, system_name, drill_name):
        # reading gives slightly more xp
        return 12 if drill_name == "Reading" else 10

    def xp_for_answer(self, system_name, drill_name, is_correct):
        base = self.xp_per_correct(system_name, drill_name)
        return base if is_correct else int(round(base * 0.15))

    def get_bucket_level_progress(self, xp_value):
        xp_per_level = 500
        level = int(xp_value // xp_per_level) + 1
        within = int(xp_value % xp_per_level)
        pct = int((within / xp_per_level) * 100)
        return level, within, xp_per_level, pct

    def total_questions_answered_overall(self):
        total = 0
        for k, v in self.kanji_stats.items():
            try:
                total += int(v.get("total_encounters", 0))
            except Exception:
                pass
        return total

    def profile_index(self):
        for i in range(self.stack.count()):
            if self.stack.widget(i) is self._profile_page:
                return i
        return None

    def results_index(self):
        for i in range(self.stack.count()):
            if self.stack.widget(i) is self._results_page:
                return i
        return None

    # ---------------- UI filter handlers ----------------
    def update_count_label(self):
        if self.drillFilters["system"] == "JLPT":
            levels = self.drillFilters["jlpt_levels"]
        else:
            levels = self.drillFilters["wanikani_levels"]

        try:
            # Note: getMaxCount signature in logic.py may vary, adjust accordingly
            self.drillFilters["max_count"] = getMaxCount(self.df_f, self.drillFilters["system"], levels, self.drillFilters["drill"])
        except TypeError:
            # fallback if getMaxCount expects different args
            try:
                self.drillFilters["max_count"] = getMaxCount(self.drillFilters["system"], levels, self.drillFilters["drill"])
            except Exception:
                self.drillFilters["max_count"] = 0
        except Exception:
            self.drillFilters["max_count"] = 0

        self.drillFilters["max_count"] = int(self.drillFilters["max_count"] or 0)

        # compute average proficiency as a float with 3 decimals
        avg_prof = self.compute_average_proficiency_for_current_filter()
        # format as XX.xxx%
        avg_text = f"{avg_prof:.3f}%"
        self.DrillMenuCountLabel.setText(f"Count: (total: {self.drillFilters['max_count']}) avg prof: {avg_text}")

        max_val = max(4, self.drillFilters["max_count"])
        try:
            self.DrillMenuCountSpin.setRange(4, max_val)
        except Exception:
            pass

        if int(self.drillFilters.get("count", 4)) < 4:
            self.drillFilters["count"] = 4
        try:
            if self.DrillMenuCountSpin.value() < 4:
                self.DrillMenuCountSpin.setValue(4)
        except Exception:
            pass

    def filtersystem_changed(self, text):
        self.drillFilters["system"] = text
        if self.drillFilters["system"] == "JLPT":
            self.DrillMenuJLPTSection.show()
            self.DrillMenuWaniKaniSection.hide()
        else:
            self.DrillMenuJLPTSection.hide()
            self.DrillMenuWaniKaniSection.show()
        if self.drillFilters["system"] == "JLPT":
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        else:
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
        try:
            self.drillFilters["max_count"] = getMaxCount(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        except Exception:
            pass
        self.update_count_label()

    def filterdrill_changed(self, text):
        self.drillFilters["drill"] = text
        # show/hide reading type combo
        # show/hide reading type combo
        if text == "Reading":
            self.DrillMenuReadingTypeCombo.show()
        else:
            self.DrillMenuReadingTypeCombo.hide()

        # show/hide meaning mode combo
        if text == "Meaning":
            self.DrillMenuMeaningModeCombo.show()
        else:
            self.DrillMenuMeaningModeCombo.hide()

        if self.drillFilters["system"] == "JLPT":
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        else:
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
        try:
            self.drillFilters["max_count"] = getMaxCount(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        except Exception:
            pass
        self.update_count_label()

    def prioritizeweakness_changed(self, state):
        self.drillFilters["prioritize_weakness"] = bool(state == Qt.CheckState.Checked)

    def readingtype_changed(self, text):
        val = "kunyomi" if text.lower().startswith("k") else "onyomi"
        self.reading_type = val
        try:
            self.update_count_label()
        except Exception:
            pass

    def meaningmode_changed(self, text):
        self.meaning_mode = "writing" if text.lower().startswith("w") else "multiple_choice"
        try:
            self.update_count_label()
        except Exception:
            pass

    def filtercount_changed(self, value):
        self.drillFilters["count"] = max(4, int(value))

    def level_filter(self, state):
        sender = self.sender()
        if sender is None:
            return
        text = sender.text()
        checked = sender.isChecked()
        if self.drillFilters["system"] == "JLPT":
            try:
                val = int(text.lstrip("Nn"))
            except Exception:
                return
            lst = self.drillFilters.setdefault("jlpt_levels", [])
            if checked:
                if val not in lst:
                    lst.append(val)
            else:
                if val in lst:
                    lst.remove(val)
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        else:
            try:
                val = int(text)
            except Exception:
                return
            lst = self.drillFilters.setdefault("wanikani_levels", [])
            if checked:
                if val not in lst:
                    lst.append(val)
            else:
                if val in lst:
                    lst.remove(val)
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
        self.update_count_label()

    # ---------------- layout helpers ----------------
    def clear_layout(self, widget_or_layout):
        layout = widget_or_layout.layout() if isinstance(widget_or_layout, QWidget) else widget_or_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
            else:
                nested = item.layout()
                if nested:
                    self.clear_layout(nested)
    def _contains_kanji(self, s: str) -> bool:
        if not s:
            return False
        for ch in s:
            code = ord(ch)
            # CJK Unified Ideographs + Extension A + Compatibility Ideographs
            if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0xF900 <= code <= 0xFAFF):
                return True
        return False

    def _answer_button_font_for_text(self, text: str) -> QFont:
        f = QFont()
        # Large for kanji answers (legibility similar to kanji prompt)
        if self._contains_kanji(text):
            f.setPointSize(44)
        else:
            f.setPointSize(14)
        return f

    # ---------------- question helpers (reading-safe) ----------------
    def _pick_readings_text(self, row, is_jlpt, prefer):
        """
        Return a single DISPLAY string representing the FULL reading list
        for the chosen type (kunyomi/onyomi). Falls back to the other type if empty.
        Example: ["ばつ","ばち"] -> "ばつ, ばち"
        Returns "" if none available.
        """
        if is_jlpt:
            kun_field = "readings_kun"
            on_field = "readings_on"
        else:
            kun_field = "wk_readings_kun"
            on_field = "wk_readings_on"

        first_field = kun_field if prefer == "kunyomi" else on_field
        second_field = on_field if prefer == "kunyomi" else kun_field

        def normalize_list(val):
            if val is None:
                return []
            if isinstance(val, (list, tuple)):
                items = [str(x).strip() for x in val if x is not None and str(x).strip()]
                return items
            # if it ever comes as a string, treat it as single reading
            s = str(val).strip()
            return [s] if s else []

        def join_items(items):
            return ", ".join(items) if items else ""

        first_items = normalize_list(row.get(first_field))
        if first_items:
            return join_items(first_items)

        second_items = normalize_list(row.get(second_field))
        if second_items:
            return join_items(second_items)

        return ""

    def _collect_reading_distractors(self, batch_df, is_jlpt, prefer, needed=3, exclude=None):
        """
        Return up to `needed` distinct non-empty reading LIST strings (joined),
        using prefer as preference for field. exclude is a set of strings to avoid.
        """
        exclude = set(exclude or [])
        candidates = []
        for _, r in batch_df.iterrows():
            rd = self._pick_readings_text(r, is_jlpt, prefer)
            if rd and rd not in exclude:
                candidates.append(rd)

        # dedupe while keeping order
        candidates = list(dict.fromkeys(candidates))
        random.shuffle(candidates)
        return candidates[:needed]
    
    def _normalize_meaning_list(self, val):
        """
        Return a clean list of meaning strings from either:
        - list/tuple: ["tall", "expensive"]
        - string: "tall, expensive"
        """
        if val is None:
            return []
        if isinstance(val, (list, tuple)):
            items = [str(x).strip() for x in val if x is not None and str(x).strip()]
            return items
        s = str(val).strip()
        if not s:
            return []
        # split common separators for stored strings
        parts = [p.strip() for p in s.replace(";", ",").split(",")]
        return [p for p in parts if p]

    def _is_meaning_input_correct(self, user_text: str, meanings_list):
        """
        Accept:
        - any single meaning
        - any subset of meanings (1..n), any order
        - not case sensitive
        - supports "tall, expensive" and "expensive, tall"
        """
        if user_text is None:
            return False

        # normalize target meanings
        targets = [m.strip().lower() for m in meanings_list if m and str(m).strip()]
        targets = [t for t in targets if t]
        if not targets:
            return False

        # normalize user input
        raw = str(user_text).strip().lower()
        if not raw:
            return False

        # Split ONLY on separators between meanings; keep internal spaces intact
        user_parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        user_parts = [p for p in user_parts if p]

        # If user typed one chunk, allow exact match to any meaning
        if len(user_parts) == 1:
            return user_parts[0] in targets

        # If multiple chunks, accept if all provided are valid meanings (subset),
        # regardless of order, and no extras beyond the target list.
        target_set = set(targets)
        user_set = set(user_parts)

        # must be subset and non-empty
        return bool(user_set) and user_set.issubset(target_set)
    
    def submit_meaning_written(self):
        # must exist
        edit = getattr(self, "meaning_input", None)
        btn = getattr(self, "meaning_enter_btn", None)
        if edit is None:
            return

        # disable immediately
        try:
            edit.setEnabled(False)
        except Exception:
            pass
        if btn is not None:
            try:
                btn.setEnabled(False)
            except Exception:
                pass

        user_text = edit.text()
        expected_display = getattr(self, "correct_answer_text", "")

        # determine correct
        meanings_list = getattr(self, "_current_meanings_list", [])
        is_correct = self._is_meaning_input_correct(user_text, meanings_list)

        # stats/session logging
        try:
            kanji_key = str(self.currentRow.get("kanji"))
        except Exception:
            kanji_key = ""

        self.session_results.append({
            "kanji": kanji_key,
            "given": user_text,
            "expected": expected_display,
            "correct": bool(is_correct)
        })

        self.update_stats_and_profile(kanji_key, bool(is_correct))

        if is_correct:
          self.show_overlay("Correct!")
        else:
            self.show_overlay(f"Wrong — correct: {expected_display}")

    # ---------------- question building ----------------
    def NewDrillQuestion(self, type_hint, index, total_count):
        if self.currentSample is None or len(self.currentSample) == 0:
            raise RuntimeError("No sample available")

        self.currentRow = getRow(self.currentSample, index)
        self.currentQuestionBatch = getRandomRows(self.currentSample, index, 3)
        is_jlpt = (self.drillFilters["system"] == "JLPT")

        def fmt_value(v):
            if v is None:
                return ""
            if isinstance(v, (list, tuple)):
                # for meanings we want readable comma-separated; for readings we won't use this formatter
                return ", ".join(str(x) for x in v if x is not None)
            return str(v)

        drill_type = self.drillFilters["drill"]
        prompt_is_kanji = False

        if drill_type == "Meaning":
            meaning_field = "meanings" if is_jlpt else "wk_meanings"

            # If Meaning mode is Writing: always show kanji prompt and require typed meaning.
            if getattr(self, "meaning_mode", "multiple_choice") == "writing":
                question_text = fmt_value(self.currentRow.get("kanji"))
                prompt_is_kanji = True

                meanings_list = self._normalize_meaning_list(self.currentRow.get(meaning_field))
                correct_answer = ", ".join(meanings_list)  # display in feedback/results
                self._current_meanings_list = meanings_list

                # store canonical correct display string
                self.current_question_prompt_is_kanji = prompt_is_kanji
                self.correct_answer_text = correct_answer

                container = QWidget()
                vlayout = QVBoxLayout(container)
                vlayout.setSpacing(8)

                qlabel = QLabel(question_text)
                qlabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
                qlabel.setWordWrap(True)
                base_font = qlabel.font()
                base_font.setPointSize(56)
                qlabel.setFont(base_font)
                vlayout.addWidget(qlabel)

                try:
                    kanji_key = str(self.currentRow.get("kanji"))
                    entry = self.kanji_stats.get(kanji_key, {})
                    mode_key = self._current_mode_key()
                    mastery = float(entry.get(self.drillFilters["system"], {}).get(mode_key, {}).get("mastery", 0.0) or 0.0)
                except Exception:
                    mastery = 0.0
                mastery_lbl = QLabel(f"Mastery: {int(round(mastery))}%")
                mastery_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vlayout.addWidget(mastery_lbl)

                tier_names = ["Beginner", "Intermediate", "Expert", "Master", "Grandmaster"]
                tier_idx = min(4, int(mastery // 20))
                tier_lbl = QLabel(f"{tier_names[tier_idx]} ({int(round(mastery))}%)")
                tier_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vlayout.addWidget(tier_lbl)

                # input row: textbox + Enter button (right)
                input_row = QHBoxLayout()
                self.meaning_input = QLineEdit()
                self.meaning_input.setPlaceholderText("Type a meaning…")
                self.meaning_input.setClearButtonEnabled(True)
                self.meaning_input.setFocus()

                self.meaning_enter_btn = QPushButton("Enter")
                self.meaning_enter_btn.setFixedWidth(90)

                input_row.addWidget(self.meaning_input)
                input_row.addWidget(self.meaning_enter_btn)
                vlayout.addLayout(input_row)

                # submit via click or Enter key
                self.meaning_enter_btn.clicked.connect(self.submit_meaning_written)
                self.meaning_input.returnPressed.connect(self.submit_meaning_written)

                display_index = index + 1
                status_label = QLabel(f"{display_index}/{total_count}")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._drill_status_label = status_label
                vlayout.addWidget(status_label)

                return container

            # Otherwise: Multiple choice behavior (your existing logic)
            kanji_to_meaning = random.choice([True, False])

            if kanji_to_meaning:
                question_text = fmt_value(self.currentRow["kanji"])
                prompt_is_kanji = True
                correct_answer = fmt_value(self.currentRow.get(meaning_field))

                wrong_answers = [fmt_value(r.get(meaning_field)) for _, r in self.currentQuestionBatch.iterrows()]
                wrong_answers = [w for w in wrong_answers if w and w != correct_answer]
                all_answers = [correct_answer] + wrong_answers

                all_answers = list(dict.fromkeys(all_answers))[:4]
                while len(all_answers) < 4:
                    all_answers.append("")
                random.shuffle(all_answers)
                button_texts = all_answers
            else:
                question_text = fmt_value(self.currentRow.get(meaning_field))
                prompt_is_kanji = False
                correct_answer = fmt_value(self.currentRow.get("kanji"))

                wrong_answers = [fmt_value(r.get("kanji")) for _, r in self.currentQuestionBatch.iterrows()]
                wrong_answers = [w for w in wrong_answers if w and w != correct_answer]
                all_answers = [correct_answer] + wrong_answers

                all_answers = list(dict.fromkeys(all_answers))[:4]
                while len(all_answers) < 4:
                    all_answers.append("")
                random.shuffle(all_answers)
                button_texts = all_answers

        elif drill_type == "Reading":
            prefer = self.reading_type  # "kunyomi" or "onyomi"

            # correct answer is the FULL LIST string (joined), not a single reading
            correct_answer = self._pick_readings_text(self.currentRow, is_jlpt, prefer)
            if not correct_answer:
                fallback = "onyomi" if prefer == "kunyomi" else "kunyomi"
                correct_answer = self._pick_readings_text(self.currentRow, is_jlpt, fallback)

            if not correct_answer:
                alt = self.currentRow.get("meanings") or self.currentRow.get("wk_meanings")
                correct_answer = fmt_value(alt) or fmt_value(self.currentRow.get("kanji")) or ""

            question_text = fmt_value(self.currentRow.get("kanji"))
            prompt_is_kanji = True

            distractors = self._collect_reading_distractors(
                self.currentQuestionBatch, is_jlpt, prefer, needed=3, exclude={correct_answer}
            )

            if len(distractors) < 3 and hasattr(self, "currentSample") and self.currentSample is not None:
                more = self._collect_reading_distractors(
                    self.currentSample, is_jlpt, prefer, needed=10, exclude={correct_answer}
                )
                for m in more:
                    if m not in distractors:
                        distractors.append(m)
                        if len(distractors) >= 3:
                            break

            while len(distractors) < 3:
                distractors.append("")

            all_answers = [correct_answer] + distractors[:3]

            # dedupe, then ensure 4 buttons exist
            ordered = list(dict.fromkeys(all_answers))
            while len(ordered) < 4:
                ordered.append("")
            ordered = ordered[:4]

            random.shuffle(ordered)
            button_texts = ordered

        else:
            # fallback: treat similar to Meaning prompt
            question_text = fmt_value(self.currentRow.get("kanji"))
            prompt_is_kanji = True
            correct_answer = fmt_value(self.currentRow.get("meanings") or self.currentRow.get("wk_meanings"))
            wrong_answers = [fmt_value(r.get("meanings") or r.get("wk_meanings")) for _, r in self.currentQuestionBatch.iterrows()]
            wrong_answers = [w for w in wrong_answers if w and w != correct_answer]
            all_answers = [correct_answer] + wrong_answers
            all_answers = list(dict.fromkeys(all_answers))[:4]
            while len(all_answers) < 4:
                all_answers.append("")
            random.shuffle(all_answers)
            button_texts = all_answers

        # store canonical correct answer (string)
        self.current_question_prompt_is_kanji = prompt_is_kanji
        self.correct_answer_text = correct_answer

        container = QWidget()
        vlayout = QVBoxLayout(container)
        vlayout.setSpacing(8)

        qlabel = QLabel(question_text)
        qlabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qlabel.setWordWrap(True)
        base_font = qlabel.font()
        if prompt_is_kanji:
            base_font.setPointSize(56)
        else:
            base_font.setPointSize(22)
        qlabel.setFont(base_font)
        vlayout.addWidget(qlabel)

        answers_widget = QWidget()
        answer_grid = QGridLayout(answers_widget)
        answer_grid.setSpacing(6)

        self.answer_buttons = []
        # correct_answer_text already set above



        # When comparing, we compare button.text() == self.correct_answer_text (exact string)
        for i, text in enumerate(button_texts[:4]):
            btn = WrapButton(text)
            btn.setFont(self._answer_button_font_for_text(text))
            is_correct = (text == self.correct_answer_text)
            # use a default argument to capture is_correct and btn for the lambda
            btn.clicked.connect(lambda checked=False, b=btn, correct=is_correct: self.checkAnswer(correct, b))
            r = i // 2
            c = i % 2
            answer_grid.addWidget(btn, r, c)
            self.answer_buttons.append(btn)

        # placeholders if fewer than 4
        for i in range(len(button_texts), 4):
            placeholder = WrapButton("")
            placeholder.setEnabled(False)
            placeholder.setMinimumHeight(80)
            r = i // 2
            c = i % 2
            answer_grid.addWidget(placeholder, r, c)
            self.answer_buttons.append(placeholder)

        vlayout.addWidget(answers_widget)
        display_index = index + 1
        status_label = QLabel(f"{display_index}/{total_count}")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drill_status_label = status_label
        vlayout.addWidget(status_label)

        return container

    # ---------------- Train flow ----------------
    def ensure_train_visible(self):
        if not hasattr(self, "TrainMainWidget") or self.TrainMainWidget is None:
            self.TrainMainWidget = QWidget()
            self.TrainMainLayout = QVBoxLayout(self.TrainMainWidget)
            self.TrainMainLayout.setContentsMargins(8, 8, 8, 8)
            self.TrainMainLayout.setSpacing(8)
        if self.TrainMainWidget.layout() is None:
            self.TrainMainWidget.setLayout(self.TrainMainLayout)
        self.TrainMainWidget.show()
        self.TrainMainWidget.repaint()
        QApplication.processEvents()

    def DrillStart(self):
        # verify there are enough cards after filtering
        if self.drillFilters["max_count"] < 1:
            QMessageBox.critical(self, "Error", "No cards avaliable, choose atleast a level")
            return

        if self.drillFilters["system"] == "JLPT":
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
        else:
            self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])

        requested = int(self.drillFilters.get("count", 4) or 4)
        requested = max(4, requested)
        max_available = len(self.df_f) if self.df_f is not None else 0
        final_count = min(requested, max_available)

        

        if final_count < 4:
            QMessageBox.critical(self, "Error", "Require at least 4 cards to start a drill. Pick more cards/levels.")
            return
        
        # ---- PW session-based cooldown setup ----
        coverage = (final_count / max_available) if max_available > 0 else 1.0

        # cooldown in *sessions* (adaptive):
        # higher coverage => allow reappearance sooner
        if coverage >= 0.40:
            self._pw_cooldown_sessions = 0
        elif coverage >= 0.25:
            self._pw_cooldown_sessions = 1
        elif coverage >= 0.12:
            self._pw_cooldown_sessions = 2
        else:
            self._pw_cooldown_sessions = 3

        # If PW mode ON, increment session counter once per drill
        if bool(self.drillFilters.get("prioritize_weakness", True)):
            try:
                self.profile_data["pw_session_counter"] = int(self.profile_data.get("pw_session_counter", 0)) + 1
            except Exception:
                self.profile_data["pw_session_counter"] = 1
            self._pw_current_session_id = int(self.profile_data.get("pw_session_counter", 0))
            # persist this immediately so session counter survives crashes mid-drill
            self.save_profile()
        else:
            self._pw_current_session_id = 0

        self.drillFilters["count"] = final_count
        self.totalQuestions = int(self.drillFilters["count"])
        try:
            self._session_start_avg_prof = float(self.compute_average_proficiency_for_current_filter() or 0.0)
        except Exception:
            self._session_start_avg_prof = 0.0
        if bool(self.drillFilters.get("prioritize_weakness", True)):
            self.currentSample = self.get_pw_weighted_sample(self.df_f, final_count)
        else:
            self.currentSample = getRandomSample(self.df_f, final_count)

        # safety check
        if hasattr(self.currentSample, "shape") and int(self.currentSample.shape[0]) < 4:
            QMessageBox.critical(self, "Error", "Require at least 4 cards to start a drill. Pick more cards/levels.")
            return

        self.currentQuestionIndex = 0
        self.session_results = []
        self.session_xp = {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}

        self.ensure_train_visible()
        try:
            self.showQuestion()
        except Exception:
            self.clear_layout(self.TrainMainLayout)
            placeholder = QLabel("Error building question — check console")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.TrainMainLayout.addWidget(placeholder)
            placeholder.show()
            self.TrainMainWidget.show()
            QApplication.processEvents()

        self.stack.slide_to(2, "left")

    def _pw_weight_for_row(self, row):
        """
        Weight based on:
        - Laplace-smoothed wrong rate using pw stats: (w+1)/(r+w+2)
        - staleness multiplier based on pw_last_seen and global pw_question_counter
        - small floor so nothing is impossible
        """
        try:
            kanji_key = str(row.get("kanji"))
        except Exception:
            kanji_key = ""

        # Ensure entry exists so we can read defaults
        if kanji_key:
            self.ensure_kanji_entry(kanji_key)

        system_name = self.drillFilters["system"]
        drill_name = self.drillFilters["drill"]

        bucket = None
        try:
            mode_key = self._current_mode_key()
            bucket = self.kanji_stats.get(kanji_key, {}).get(system_name, {}).get(mode_key, {})
        except Exception:
            bucket = {}

        r = int(bucket.get("pw_right", 0) or 0)
        w = int(bucket.get("pw_wrong", 0) or 0)
        last = int(bucket.get("pw_last_seen", 0) or 0)

        last_sess = int(bucket.get("pw_last_seen_session", 0) or 0)
        now_sess = int(self.profile_data.get("pw_session_counter", 0) or 0)
        sess_age = max(0, now_sess - last_sess)

        # Laplace smoothing
        wrong_rate = (w + 1.0) / (r + w + 2.0)  # 0..1

        # staleness
        now = int(self.profile_data.get("pw_question_counter", 0) or 0)
        age = max(0, now - last)

        # cap controls how quickly staleness ramps (tweak later)
        cap = 200.0
        stale_mult = 1.0 + min(age, cap) / cap  # 1.0..2.0

        # Session cooldown penalty (soft): recently-seen-in-session => lower weight
        cool_sess = int(getattr(self, "_pw_cooldown_sessions", 0) or 0)
        if cool_sess > 0 and sess_age <= cool_sess:
            # sess_age=0 (same session) shouldn't occur with no-replacement sampling,
            # but keep safe. This ramps up toward 1.0 as it ages out of cooldown.
            session_cooldown_factor = 0.20 + 0.80 * (sess_age / float(cool_sess))
        else:
            session_cooldown_factor = 1.0

        floor = 0.08  # tweak later
        weight = (floor + (wrong_rate * stale_mult)) * session_cooldown_factor
        return max(0.0001, float(weight))


    def _weighted_choice_index(self, indices, weights):
        """
        Pick one index from indices using weights (same length), returns chosen index position.
        """
        total = 0.0
        for w in weights:
            total += float(w)

        if total <= 0.0:
            return random.randrange(len(indices))

        r = random.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += float(w)
            if acc >= r:
                return i
        return len(indices) - 1


    def get_pw_weighted_sample(self, df, n):
        """
        Returns a DataFrame sample of size n without replacement using pw weights.
        Falls back to uniform random if anything goes wrong.
        """
        try:
            # pandas dataframe assumed
            if df is None or len(df) == 0:
                return df

            n = int(n)
            n = max(1, min(n, len(df)))

            # Build lists so we can remove chosen rows (without replacement)
            rows = []
            weights = []
            for idx, row in df.iterrows():
                rows.append((idx, row))
                weights.append(self._pw_weight_for_row(row))

            chosen_indices = []
            # sample without replacement
            for _ in range(n):
                pick_pos = self._weighted_choice_index(rows, weights)
                idx, _row = rows.pop(pick_pos)
                weights.pop(pick_pos)
                chosen_indices.append(idx)

            sampled = df.loc[chosen_indices]
            sampled = sampled.reindex(chosen_indices)
            return sampled

        except Exception:
            # hard fallback
            try:
                return getRandomSample(df, n)
            except Exception:
                return df
            
    def compute_average_proficiency_for_current_filter(self):
        """
        Compute average mastery (0-100 float) for the currently filtered set (self.df_f)
        using the current mode key. Returns float rounded to 3 decimals.
        """
        if getattr(self, "df_f", None) is None or len(self.df_f) == 0:
            return 0.0
        mode_key = self._current_mode_key()
        total = 0.0
        count = 0
        for _, row in self.df_f.iterrows():
            k = str(row.get("kanji") or "")
            if not k:
                continue
            entry = self.kanji_stats.get(k, {})
            try:
                system_blob = entry.get(self.drillFilters["system"], {})
                bucket = system_blob.get(mode_key, {})
                m = float(bucket.get("mastery", 0.0) or 0.0)
            except Exception:
                m = 0.0
            total += m
            count += 1
        avg = (total / count) if count > 0 else 0.0
        return float(round(avg, 3))

    def showQuestion(self):
        if self.currentQuestionIndex >= self.totalQuestions:
            self.finishTraining()
            return
        if self.currentSample is None or len(self.currentSample) == 0:
            self.finishTraining()
            return
        if self.currentQuestionIndex >= len(self.currentSample):
            self.finishTraining()
            return

        self.clear_layout(self.TrainMainLayout)
        qwidget = None
        try:
            qwidget = self.NewDrillQuestion(type_hint=None, index=self.currentQuestionIndex, total_count=self.totalQuestions)
        except Exception:
            qwidget = None

        if qwidget is None:
            placeholder = QLabel("Could not build question — check console")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.TrainMainLayout.addWidget(placeholder)
            placeholder.show()
        else:
            qwidget.setParent(self.TrainMainWidget)
            self.TrainMainLayout.addWidget(qwidget)
            qwidget.show()

        self.TrainMainWidget.show()
        self.TrainMainWidget.repaint()
        QApplication.processEvents()

    # ---------------- overlay for feedback ----------------
    def _create_overlay(self):
        if getattr(self, "_train_overlay", None) is not None:
            return
        overlay = QWidget(self.TrainMainWidget)
        overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overlay.setStyleSheet("background-color: rgba(0,0,0,0.45);")
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.setSpacing(12)
        msg_label = QLabel("", overlay)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        msg_font = QFont()
        msg_font.setPointSize(26)
        msg_label.setFont(msg_font)
        msg_label.setStyleSheet("color: white;")
        overlay_layout.addStretch()
        overlay_layout.addWidget(msg_label)
        overlay_layout.addStretch()
        self._train_overlay = overlay
        self._train_overlay_label = msg_label
        overlay.hide()

    def show_overlay(self, text, timeout_ms=None):
        """
        Show overlay for `timeout_ms` milliseconds.
        If timeout_ms is None, use self.popup_seconds * 1000.
        If that value is 0, skip showing overlay and continue to _advance_after_popup immediately.
        """
        # determine timeout
        if timeout_ms is None:
            try:
                t_ms = int(round(float(self.popup_seconds) * 1000.0))
            except Exception:
                t_ms = int(round(1500))
        else:
            t_ms = int(timeout_ms)

        # if t_ms == 0, skip overlay
        if t_ms <= 0:
            # still do the minimal UI feedback (buttons colored) but skip the overlay widget
            QApplication.processEvents()
            # small delay optional? we avoid sleeping in UI thread; go straight to advance
            QTimer.singleShot(0, lambda: self._advance_after_popup())
            return

        self._create_overlay()
        overlay = self._train_overlay
        label = self._train_overlay_label
        label.setText(text)
        overlay.setGeometry(self.TrainMainWidget.rect())
        overlay.raise_()
        overlay.show()
        overlay.repaint()
        QApplication.processEvents()
        QTimer.singleShot(t_ms, lambda: (overlay.hide(), self._advance_after_popup()))
    # ---------------- stats/profile updates ----------------
    def ensure_kanji_entry(self, kanji_key):
        def bucket_defaults():
            return {
                "right": 0,
                "wrong": 0,
                "streak": 0,
                "pw_right": 0,
                "pw_wrong": 0,
                "pw_streak": 0,
                "pw_last_seen": 0,
                "pw_last_seen_session": 0,
                "mastery": 0.0,
                "mastery_streak": 0,
                "mastery_last_seen": 0
            }

        # If missing entirely, create the whole structure (with mode buckets)
        if kanji_key not in self.kanji_stats:
            self.kanji_stats[kanji_key] = {
                "total_encounters": 0,
                "JLPT": {},
                "WaniKani": {}
            }

        entry = self.kanji_stats[kanji_key]
        entry.setdefault("total_encounters", 0)
        entry.setdefault("JLPT", {})
        entry.setdefault("WaniKani", {})

        # Ensure mode-specific buckets exist for each system, with defaults
        modes = ["Meaning:writing", "Meaning:multiple_choice", "Reading:kunyomi", "Reading:onyomi"]
        for sysn in ("JLPT", "WaniKani"):
            entry.setdefault(sysn, {})
            for m in modes:
                if m not in entry[sysn]:
                    entry[sysn][m] = bucket_defaults().copy()
                else:
                    # normalize any missing fields in existing bucket
                    b = entry[sysn][m]
                    b.setdefault("right", 0)
                    b.setdefault("wrong", 0)
                    b.setdefault("streak", 0)
                    b.setdefault("pw_right", 0)
                    b.setdefault("pw_wrong", 0)
                    b.setdefault("pw_streak", 0)
                    b.setdefault("pw_last_seen", 0)
                    b.setdefault("pw_last_seen_session", 0)
                    b.setdefault("mastery", 0.0)
                    b.setdefault("mastery_streak", 0)
                    b.setdefault("mastery_last_seen", 0)



    def update_stats_and_profile(self, kanji_key, is_correct):
        system_name = self.drillFilters["system"]
        drill_name = self.drillFilters["drill"]

        self.ensure_kanji_entry(kanji_key)
        entry = self.kanji_stats[kanji_key]
        entry["total_encounters"] = int(entry.get("total_encounters", 0)) + 1

        mode_key = self._current_mode_key()  # e.g., "Meaning:writing" or "Reading:kunyomi"
        bucket = entry[system_name].setdefault(mode_key, {})
        # ensure defaults exist (call ensure_kanji_entry already does, but be defensive)
        bucket.setdefault("right", 0)
        bucket.setdefault("wrong", 0)
        bucket.setdefault("streak", 0)
        bucket.setdefault("pw_right", 0)
        bucket.setdefault("pw_wrong", 0)
        bucket.setdefault("pw_streak", 0)
        bucket.setdefault("pw_last_seen", 0)
        bucket.setdefault("pw_last_seen_session", 0)
        bucket.setdefault("mastery", 0.0)
        bucket.setdefault("mastery_streak", 0)
        bucket.setdefault("mastery_last_seen", 0)

        # ---- always update BASE stats (normal mode tracking) ----
        if is_correct:
            bucket["right"] = int(bucket.get("right", 0)) + 1
            bucket["streak"] = int(bucket.get("streak", 0)) + 1
        else:
            bucket["wrong"] = int(bucket.get("wrong", 0)) + 1
            bucket["streak"] = 0

        # ---- if PW mode enabled, also update PW stats ----
        if bool(self.drillFilters.get("prioritize_weakness", True)):
            # increment global PW counter
            try:
                self.profile_data["pw_question_counter"] = int(self.profile_data.get("pw_question_counter", 0)) + 1
            except Exception:
                self.profile_data["pw_question_counter"] = 1

            now = int(self.profile_data.get("pw_question_counter", 0))
            bucket["pw_last_seen"] = now
            try:
                bucket["pw_last_seen_session"] = int(getattr(self, "_pw_current_session_id", 0) or 0)
            except Exception:
                bucket["pw_last_seen_session"] = 0

            if is_correct:
                bucket["pw_right"] = int(bucket.get("pw_right", 0)) + 1
                bucket["pw_streak"] = int(bucket.get("pw_streak", 0)) + 1
            else:
                bucket["pw_wrong"] = int(bucket.get("pw_wrong", 0)) + 1
                bucket["pw_streak"] = 0

            try:
                mastery = float(bucket.get("mastery", 0.0) or 0.0)
            except Exception:
                mastery = 0.0

            # lazy decay: apply decay based on question counter age
            now_q = int(self.profile_data.get("pw_question_counter", 0) or 0)
            last_seen_q = int(bucket.get("mastery_last_seen", 0) or 0)
            age = max(0, now_q - last_seen_q)
            if age > 0:
                # small decay per 100 questions (tune as you like)
                decay_per_100q = 1.0  # percent lost per 100 questions not seen
                decay = (age / 100.0) * decay_per_100q
                mastery = max(0.0, mastery - decay)

            # apply result-based update
            if is_correct:
                # base gains (tweakable): Reading gives slightly more
                base_gain = 3.5 if drill_name == "Reading" else 2.5
                # scale gain down as mastery approaches 100
                gain = base_gain * (1.0 - (mastery / 100.0))
                # bump streak
                bucket["mastery_streak"] = int(bucket.get("mastery_streak", 0)) + 1
                mastery += gain
                # avoid 99% creep: require a certification streak + minimum encounters to reach 100
                if mastery >= 99.0:
                    streak = int(bucket.get("mastery_streak", 0))
                    total_enc = int(entry.get("total_encounters", 0) or 0)
                    if streak >= 7 and total_enc >= 25:
                        mastery = 100.0
                    else:
                        # cap at 99.0 if not yet certified
                        mastery = min(mastery, 99.0)
            else:
                # punish mistakes strongly when mastery high
                penalty = max(12.0, mastery * 0.15)
                mastery = max(0.0, mastery - penalty)
                bucket["mastery_streak"] = 0

            bucket["mastery"] = round(float(mastery), 2)
            bucket["mastery_last_seen"] = int(self.profile_data.get("pw_question_counter", 0) or 0)

        # XP stays the same
        gained = self.xp_for_answer(system_name, drill_name, is_correct)
        self.profile_data["xp"][system_name][drill_name] = int(self.profile_data["xp"][system_name][drill_name]) + int(gained)
        self.session_xp[system_name][drill_name] = int(self.session_xp[system_name][drill_name]) + int(gained)

        self.save_stats()
        self.save_profile()

    # ---------------- answer checking ----------------
    def checkAnswer(self, is_correct, clicked_button):
        # disable buttons immediately
        for b in getattr(self, "answer_buttons", []):
            try:
                b.setEnabled(False)
            except Exception:
                pass

        try:
            kanji_key = str(self.currentRow.get("kanji"))
        except Exception:
            kanji_key = ""

        given_text = clicked_button.text() if clicked_button is not None else ""
        expected_text = getattr(self, "correct_answer_text", "")

        # append session result
        self.session_results.append({"kanji": kanji_key, "given": given_text, "expected": expected_text, "correct": bool(is_correct)})

        # update stats/profile
        self.update_stats_and_profile(kanji_key, bool(is_correct))

        # visual feedback
        if is_correct:
            if clicked_button is not None:
                try:
                    clicked_button.setStyleSheet("background-color: lightgreen;")
                except Exception:
                    pass
            self.show_overlay("Correct!")
        else:
            # highlight the correct one
            for b in getattr(self, "answer_buttons", []):
                try:
                    if b.text() == expected_text:
                        b.setStyleSheet("background-color: lightgreen;")
                    else:
                        # reset others
                        b.setStyleSheet("")
                except Exception:
                    pass
            if clicked_button is not None:
                try:
                    clicked_button.setStyleSheet("background-color: lightcoral;")
                except Exception:
                    pass
            self.show_overlay(f"Wrong — correct: {expected_text}")

    def _advance_after_popup(self):
        self.currentQuestionIndex += 1
        try:
            if hasattr(self, "_drill_status_label") and self._drill_status_label is not None:
                display_index = min(self.currentQuestionIndex + 1, self.totalQuestions)
                self._drill_status_label.setText(f"{display_index}/{self.totalQuestions}")
        except Exception:
            pass
        self.showQuestion()

    def _current_mode_key(self):
        """
        Return a mode key string used for per-mode stats/mastery:
        - Meaning:writing or Meaning:multiple_choice
        - Reading:kunyomi or Reading:onyomi
        """
        dr = self.drillFilters.get("drill", "Meaning")
        if dr == "Meaning":
            mode = "writing" if getattr(self, "meaning_mode", "multiple_choice") == "writing" else "multiple_choice"
            return f"Meaning:{mode}"
        else:
            rt = getattr(self, "reading_type", "kunyomi")
            return f"Reading:{rt}"

    def finishTraining(self):
        self.build_results_page()
        idx = self.results_index()
        if idx is None:
            self.stack.slide_to(1, "right")
            return
        self.stack.slide_to(idx, "left")

    # ---------------- results page ----------------
    def build_results_page(self):
        if getattr(self, "_results_page", None) is None:
            layout = QVBoxLayout()
            back_layout = QHBoxLayout()
            back_btn = QPushButton("← Back")
            back_btn.setFixedSize(80, 28)
            back_btn.clicked.connect(lambda: self.stack.slide_to(1, "right"))
            back_layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
            back_layout.addStretch()
            layout.addLayout(back_layout)
            self._results_percent_label = QLabel("")
            self._results_percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._results_percent_label)
            self._results_count_label = QLabel("")
            self._results_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._results_count_label)
            self._results_xp_label = QLabel("")
            self._results_xp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_xp_label.setWordWrap(True)
            layout.addWidget(self._results_xp_label)

            self._results_xp_label = QLabel("")
            self._results_xp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_xp_label.setWordWrap(True)
            layout.addWidget(self._results_xp_label)

            # --- New Session button (starts a new drill with current filters) ---
            self._results_new_session_btn = QPushButton("New Session")
            self._results_new_session_btn.setFixedSize(160, 36)
            # center it under the XP/avg label
            layout.addWidget(self._results_new_session_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

            # connect to a small helper so behaviour is isolated
            self._results_new_session_btn.clicked.connect(lambda: self._start_new_session_from_results())

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            container = QWidget()
            self._results_list_layout = QVBoxLayout(container)
            self._results_list_layout.setContentsMargins(6, 6, 6, 6)
            self._results_list_layout.setSpacing(8)
            scroll.setWidget(container)
            layout.addWidget(scroll)

            page = QWidget()
            page.setLayout(layout)
            self._results_page = page
            self.stack.addWidget(self._results_page)

        total = len(self.session_results)
        correct_count = sum(1 for r in self.session_results if r.get("correct"))
        percent = int((correct_count / total) * 100) if total > 0 else 0
        self._results_percent_label.setText(f"{percent}%")
        self._results_count_label.setText(f"{correct_count}/{total} correct")

        try:
            end_avg = float(self.compute_average_proficiency_for_current_filter() or 0.0)
        except Exception:
            end_avg = 0.0
        start_avg = float(self._session_start_avg_prof or 0.0)
        delta = end_avg - start_avg
        sign = "+" if delta >= 0 else "-"
        delta_text = f"{sign}{abs(delta):.3f}%"
       
        s = self.drillFilters["system"]
        d = self.drillFilters["drill"]
        gained = int(self.session_xp.get(s, {}).get(d, 0))
        self._results_xp_label.setText(f"Session XP ({s} / {d}): +{gained}    Filter avg: {end_avg:.3f}% ( {delta_text})")

        # clear list
        while self._results_list_layout.count():
            item = self._results_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        wrongs = [r for r in self.session_results if not r.get("correct")]
        if not wrongs:
            lbl = QLabel("No wrong answers — great job!")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_list_layout.addWidget(lbl)
        else:
            for r in wrongs:
                frame = QFrame()
                frame.setFrameShape(QFrame.StyledPanel)
                f_layout = QHBoxLayout(frame)
                kanji_lbl = QLabel(str(r.get("kanji", "")))
                kanji_lbl.setFixedWidth(80)
                kanji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                expected_lbl = QLabel("Expected: " + str(r.get("expected", "")))
                expected_lbl.setWordWrap(True)
                f_layout.addWidget(kanji_lbl)
                f_layout.addWidget(expected_lbl)
                self._results_list_layout.addWidget(frame)
        self._results_list_layout.addStretch()

    # ---------------- profile page ----------------
    def change_profile_pfp(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Profile Picture", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"]:
            return
        # save the chosen image into the user data dir so it persists across runs
        new_local_name = os.path.join(self.appdata, "pfp" + ext)
        try:
            shutil.copyfile(path, new_local_name)
        except Exception:
            QMessageBox.warning(self, "Error", "Could not copy the selected image.")
            return
        self.profile_data["pfp_path"] = new_local_name
        self.save_profile()
        # update UI pixmaps if created
        try:
            pix = QPixmap(new_local_name).scaledToHeight(215, Qt.SmoothTransformation)
            if hasattr(self, "profilePFP"):
                self.profilePFP.setPixmap(pix)
            main_pix = QPixmap(new_local_name).scaledToHeight(215, Qt.SmoothTransformation)
            self.mainMenuPFP.setPixmap(main_pix)
            # adjust fixed size to new pixmap
            self.mainMenuPFP.setFixedSize(main_pix.width(), main_pix.height())
        except Exception:
            pass

    def save_username_from_profile(self):
        new_name = self.profileNameEdit.text().strip()
        if new_name == "":
            return
        self.profile_data["username"] = new_name
        self.save_profile()
        self.refresh_profile_page()

    def build_profile_page(self):
        if getattr(self, "_profile_page", None) is None:
            layout = QVBoxLayout()
            back_layout = QHBoxLayout()
            back_btn = QPushButton("← Back")
            back_btn.setFixedSize(80, 28)
            back_btn.clicked.connect(lambda: self.stack.slide_to(0, "right"))
            back_layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
            back_layout.addStretch()
            layout.addLayout(back_layout)

            self.profilePFP = ClickableLabel()
            pix_path = self.profile_data.get("pfp_path", resource_path("pfp.png"))
            try:
                pix = QPixmap(pix_path)
                if pix.isNull():
                    pix = QPixmap(resource_path("pfp.png"))
            except Exception:
                pix = QPixmap(resource_path("pfp.png"))
            pix = pix.scaledToHeight(215, Qt.SmoothTransformation)
            self.profilePFP.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.profilePFP.setPixmap(pix)
            self.profilePFP.set_on_click(self.change_profile_pfp)
            layout.addWidget(self.profilePFP)

            name_row = QHBoxLayout()
            self.profileNameEdit = QLineEdit()
            self.profileNameEdit.setText(self.profile_data.get("username", "User"))
            self.profileNameEdit.setMaximumWidth(260)
            save_name_btn = QPushButton("Save")
            save_name_btn.setFixedSize(70, 28)
            save_name_btn.clicked.connect(self.save_username_from_profile)
            self.profileNameEdit.returnPressed.connect(self.save_username_from_profile)
            name_row.addStretch()
            name_row.addWidget(self.profileNameEdit)
            name_row.addWidget(save_name_btn)
            name_row.addStretch()
            layout.addLayout(name_row)

            self.profileTotalQuestions = QLabel("")
            self.profileTotalQuestions.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(self.profileTotalQuestions)

            grid = QGridLayout()
            grid.setSpacing(8)
            self.profileBuckets = {}
            buckets = [("JLPT", "Meaning"), ("JLPT", "Reading"), ("WaniKani", "Meaning"), ("WaniKani", "Reading")]
            for i, (system_name, drill_name) in enumerate(buckets):
                block = QFrame()
                block.setFrameShape(QFrame.StyledPanel)
                bl = QVBoxLayout(block)
                title = QLabel(f"{system_name} / {drill_name}")
                title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                bl.addWidget(title)
                lvl_lbl = QLabel("")
                lvl_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                bl.addWidget(lvl_lbl)
                bar = QProgressBar()
                bar.setRange(0, 500)
                bl.addWidget(bar)
                pct_lbl = QLabel("")
                pct_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                bl.addWidget(pct_lbl)
                r = i // 2
                c = i % 2
                grid.addWidget(block, r, c)
                self.profileBuckets[(system_name, drill_name)] = (lvl_lbl, bar, pct_lbl)

            layout.addLayout(grid)

            page = QWidget()
            page.setLayout(layout)
            self._profile_page = page
            self.stack.addWidget(self._profile_page)

        self.refresh_profile_page()

    def _start_new_session_from_results(self):
        """
        Called from the results page 'New Session' button.
        Starts a new drill using the currently selected filters (re-uses DrillStart()).
        """
        # Close/hide results page and start a new drill in-place
        # Keep the same filters; DrillStart() will re-evaluate df_f and sample.
        try:
            self.DrillStart()
        except Exception:
            # fall back to sliding back to the Drill menu if drill fails
            idx = 1  # drill menu index
            self.stack.slide_to(idx, "right")

    def _on_stack_changed(self, index: int):
        """
        Called when the stacked widget changes page.
        When returning to the Drill menu (index 1) recompute the filtered df and update the label.
        """
        # index 1 is the Drill menu in your current setup
        if index == 1:
            # rebuild df_f so update_count_label sees the latest stats/mastery values
            try:
                if self.drillFilters["system"] == "JLPT":
                    self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
                else:
                    self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
            except Exception:
                pass
            # update label (this will call compute_average_proficiency_for_current_filter)
            try:
                self.update_count_label()
            except Exception:
                pass

    def refresh_profile_page(self):
        if getattr(self, "_profile_page", None) is None:
            return
        # sync username edit
        try:
            self.profileNameEdit.setText(self.profile_data.get("username", "User"))
        except Exception:
            pass
        # total questions
        self.profileTotalQuestions.setText(f"Total Questions Answered: {self.total_questions_answered_overall()}")
        for (system_name, drill_name), (lvl_lbl, bar, pct_lbl) in self.profileBuckets.items():
            xp_value = int(self.profile_data["xp"].get(system_name, {}).get(drill_name, 0))
            level, within, cap, pct = self.get_bucket_level_progress(xp_value)
            lvl_lbl.setText(f"Level {level}")
            bar.setRange(0, cap)
            bar.setValue(within)
            pct_lbl.setText(f"{pct}% ({within}/{cap})")
        self.mainMenuUsername.setText(self.profile_data.get("username", "User"))
        try:
            pix = QPixmap(self.profile_data.get("pfp_path", resource_path("pfp.jpg"))).scaledToHeight(215, Qt.SmoothTransformation)
            self.mainMenuPFP.setPixmap(pix)
            self.mainMenuPFP.setFixedSize(pix.width(), pix.height())
        except Exception:
            pass

    # ---------------- keyboard handling ----------------
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            idx = self.stack.currentIndex()
            if idx == 1:
                self.stack.slide_to(0, "right")
                return
            if idx == 2:
                self.stack.slide_to(1, "right")
                return
            r_idx = self.results_index()
            if r_idx is not None and idx == r_idx:
                self.stack.slide_to(1, "right")
                return
            p_idx = self.profile_index()
            if p_idx is not None and idx == p_idx:
                self.stack.slide_to(0, "right")
                return

        keys = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2, Qt.Key_4: 3}
        if key in keys and hasattr(self, "answer_buttons"):
            idx = keys[key]
            if idx < len(self.answer_buttons):
                btn = self.answer_buttons[idx]
                if btn is not None and btn.isEnabled():
                    is_correct = (btn.text() == getattr(self, "correct_answer_text", ""))
                    self.checkAnswer(is_correct, btn)
                    return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            r_idx = self.results_index()
            if r_idx is not None and self.stack.currentIndex() == r_idx:
                btn = getattr(self, "_results_new_session_btn", None)
                if btn is not None and btn.isEnabled():
                    # emulate click
                    btn.click()
                    return

        super().keyPressEvent(event)


def basicLoop():
    app = QApplication(sys.argv)

    icon_path = resource_path("app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    basicLoop()
