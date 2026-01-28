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
from PySide6.QtGui import QFont, QColor, QPixmap, QPainter, QTextOption, QIcon
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


def resource_path(relative_path: str) -> str:
    """
    Return a path to a resource that works both bundled by PyInstaller (onefile)
    and in development.
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)


def user_data_dir(app_name: str = "KanjiDriller") -> str:
    
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")

    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path


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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect()
        painter.fillRect(r, self.palette().button())

        painter.setPen(self.palette().buttonText().color())
        painter.setFont(self.font())

        pad = 8
        text_rect = QRect(r.left() + pad, r.top() + pad, r.width() - pad * 2, r.height() - pad * 2)

        flags = Qt.TextWordWrap | Qt.AlignCenter
        painter.drawText(text_rect, int(flags), self._wrap_text)

        if self.underMouse():
            painter.setPen(self.palette().mid().color())
            painter.drawRect(r.adjusted(0, 0, -1, -1))

        painter.end()


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

class HeatmapDialog(QWidget):
    def __init__(self, parent=None, activity=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Activity Heatmap")
        self.activity = activity or {}
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()

        self.year_combo = QComboBox()
        self.month_combo = QComboBox()

        years = self._available_years()
        if not years:
            years = [int(time.strftime("%Y"))]
        for y in sorted(years, reverse=True):
            self.year_combo.addItem(str(y))

        import calendar as _calendar
        months = [("All", 0)] + [( _calendar.month_name[m], m) for m in range(1, 13)]
        self.months = months
        for name, m in self.months:
            self.month_combo.addItem(name, m)

        controls.addWidget(QLabel("Year:"))
        controls.addWidget(self.year_combo)
        controls.addWidget(QLabel("Month:"))
        controls.addWidget(self.month_combo)
        controls.addStretch()

        self.legend_label = QLabel("")
        controls.addWidget(self.legend_label)

        layout.addLayout(controls)

        class Canvas(QWidget):
            def __init__(self, owner):
                super().__init__(owner)
                self.owner = owner
                self.setMouseTracking(True)

            def paintEvent(self, ev):
                painter = QPainter(self)
                try:
                    self.owner._draw_heatmap(self, painter)
                finally:
                    painter.end()

            def mouseMoveEvent(self, ev):
                self.owner._handle_mouse_move(self, ev.pos())

            def leaveEvent(self, ev):
                self.owner._hide_hover()

        self.canvas = Canvas(self)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.canvas)

        self._hover_label = QLabel("", self.canvas)
        self._hover_label.setStyleSheet("background: rgba(0,0,0,0.75); color: white; padding:4px; border-radius:4px;")
        self._hover_label.hide()

        self.year_combo.currentIndexChanged.connect(lambda _: self.canvas.update())
        self.month_combo.currentIndexChanged.connect(lambda _: self.canvas.update())

    def _available_years(self):
        years = set()
        for k in (self.activity or {}).keys():
            try:
                years.add(int(k[:4]))
            except Exception:
                pass
        return sorted(years)

    def _gather_month_map(self, year, month):
        data = {}
        if month == 0:
            for daykey, v in (self.activity or {}).items():
                try:
                    y, m, d = daykey.split("-")
                    y_i = int(y); m_i = int(m)
                except Exception:
                    continue
                if y_i != year:
                    continue
                rec = data.setdefault(m_i, {"questions": 0, "seconds": 0})
                rec["questions"] += int((v or {}).get("questions", 0) or 0)
                rec["seconds"] += int((v or {}).get("seconds", 0) or 0)
        else:
            import calendar
            _, ndays = calendar.monthrange(year, month)
            for day in range(1, ndays + 1):
                key = f"{year:04d}-{month:02d}-{day:02d}"
                rec = self.activity.get(key) or {}
                data[day] = {"questions": int(rec.get("questions", 0) or 0), "seconds": int(rec.get("seconds", 0) or 0)}
        return data

    def _max_value_in_map(self, m):
        if not m:
            return 0
        return max((v.get("questions", 0) for v in m.values()), default=0)

    def _mix_gray_to_green(self, t):
        from PySide6.QtGui import QColor
        t = max(0.0, min(1.0, float(t)))
        g_r = int(200 + (0 - 200) * t)
        g_g = int(200 + (180 - 200) * t)
        g_b = int(200 + (0 - 200) * t)
        return QColor(g_r, g_g, g_b)

    def _draw_heatmap(self, canvas_widget, painter):
        w = canvas_widget.width()
        h = canvas_widget.height()
        painter.fillRect(0, 0, w, h, canvas_widget.palette().window())

        year_text = self.year_combo.currentText()
        try:
            year = int(year_text)
        except Exception:
            year = int(time.strftime("%Y"))
        month = int(self.month_combo.currentData() or 0)

        data_map = self._gather_month_map(year, month)
        maxv = max(1, self._max_value_in_map(data_map))

        painter.setPen(Qt.black)

        if month == 0:
            cols = 4
            rows = 3
            pad = 12
            box_w = max(24, (w - pad * 2) // cols - 8)
            box_h = max(24, (h - 60 - pad * 2) // rows - 8)
            for i in range(12):
                mnum = i + 1
                r = i // cols
                c = i % cols
                x = pad + c * (box_w + 8)
                y = pad + r * (box_h + 8) + 30
                rec = data_map.get(mnum, {"questions": 0, "seconds": 0})
                val = int(rec.get("questions", 0) or 0)
                t = val / float(maxv)
                color = self._mix_gray_to_green(t)
                painter.fillRect(x, y, box_w, box_h, color)
                painter.drawRect(x, y, box_w, box_h)
                painter.drawText(x + 6, y + 18, time.strftime("%b", time.strptime(f"{mnum}", "%m")))
                setattr(self, f"_cell_{i}", QRect(x, y, box_w, box_h))
                setattr(self, f"_cell_val_{i}", (mnum, rec))
        else:
            import calendar
            cal = calendar.Calendar(firstweekday=0)
            days = list(cal.itermonthdates(year, month))
            month_days = [d for d in days if d.month == month]
            cols = 7
            first_weekday = month_days[0].weekday()
            rows = ((len(month_days) + first_weekday) + (cols - 1)) // cols
            pad = 10
            top = 30
            box_w = max(18, (w - pad * 2) // cols - 6)
            box_h = max(18, (h - top - pad * 2) // rows - 6)
            import datetime

            today = datetime.date.today()
            is_current_month = (today.year == year and today.month == month)

            header_h = 22
            header_y = top - header_h - 6

            base_bg = canvas_widget.palette().window().color()
            header_grey = canvas_widget.palette().mid().color()
            header_grey_brush = header_grey

            today_highlight = QColor(180, 210, 255)

            border_color = canvas_widget.palette().shadow().color()
            painter.setPen(border_color)

            weekday_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            for c in range(7):
                txt = weekday_names[c]
                hx = pad + c * (box_w + 6)
                header_rect = QRect(hx, header_y, box_w, header_h)

                if is_current_month and c == today.weekday():
                    painter.fillRect(header_rect, today_highlight)
                else:
                    painter.fillRect(header_rect, header_grey_brush)

                painter.drawRect(header_rect)
                painter.setPen(Qt.black)
                painter.drawText(header_rect, Qt.AlignCenter, txt)
            for idx, d in enumerate(month_days):
                pos = idx + first_weekday
                r = pos // cols
                c = pos % cols
                x = pad + c * (box_w + 6)
                y = top + r * (box_h + 6)
                rec = data_map.get(d.day, {"questions": 0, "seconds": 0})
                val = int(rec.get("questions", 0) or 0)
                t = val / float(maxv)
                color = self._mix_gray_to_green(t)
                cell_rect = QRect(x, y, box_w, box_h)
                painter.fillRect(cell_rect, color)
                painter.drawRect(cell_rect)

                painter.setPen(Qt.black)
                painter.drawText(cell_rect, Qt.AlignCenter, str(d.day))
                setattr(self, f"_cell_{idx}", QRect(x, y, box_w, box_h))
                setattr(self, f"_cell_val_{idx}", (d, rec))

        self.legend_label.setText(f"Max: {maxv} questions — gray→green scale")

    def _handle_mouse_move(self, canvas_widget, pos):
        def fmt_time(seconds):
            try:
                s = int(seconds or 0)
                h = s // 3600
                m = (s % 3600) // 60
                if h > 0:
                    return f"{h}h {m}m"
                return f"{m}m"
            except Exception:
                return "0m"

        for attr in dir(self):
            if not attr.startswith("_cell_") or attr.startswith("_cell_val_"):
                continue
            rect = getattr(self, attr)
            if isinstance(rect, QRect) and rect.contains(pos):
                idx = attr.split("_")[-1]
                valattr = f"_cell_val_{idx}"
                if hasattr(self, valattr):
                    v = getattr(self, valattr)
                    if isinstance(v, tuple):
                        key, rec = v
                        rec = rec or {}
                        q = int(rec.get("questions", 0) or 0)
                        secs = int(rec.get("seconds", 0) or 0)
                        timestr = fmt_time(secs)
                        if isinstance(key, int):
                            try:
                                month_name = time.strftime('%B', time.strptime(str(key), '%m'))
                            except Exception:
                                month_name = str(key)
                            text = f"{month_name} {self.year_combo.currentText()}: {q} questions — {timestr}"
                        else:
                            text = f"{key.isoformat()}: {q} questions — {timestr}"
                        self._hover_label.setText(text)
                        self._hover_label.adjustSize()
                        x = pos.x() + 12
                        y = pos.y() + 12
                        max_x = canvas_widget.width() - self._hover_label.width() - 6
                        max_y = canvas_widget.height() - self._hover_label.height() - 6
                        x = min(max(6, x), max_x)
                        y = min(max(6, y), max_y)
                        self._hover_label.move(x, y)
                        self._hover_label.show()
                        return
        self._hover_label.hide()

    def _hide_hover(self):
        if hasattr(self, "_hover_label"):
            self._hover_label.hide()
    

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        appdata = user_data_dir("KanjiDriller")
        self.stats_path = os.path.join(appdata, "kanji_stats.json")
        self.profile_path = os.path.join(appdata, "profile.json")
        self.appdata = appdata

        self.drillFilters = {
            "system": "JLPT",
            "drill": "Meaning",
            "jlpt_levels": [5],
            "wanikani_levels": [],
            "count": 4,
            "max_count": 79,
            "prioritize_weakness": True
        }

        self.jlpt_sublevel_counts = {
            1: 7,
            2: 2,
            3: 2
        }
        self.drillFilters.setdefault("jlpt_sublevels", {})
        self.drillFilters.setdefault("jlpt_levels", [])
        self.kanji_stats = {}
        self.profile_data = {}
        self._results_page = None
        self._profile_page = None

        self.load_or_create_stats()
        self.load_or_create_profile()

        self.profile_data.setdefault("activity", {})
        self.save_profile()

        self.df_f = self.build_filtered_df()
        self.currentSample = getRandomSample(self.df_f, self.drillFilters["count"])

        self.currentRow = None
        self.currentQuestionBatch = None
        self.currentAnswer = None

        self.currentQuestionIndex = 0
        self.totalQuestions = 0

        self.popup_seconds = 1.5
        self._session_start_avg_prof = None

        self.session_results = []
        self.session_xp = {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}

        self.setWindowTitle("Kanji Driller")
        self.setFixedSize(500, 600)

        self._button_min_width = max(300, self.width() - 40)

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

        mainMenuLayout = QVBoxLayout()
        mainMenuLayout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mainMenuLayout.setContentsMargins(24, 16, 24, 16)
        mainMenuLayout.setSpacing(12)

        mainMenuTitle = QLabel("Kanji Driller")
        mainMenuTitle.setSizePolicy(mainMenuTitle.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        mainMenuTitle.setFont(QFont(mainMenuTitle.font().family(), 42))
        mainMenuLayout.addWidget(mainMenuTitle, alignment=Qt.AlignmentFlag.AlignHCenter)

        profile_col = QVBoxLayout()
        profile_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        profile_col.setSpacing(8)

        self.mainMenuUsername = QLabel(self.profile_data.get("username", "User"))
        self.mainMenuUsername.setFont(QFont(mainMenuTitle.font().family(), 18))
        self.mainMenuUsername.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mainMenuPFP = ClickableLabel()
        main_pix_path = self.profile_data.get("pfp_path", resource_path("pfp.png"))
        try:
            mainPix = QPixmap(main_pix_path)
            if mainPix.isNull():
                mainPix = QPixmap(resource_path("pfp.jpg"))
        except Exception:
            mainPix = QPixmap(resource_path("pfp.jpg"))
        mainPix = mainPix.scaledToHeight(215, Qt.SmoothTransformation)
        self.mainMenuPFP.setPixmap(mainPix)
        self.mainMenuPFP.setFixedSize(mainPix.width(), mainPix.height())
        self.mainMenuPFP.set_on_click(lambda: (self.build_profile_page(), self.stack.slide_to(self.profile_index(), "left")))

        profile_col.addWidget(self.mainMenuUsername)
        profile_col.addWidget(self.mainMenuPFP)
        mainMenuLayout.addLayout(profile_col)

        mainMenuLayout.addSpacing(12)

        buttons_box = QVBoxLayout()
        buttons_box.setSpacing(14)
        buttons_box.setContentsMargins(0, 0, 0, 0)

        available_width = max(0, self.width() - (mainMenuLayout.contentsMargins().left() + mainMenuLayout.contentsMargins().right()))
        target_block_width = min(self._button_min_width, max(300, available_width - 80))

        mainMenuDrillButton = QPushButton("Drill")
        mainMenuDrillButton.setFixedWidth(target_block_width)
        mainMenuDrillButton.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Fixed)
        mainMenuDrillButton.setFixedHeight(88)
        mainMenuDrillButton.clicked.connect(lambda: self.stack.slide_to(1, "left"))

        mainMenuProfileButton = QPushButton("Profile")
        mainMenuProfileButton.setFixedWidth(target_block_width)
        mainMenuProfileButton.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Fixed)
        mainMenuProfileButton.setFixedHeight(88)
        mainMenuProfileButton.clicked.connect(lambda: (self.build_profile_page(), self.stack.slide_to(self.profile_index(), "left")))

        buttons_box.addWidget(mainMenuDrillButton, alignment=Qt.AlignmentFlag.AlignHCenter)
        buttons_box.addWidget(mainMenuProfileButton, alignment=Qt.AlignmentFlag.AlignHCenter)

        buttons_container_h = QHBoxLayout()
        buttons_container_h.setContentsMargins(0, 0, 0, 0)
        buttons_container_h.addStretch()
        buttons_container_h.addLayout(buttons_box)
        buttons_container_h.addStretch()

        mainMenuLayout.addLayout(buttons_container_h)
        mainMenuLayout.addStretch()

        mainMenuPage = QWidget()
        mainMenuPage.setLayout(mainMenuLayout)

        DrillMenuLayout = QVBoxLayout()

        DrillMenuBackLayout = QHBoxLayout()
        DrillMenuBack = QPushButton("← Back")
        DrillMenuBack.setFixedSize(80, 28)
        DrillMenuBack.clicked.connect(lambda: self.stack.slide_to(0, "right"))
        DrillMenuBackLayout.addWidget(DrillMenuBack, alignment=Qt.AlignmentFlag.AlignLeft)
        DrillMenuBackLayout.addStretch()
        DrillMenuLayout.addLayout(DrillMenuBackLayout)

        self.DrillMenuSystemCombo = QComboBox()
        self.DrillMenuSystemCombo.addItems(["JLPT", "WaniKani"])
        try:
            cur_sys = str(self.drillFilters.get("system", "JLPT"))
            idx = 0 if cur_sys == "JLPT" else 1
            self.DrillMenuSystemCombo.setCurrentIndex(idx)
        except Exception:
            pass
        self.DrillMenuSystemCombo.currentTextChanged.connect(self.filtersystem_changed)
        DrillMenuLayout.addWidget(self.DrillMenuSystemCombo)

        DrillMenuDrillCombo = QComboBox()
        DrillMenuDrillCombo.addItems(["Meaning", "Reading"])
        DrillMenuDrillCombo.currentTextChanged.connect(self.filterdrill_changed)
        DrillMenuLayout.addWidget(DrillMenuDrillCombo)

        self.DrillMenuMeaningModeCombo = QComboBox()
        self.DrillMenuMeaningModeCombo.addItems(["Multiple Choice", "Writing"])
        self.DrillMenuMeaningModeCombo.setCurrentIndex(0)
        self.DrillMenuMeaningModeCombo.currentTextChanged.connect(self.meaningmode_changed)
        DrillMenuLayout.addWidget(self.DrillMenuMeaningModeCombo)

        if self.drillFilters.get("drill", "Meaning") != "Meaning":
            self.DrillMenuMeaningModeCombo.hide()

        self.DrillMenuReadingTypeCombo = QComboBox()
        self.DrillMenuReadingTypeCombo.addItems(["Kunyomi", "Onyomi"])
        self.DrillMenuReadingTypeCombo.setCurrentIndex(0)
        self.DrillMenuReadingTypeCombo.currentTextChanged.connect(self.readingtype_changed)
        DrillMenuLayout.addWidget(self.DrillMenuReadingTypeCombo)
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

        self.DrillMenuPopupSpin = popup_spin
        popup_spin.valueChanged.connect(lambda v: setattr(self, "popup_seconds", float(v)))

        popup_row.addWidget(popup_label)
        popup_row.addWidget(popup_spin)
        DrillMenuLayout.addLayout(popup_row)

        self.DrillMenuPrioritizeWeaknessCB = QCheckBox("Prioritize weakness")
        self.DrillMenuPrioritizeWeaknessCB.setChecked(bool(self.drillFilters.get("prioritize_weakness", True)))
        self.DrillMenuPrioritizeWeaknessCB.stateChanged.connect(self.prioritizeweakness_changed)
        DrillMenuLayout.addWidget(self.DrillMenuPrioritizeWeaknessCB)

        self.DrillMenuJLPTSection = QWidget()
        jlpt_v = QVBoxLayout(self.DrillMenuJLPTSection)
        jlpt_v.setAlignment(Qt.AlignmentFlag.AlignTop)
        jlpt_v.setContentsMargins(0, 0, 0, 0)
        jlpt_v.setSpacing(20)

        jlpt_label = QLabel("Level:")
        f = jlpt_label.font()
        f.setUnderline(True)
        jlpt_label.setFont(f)
        jlpt_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        jlpt_v.addWidget(jlpt_label)

        jlpt_grid_widget = QWidget()
        jlpt_grid = QGridLayout(jlpt_grid_widget)
        jlpt_grid.setContentsMargins(0, 0, 0, 0)
        jlpt_grid.setHorizontalSpacing(6)
        jlpt_grid.setVerticalSpacing(20)

        self._jlpt_base_checkboxes = {}
        self._jlpt_sub_checkboxes = {}

        levels_order = []
        levels_order.append((5, None))
        levels_order.append((4, None))
        for si in range(1, self.jlpt_sublevel_counts.get(3, 1) + 1):
            levels_order.append((3, si))
        for si in range(1, self.jlpt_sublevel_counts.get(2, 1) + 1):
            levels_order.append((2, si))
        for si in range(1, self.jlpt_sublevel_counts.get(1, 1) + 1):
            levels_order.append((1, si))

        cols = 5
        for idx, (base, sub) in enumerate(levels_order):
            r = idx // cols
            c = idx % cols
            text = f"N{base}" if sub is None else f"N{base}.{sub}"
            cb = QCheckBox(text)
            cb.stateChanged.connect(self.level_filter)
            if sub is None:
                cb.setChecked(base in self.drillFilters.get("jlpt_levels", []))
                self._jlpt_base_checkboxes[base] = cb
            else:
                existing = self.drillFilters.get("jlpt_sublevels", {}).get(base)
                if existing and sub in existing:
                    cb.setChecked(True)
                self._jlpt_sub_checkboxes[(base, sub)] = cb
            jlpt_grid.addWidget(cb, r, c)

        jlpt_v.addWidget(jlpt_grid_widget)
        DrillMenuLayout.addWidget(self.DrillMenuJLPTSection)

        self.DrillMenuWaniKaniSection = QWidget()
        wk_v = QVBoxLayout(self.DrillMenuWaniKaniSection)
        wk_v.setAlignment(Qt.AlignmentFlag.AlignTop)
        wk_v.setContentsMargins(0, 0, 0, 0)
        wk_v.setSpacing(20)

        wk_label = QLabel("Level:")
        f = wk_label.font()
        f.setUnderline(True)
        wk_label.setFont(f)
        wk_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        wk_v.addWidget(wk_label)

        wk_grid_widget = QWidget()
        wk_grid = QGridLayout(wk_grid_widget)
        wk_grid.setHorizontalSpacing(5)
        wk_grid.setVerticalSpacing(12)
        wk_grid.setContentsMargins(0, 0, 0, 0)

        columns = 10
        start_col = 1
        for i in range(1, 61):
            checkbox = QCheckBox(str(i))
            checkbox.stateChanged.connect(self.level_filter)
            index = i - 1
            row = index // columns
            col = index % columns
            wk_grid.addWidget(checkbox, row, col)

        wk_v.addWidget(wk_grid_widget)
        DrillMenuLayout.addWidget(self.DrillMenuWaniKaniSection)
        self.DrillMenuWaniKaniSection.hide()

        if self.drillFilters.get("system", "JLPT") == "WaniKani":
            self.DrillMenuJLPTSection.hide()
            self.DrillMenuWaniKaniSection.show()
        else:
            self.DrillMenuJLPTSection.show()
            self.DrillMenuWaniKaniSection.hide()

        mainMenuDrillButton = QPushButton("Drill")
        mainMenuDrillButton.clicked.connect(lambda: self.DrillStart())
        DrillMenuLayout.addWidget(mainMenuDrillButton)

        DrillMenuPage = QWidget()
        DrillMenuPage.setLayout(DrillMenuLayout)

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

        self.stack.addWidget(mainMenuPage)
        self.stack.addWidget(DrillMenuPage)
        self.stack.addWidget(TrainPage)

        self.setCentralWidget(self.stack)

        self.update_count_label()

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
        default_profile = {
            "username": "User",
            "pfp_path": os.path.join(self.appdata, "pfp.png"),
            "xp": {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}
        }

        self.profile_data.setdefault("activity", {})

        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    self.profile_data = json.load(f)
            except Exception:
                self.profile_data = default_profile.copy()
        else:
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
                self.profile_data["pfp_path"] = resource_path("pfp.jpg")

            try:
                if not os.path.exists(target_pfp):
                    shutil.copyfile(bundled_pfp, target_pfp)
            except Exception:
                pass
            self.profile_data = default_profile.copy()
            self.save_profile()

        self.profile_data.setdefault("username", "User")
        pfp_path = self.profile_data.get("pfp_path")
        if not pfp_path:
            pfp_path = os.path.join(self.appdata, "pfp.jpg")
            self.profile_data["pfp_path"] = pfp_path

        if not os.path.exists(pfp_path):
            bundled = resource_path("pfp.jpg")
            try:
                shutil.copyfile(bundled, os.path.join(self.appdata, "pfp.jpg"))
                self.profile_data["pfp_path"] = os.path.join(self.appdata, "pfp.jpg")
            except Exception:
                self.profile_data["pfp_path"] = bundled

        self.profile_data.setdefault("xp", {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}})
        for sysn in ("JLPT", "WaniKani"):
            self.profile_data["xp"].setdefault(sysn, {})
            for dr in ("Meaning", "Reading"):
                self.profile_data["xp"][sysn].setdefault(dr, 0)
        self.profile_data.setdefault("pw_question_counter", 0)
        self.profile_data.setdefault("pw_session_counter", 0)
        self.save_profile()

    def save_profile(self):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def xp_per_correct(self, system_name, drill_name):
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

    def update_count_label(self):
        if self.drillFilters["system"] == "JLPT":
            levels = self.drillFilters["jlpt_levels"]
        else:
            levels = self.drillFilters["wanikani_levels"]

        try:
            if getattr(self, "df_f", None) is not None:
                self.drillFilters["max_count"] = int(getattr(self.df_f, "shape", (0, 0))[0])
            else:
                try:
                    self.drillFilters["max_count"] = int(getMaxCount(self.drillFilters["system"], levels, self.drillFilters["drill"]))
                except Exception:
                    self.drillFilters["max_count"] = 0
        except Exception:
            self.drillFilters["max_count"] = 0

        self.drillFilters["max_count"] = int(self.drillFilters["max_count"] or 0)

        avg_prof = self.compute_average_proficiency_for_current_filter()
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
        self.drillFilters["system"] = str(text)

        try:
            if self.drillFilters["system"] == "WaniKani":
                self.DrillMenuJLPTSection.hide()
                self.DrillMenuWaniKaniSection.show()
            else:
                self.DrillMenuWaniKaniSection.hide()
                self.DrillMenuJLPTSection.show()
        except Exception:
            pass

        if self.drillFilters.get("drill", "Meaning") == "Reading":
            self.DrillMenuReadingTypeCombo.show()
        else:
            self.DrillMenuReadingTypeCombo.hide()

        if self.drillFilters.get("drill", "Meaning") == "Meaning":
            self.DrillMenuMeaningModeCombo.show()
        else:
            self.DrillMenuMeaningModeCombo.hide()

        try:
            self.df_f = self.build_filtered_df()
        except Exception:
            try:
                if self.drillFilters["system"] == "JLPT":
                    self.df_f = filterDataFrame("JLPT", self.drillFilters.get("jlpt_levels", []), self.drillFilters.get("drill", "Meaning"))
                else:
                    self.df_f = filterDataFrame("WaniKani", self.drillFilters.get("wanikani_levels", []), self.drillFilters.get("drill", "Meaning"))
            except Exception:
                self.df_f = None

        try:
            self.update_count_label()
        except Exception:
            pass

    def filterdrill_changed(self, text):
        self.drillFilters["drill"] = text
        if text == "Reading":
            self.DrillMenuReadingTypeCombo.show()
        else:
            self.DrillMenuReadingTypeCombo.hide()

        if text == "Meaning":
            self.DrillMenuMeaningModeCombo.show()
        else:
            self.DrillMenuMeaningModeCombo.hide()

        if self.drillFilters["system"] == "JLPT":
            self.df_f = self.build_filtered_df()
        else:
            self.df_f = self.build_filtered_df()
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
            if text.lower().startswith("n"):
                parts = text.lstrip("Nn").split(".")
                try:
                    base = int(parts[0])
                except Exception:
                    return
                jlpt_levels = self.drillFilters.setdefault("jlpt_levels", [])
                if len(parts) == 1:
                    if checked:
                        if base not in jlpt_levels:
                            jlpt_levels.append(base)
                    else:
                        if base in jlpt_levels:
                            jlpt_levels.remove(base)
                        self.drillFilters.setdefault("jlpt_sublevels", {}).pop(base, None)
                        for si in range(1, self.jlpt_sublevel_counts.get(base, 1) + 1):
                            cb = self._jlpt_sub_checkboxes.get((base, si))
                            if cb:
                                try:
                                    cb.blockSignals(True)
                                    cb.setChecked(False)
                                finally:
                                    cb.blockSignals(False)
                else:
                    try:
                        subidx = int(parts[1])
                    except Exception:
                        return
                    submap = self.drillFilters.setdefault("jlpt_sublevels", {})
                    slist = submap.setdefault(base, [])
                    # ensure it's a list (in case older data used sets)
                    if isinstance(slist, set):
                        slist = list(slist)
                        submap[base] = slist

                    if checked:
                        if subidx not in slist:
                            slist.append(subidx)
                        if base not in jlpt_levels:
                            jlpt_levels.append(base)
                            base_cb = self._jlpt_base_checkboxes.get(base)
                            if base_cb:
                                try:
                                    base_cb.blockSignals(True)
                                    base_cb.setChecked(True)
                                finally:
                                    base_cb.blockSignals(False)
                    else:
                        if subidx in slist:
                            try:
                                slist.remove(subidx)
                            except ValueError:
                                pass

                        if not slist:
                            submap.pop(base, None)
                            try:
                                if base in jlpt_levels:
                                    jlpt_levels.remove(base)
                                    base_cb = self._jlpt_base_checkboxes.get(base)
                                    if base_cb:
                                        try:
                                            base_cb.blockSignals(True)
                                            base_cb.setChecked(False)
                                        finally:
                                            base_cb.blockSignals(False)
                            except Exception:
                                pass
                try:
                    self.df_f = self.build_filtered_df()
                except Exception:
                    try:
                        self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
                    except Exception:
                        self.df_f = None
                self.update_count_label()
                return
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
        try:
            self.df_f = self.build_filtered_df()
        except Exception:
            try:
                self.df_f = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
            except Exception:
                self.df_f = None
        self.update_count_label()

    def _start_session_timer(self):
        try:
            self._session_timer_start = time.time()
            self._session_accum_seconds = 0.0
        except Exception:
            self._session_timer_start = None
            self._session_accum_seconds = 0.0

    def _slice_df_into_subgroups(self, df_level, group_count, subindex):
        import pandas as pd
        if df_level is None or getattr(df_level, "shape", (0, 0))[0] == 0:
            return df_level.iloc[0:0].copy()
        n = int(df_level.shape[0])
        base = n // group_count
        rem = n % group_count
        idx = subindex - 1
        start = idx * base + min(idx, rem)
        size = base + (1 if idx < rem else 0)
        return df_level.iloc[start:start + size].copy()

    def build_filtered_df(self):
        import pandas as pd
        system = self.drillFilters.get("system", "JLPT")
        drill = self.drillFilters.get("drill", "Meaning")
        if system != "JLPT":
            try:
                return filterDataFrame(system, self.drillFilters.get("wanikani_levels", []), drill)
            except Exception:
                try:
                    return filterDataFrame(system, self.drillFilters.get("wanikani_levels", []), drill)
                except Exception:
                    return pd.DataFrame()
        result_parts = []
        jlpt_levels = list(sorted(set(self.drillFilters.get("jlpt_levels", [])), reverse=False))
        if not jlpt_levels:
            return pd.DataFrame()
        for base in jlpt_levels:
            try:
                level_df = filterDataFrame("JLPT", [base], drill)
            except Exception:
                try:
                    level_df = filterDataFrame("JLPT", [base], drill)
                except Exception:
                    level_df = None
            if level_df is None or getattr(level_df, "shape", (0, 0))[0] == 0:
                continue
            group_count = self.jlpt_sublevel_counts.get(base, 1)
            selected_subs = self.drillFilters.get("jlpt_sublevels", {}).get(base, [])
            if selected_subs is None:
                selected_subs = []
            try:
                selected_subs = sorted(int(x) for x in list(selected_subs))
            except Exception:
                selected_subs = []
            if group_count == 1:
                result_parts.append(level_df.copy())
            else:
                if selected_subs:
                    for subidx in selected_subs:
                        if subidx < 1 or subidx > group_count:
                            continue
                        slice_df = self._slice_df_into_subgroups(level_df, group_count, subidx)
                        result_parts.append(slice_df)
                else:
                    result_parts.append(level_df.copy())
        if not result_parts:
            return pd.DataFrame()
        combined = pd.concat(result_parts, ignore_index=True)
        return combined

    def _stop_session_timer_and_record(self):
        try:
            if self._session_timer_start is None:
                return
            elapsed = time.time() - float(self._session_timer_start)
            self._session_accum_seconds += max(0.0, float(elapsed))
            self._session_timer_start = None
        except Exception:
            elapsed = 0.0

        today = time.strftime("%Y-%m-%d")
        act = self.profile_data.setdefault("activity", {})
        entry = act.setdefault(today, {"questions": 0, "seconds": 0})
        try:
            entry["seconds"] = int(entry.get("seconds", 0)) + int(round(self._session_accum_seconds))
        except Exception:
            entry["seconds"] = int(round(self._session_accum_seconds))
        self.save_profile()
        self._session_accum_seconds = 0.0

    def _record_one_question_now(self):
        today = time.strftime("%Y-%m-%d")
        act = self.profile_data.setdefault("activity", {})
        entry = act.setdefault(today, {"questions": 0, "seconds": 0})
        try:
            entry["questions"] = int(entry.get("questions", 0)) + 1
        except Exception:
            entry["questions"] = 1
        self.save_profile()

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
            if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF) or (0xF900 <= code <= 0xFAFF):
                return True
        return False

    def _answer_button_font_for_text(self, text: str) -> QFont:
        f = QFont()
        if self._contains_kanji(text):
            f.setPointSize(44)
        else:
            f.setPointSize(14)
        return f

    def _pick_readings_text(self, row, is_jlpt, prefer):
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
        exclude = set(exclude or [])
        candidates = []
        for _, r in batch_df.iterrows():
            rd = self._pick_readings_text(r, is_jlpt, prefer)
            if rd and rd not in exclude:
                candidates.append(rd)

        candidates = list(dict.fromkeys(candidates))
        random.shuffle(candidates)
        return candidates[:needed]
    
    def _normalize_meaning_list(self, val):
        if val is None:
            return []
        if isinstance(val, (list, tuple)):
            items = [str(x).strip() for x in val if x is not None and str(x).strip()]
            return items
        s = str(val).strip()
        if not s:
            return []
        parts = [p.strip() for p in s.replace(";", ",").split(",")]
        return [p for p in parts if p]

    def _is_meaning_input_correct(self, user_text: str, meanings_list):
        if user_text is None:
            return False

        targets = [m.strip().lower() for m in meanings_list if m and str(m).strip()]
        targets = [t for t in targets if t]
        if not targets:
            return False

        raw = str(user_text).strip().lower()
        if not raw:
            return False

        user_parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        user_parts = [p for p in user_parts if p]

        if len(user_parts) == 1:
            return user_parts[0] in targets

        target_set = set(targets)
        user_set = set(user_parts)

        return bool(user_set) and user_set.issubset(target_set)
    
    def submit_meaning_written(self):
        edit = getattr(self, "meaning_input", None)
        btn = getattr(self, "meaning_enter_btn", None)
        if edit is None:
            return

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

        meanings_list = getattr(self, "_current_meanings_list", [])
        is_correct = self._is_meaning_input_correct(user_text, meanings_list)

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
            targets = [m.strip().lower() for m in meanings_list if m and str(m).strip()]

            raw = str(user_text).strip().lower()
            user_parts = [p.strip() for p in raw.replace(";", ",").split(",")]
            user_parts = [p for p in user_parts if p]

            missed = sorted(set(targets) - set(user_parts))

            if missed:
                missed_display = ", ".join(missed)
                self.show_overlay(
                    text="Partially correct",
                    is_correct=True,
                    answers=missed_display
                )
            else:
                self.show_overlay(
                    text="Correct",
                    is_correct=True,
                    answers=""
                )
        else:
            self.show_overlay(is_correct=False, answers=expected_display)

    def NewDrillQuestion(self, type_hint=None, index=0, total_count=0):
        if self.currentSample is None or len(self.currentSample) == 0:
            raise RuntimeError("No sample available")

        self.currentRow = getRow(self.currentSample, index)
        try:
            self.currentQuestionBatch = getRandomRows(self.currentSample, index, 3)
        except Exception:
            import pandas as pd
            self.currentQuestionBatch = pd.DataFrame()

            fallback_df = getattr(self, "df_f", None)
            current_kanji = ""
            try:
                current_kanji = str(self.currentRow.get("kanji") or "")
            except Exception:
                current_kanji = ""

            if fallback_df is not None and getattr(fallback_df, "shape", (0, 0))[0] > 0:
                try:
                    if "kanji" in fallback_df.columns and current_kanji:
                        other = fallback_df[fallback_df["kanji"] != current_kanji].copy()
                    else:
                        other = fallback_df.copy()

                    if len(other) >= 3:
                        try:
                            self.currentQuestionBatch = getRandomRows(other, 0, 3)
                        except Exception:
                            self.currentQuestionBatch = other.sample(n=3, replace=False).copy()
                    else:
                        self.currentQuestionBatch = other.head(min(3, len(other))).copy()
                except Exception:
                    self.currentQuestionBatch = pd.DataFrame()
            else:
                self.currentQuestionBatch = pd.DataFrame()
        is_jlpt = (self.drillFilters["system"] == "JLPT")

        def fmt_value(v):
            if v is None:
                return ""
            if isinstance(v, (list, tuple)):
                return ", ".join(str(x) for x in v if x is not None)
            return str(v)

        drill_type = self.drillFilters["drill"]
        prompt_is_kanji = False

        if drill_type == "Meaning":
            meaning_field = "meanings" if is_jlpt else "wk_meanings"

            if getattr(self, "meaning_mode", "multiple_choice") == "writing":
                question_text = fmt_value(self.currentRow.get("kanji"))
                prompt_is_kanji = True

                meanings_list = self._normalize_meaning_list(self.currentRow.get(meaning_field))
                correct_answer = ", ".join(meanings_list)
                self._current_meanings_list = meanings_list

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
                    kanji_key = str(self.currentRow.get("kanji") or "")
                    if kanji_key:
                        try:
                            self.ensure_kanji_entry(kanji_key)
                        except Exception:
                            pass
                    entry = self.kanji_stats.get(kanji_key, {}) if kanji_key else {}
                    mode_key = self._current_mode_key()
                    mastery = float(entry.get(self.drillFilters["system"], {}).get(mode_key, {}).get("mastery", 0.0) or 0.0)
                except Exception:
                    mastery = 0.0

                proficiency_lbl = QLabel(f"Proficiency: {int(round(mastery))}%")
                proficiency_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vlayout.addWidget(proficiency_lbl)

                

                

                input_row = QHBoxLayout()
                self.meaning_input = QLineEdit()
                self.meaning_input.setPlaceholderText("Type a meaning…")
                self.meaning_input.setClearButtonEnabled(True)

                self.meaning_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                QTimer.singleShot(50, lambda: (self.meaning_input.setFocus(), self.meaning_input.selectAll()))

                self.meaning_enter_btn = QPushButton("Enter")
                self.meaning_enter_btn.setFixedWidth(90)

                input_row.addWidget(self.meaning_input)
                input_row.addWidget(self.meaning_enter_btn)
                vlayout.addLayout(input_row)

                self.meaning_enter_btn.clicked.connect(self.submit_meaning_written)
                self.meaning_input.returnPressed.connect(self.submit_meaning_written)

                display_index = index + 1
                status_label = QLabel(f"{display_index}/{total_count}")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._drill_status_label = status_label
                vlayout.addWidget(status_label)

                return container

            kanji_to_meaning = random.choice([True, False])

            if kanji_to_meaning:
                question_text = self._fmt_value(self.currentRow["kanji"])
                prompt_is_kanji = True
                correct_answer = self._fmt_value(self.currentRow.get(meaning_field))

                wrong_answers = self._collect_unique_field_distractors(meaning_field, correct_answer, self.currentQuestionBatch, needed=3)
                all_answers = [correct_answer] + [w for w in wrong_answers if w and w != correct_answer]
                all_answers = list(dict.fromkeys(all_answers))[:4]
                while len(all_answers) < 4:
                    all_answers.append("")
                random.shuffle(all_answers)
                button_texts = all_answers
            else:
                question_text = self._fmt_value(self.currentRow.get(meaning_field))
                prompt_is_kanji = False
                correct_answer = self._fmt_value(self.currentRow.get("kanji"))

                wrong_answers = self._collect_unique_field_distractors("kanji", correct_answer, self.currentQuestionBatch, needed=3)
                all_answers = [correct_answer] + [w for w in wrong_answers if w and w != correct_answer]
                all_answers = list(dict.fromkeys(all_answers))[:4]
                while len(all_answers) < 4:
                    all_answers.append("")
                random.shuffle(all_answers)
                button_texts = all_answers

        elif drill_type == "Reading":
            prefer = self.reading_type

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

            ordered = list(dict.fromkeys(all_answers))
            while len(ordered) < 4:
                ordered.append("")
            ordered = ordered[:4]

            random.shuffle(ordered)
            button_texts = ordered

        else:
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

        try:
            kanji_key = str(self.currentRow.get("kanji"))
            entry = self.kanji_stats.get(kanji_key, {})
            mode_key = self._current_mode_key()
            proficiency = float(entry.get(self.drillFilters["system"], {}).get(mode_key, {}).get("mastery", 0.0) or 0.0)
        except Exception:
            proficiency = 0.0

        proficiency_lbl = QLabel(f"Proficiency: {int(round(proficiency))}%")
        proficiency_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vlayout.addWidget(proficiency_lbl)

        answers_widget = QWidget()
        answer_grid = QGridLayout(answers_widget)
        answer_grid.setSpacing(6)

        self.answer_buttons = []



        for i, text in enumerate(button_texts[:4]):
            btn = WrapButton(text)
            btn.setFont(self._answer_button_font_for_text(text))
            is_correct = (text == self.correct_answer_text)
            btn.clicked.connect(lambda checked=False, b=btn, correct=is_correct: self.checkAnswer(correct, b))
            r = i // 2
            c = i % 2
            answer_grid.addWidget(btn, r, c)
            self.answer_buttons.append(btn)

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
        if self.drillFilters["max_count"] < 1:
            QMessageBox.critical(self, "Error", "No cards available — choose at least one level.")
            return

        if self.drillFilters["system"] == "JLPT":
            self.df_f = self.build_filtered_df()
        else:
            self.df_f = self.build_filtered_df()

        requested = int(self.drillFilters.get("count", 4) or 4)
        requested = max(4, requested)
        max_available = len(self.df_f) if self.df_f is not None else 0
        final_count = min(requested, max_available)

        

        if final_count < 4:
            QMessageBox.critical(self, "Error", "Require at least 4 cards to start a drill. Pick more cards/levels.")
            return
        
        coverage = (final_count / max_available) if max_available > 0 else 1.0

        if coverage >= 0.40:
            self._pw_cooldown_sessions = 0
        elif coverage >= 0.25:
            self._pw_cooldown_sessions = 1
        elif coverage >= 0.12:
            self._pw_cooldown_sessions = 2
        else:
            self._pw_cooldown_sessions = 3

        if bool(self.drillFilters.get("prioritize_weakness", True)):
            try:
                self.profile_data["pw_session_counter"] = int(self.profile_data.get("pw_session_counter", 0)) + 1
            except Exception:
                self.profile_data["pw_session_counter"] = 1
            self._pw_current_session_id = int(self.profile_data.get("pw_session_counter", 0))
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

        try:
            self._start_session_timer()
        except Exception:
            pass

        self.stack.slide_to(2, "left")

    def _pw_weight_for_row(self, row):
        try:
            kanji_key = str(row.get("kanji"))
        except Exception:
            kanji_key = ""

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

        wrong_rate = (w + 1.0) / (r + w + 2.0)

        now = int(self.profile_data.get("pw_question_counter", 0) or 0)
        age = max(0, now - last)

        cap = 200.0
        stale_mult = 1.0 + min(age, cap) / cap

        cool_sess = int(getattr(self, "_pw_cooldown_sessions", 0) or 0)
        if cool_sess > 0 and sess_age <= cool_sess:
            session_cooldown_factor = 0.20 + 0.80 * (sess_age / float(cool_sess))
        else:
            session_cooldown_factor = 1.0

        floor = 0.08
        weight = (floor + (wrong_rate * stale_mult)) * session_cooldown_factor
        return max(0.0001, float(weight))


    def _weighted_choice_index(self, indices, weights):
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
        try:
            if df is None or len(df) == 0:
                return df

            n = int(n)
            n = max(1, min(n, len(df)))

            rows = []
            weights = []
            for pos, (idx, row) in enumerate(df.iterrows()):
                rows.append((pos, row))
                weights.append(self._pw_weight_for_row(row))

            chosen_positions = []
            for _ in range(n):
                pick_pos = self._weighted_choice_index(list(range(len(rows))), weights)
                pos, _row = rows.pop(pick_pos)
                weights.pop(pick_pos)
                chosen_positions.append(pos)

            sampled = df.iloc[chosen_positions].copy()
            sampled = sampled.reset_index(drop=True)
            return sampled

        except Exception:
            try:
                return getRandomSample(df, n)
            except Exception:
                return df
            
    def compute_average_proficiency_for_current_filter(self):
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
            qwidget = self.NewDrillQuestion(index=self.currentQuestionIndex, total_count=self.totalQuestions)
        except Exception:
            import traceback
            traceback.print_exc()
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

    def show_overlay(self, text=None, timeout_ms=None, is_correct: Optional[bool] = None, answers: Optional[str] = None):
        def _esc(s):
            if s is None:
                return ""
            return (str(s)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;"))

        if timeout_ms is None:
            try:
                t_ms = int(round(float(self.popup_seconds) * 1000.0))
            except Exception:
                t_ms = 1500
        else:
            try:
                t_ms = int(timeout_ms)
            except Exception:
                t_ms = 1500

        if t_ms <= 0:
            QApplication.processEvents()
            QTimer.singleShot(0, lambda: self._advance_after_popup())
            return

        self._create_overlay()
        overlay = self._train_overlay
        label = self._train_overlay_label

        if is_correct is None:
            safe_text = _esc(text or "")
            html = f"<div style='white-space:pre-wrap; font-size:18px; color: white;'>{safe_text}</div>"
        else:
            verdict_raw = text if text is not None else ("Correct" if is_correct else "Wrong")
            verdict = _esc(verdict_raw)

            color = "#0b8f3b" if is_correct else "#d54e4e"

            first = f"<div style='color:{color}; font-weight:700; font-size:32px; margin-bottom:6px;'>{verdict}</div>"

            if answers is not None and str(answers).strip() != "":
                ans_text = _esc(answers)
                ans_html = f"<div style='color: white; font-size:16px; white-space:pre-wrap;'>{ans_text}</div>"
            else:
                ans_html = ""

            html = first + ans_html

        label.setTextFormat(Qt.RichText)
        label.setText(html)

        overlay.setGeometry(self.TrainMainWidget.rect())
        overlay.raise_()
        overlay.show()
        overlay.repaint()
        QApplication.processEvents()
        QTimer.singleShot(t_ms, lambda: (overlay.hide(), self._advance_after_popup()))


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

        modes = ["Meaning:writing", "Meaning:multiple_choice", "Reading:kunyomi", "Reading:onyomi"]
        for sysn in ("JLPT", "WaniKani"):
            entry.setdefault(sysn, {})
            for m in modes:
                if m not in entry[sysn]:
                    entry[sysn][m] = bucket_defaults().copy()
                else:
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

        try:
            self._record_one_question_now()
        except Exception:
            pass

        mode_key = self._current_mode_key()
        bucket = entry[system_name].setdefault(mode_key, {})
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

        if is_correct:
            bucket["right"] = int(bucket.get("right", 0)) + 1
            bucket["streak"] = int(bucket.get("streak", 0)) + 1
        else:
            bucket["wrong"] = int(bucket.get("wrong", 0)) + 1
            bucket["streak"] = 0

        if bool(self.drillFilters.get("prioritize_weakness", True)):
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

            now_q = int(self.profile_data.get("pw_question_counter", 0) or 0)
            last_seen_q = int(bucket.get("mastery_last_seen", 0) or 0)

            age = 0
            if last_seen_q > 0:
                age = max(0, now_q - last_seen_q)

            MIN_AGE_FOR_DECAY = 20
            if age >= MIN_AGE_FOR_DECAY:
                if age < 200:
                    decay_per_100q = 0.5
                else:
                    decay_per_100q = 1.0

                decay = (age / 100.0) * decay_per_100q
                mastery = max(0.0, mastery - decay)

            if is_correct:
                base_gain = 3.5 if drill_name == "Reading" else 2.5
                gain = base_gain * (1.0 - (mastery / 100.0))

                try:
                    if bool(self.drillFilters.get("prioritize_weakness", True)):
                        gain = gain * 0.5
                except Exception:
                    pass

                bucket["mastery_streak"] = int(bucket.get("mastery_streak", 0)) + 1
                mastery += gain
                if mastery >= 99.0:
                    streak = int(bucket.get("mastery_streak", 0))
                    total_enc = int(entry.get("total_encounters", 0) or 0)
                    if streak >= 7 and total_enc >= 25:
                        mastery = 100.0
                    else:
                        mastery = min(mastery, 99.0)
            else:
                penalty = max(12.0, mastery * 0.15)
                mastery = max(0.0, mastery - penalty)
                bucket["mastery_streak"] = 0

            bucket["mastery"] = round(float(mastery), 2)
            bucket["mastery_last_seen"] = int(self.profile_data.get("pw_question_counter", 0) or 0)

        gained = self.xp_for_answer(system_name, drill_name, is_correct)
        self.profile_data["xp"][system_name][drill_name] = int(self.profile_data["xp"][system_name][drill_name]) + int(gained)
        self.session_xp[system_name][drill_name] = int(self.session_xp[system_name][drill_name]) + int(gained)

        self.save_stats()
        self.save_profile()

    def checkAnswer(self, is_correct, clicked_button):
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

        self.session_results.append({"kanji": kanji_key, "given": given_text, "expected": expected_text, "correct": bool(is_correct)})

        self.update_stats_and_profile(kanji_key, bool(is_correct))

        if is_correct:
            if clicked_button is not None:
                try:
                    clicked_button.setStyleSheet("background-color: lightgreen;")
                except Exception:
                    pass
            self.show_overlay(is_correct=True, answers=expected_text)
        else:
            for b in getattr(self, "answer_buttons", []):
                try:
                    if b.text() == expected_text:
                        b.setStyleSheet("background-color: lightgreen;")
                    else:
                        b.setStyleSheet("")
                except Exception:
                    pass
            if clicked_button is not None:
                try:
                    clicked_button.setStyleSheet("background-color: lightcoral;")
                except Exception:
                    pass
            self.show_overlay(is_correct=False, answers=expected_text)


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
        dr = self.drillFilters.get("drill", "Meaning")
        if dr == "Meaning":
            mode = "writing" if getattr(self, "meaning_mode", "multiple_choice") == "writing" else "multiple_choice"
            return f"Meaning:{mode}"
        else:
            rt = getattr(self, "reading_type", "kunyomi")
            return f"Reading:{rt}"

    def finishTraining(self):
        try:
            self._stop_session_timer_and_record()
        except Exception:
            pass
        self.build_results_page()
        idx = self.results_index()
        if idx is None:
            self.stack.slide_to(1, "right")
            return
        self.stack.slide_to(idx, "left")

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

            actions_h = QHBoxLayout()
            actions_h.setSpacing(12)
            actions_h.setContentsMargins(0, 8, 0, 8)

            self._results_new_session_btn = QPushButton("New Session")
            self._results_new_session_btn.setFixedSize(160, 36)
            self._results_new_session_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._results_new_session_btn.clicked.connect(lambda: self._start_new_session_from_results())

            self._results_repeat_failures_btn = QPushButton("Repeat Failures")
            self._results_repeat_failures_btn.setFixedSize(160, 36)
            self._results_repeat_failures_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._results_repeat_failures_btn.clicked.connect(lambda: self._repeat_failures_from_results())

            actions_h.addStretch()
            actions_h.addWidget(self._results_new_session_btn)
            actions_h.addWidget(self._results_repeat_failures_btn)
            actions_h.addStretch()
            layout.addLayout(actions_h)

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

        elif not hasattr(self, "_results_list_layout") or self._results_list_layout is None:
            try:
                page_layout = self._results_page.layout()
                scroll_found = None
                for i in range(page_layout.count()):
                    item = page_layout.itemAt(i)
                    widget = item.widget() if item is not None else None
                    if isinstance(widget, QScrollArea):
                        scroll_found = widget
                        break
                if scroll_found is not None:
                    container = QWidget()
                    self._results_list_layout = QVBoxLayout(container)
                    self._results_list_layout.setContentsMargins(6, 6, 6, 6)
                    self._results_list_layout.setSpacing(8)
                    scroll_found.setWidget(container)
                else:
                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    container = QWidget()
                    self._results_list_layout = QVBoxLayout(container)
                    self._results_list_layout.setContentsMargins(6, 6, 6, 6)
                    self._results_list_layout.setSpacing(8)
                    scroll.setWidget(container)
                    page_layout.addWidget(scroll)
            except Exception:
                self._results_list_layout = QVBoxLayout()
        
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

        try:
            while self._results_list_layout.count():
                item = self._results_list_layout.takeAt(0)
                if item is None:
                    continue
                w = item.widget()
                if w:
                    w.setParent(None)
                else:
                    nested = item.layout()
                    if nested:
                        while nested.count():
                            it2 = nested.takeAt(0)
                            w2 = it2.widget()
                            if w2:
                                w2.setParent(None)
        except Exception:
            pass

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

        try:
            self._results_list_layout.addStretch()
        except Exception:
            pass


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

    def change_profile_pfp(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Profile Picture", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"]:
            return
        new_local_name = os.path.join(self.appdata, "pfp" + ext)
        try:
            shutil.copyfile(path, new_local_name)
        except Exception:
            QMessageBox.warning(self, "Error", "Could not copy the selected image.")
            return
        self.profile_data["pfp_path"] = new_local_name
        self.save_profile()
        try:
            pix = QPixmap(new_local_name).scaledToHeight(215, Qt.SmoothTransformation)
            if hasattr(self, "profilePFP"):
                self.profilePFP.setPixmap(pix)
            main_pix = QPixmap(new_local_name).scaledToHeight(215, Qt.SmoothTransformation)
            self.mainMenuPFP.setPixmap(main_pix)
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

            today_col = QVBoxLayout()
            self.profileTodaySummary = QLabel("")
            self.profileTodaySummary.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.profileTodaySummary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            today_col.addWidget(self.profileTodaySummary, alignment=Qt.AlignmentFlag.AlignHCenter)

            heatmap_btn = QPushButton("Open Heatmap")
            heatmap_btn.setFixedSize(120, 28)
            heatmap_btn.clicked.connect(self.open_heatmap)
            today_col.addWidget(heatmap_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

            layout.addLayout(today_col)

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
        try:
            self.DrillStart()
        except Exception:
            idx = 1
            self.stack.slide_to(idx, "right")
    def _repeat_failures_from_results(self):
        wrongs = [r.get("kanji") for r in self.session_results if not r.get("correct")]
        seen = set()
        wrongs_unique = []
        for k in wrongs:
            if not k:
                continue
            if k in seen:
                continue
            seen.add(k)
            wrongs_unique.append(k)
        if not wrongs_unique:
            QMessageBox.information(self, "Repeat Failures", "No wrong answers to repeat — great job!")
            return

        base_df = getattr(self, "df_f", None)
        if base_df is None or len(base_df) == 0:
            try:
                if self.drillFilters["system"] == "JLPT":
                    base_df = filterDataFrame(self.drillFilters["system"], self.drillFilters["jlpt_levels"], self.drillFilters["drill"])
                else:
                    base_df = filterDataFrame(self.drillFilters["system"], self.drillFilters["wanikani_levels"], self.drillFilters["drill"])
            except Exception:
                base_df = None

        if base_df is None or len(base_df) == 0:
            QMessageBox.warning(self, "Repeat Failures", "Could not build a failure-only session (no reference dataset).")
            return

        try:
            mask = base_df["kanji"].isin(wrongs_unique)
            df_failures = base_df.loc[mask].copy()
            df_failures["__order_tmp"] = df_failures["kanji"].apply(lambda k: wrongs_unique.index(k) if k in wrongs_unique else 9999)
            df_failures = df_failures.sort_values("__order_tmp").drop(columns=["__order_tmp"])
            df_failures = base_df[base_df["kanji"].isin(wrongs_unique)].copy()
            df_failures = df_failures.reset_index(drop=True)
        except Exception:
            df_failures = base_df[base_df["kanji"].isin(wrongs_unique)].copy()
            df_failures = df_failures.reset_index(drop=True)

        n_fail = int(getattr(df_failures, "shape", (0, 0))[0])

        allow_under_four = False
        try:
            if self.drillFilters.get("drill", "Meaning") == "Meaning":
                if getattr(self, "meaning_mode", "multiple_choice") == "writing":
                    allow_under_four = True
        except Exception:
            pass

        if n_fail < 4 and (not allow_under_four):
            drill = self.drillFilters.get("drill", "Meaning")
            if drill == "Meaning":
                is_jlpt = (self.drillFilters["system"] == "JLPT")
                meaning_field = "meanings" if is_jlpt else "wk_meanings"
                try:
                    pool_candidates = [self._fmt_value(v).strip() for _, r in base_df.iterrows() for v in ([r.get(meaning_field)] if meaning_field in r else [])]
                    pool_candidates = [p for p in pool_candidates if p]
                    pool_unique = set(pool_candidates)
                except Exception:
                    pool_unique = set()
                if len(pool_unique) < 4:
                    QMessageBox.critical(self, "Repeat Failures", "Need at least 4 unique answer options in the filtered pool to start a multiple-choice repeat session.")
                    return
            else:
                try:
                    pool_unique = set([self._fmt_value(r.get("kanji")) for _, r in base_df.iterrows() if self._fmt_value(r.get("kanji"))])
                except Exception:
                    pool_unique = set()
                if len(pool_unique) < 4:
                    QMessageBox.critical(self, "Repeat Failures", "Need at least 4 unique kanji in the filtered pool to start a multiple-choice repeat session.")
                    return

        if n_fail == 0:
            QMessageBox.information(self, "Repeat Failures", "No matching failed kanji found in the current filter set.")
            return

        try:
            import copy
            if not hasattr(self, "_saved_drillFilters_for_repeat_failures"):
                self._saved_drillFilters_for_repeat_failures = copy.deepcopy(self.drillFilters)
        except Exception:
            self._saved_drillFilters_for_repeat_failures = dict(self.drillFilters)

        self.currentSample = df_failures.copy().reset_index(drop=True)

        self.totalQuestions = int(len(self.currentSample))
        self.currentQuestionIndex = 0
        self.session_results = []
        self.session_xp = {"JLPT": {"Meaning": 0, "Reading": 0}, "WaniKani": {"Meaning": 0, "Reading": 0}}

        self.ensure_train_visible()
        try:
            self.showQuestion()
            try:
                self._start_session_timer()
            except Exception:
                pass
            self.stack.slide_to(2, "left")
        except Exception:
            QMessageBox.warning(self, "Repeat Failures", "Could not start the repeat session — check console.")
            return
        
    def _on_stack_changed(self, index: int):
        if index == 1:
            try:
                if self.drillFilters["system"] == "JLPT":
                    self.df_f = self.build_filtered_df()
                else:
                    self.df_f = self.build_filtered_df()
            except Exception:
                pass
            try:
                self.update_count_label()
            except Exception:
                pass
    
    def _fmt_value(self, v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v if x is not None)
        return str(v)

    def _collect_unique_field_distractors(self, field_name, correct, batch_df, needed=3):

        seen = set()
        results = []

        def try_add(val):
            s = self._fmt_value(val).strip()
            if not s:
                return
            if s == correct:
                return
            if s in seen:
                return
            seen.add(s)
            results.append(s)

        try:
            if batch_df is not None:
                for _, r in batch_df.iterrows():
                    try_add(r.get(field_name))
                    if len(results) >= needed:
                        return results[:needed]
        except Exception:
            pass

        try:
            if getattr(self, "currentSample", None) is not None:
                for _, r in self.currentSample.iterrows():
                    try_add(r.get(field_name))
                    if len(results) >= needed:
                        return results[:needed]
        except Exception:
            pass

        try:
            if getattr(self, "df_f", None) is not None:
                for _, r in self.df_f.iterrows():
                    try_add(r.get(field_name))
                    if len(results) >= needed:
                        return results[:needed]
        except Exception:
            pass

        while len(results) < needed:
            results.append("")
        return results[:needed]
            
    def open_heatmap(self):
        dlg = HeatmapDialog(parent=self, activity=self.profile_data.get("activity", {}))
        dlg.show()
        dlg.raise_()

    def refresh_profile_page(self):
        if getattr(self, "_profile_page", None) is None:
            return
        try:
            self.profileNameEdit.setText(self.profile_data.get("username", "User"))
        except Exception:
            pass
        self.profileTotalQuestions.setText(f"Total Questions Answered: {self.total_questions_answered_overall()}")
        try:
            today = time.strftime("%Y-%m-%d")
            act = self.profile_data.get("activity", {}) or {}
            today_entry = act.get(today, {"questions": 0, "seconds": 0})
            q = int(today_entry.get("questions", 0) or 0)
            secs = int(today_entry.get("seconds", 0) or 0)
            h = secs // 3600
            m = (secs % 3600) // 60
            if h > 0:
                timestr = f"{h}h {m}m"
            else:
                timestr = f"{m}m"
            self.profileTodaySummary.setText(f"Today: {q} questions — {timestr}")
        except Exception:
            self.profileTodaySummary.setText("")
        
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
                    btn.click()
                    return

        if key == Qt.Key_Backspace:
            r_idx = self.results_index()
            if r_idx is not None and self.stack.currentIndex() == r_idx:
                btn = getattr(self, "_results_repeat_failures_btn", None)
                if btn is not None and btn.isEnabled():
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
