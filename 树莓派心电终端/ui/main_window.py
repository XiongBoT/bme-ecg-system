"""Chinese local-screen UI. Only the Tk thread accesses widgets."""
from __future__ import annotations

from datetime import datetime
from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue
import math
import os
import subprocess
import sys
import threading
import time
from device import save_problem, poweroff_supported, request_poweroff
from ui.render_cache import Label as CachedLabel, TtkLabel as CachedTtkLabel, TtkButton as CachedTtkButton
import tkinter as tk
from tkinter import filedialog, font, messagebox, simpledialog, ttk

import numpy as np

from .waveform import WaveformCanvas


BG, PANEL, FG, MUTED = "#050807", "#09110c", "#e2ebe5", "#7c9084"
GREEN, CYAN, AMBER, RED = "#44f083", "#98cdb0", "#e8bd69", "#f28b89"
SOURCES = {"STM32 串口": "serial", "合成模拟": "demo", "文件回放": "replay"}
SOURCE_NAMES = {value: key for key, value in SOURCES.items()}
MODES = {"处理后": "filtered", "原始": "raw", "双波形": "both"}
CLASS_COLORS = {"N": "#56d8d0", "S": "#efb66b", "V": "#c79af5"}
CLASS_NAMES = {"N": "常见搏动组", "S": "室上性 · 待复核", "V": "室性 · 待复核"}
DEFAULT_UI_SETTINGS = {
    "display_seconds": 5, "display_mode": "filtered", "auto_scale": True,
    "vref": 3.3, "classification_enabled": True, "export_dir": "data/exports",
    "last_export_dir": "", "remember_export_dir": True, "export_include_raw": True,
    "low_space_warn_mb": 512, "low_space_stop_mb": 128, "auto_time_sync": True,
}


def _size(value):
    if value is None:
        return "未知"
    value = max(0, int(value))
    return f"{value / 1024**3:.1f} GB" if value >= 1024**3 else f"{value / 1024**2:.1f} MB"


def _local_time(value, full=False):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M:%S" if full else "%m-%d %H:%M:%S")
    except ValueError:
        return str(value or "时间未知")


def _number(value, decimals=0):
    try:
        value = float(value)
        return f"{value:.{decimals}f}" if math.isfinite(value) else "--"
    except (ValueError, TypeError):
        return "--"


def _sample_wait(row):
    try:
        return _number(float(row.get("sample_latency_ms"))/1000, 2)
    except (ValueError, TypeError):
        return "--"


def _short(value, maximum):
    value = str(value)
    return value if len(value) <= maximum else value[:maximum - 1] + "…"


def source_label(source, mode=None):
    if source == "serial":
        return {0: "STM32 · 实采", 1: "STM32 · 板端模拟"}.get(mode, "STM32 · 等待模式")
    if source == "replay":
        return {0: "回放 · 实采", 1: "回放 · 模拟"}.get(mode, "文件回放 · 来源未知")
    return SOURCE_NAMES.get(source, "等待连接")


def classification_display(snapshot):
    """Fail closed; model scores are never presented as calibrated certainty."""
    model = snapshot.get("classification") or {}
    last = model.get("last")
    eligible = (snapshot.get("running") and snapshot.get("state") == "RECORDING"
                and snapshot.get("source") in ("serial", "replay") and snapshot.get("board_mode") == 0
                and snapshot.get("signal_state") == "good" and model.get("state") == "ready")
    if not eligible or not last:
        detail = model.get("detail", "等待有效实采信号")
        if model.get("state") == "collecting" and model.get("context_seconds") is not None:
            collected = max(0, float(model["context_seconds"]))
            required = float(model.get("context_required_seconds", 8))
            if collected < required:
                detail = f"积累有效信号 {collected:.1f}/{required:g}s"
        return "--", detail, "N / S / V · 研究输出"
    label = last.get("label")
    if label not in ("N", "S", "V"):
        return "--", "分类结果无效", "N / S / V · 研究输出"
    scores = last.get("scores", {})
    latency = last.get("sample_latency_ms")
    detail = CLASS_NAMES[label]
    if latency is not None:
        detail += f" · 等待 {max(0, float(latency))/1000:.1f}s"
    return label, detail, "模型分数 · 非诊断概率\n" + "  ".join(f"{k} {100*float(scores.get(k,0)):.0f}" for k in ("N","S","V"))


def classification_events(snapshot):
    """Never place a different session's history on the current trace."""
    sid = snapshot.get("session_id")
    if not sid:
        return []
    return [dict(row) for row in (snapshot.get("classification") or {}).get("recent", []) if valid_classification_row(row, sid)]


def valid_classification_row(row, sid):
    return (isinstance(row, dict) and not row.get("integrity_error") and row.get("session_id") == sid
            and row.get("label") in CLASS_NAMES
            and all(isinstance(row.get(key), (int, np.integer)) and not isinstance(row.get(key), bool)
                    and row[key] >= 0 for key in ("r_sample", "segment_id")))


class MainWindow:
    def __init__(self, root, controller, simple_mode=False):
        self.root, self.controller = root, controller
        self.simple_mode = simple_mode
        self._ports_scanning = False
        self._known_ports = []
        self._auto_port = None
        self._next_port_scan = 0
        self._device_dialog = None
        self._shutdown_requested = False
        self._poweroff_pending = False
        self._cloud_stopping = False
        self._cloud_resume_pending = False
        self._close_started = None
        # Tk briefly releases the GIL for widget calls. On the Pi, a busy
        # analysis/upload thread can otherwise consume a 5 ms Python slice
        # between each of dozens of calls in a frame. Keep those handoffs short.
        self._previous_switch_interval = sys.getswitchinterval()
        if sys.platform.startswith('linux'):
            sys.setswitchinterval(min(.001, self._previous_switch_interval))
            self.root.bind('<Destroy>', self._restore_thread_schedule, add='+')
        self.root.title("心电采集终端 · Raspberry Pi 2")
        self.root.minsize(800, 480)
        self.root.configure(background=BG)
        self._messages = Queue()
        self._pending_tasks = 0
        self._closed = False
        self._closing = False
        self._action_pending = False
        self._mode_check_pending = False
        self._stop_requested = False
        self._last_snapshot = {}
        self._frozen_wave = None
        self._frozen_classification = None
        self._strip_events = []
        self._strip_signature = None
        self._last_wave = {"x": [], "raw": [], "filtered": []}
        self._last_session = None
        self._last_context = None
        self._replay_path = None
        self._compact = None
        self._control_source = None
        self._control_state = None
        self._status_width = 360
        self._fitted_status = {}
        self._ports_message = ""
        self._settings = dict(DEFAULT_UI_SETTINGS)
        getter = getattr(controller, "get_settings", None)
        if callable(getter):
            saved = getter()
            if isinstance(saved, dict):
                self._settings.update(saved)
        self.vref = float(self._settings["vref"])
        self._fonts()
        self._styles()
        self.source = tk.StringVar(value="STM32 串口")
        self.port = tk.StringVar()
        self.mode = tk.StringVar(value=next((k for k, v in MODES.items() if v == self._settings["display_mode"]), "处理后"))
        self.window_s = tk.StringVar(value=f'{self._settings["display_seconds"]:g} 秒')
        self.auto_scale = tk.BooleanVar(value=bool(self._settings["auto_scale"]))
        self.cloud = None
        self.cloud_owner_id = None
        self.cloud_owner_name = '未分配'
        self._show_next_summary = False
        self._summary_session = None
        if isinstance(getattr(controller, "data_dir", None), (str, Path)):
            from cloud.service import CloudService
            self.cloud = CloudService(controller.data_dir, controller=controller)
        self._build()
        self.root.bind("<F11>", lambda _: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _: self.root.attributes("-fullscreen", False))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(0, self.refresh_ports)
        self.root.after(0, self._tick)

    def _restore_thread_schedule(self, event):
        if event.widget is self.root:
            sys.setswitchinterval(self._previous_switch_interval)

    def _fonts(self):
        choices = ("Noto Sans CJK SC", "Microsoft YaHei UI", "Microsoft YaHei", "WenQuanYi Micro Hei")
        available = set(font.families(self.root))
        self.family = next((name for name in choices if name in available), "DejaVu Sans")
        font.nametofont("TkDefaultFont").configure(family=self.family, size=10)
        font.nametofont("TkTextFont").configure(family=self.family, size=10)
        font.nametofont("TkMenuFont").configure(family=self.family, size=10)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Bar.TFrame", background="#111a15")
        style.configure("TLabel", background=BG, foreground=FG, font=(self.family, 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("TButton", background="#18261e", foreground=FG, padding=(12, 8),
                        borderwidth=0, relief="flat", focusthickness=1, focuscolor=CYAN,
                        font=(self.family, 10))
        style.map("TButton", background=[("disabled", "#0d1711"), ("pressed", "#2e4637"),
                                         ("active", "#243c2c")],
                  foreground=[("disabled", "#52685a")])
        style.configure("Quiet.TButton", background=BG, foreground=MUTED)
        style.map("Quiet.TButton", background=[("active", "#18261e")],
                  foreground=[("active", FG), ("disabled", "#52685a")])
        style.configure("CloudOnline.Quiet.TButton", foreground=GREEN)
        style.configure("Start.TButton", background=GREEN, foreground="#09251e", font=(self.family, 10, "bold"))
        style.map("Start.TButton", background=[("disabled", "#102719"), ("active", "#7bf7a6")],
                  foreground=[("disabled", "#477454"), ("active", "#09251e")])
        style.configure("Stop.TButton", background="#32242d", foreground=RED)
        style.map("Stop.TButton", background=[("disabled", "#0d1711"), ("active", "#4a3039")],
                  foreground=[("disabled", "#52685a")])
        style.configure("TCheckbutton", background=BG, foreground=FG, font=(self.family, 10))
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", "#52685a")])
        style.configure("TCombobox", fieldbackground="#101c14", background="#101c14", foreground=FG,
                        arrowcolor=MUTED, bordercolor="#293f30", lightcolor="#101c14", darkcolor="#101c14",
                        padding=(8, 6), arrowsize=12)
        style.map("TCombobox", fieldbackground=[("readonly", "#101c14"), ("disabled", PANEL)],
                  foreground=[("disabled", "#52685a"), ("readonly", FG)],
                  bordercolor=[("focus", "#4a9162")])
        style.configure("TEntry", fieldbackground="#101c14", foreground=FG, padding=6,
                        insertcolor=FG, bordercolor="#293f30")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                        borderwidth=0, rowheight=34, font=(self.family, 10))
        style.configure("Treeview.Heading", background="#18261e", foreground=MUTED,
                        padding=(8, 8), relief="flat", font=(self.family, 9))
        style.map("Treeview", background=[("selected", "#214c31")], foreground=[("selected", FG)])
        style.configure("Vertical.TScrollbar", background="#304f3b", troughcolor=PANEL,
                        arrowcolor=MUTED, borderwidth=0)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#142219", foreground=MUTED, padding=(18, 8))
        style.map("TNotebook.Tab", background=[("selected", "#214c31")], foreground=[("selected", FG)])
        style.configure("TRadiobutton", background=BG, foreground=FG)
        self.root.option_add("*TCombobox*Listbox.background", "#101c14")
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#255538")

    def _build(self):
        self.outer = ttk.Frame(self.root, padding=(16, 10))
        self.outer.pack(fill="both", expand=True)
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(1, weight=1)
        self.header = ttk.Frame(self.outer)
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.header.columnconfigure(2, weight=1)
        self.title_label = CachedTtkLabel(self.header, text="ECG  心电监测", foreground=GREEN, font=(self.family, 18, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        self.source_badge = CachedLabel(self.header, text="等待连接", background="#142219", foreground=MUTED,
                                     font=(self.family, 9), padx=9, pady=5)
        self.source_badge.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.preprocess_label = CachedTtkLabel(self.header, text="", foreground=CYAN, font=(self.family, 8))
        self.preprocess_label.grid(row=0, column=2, sticky="w", padx=(10, 0))
        clock = ttk.Frame(self.header)
        clock.grid(row=0, column=3, sticky="e", padx=(8, 20))
        CachedTtkLabel(clock, text="记录", style="Muted.TLabel", font=(self.family, 9)).pack(side="left", padx=(0, 8))
        self.clock_label = CachedTtkLabel(clock, text="00:00", font=(self.family, 16, "bold"))
        self.clock_label.pack(side="left")
        actions = ttk.Frame(self.header)
        actions.grid(row=0, column=4, sticky="e")
        CachedTtkButton(actions, text="历史记录", command=self.show_history, style="Quiet.TButton", width=0, padding=(8, 8)).pack(side="left")
        CachedTtkButton(actions, text="设置", command=self.settings, style="Quiet.TButton", width=0, padding=(8, 8)).pack(side="left")
        CachedTtkButton(actions, text="全屏", command=self.toggle_fullscreen, style="Quiet.TButton", width=0, padding=(8, 8)).pack(side="left")
        if self.cloud is not None:
            from ui.cloud_dialog import show_cloud
            self.cloud_button = CachedTtkButton(actions, text="云端", command=lambda: show_cloud(self), style="Quiet.TButton", width=0, padding=(8, 8))
            self.cloud_button.pack(side="left")

        body = ttk.Frame(self.outer)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        plot = ttk.Frame(body)
        plot.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        plot.rowconfigure(1, weight=1)
        plot.columnconfigure(0, weight=1)
        self.plot_header = ttk.Frame(plot, padding=(8, 8))
        self.plot_header.grid(row=0, column=0, sticky="ew")
        self.plot_header.columnconfigure(2, weight=1)
        CachedTtkLabel(self.plot_header, text="ECG", foreground=GREEN, font=(self.family, 14, "bold")).grid(row=0, column=0, sticky="w")
        self.quality_label = CachedLabel(self.plot_header, text="等待信号", bg=BG, fg=MUTED, font=(self.family, 9), anchor="w")
        self.quality_label.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.paused_label = CachedLabel(self.plot_header, text="", bg=BG, fg=AMBER, font=(self.family, 9))
        self.beat_strip = tk.Canvas(self.plot_header, width=226, height=32, background=BG, highlightthickness=0)
        self.beat_strip.grid(row=0, column=2, sticky="ew", padx=8)
        self.beat_strip.bind("<Configure>", lambda _: self._draw_beat_strip())
        self.beat_strip.bind("<Button-1>", self._click_beat_strip)
        self.mode_combo = ttk.Combobox(self.plot_header, textvariable=self.mode, values=list(MODES), state="readonly", width=7)
        self.mode_combo.grid(row=0, column=3, padx=(0, 8))
        self.window_combo = ttk.Combobox(self.plot_header, textvariable=self.window_s, values=["2 秒", "5 秒", "10 秒"], state="readonly", width=5)
        self.window_combo.grid(row=0, column=4)
        self.waveform = WaveformCanvas(plot)
        self.waveform.grid(row=1, column=0, sticky="nsew")
        self.waveform.on_marker_click = self.show_classification_details
        self.standby_card = tk.Frame(self.waveform, bg=PANEL, padx=18, pady=16)
        CachedLabel(self.standby_card, text="准备好后，开始采集", bg=PANEL, fg=FG,
                    font=(self.family, 15, "bold")).pack(anchor="w")
        CachedLabel(self.standby_card, text="连接采集模块 → 点击开始 → 停止并保存", bg=PANEL,
                    fg=MUTED, font=(self.family, 10)).pack(anchor="w", pady=(8, 12))
        self.standby_hint = CachedLabel(self.standby_card, text="正在检查 USB 串口…", bg=PANEL,
                                       fg=CYAN, font=(self.family, 10), wraplength=360, justify="left")
        self.standby_hint.pack(anchor="w")

        self.sidebar = tk.Frame(body, background=PANEL, width=230, highlightthickness=1, highlightbackground="#24392b")
        self.sidebar.grid(row=0, column=1, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(0, weight=4)
        self.sidebar.rowconfigure(2, weight=2)
        # Keep the complete classification explanation visible on 480px screens;
        # the large HR/RR figures absorb vertical resizing instead.
        self.sidebar.rowconfigure(4, weight=0)
        self.sidebar.rowconfigure(6, weight=0)
        hr = tk.Frame(self.sidebar, bg=PANEL, padx=16, pady=14)
        hr.grid(row=0, column=0, sticky="nsew")
        hr.columnconfigure(0, weight=1)
        hr.rowconfigure(1, weight=1)
        hr_heading = tk.Frame(hr, bg=PANEL)
        hr_heading.grid(row=0, column=0, sticky="ew")
        CachedLabel(hr_heading, text="HR  心率", bg=PANEL, fg=GREEN, font=(self.family, 13, "bold")).pack(side="left")
        CachedLabel(hr_heading, text="bpm", bg=PANEL, fg=GREEN, font=(self.family, 10)).pack(side="right")
        self.hr_label = CachedLabel(hr, text="--", bg=PANEL, fg=GREEN, font=("DejaVu Sans", 72, "bold"), anchor="e")
        self.hr_label.grid(row=1, column=0, sticky="nsew")
        tk.Frame(self.sidebar, bg="#24392b", height=1).grid(row=1, column=0, sticky="ew", padx=14)
        rr = tk.Frame(self.sidebar, bg=PANEL, padx=16, pady=12)
        rr.grid(row=2, column=0, sticky="nsew")
        rr.columnconfigure(0, weight=1)
        rr.rowconfigure(1, weight=1)
        rr_heading = tk.Frame(rr, bg=PANEL)
        rr_heading.grid(row=0, column=0, sticky="ew")
        CachedLabel(rr_heading, text="RR  间期", bg=PANEL, fg=CYAN, font=(self.family, 11)).pack(side="left")
        CachedLabel(rr_heading, text="ms", bg=PANEL, fg=CYAN, font=(self.family, 10)).pack(side="right")
        self.rr_label = CachedLabel(rr, text="--", bg=PANEL, fg=CYAN, font=("DejaVu Sans", 40, "bold"), anchor="e")
        self.rr_label.grid(row=1, column=0, sticky="nsew")
        tk.Frame(self.sidebar, bg="#24392b", height=1).grid(row=3, column=0, sticky="ew", padx=14)
        record = tk.Frame(self.sidebar, bg=PANEL, padx=16, pady=12)
        record.grid(row=6, column=0, sticky="nsew")
        record.columnconfigure(0, weight=1)
        CachedLabel(record, text="已保存 / 点", bg=PANEL, fg=MUTED, font=(self.family, 10), anchor="w").grid(row=0, column=0, sticky="ew")
        self.saved_label = CachedLabel(record, text="0", bg=PANEL, fg=FG, font=("DejaVu Sans", 21, "bold"), anchor="e")
        self.saved_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        model = tk.Frame(self.sidebar, bg=PANEL, padx=12, pady=8)
        model.grid(row=4, column=0, sticky="nsew")
        model.columnconfigure(0, weight=1)
        model_heading = tk.Frame(model, bg=PANEL)
        model_heading.grid(row=0, column=0, sticky="ew")
        model_heading.columnconfigure(0, weight=1)
        CachedLabel(model_heading, text="AI 心搏 · 研究", bg=PANEL, fg=CYAN,
                 font=(self.family, 9)).grid(row=0,column=0,sticky="w")
        self.class_details_button = CachedTtkButton(model_heading, text="详情", command=self.show_classification_details,
                                               style="Quiet.TButton", padding=(3, 2), width=3)
        self.class_details_button.grid(row=0, column=1, sticky="e")
        self.class_label = CachedLabel(model,text="--",bg=PANEL,fg=CYAN,font=("DejaVu Sans",26,"bold"))
        self.class_label.grid(row=1,column=0,sticky="ew")
        self.class_detail = CachedLabel(model,text="等待实采信号",bg=PANEL,fg=MUTED,font=(self.family,8),wraplength=150)
        self.class_detail.grid(row=2,column=0,sticky="ew")
        self.class_scores = CachedLabel(model,text="N / S / V",bg=PANEL,fg=MUTED,font=(self.family,7))
        self.class_scores.grid(row=3,column=0,sticky="ew")
        tk.Frame(self.sidebar,bg="#24392b",height=1).grid(row=5,column=0,sticky="ew",padx=14)
        self._stat_frames = (hr, rr, record, model)

        controls = ttk.Frame(self.outer, style="Bar.TFrame", padding=(10, 9))
        controls.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        controls.columnconfigure(0, weight=1)
        self.source_controls = ttk.Frame(controls, style="Bar.TFrame")
        self.source_controls.grid(row=0, column=0, sticky="w")
        self.simple_controls = ttk.Frame(controls, style="Bar.TFrame")
        CachedTtkButton(self.simple_controls, text="更多…", command=self.show_device, style="Quiet.TButton").pack(side="left")
        self.review_button = CachedTtkButton(self.simple_controls, text="查看本次记录", state="disabled",
                    command=lambda: self.show_history(self._last_snapshot.get('session_id')), style="Quiet.TButton")
        self.review_button.pack(side="left", padx=(8, 0))
        if self.simple_mode:
            self.source_controls.grid_remove()
            self.simple_controls.grid(row=0, column=0, sticky="w")
        self.source_combo = ttk.Combobox(self.source_controls, textvariable=self.source, values=list(SOURCES), state="readonly", width=9)
        self.source_combo.grid(row=0, column=0, padx=(0, 8))
        self.source_combo.bind("<<ComboboxSelected>>", self._update_controls)
        self.port_combo = ttk.Combobox(self.source_controls, textvariable=self.port, state="normal", width=17)
        self.port_combo.grid(row=0, column=1, padx=(0, 4))
        self.port_combo.bind('<<ComboboxSelected>>', self._port_selected)
        self.refresh_button = CachedTtkButton(self.source_controls, text="刷新", command=self.refresh_ports, width=4)
        self.refresh_button.grid(row=0, column=2)
        self.file_button = CachedTtkButton(self.source_controls, text="选择 CSV", command=self.select_replay)
        self.file_button.grid(row=0, column=1)
        self.source_hint = CachedTtkLabel(self.source_controls, text="模拟波形 · 非实采", background="#111a15", foreground=MUTED, font=(self.family, 9))
        self.source_hint.grid(row=0, column=1, sticky="w")
        primary = ttk.Frame(controls, style="Bar.TFrame")
        primary.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.pause_button = CachedTtkButton(primary, text="暂停显示", command=self.toggle_pause, width=8)
        self.pause_button.pack(side="left", padx=(0, 8))
        self.stop_button = CachedTtkButton(primary, text="停止并保存" if self.simple_mode else "停止", command=self.stop,
                                          style="Stop.TButton", width=10 if self.simple_mode else 4, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))
        self.start_button = CachedTtkButton(primary, text="开始采集", command=self.prepare_measurement, style="Start.TButton", width=8)
        self.start_button.pack(side="left")
        self.footer = ttk.Frame(self.outer)
        self.footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.footer.columnconfigure(1, weight=1)
        self._status_font = font.Font(root=self.root, family=self.family, size=9)
        self.connection_label = CachedTtkLabel(self.footer, text="未连接", foreground=MUTED, font=self._status_font)
        self.connection_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.status_label = CachedTtkLabel(self.footer, text="选择来源，开始采集", foreground=MUTED, font=self._status_font, width=1)
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.count_label = CachedTtkLabel(self.footer, text="原始数据自动保存", style="Muted.TLabel", font=(self.family, 9))
        self.count_label.grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.mode_feedback_row = ttk.Frame(self.footer)
        self.mode_feedback_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3, 0))
        self.mode_feedback_row.columnconfigure(0, weight=1)
        self.mode_feedback_label = CachedTtkLabel(self.mode_feedback_row, text="模式由 STM32 的 SW2 按键切换", foreground=MUTED,
                                             font=self._status_font, width=1)
        self.mode_feedback_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.mode_check_button = CachedTtkButton(self.mode_feedback_row, text="检查切换", command=self.check_mode_switch,
                                            style="Quiet.TButton", padding=(8, 3), state="disabled")
        self.mode_check_button.grid(row=0, column=1, sticky="e")
        self.outer.bind("<Configure>", self._resize)
        self._update_controls()

    def _resize(self, event):
        if event.widget is not self.outer:
            return
        size = 0 if event.width < 1000 else 1 if event.width < 1400 else 2
        if size != self._compact:
            self._compact = size
            if size == 0:
                self.preprocess_label.grid_remove()
            else:
                self.preprocess_label.grid()
            self.outer.configure(padding=(10, 8) if size == 0 else (18, 12))
            self.title_label.configure(font=(self.family, 15 if size == 0 else 18, "bold"))
            self.header.grid_configure(pady=(0, 7 if size == 0 else 12))
            self.plot_header.configure(padding=(6, 4) if size == 0 else (8, 8))
            self.sidebar.configure(width=(174, 228, 330)[size])
            self.hr_label.configure(font=("DejaVu Sans", (24, 52, 86)[size], "bold"))
            self.rr_label.configure(font=("DejaVu Sans", (18, 30, 48)[size], "bold"))
            self.saved_label.configure(font=("DejaVu Sans", 12 if size == 0 else 17, "bold"))
            self.class_label.configure(font=("DejaVu Sans", (17,28,40)[size], "bold"))
            self.class_detail.configure(wraplength=(150,200,290)[size])
            for frame in self._stat_frames:
                frame.configure(padx=8 if size == 0 else 14, pady=3 if size == 0 else 8)
            self.port_combo.configure(width=12 if size == 0 else 20)
        self._status_width = max(80, event.width - self.count_label.winfo_reqwidth()
                                  - self.connection_label.winfo_reqwidth() - 50)

    def _task(self, operation, success=None, failure=None):
        if self._closing and operation is not request_poweroff:
            if failure:
                failure('正在退出，请等待后台操作结束')
            return
        self._pending_tasks += 1
        def work():
            try:
                result = operation()
                self._messages.put((success, result, None, failure))
            except Exception as exc:
                self._messages.put((success, None, str(exc), failure))
        threading.Thread(target=work, daemon=True).start()

    def refresh_ports(self):
        if self._ports_scanning or self._closing or self._action_pending or self._last_snapshot.get('running'):
            return
        self._ports_scanning = True
        self.refresh_button.configure(state="disabled")
        def done(ports):
            self._ports_scanning = False
            self._next_port_scan = time.monotonic() + 2
            if isinstance(ports, str):
                self._known_ports = []
                self._ports_message = '串口检查失败：' + ports
                self._control_state = None
                self._update_controls()
                return
            self._known_ports = ports
            devices = [str(item.get("device", "")) if isinstance(item, dict) else str(item) for item in ports]
            self._control_state = None
            self.port_combo.configure(values=devices)
            usb = [item["device"] for item in ports if isinstance(item, dict) and item.get("usb")]
            if self.port.get() == self._auto_port and (self._auto_port not in devices or len(usb) > 1):
                self.port.set('')
                self._auto_port = None
            if self.port.get() in ('', 'auto') and len(usb) == 1:
                self.port.set(usb[0])
                self._auto_port = usb[0]
            self._ports_message = ("未检测到 USB 串口，请插入采集模块" if not usb else
                                   "检测到多个 USB 串口，请在“更多”选择采集端口" if len(usb) > 1 else
                                   "已识别采集端口，点击“开始采集”检查信号")
            self._update_controls()
        def scan():
            try:
                return self.controller.list_ports()
            except Exception as exc:
                return str(exc)
        self._task(scan, done)

    def _port_available(self):
        selected = self.port.get().strip()
        return bool(selected) and any(selected in (p.get('device'), p.get('system_device'))
                                     for p in self._known_ports if isinstance(p, dict))

    def _port_selected(self, _event=None):
        self._auto_port = None
        self._update_controls()

    def select_replay(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择导出的完整心电 CSV",
                                         filetypes=[("心电 CSV", "*.csv"), ("所有文件", "*")])
        if path:
            self._replay_path = path
            self.source.set("文件回放")
            self.status_label.configure(text="回放文件：" + Path(path).name, foreground=CYAN)
            self._update_controls()

    def prepare_measurement(self):
        from ui.measurement import prepare_measurement
        prepare_measurement(self)

    def show_measurement_summary(self,session_id):
        from ui.measurement import show_summary
        show_summary(self,session_id)

    def start(self, duration=None, _owner_checked=False):
        if self._closing or self._action_pending or self._last_snapshot.get("running"):
            return
        source = SOURCES[self.source.get()]
        if self.simple_mode and source == 'serial' and not self._port_available():
            messagebox.showinfo('连接采集模块', self._ports_message or '请先连接并选择采集端口', parent=self.root)
            return
        if source == "serial" and not self.port.get().strip():
            messagebox.showinfo("选择串口", "请连接 USB 转串口设备，刷新并选择串口。", parent=self.root)
            return
        if source == "replay" and not self._replay_path:
            self.select_replay()
            if not self._replay_path:
                return
        if self.cloud is not None and self.cloud.snapshot().get('auth_required') is True and not _owner_checked:
            from ui.cloud_owner import choose_owner
            choose_owner(self, lambda: self.start(duration, _owner_checked=True))
            return
        self._frozen_wave = None
        self._frozen_classification = None
        self._stop_requested = False
        self.pause_button.configure(text="暂停显示")
        self._action_pending = True
        self._update_controls()
        self.status_label.configure(text="正在准备会话…", foreground=CYAN)
        # Read Tk variables before leaving the Tk thread.
        kwargs = dict(source=source, port=self.port.get().strip() or None,
                      replay_path=self._replay_path, vref=self.vref,
                      duration=duration)
        if self.cloud_owner_id:
            kwargs['cloud_owner_id'] = self.cloud_owner_id
            kwargs['cloud_owner_name'] = self.cloud_owner_name
        def done(sid):
            self._action_pending = False
            if self._show_next_summary:
                self._summary_session = sid
                self._show_next_summary = False
            self._update_controls()
        self._task(lambda: self.controller.start(**kwargs), done)

    def stop(self):
        self._stop_requested = True
        if self._action_pending:
            self.status_label.configure(text="连接准备完成后将停止采集…", foreground=AMBER)
            return
        try:
            self.controller.stop()
            self.status_label.configure(text="正在停止采集并完成保存…", foreground=AMBER)
        except Exception as exc:
            self.status_label.configure(text="停止失败：" + str(exc), foreground=RED)

    def toggle_pause(self):
        if self._frozen_wave is None:
            self._frozen_wave = {key: np.asarray(value).copy() for key, value in self._last_wave.items()}
            keys = ("session_id", "source", "board_mode", "state", "running", "signal_state", "classification")
            self._frozen_classification = deepcopy({key: self._last_snapshot.get(key) for key in keys})
            self.pause_button.configure(text="恢复显示")
        else:
            self._frozen_wave = None
            self._frozen_classification = None
            self.pause_button.configure(text="暂停显示")

    def toggle_fullscreen(self):
        self.root.attributes("-fullscreen", not bool(self.root.attributes("-fullscreen")))

    def _can_check_mode(self):
        state = self._last_snapshot
        return (state.get("source") == "serial" and state.get("running")
                and state.get("state") == "RECORDING" and state.get("serial_aligned")
                and state.get("board_mode") in (0, 1)
                and state.get("mode_check_state") != "waiting"
                and not self._mode_check_pending and not self._action_pending and not self._closing)

    def check_mode_switch(self):
        """Observe a physical SW2 action; this never sends a command to STM32."""
        if not self._can_check_mode():
            return
        self._mode_check_pending = True
        self.mode_feedback_label.configure(text="正在准备检查，请随后按 STM32 的 SW2…", foreground=AMBER)
        self._update_controls()
        def done(_):
            self._mode_check_pending = False
            # _tick reads the controller snapshot immediately after this
            # callback, before the event loop accepts another button click.
            self._control_state = None
            self._update_controls()
        def failed(error):
            self._mode_check_pending = False
            self.mode_feedback_label.configure(text="切换检查未开始：" + str(error), foreground=AMBER)
            self._control_state = None
            self._update_controls()
        self._task(lambda: self.controller.begin_mode_check(timeout_s=10), done, failed)

    def _update_controls(self, _event=None):
        active = bool(self._last_snapshot.get("running")) or self._action_pending or self._closing
        stopping = str(self._last_snapshot.get("state", "")).upper() == "STOPPING"
        source = SOURCES.get(self.source.get())
        mode_check_enabled = self._can_check_mode()
        mode_check_waiting = self._last_snapshot.get("mode_check_state") == "waiting"
        signature = (active, stopping, self._closing, source, self._frozen_wave is not None,
                     bool(self._replay_path), mode_check_enabled, mode_check_waiting,
                     self.port.get(), self._port_available(), self._ports_scanning,
                     self._last_snapshot.get('session_id'))
        if signature == self._control_state:
            return
        self._control_state = signature
        if source != self._control_source:
            self._control_source = source
            for widget in (self.port_combo, self.refresh_button, self.file_button, self.source_hint):
                widget.grid_remove()
            if source == "serial":
                self.port_combo.grid()
                self.refresh_button.grid()
            elif source == "replay":
                self.file_button.grid()
            else:
                self.source_hint.grid()
        self.source_combo.configure(state="disabled" if active else "readonly")
        serial = source == "serial"
        self.port_combo.configure(state="normal" if serial and not active else "disabled")
        self.refresh_button.configure(state="normal" if serial and not active and not self._ports_scanning else "disabled")
        self.file_button.configure(state="disabled" if active else "normal")
        self.file_button.configure(text="更换 CSV" if self._replay_path else "选择 CSV")
        self.start_button.configure(state="disabled" if active or (self.simple_mode and serial and not self._port_available()) else "normal",
                                    text={"serial": "开始采集", "demo": "开始演示", "replay": "开始回放"}.get(source, "开始采集"))
        self.stop_button.configure(state="normal" if active and not stopping and not self._closing else "disabled")
        self.review_button.configure(state='normal' if not active and self._last_snapshot.get('session_id') else 'disabled')
        self.pause_button.configure(state="normal" if (active or self._frozen_wave is not None) and not self._closing else "disabled")
        self.mode_check_button.configure(state="normal" if mode_check_enabled else "disabled",
                                         text="检查中…" if mode_check_waiting else "检查切换")
        if source == "serial" and (not self.simple_mode or active):
            self.mode_feedback_row.grid()
        else:
            self.mode_feedback_row.grid_remove()

    def _tick(self):
        if self._closed:
            return
        try:
            while True:
                callback, result, error, failure = self._messages.get_nowait()
                self._pending_tasks = max(0, self._pending_tasks - 1)
                try:
                    if error:
                        self._action_pending = False
                        self._control_state = None
                        self.status_label.configure(text=error, foreground=RED)
                        self._update_controls()
                        if failure:
                            failure(error)
                        messagebox.showerror("操作未完成", error, parent=self.root)
                    elif callback:
                        callback(result)
                except tk.TclError:
                    # A history/settings window can close while its task finishes.
                    pass
                except Exception as exc:
                    self.status_label.configure(text="操作结果处理失败：" + str(exc), foreground=RED)
        except Empty:
            pass
        snapshot_ok = False
        try:
            seconds = float(self.window_s.get().split()[0])
            # Retain the selectable history when freezing the display, so a
            # paused 2-second view can still expand back to 5 or 10 seconds.
            snapshot = self.controller.snapshot(window_s=max(seconds, 10))
            self._last_snapshot = snapshot
            snapshot_ok = True
            self._show_snapshot(snapshot, seconds)
            if (not self._closing and not self._action_pending and not snapshot.get('running')
                    and self._summary_session and snapshot.get('session_id')==self._summary_session):
                sid=self._summary_session;self._summary_session=None
                self.show_measurement_summary(sid)
            if (self._closing or self._stop_requested) and not self._action_pending:
                if snapshot.get("running") and str(snapshot.get("state", "")).upper() != "STOPPING":
                    self.controller.stop()
                elif not snapshot.get("running"):
                    self._stop_requested = False
        except Exception as exc:
            self.status_label.configure(text="界面数据更新失败：" + str(exc), foreground=RED)
        if snapshot_ok:
            self._advance_close()
        if self._closed:
            return
        if self.simple_mode and time.monotonic() >= self._next_port_scan:
            self.refresh_ports()
        if self.cloud is not None:
            if self._cloud_resume_pending and not self._closing and not self._poweroff_pending and self.cloud.wait(0):
                self.cloud.resume()
                self._cloud_resume_pending = False
            state = self.cloud.snapshot()
            remote_port=self.port.get().strip() if SOURCES[self.source.get()]=='serial' else ''
            self.cloud.update_device_status(dict(self._last_snapshot,remote_port=remote_port,
                remote_idle=not (self._closing or self._action_pending or self._poweroff_pending)))
            online = state["connection"] == "online"
            hint = '未授权' if state['connection']=='unauthorized' else '离线' if state['connection']=='offline' else '连接中'
            text = ("云端 ●" if online else '云端 · '+hint) if self.root.winfo_width() < 1000 else "云端 · " + ("可上传" if online else hint)
            self.cloud_button.configure(text=text, style="CloudOnline.Quiet.TButton" if online else "Quiet.TButton")
        self.root.after(100, self._tick)

    def _show_snapshot(self, snapshot, seconds):
        self._last_snapshot = snapshot
        session = snapshot.get("session_id")
        source = str(snapshot.get("source") or "")
        context = (session, source, snapshot.get("board_mode"), snapshot.get("analysis_generation"))
        if session != self._last_session or context != self._last_context:
            # A frozen old-mode trace must not acquire the new mode's label.
            self._frozen_wave = None
            self._frozen_classification = None
            self.pause_button.configure(text="暂停显示")
            self._last_session = session
            self._last_context = context
        name = SOURCE_NAMES.get(source, self.source.get())
        if snapshot.get("running") and source in SOURCE_NAMES:
            if self.source.get() != name:
                self.source.set(name)
            if source == "serial" and snapshot.get("port"):
                if self.port.get() != snapshot["port"]:
                    self.port.set(snapshot["port"])
        selected_source = source or SOURCES.get(self.source.get())
        real_serial = selected_source == "serial" and snapshot.get("board_mode") == 0
        self.source_badge.configure(text=source_label(selected_source, snapshot.get("board_mode")),
                                     foreground=GREEN if real_serial else AMBER,
                                     background="#14342e" if real_serial else "#30291f")
        idle = not snapshot.get('running') and not self._action_pending and not self._closing
        if self.simple_mode and idle:
            provenance = {'demo': '合成模拟', 'serial': {0: '实采', 1: '板端模拟'}.get(snapshot.get('board_mode'), '串口'),
                          'replay': '文件回放'}.get(source, '记录')
            self.source_badge.configure(text=('已停 · ' + provenance) if snapshot.get('received') else '待机 · 未采集',
                                        foreground=CYAN, background='#142219')
        if self.simple_mode and idle and not snapshot.get('received'):
            self.standby_card.place(relx=.5, rely=.5, anchor='center')
            self.standby_hint.configure(text=self._ports_message if SOURCES.get(self.source.get()) == 'serial' else
                                       '当前选择：' + self.source.get() + '，点击开始后运行')
        else:
            self.standby_card.place_forget()
        self.preprocess_label.configure(text="实采预处理" if snapshot.get("preprocessing_active") else "")
        elapsed = max(0, int(float(snapshot.get("elapsed_s") or 0)))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds_elapsed = divmod(remainder, 60)
        clock = f"{hours:02}:{minutes:02}:{seconds_elapsed:02}" if hours else f"{minutes:02}:{seconds_elapsed:02}"
        self.clock_label.configure(text=clock)
        if snapshot.get('running') and snapshot.get('remaining_s') is not None:
            remaining=max(0,int(math.ceil(snapshot['remaining_s'])))
            self.clock_label.configure(text=f'剩余 {remaining//60:02}:{remaining%60:02}')
        running = bool(snapshot.get("running"))
        receiving = running and snapshot.get("state") == "RECORDING"
        if source == "serial":
            receiving = receiving and bool(snapshot.get("serial_aligned"))
        # Fail closed if the quality permission is absent or stale. Displaying
        # a plausible old HR during bad signal is worse than showing '--'.
        hr_allowed = receiving and snapshot.get("hr_allowed") is True
        self.hr_label.configure(text=_number(snapshot.get("hr")) if hr_allowed else "--")
        self.rr_label.configure(text=_number(snapshot.get("rr_ms")) if hr_allowed else "--")
        classification_snapshot = self._frozen_classification if self._frozen_wave is not None and self._frozen_classification is not None else snapshot
        label,detail,scores = classification_display(classification_snapshot)
        self.class_label.configure(text=label,foreground=CLASS_COLORS.get(label, CYAN))
        self.class_detail.configure(text=detail)
        self.class_scores.configure(text=scores)
        self._strip_events = classification_events(classification_snapshot)[-20:]
        self._draw_beat_strip()
        self.class_details_button.configure(state="normal" if classification_snapshot.get("session_id") else "disabled")
        quality = snapshot.get("signal_text") or snapshot.get("quality", "等待信号")
        if isinstance(quality, dict):
            quality = quality.get("status") or quality.get("message") or "质量统计已记录"
        signal_state = snapshot.get("signal_state", "unknown")
        if not running:
            quality = "已停止" if snapshot.get("received") else "未开始采集" if self.simple_mode else "等待信号"
        elif snapshot.get("state") == "STOPPING":
            quality = "正在保存"
        elif not receiving:
            quality = snapshot.get("signal_text") if signal_state in ("interrupted", "waiting", "unknown") else "等待信号"
        signal_good = receiving and signal_state == "good"
        self.quality_label.configure(text="· " + _short(quality or "等待信号", 10),
                                      foreground=GREEN if signal_good else MUTED if not running else AMBER)
        received, saved = int(snapshot.get("received") or 0), int(snapshot.get("saved") or 0)
        self.saved_label.configure(text=f"{saved:,}")
        pending = max(0, received-saved)
        self.count_label.configure(text=f"待保存 {pending:,} 点" if pending else "记录已保存" if saved and not snapshot.get("running") else "原始数据自动保存")
        if not running and snapshot.get('error'):
            self.count_label.configure(text='记录需检查')
        elif self.simple_mode and idle and not snapshot.get('session_id'):
            self.count_label.configure(text='尚未建立记录')
        if source == "serial" and snapshot.get("running"):
            self.count_label.configure(text=f"串口 {int(snapshot.get('serial_bytes') or 0):,} B · 已收 {received:,} 点")
        connection_state = snapshot.get("connection_state", "unknown")
        connection = snapshot.get("connection_text")
        if not connection:
            connection = ("串口接收正常" if source == "serial" and receiving else
                          "串口等待数据" if source == "serial" and running else
                          "本地演示" if source == "demo" and running else
                          "文件回放" if source == "replay" and running else "已停止" if saved else "未连接")
        connection_color = (RED if connection_state == "error" or snapshot.get("error") else
                            GREEN if connection_state == "receiving" and receiving else
                            CYAN if running and source in ("demo", "replay") else AMBER if running else MUTED)
        self.connection_label.configure(text=_short(connection, 18), foreground=connection_color)
        if self.simple_mode and idle:
            self.connection_label.configure(text='设备已识别' if self._port_available() else '等待设备', foreground=CYAN if self._port_available() else MUTED)
        status = str(snapshot.get("error") or snapshot.get("signal_detail")
                     or snapshot.get("status") or "等待采集")
        if not snapshot.get("running") and not snapshot.get("error") and not self._action_pending:
            if self.simple_mode:
                status = (f'已保存 {saved:,} 点 · 可查看本次记录' if saved and not save_problem(snapshot) else
                          self._ports_message if SOURCES.get(self.source.get()) == 'serial' else '准备就绪，点击开始')
            if SOURCES.get(self.source.get()) == "serial" and not self.port.get():
                status = self._ports_message or "接入 USB-TTL，刷新并选择串口"
        if source == "serial" and receiving and not snapshot.get("signal_detail"):
            status = {0: "实采 · 等待信号质量判断", 1: "板端模拟 · 非人体心电"}.get(
                snapshot.get("board_mode"), "等待数据来源")
        if self._frozen_wave is not None:
            if not snapshot.get("error"):
                status = "暂停回看 · 波形与分类已冻结，采集保存继续" if snapshot.get("running") else "暂停回看 · 波形与分类已冻结"
        storage = snapshot.get("storage") or {}
        storage_state = storage.get("state", "ok")
        if storage_state in ("warning", "critical"):
            status = str(storage.get("detail") or ("存储空间不足，已保护性停止" if storage_state == "critical" else "存储空间偏低，请导出或清理历史记录"))
            self.count_label.configure(text="剩余 " + _size(storage.get("free_bytes")), foreground=RED if storage_state == "critical" else AMBER)
        else:
            self.count_label.configure(foreground=MUTED)
        self.paused_label.configure(text="暂停回看" if self._frozen_wave is not None else "")
        status = _short(status, 90)
        footer_width = self.footer.winfo_width()
        if footer_width <= 1:
            footer_width = max(100, self.root.winfo_width() - 36)
        self._status_width = max(80, footer_width - self.connection_label.winfo_reqwidth()
                                  - self.count_label.winfo_reqwidth() - 30)
        status = self._fit_status(status, self._status_width)
        self.status_label.configure(text=status, foreground=RED if snapshot.get("error") or storage_state == "critical" else AMBER if storage_state == "warning" or running and not signal_good else MUTED)
        check_state = snapshot.get("mode_check_state", "idle")
        feedback = str(snapshot.get("mode_feedback") or "模式由 STM32 的 SW2 按键切换；点击检查后按键")
        if check_state == "waiting":
            remaining = snapshot.get("mode_check_remaining_s")
            if remaining is not None:
                feedback += f" · 剩余 {max(0, math.ceil(float(remaining)))} 秒"
        feedback_width = max(100, footer_width - self.mode_check_button.winfo_reqwidth() - 12)
        feedback = self._fit_status(feedback, feedback_width)
        self.mode_feedback_label.configure(text=feedback,
                                           foreground=GREEN if check_state == "confirmed" and receiving else
                                           AMBER if check_state in ("waiting", "timeout", "interrupted") else MUTED)
        wave = snapshot.get("wave") or {"x": [], "raw": [], "filtered": []}
        self._last_wave = wave
        self.waveform.render(self._frozen_wave if self._frozen_wave is not None else wave,
                             window_s=seconds, mode=MODES[self.mode.get()],
                             auto_scale=self.auto_scale.get(), vref=self.vref,
                             markers=classification_events(classification_snapshot))
        self._update_controls()

    def _fit_status(self, text, width):
        key = (text, int(width))
        if key not in self._fitted_status:
            fitted = text
            while len(fitted) > 6 and self._status_font.measure(fitted) > width:
                fitted = fitted[:-2] + "…"
            if len(self._fitted_status) >= 128:
                self._fitted_status.clear()
            self._fitted_status[key] = fitted
        return self._fitted_status[key]

    def _draw_beat_strip(self):
        canvas = self.beat_strip
        width = max(20, canvas.winfo_width())
        signature = (width, self._frozen_wave is not None,
                     tuple((row.get("prediction_id"), row.get("r_sample"), row.get("segment_id"), row.get("label")) for row in self._strip_events))
        if signature == self._strip_signature:
            return
        self._strip_signature = signature
        canvas.delete("all")
        title = "暂停回看 · 最近已分类" if self._frozen_wave is not None else "最近 20 搏 · 已分类"
        canvas.create_text(1, 0, anchor="nw", text=title, fill=AMBER if self._frozen_wave is not None else MUTED,
                           font=(self.family, 7))
        if not self._strip_events:
            canvas.create_text(1, 17, anchor="nw", text="等待可分类心搏", fill=MUTED, font=(self.family, 7))
            return
        cell = width / 20
        for index, row in enumerate(self._strip_events[-20:]):
            left = index * cell
            color = CLASS_COLORS[row["label"]]
            canvas.create_rectangle(left, 15, left+cell-1, 31, fill="#11221c", outline=color, width=1)
            canvas.create_text(left+cell/2, 23, text=row["label"], fill=color, font=("DejaVu Sans", 8, "bold"))

    def _click_beat_strip(self, event):
        if event.y < 15 or not self._strip_events:
            return
        index = int(event.x / (max(20, self.beat_strip.winfo_width()) / 20))
        if 0 <= index < len(self._strip_events):
            self.show_classification_details(self._strip_events[index])

    def show_classification_details(self, initial=None, session_id=None):
        """Inspect saved predictions; review never touches the live sampling path."""
        initial = dict(initial) if isinstance(initial, dict) else None
        shown = self._frozen_classification or self._last_snapshot
        sid = session_id or (initial or {}).get("session_id") or shown.get("session_id")
        if not sid:
            messagebox.showinfo("分类详情", "尚无会话记录。开始采集后可查看分类详情。", parent=self.root)
            return
        existing = getattr(self, "_classification_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
        dialog = tk.Toplevel(self.root)
        self._classification_dialog = dialog
        dialog.title("心搏分类 · 统计与回看")
        dialog.configure(bg=BG)
        self._place_dialog(dialog, 776, 430)
        dialog.minsize(760, 420)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        CachedTtkLabel(frame, text="会话：" + str(sid), style="Muted.TLabel", font=(self.family, 8), wraplength=735).grid(row=0, column=0, sticky="w", pady=(0, 6))
        tabs = ttk.Notebook(frame)
        tabs.grid(row=1, column=0, sticky="nsew")
        summary = ttk.Frame(tabs, padding=(10, 8))
        review = ttk.Frame(tabs, padding=(8, 8))
        tabs.add(summary, text="分类概览")
        tabs.add(review, text="心搏回看")
        summary.columnconfigure(0, weight=1)
        summary.rowconfigure(3, weight=1)
        review.columnconfigure(0, weight=1)
        review.rowconfigure(1, weight=1)
        counts_frame = ttk.Frame(summary)
        counts_frame.grid(row=0, column=0, sticky="ew")
        count_labels = {}
        for column, label in enumerate(("N", "S", "V")):
            counts_frame.columnconfigure(column, weight=1)
            count_labels[label] = CachedTtkLabel(counts_frame, text=label+"  --", foreground=CLASS_COLORS[label], font=(self.family, 11, "bold"))
            count_labels[label].grid(row=0, column=column, sticky="w", padx=(0, 8))
        totals = CachedTtkLabel(summary, text="正在读取已保存的分类记录…", style="Muted.TLabel", font=(self.family, 8), wraplength=710)
        totals.grid(row=1, column=0, sticky="w", pady=(5, 6))
        filter_row = ttk.Frame(summary)
        filter_row.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        CachedTtkLabel(filter_row, text="记录筛选", style="Muted.TLabel", font=(self.family, 9)).pack(side="left", padx=(0, 8))
        selected_filter = tk.StringVar(value="待复核 S/V")
        filter_box = ttk.Combobox(filter_row, textvariable=selected_filter, values=("待复核 S/V", "全部已分类", "N", "S", "V"), state="readonly", width=12)
        filter_box.pack(side="left")
        CachedTtkLabel(filter_row, text="选中后回看；N 不等于完全健康", style="Muted.TLabel", font=(self.family, 8)).pack(side="left", padx=12)
        table_frame = ttk.Frame(summary)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=("time", "label", "score", "latency", "segment"), show="headings", selectmode="browse", height=3)
        for name, heading, width in (("time", "R 点时刻 / s", 125), ("label", "研究分类", 185), ("score", "模型分数", 110), ("latency", "采样等待 / s", 120), ("segment", "数据段", 100)):
            tree.heading(name, text=heading)
            tree.column(name, width=width, minwidth=65, stretch=name == "label")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        selected_text = CachedTtkLabel(review, text="在分类概览中选择心搏，或点击主波形上的 N/S/V 标记。", foreground=CYAN, font=(self.family, 9), wraplength=710)
        selected_text.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        canvas = WaveformCanvas(review)
        canvas.grid(row=1, column=0, sticky="nsew")
        review_note = CachedTtkLabel(review, text="仅回看已保存的原始数据；分类标记与对应 R 点对齐。", style="Muted.TLabel", font=(self.family, 8), wraplength=710)
        review_note.grid(row=2, column=0, sticky="w", pady=(4, 0))
        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        actions.columnconfigure(0, weight=1)
        status = CachedTtkLabel(actions, text="模型分数不是诊断概率；S/V 结果需复核。", style="Muted.TLabel", font=(self.family, 8), wraplength=420)
        status.grid(row=0, column=0, sticky="w", padx=(0, 10))
        cache = {"rows": [], "selected": None, "wave": None, "busy": False, "loading": False}
        opening_target = [initial if valid_classification_row(initial, sid) else None]
        row_map = {}
        def alive():
            return bool(dialog.winfo_exists())
        def controls():
            if alive():
                review_button.configure(state="disabled" if cache["loading"] or not tree.selection() else "normal")
                refresh_button.configure(state="disabled" if cache["busy"] else "normal")
        def populate(_=None):
            if not alive():
                return
            tree.delete(*tree.get_children())
            row_map.clear()
            chosen = selected_filter.get()
            rows = [row for row in cache["rows"] if chosen == "全部已分类" or row.get("label") == chosen or chosen == "待复核 S/V" and row.get("label") in ("S", "V")]
            for index, row in enumerate(reversed(rows)):
                iid = str(index)
                row_map[iid] = row
                label = row.get("label", "--")
                score = (row.get("scores") or {}).get(label)
                tree.insert("", "end", iid=iid, values=(f'{int(row["r_sample"])/360:.3f}', label+" · "+CLASS_NAMES.get(label, "待复核"),
                    _number(float(score)*100) if score is not None else "--", _sample_wait(row), row.get("segment_id", "--")), tags=(label,))
            for label, color in CLASS_COLORS.items():
                tree.tag_configure(label, foreground=color)
            status.configure(text=(f"本页 {len(rows)} 个已分类心搏。模型分数非诊断概率。" if rows else "此筛选暂无已保存心搏。采集中请稍候刷新。"), foreground=MUTED)
            controls()
        def render_review(_=None):
            item = cache.get("wave")
            if not alive() or not item:
                return
            begin, end = float(item["begin_s"]), float(item["end_s"])
            markers = [row for row in cache["rows"] if row.get("session_id") == sid and begin <= int(row["r_sample"])/360 <= end]
            prediction = item.get("prediction") or cache["selected"]
            if prediction and prediction not in markers:
                markers.append(prediction)
            display_mode = MODES[self.mode.get()]
            filtered = np.asarray(item["wave"].get("filtered", []), dtype=float)
            raw = np.asarray(item["wave"].get("raw", []), dtype=float)
            raw_fallback = display_mode != "raw" and not np.isfinite(filtered).any() and np.isfinite(raw).any()
            if raw_fallback:
                display_mode = "raw"
            note = cache.get("review_note", "")
            if raw_fallback:
                note += " 此记录无可用处理波形，已显示原始数据。"
            review_note.configure(text=note, foreground=AMBER if raw_fallback or item.get("partial") else MUTED)
            canvas.render(item["wave"], mode=display_mode, auto_scale=True,
                          vref=float(item.get("vref", self.vref)), markers=markers, bounds=(begin, end))
        def review_failed(error):
            cache["loading"] = False
            if alive():
                review_note.configure(text="暂无法回看：" + str(error) + "。最新心搏可能仍在保存，请约 1 秒后重试。", foreground=AMBER)
                status.configure(text="回看未完成，原始采集继续。", foreground=AMBER)
                controls()
        def load_review(row=None):
            if cache["loading"] or not alive():
                return
            if row is None:
                selected = tree.selection()
                row = row_map.get(selected[0]) if selected else None
            if not row:
                return
            row = dict(row)
            if not valid_classification_row(row, sid):
                review_failed("所选心搏记录不完整或与当前会话不一致")
                return
            cache["selected"], cache["loading"] = row, True
            cache["wave"] = None
            tabs.select(review)
            canvas.render({"x": [], "raw": [], "filtered": []})
            selected_text.configure(text="正在读取所选心搏前后各 2 秒的已保存波形…")
            review_note.configure(text="后台读取，不影响实时采集。", foreground=MUTED)
            controls()
            def loaded(result):
                cache["loading"] = False
                if not alive():
                    return
                if not isinstance(result, dict) or not result.get("wave"):
                    review_failed("尚无可回看的保存数据")
                    return
                prediction = result.get("prediction") or row
                if not valid_classification_row(prediction, sid):
                    review_failed("回看记录不完整或与会话不一致")
                    return
                cache["wave"] = result
                label = prediction.get("label", "--")
                scores = prediction.get("scores") or {}
                score_text = " · ".join(k+" "+_number(float(scores.get(k, 0))*100) for k in ("N", "S", "V"))
                selected_text.configure(text=f'{label} · {CLASS_NAMES.get(label, "待复核")}  |  R 点 {int(prediction["r_sample"])/360:.3f}s  |  采样等待 {_sample_wait(prediction)}s\n模型分数（非诊断概率）：'+score_text,
                                        foreground=CLASS_COLORS.get(label, CYAN))
                note = str(result.get("note") or "原始记录回看；处理波形用于观察。")
                note += " 采样等待不含全部排队与推理耗时。"
                if result.get("partial"):
                    note = "窗口不完整（边界、断点或数据尚未保存）。" + note
                cache["review_note"] = note
                review_note.configure(text=note, foreground=AMBER if result.get("partial") else MUTED)
                render_review()
                status.configure(text="历史心搏回看 · 实时采集状态仍在主窗口显示。", foreground=MUTED)
                controls()
            self._task(lambda: self.controller.review_beat(sid, int(row["r_sample"]), row["segment_id"], before_s=2, after_s=2), loaded, review_failed)
        canvas.on_marker_click = load_review
        canvas.bind("<Configure>", render_review, add="+")
        def failed(error):
            cache["busy"] = False
            if alive():
                status.configure(text="读取未完成：" + str(error), foreground=AMBER)
                controls()
        def loaded_details(result):
            cache["busy"] = False
            if not alive():
                return
            if not isinstance(result, dict) or result.get("session_id") != sid:
                failed("未找到该会话的分类记录")
                return
            returned_rows = result.get("rows", [])
            cache["rows"] = sorted((dict(row) for row in returned_rows if valid_classification_row(row, sid)), key=lambda row: int(row["r_sample"]))
            excluded = len(returned_rows) - len(cache["rows"])
            counts = result.get("counts") or {}
            total = sum(max(0, int(counts.get(label, 0))) for label in CLASS_NAMES)
            for label, widget in count_labels.items():
                count = max(0, int(counts.get(label, 0)))
                percentage = f"{100*count/total:.1f}%" if total else "--"
                widget.configure(text=f"{label}  {count:,}  ·  {percentage}")
            rejected = result.get("rejected")
            rejected_text = "未知" if rejected is None else f"{int(rejected):,}"
            detail = f"占比仅以 {total:,} 个已分类心搏为分母。已拒绝候选 {rejected_text}；不可判定期间的心搏数未知。"
            if result.get("truncated"):
                detail += f'\n列表仅显示最近 {len(cache["rows"]):,} / {int(result.get("total_rows", len(cache["rows"]))):,} 条；统计包含完整会话。'
            else:
                detail += "\nS：室上性异位倾向；V：室性异位倾向，均需复核。"
            if excluded:
                detail += f" 已排除 {excluded} 条不完整或会话不符的记录。"
            totals.configure(text=detail)
            populate()
            if opening_target[0]:
                target, opening_target[0] = opening_target[0], None
                load_review(target)
        def refresh():
            if cache["busy"]:
                return
            cache["busy"] = True
            status.configure(text="正在读取已保存的分类记录…", foreground=CYAN)
            controls()
            self._task(lambda: self.controller.classification_details(session_id=sid), loaded_details, failed)
        review_button = CachedTtkButton(actions, text="回看选中心搏", command=load_review, padding=(8, 5))
        review_button.grid(row=0, column=1, padx=(0, 6))
        refresh_button = CachedTtkButton(actions, text="刷新", command=refresh, style="Quiet.TButton", padding=(8, 5))
        refresh_button.grid(row=0, column=2)
        CachedTtkButton(actions, text="关闭", command=dialog.destroy, style="Quiet.TButton", padding=(8, 5)).grid(row=0, column=3)
        filter_box.bind("<<ComboboxSelected>>", populate)
        tree.bind("<<TreeviewSelect>>", lambda _: controls())
        tree.bind("<Double-1>", lambda _: load_review())
        refresh()

    def _place_dialog(self, dialog, width, height):
        dialog.transient(self.root)
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_view_settings(self, values):
        self._settings.update(values)
        self.vref = float(self._settings["vref"])
        self.auto_scale.set(bool(self._settings["auto_scale"]))
        self.mode.set(next((k for k, v in MODES.items() if v == self._settings["display_mode"]), "处理后"))
        self.window_s.set(f'{self._settings["display_seconds"]:g} 秒')

    def _is_busy(self):
        return bool(self._last_snapshot.get("running")) or self._action_pending or self._closing

    def _export_directory(self):
        recent = self._settings.get("last_export_dir")
        return str(recent if self._settings.get("remember_export_dir") and recent else self._settings["export_dir"])

    def _open_export_directory(self):
        path = Path(self._export_directory()).expanduser().resolve()
        def operation():
            path.mkdir(parents=True, exist_ok=True)
            try:
                process = subprocess.Popen(["explorer.exe", str(path)] if os.name == "nt" else ["xdg-open", str(path)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    result = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # A file manager may keep its process alive while its window is open.
                    return str(path)
                if result:
                    raise OSError("文件管理器未能打开此目录")
            except OSError as exc:
                raise RuntimeError("无法打开文件管理器。可通过 VS Code 或文件传输工具访问：\n" + str(path) + "\n" + str(exc)) from exc
            return str(path)
        self._task(operation)

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("设置")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        self._place_dialog(dialog, 740, 416)
        content = ttk.Frame(dialog, padding=(16, 12))
        content.pack(fill="both", expand=True)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        tabs = ttk.Notebook(content)
        tabs.grid(row=0, column=0, sticky="nsew")
        # Construct acquisition first to preserve keyboard/test entry ordering.
        acquisition = ttk.Frame(tabs, padding=16)
        display = ttk.Frame(tabs, padding=16)
        storage = ttk.Frame(tabs, padding=16)
        time_tab = ttk.Frame(tabs, padding=16)
        for pane, title in ((display, "显示"), (acquisition, "采集"), (storage, "存储"), (time_tab, "时间")):
            tabs.add(pane, text=title)
            pane.columnconfigure(1, weight=1)
        vars_ = {
            "vref": tk.StringVar(value=str(self.vref)),
            "classification_enabled": tk.BooleanVar(value=bool(self._settings["classification_enabled"])),
            "display_seconds": tk.StringVar(value=self.window_s.get()),
            "display_mode": tk.StringVar(value=self.mode.get()),
            "auto_scale": tk.BooleanVar(value=self.auto_scale.get()),
            "export_dir": tk.StringVar(value=str(self._settings["export_dir"])),
            "remember_export_dir": tk.BooleanVar(value=bool(self._settings["remember_export_dir"])),
            "export_include_raw": tk.BooleanVar(value=bool(self._settings["export_include_raw"])),
            "low_space_warn_mb": tk.StringVar(value=str(self._settings["low_space_warn_mb"])),
            "low_space_stop_mb": tk.StringVar(value=str(self._settings["low_space_stop_mb"])),
            "auto_time_sync": tk.BooleanVar(value=bool(self._settings["auto_time_sync"])),
        }
        CachedTtkLabel(acquisition, text="ADC 参考电压 / V").grid(row=0, column=0, sticky="w", pady=6)
        reference = ttk.Entry(acquisition, textvariable=vars_["vref"], width=10)
        reference.grid(row=0, column=1, sticky="w", padx=18)
        model = ttk.Checkbutton(acquisition, text="启用 N / S / V 心搏分类（下次采集生效）", variable=vars_["classification_enabled"])
        model.grid(row=1, column=0, columnspan=2, sticky="w", pady=10)
        acquisition_note = CachedTtkLabel(acquisition, text="", foreground=AMBER)
        acquisition_note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 8))
        CachedTtkLabel(acquisition, text="默认 3.300 V，未校准。ADC × 参考电压 ÷ 4095 得到 ADC 输入端电压。\n"
                  "实采预处理：0.5 Hz 高通 → 50 Hz 陷波 → 40 Hz 低通；原始数据始终保留。\n"
                  "采样 360 Hz · 串口 115200 / 8N1。模型仅对有效实采信号输出研究分类。",
                  style="Muted.TLabel", wraplength=650, font=(self.family, 9)).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        for row, title, name, choices in ((0, "显示时长", "display_seconds", ("2 秒", "5 秒", "10 秒")),
                                         (1, "波形内容", "display_mode", tuple(MODES))):
            CachedTtkLabel(display, text=title).grid(row=row, column=0, sticky="w", pady=10)
            ttk.Combobox(display, textvariable=vars_[name], values=choices, state="readonly", width=14).grid(row=row, column=1, sticky="w", padx=22)
        ttk.Checkbutton(display, text="自动调整波形纵轴", variable=vars_["auto_scale"]).grid(row=2, column=0, columnspan=2, sticky="w", pady=12)
        CachedTtkLabel(display, text="2 秒观察单个心搏；5 秒日常监看；10 秒观察节律。\n暂停显示不会停止采集与保存。\nF11 全屏切换 · Esc 退出全屏 · Alt+F4 关闭窗口。",
                  style="Muted.TLabel", wraplength=640).grid(row=3, column=0, columnspan=2, sticky="w", pady=12)
        CachedTtkLabel(storage, text="默认导出目录").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(storage, textvariable=vars_["export_dir"]).grid(row=0, column=1, sticky="ew", padx=10)
        def choose_directory():
            selected = filedialog.askdirectory(parent=dialog, title="选择默认导出目录", initialdir=vars_["export_dir"].get())
            if selected:
                vars_["export_dir"].set(selected)
        CachedTtkButton(storage, text="选择…", command=choose_directory).grid(row=0, column=2)
        ttk.Checkbutton(storage, text="记住最近一次导出位置", variable=vars_["remember_export_dir"]).grid(row=1, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Checkbutton(storage, text="完整 ZIP 包含原始分块（便于复核与恢复）", variable=vars_["export_include_raw"]).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))
        limits = ttk.Frame(storage)
        limits.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        CachedTtkLabel(limits, text="剩余空间预警 / MB").pack(side="left")
        ttk.Entry(limits, textvariable=vars_["low_space_warn_mb"], width=7).pack(side="left", padx=(10, 20))
        CachedTtkLabel(limits, text="自动停止 / MB").pack(side="left")
        ttk.Entry(limits, textvariable=vars_["low_space_stop_mb"], width=7).pack(side="left", padx=10)
        disk_text = CachedTtkLabel(storage, text="正在检查存储空间…", foreground=CYAN, wraplength=650)
        disk_text.grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 6))
        CachedTtkLabel(storage, text="自动停止阈值须小于预警阈值。系统不会自动删除历史数据；回收站也占用空间。",
                  style="Muted.TLabel", wraplength=650, font=(self.family, 9)).grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(time_tab, text="启动时尝试联网校时", variable=vars_["auto_time_sync"]).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        time_text = CachedTtkLabel(time_tab, text="正在读取系统时间…", foreground=CYAN, wraplength=650)
        time_text.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        timezone = datetime.now().astimezone().strftime("%Z (UTC%z)")
        CachedTtkLabel(time_tab, text="手动设置本机时间 · " + timezone, style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        manual_time = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ttk.Entry(time_tab, textvariable=manual_time, width=24).grid(row=3, column=0, sticky="w")
        clock_pending = [False]
        settings_pending = [False]
        def show_clock(info):
            clock_pending[0] = False
            if not dialog.winfo_exists():
                return
            info = info if isinstance(info, dict) else {}
            trusted = bool(info.get("trusted"))
            source = {"ntp": "联网校验", "manual": "手动设置", "unknown": "来源未知", "system_unverified": "本机系统时间"}.get(info.get("source"), "本机系统时间")
            text = "当前：" + _local_time(info.get("local") or info.get("utc"), full=True) + " · " + source
            text += " · 时间已校验" if trusted else " · 时间未联网校验"
            if info.get("detail"):
                text += "\n" + str(info["detail"])
            time_text.configure(text=text, foreground=CYAN if trusted else AMBER)
            update_locks()
        def clock_failed(error):
            clock_pending[0] = False
            if dialog.winfo_exists():
                time_text.configure(text="校时未完成：" + str(error), foreground=AMBER)
                update_locks()
        def clock_result(info, operation, authorized=False):
            if not dialog.winfo_exists():
                return
            if not isinstance(info, dict) or not info.get("authorization_required"):
                show_clock(info)
                return
            if authorized:
                clock_failed(info.get("detail") or "本次授权未能完成校时，请稍后重试。")
                return
            if self._is_busy():
                clock_failed("采集中无法校时，请停止采集后重试。")
                return
            password = simpledialog.askstring("校时授权", "请输入当前树莓派用户的系统密码（仅用于本次授权，不保存）：",
                                              show="*", parent=dialog)
            if password is None:
                clock_pending[0] = False
                time_text.configure(text="已取消校时授权，系统时间未修改。", foreground=MUTED)
                update_locks()
                return
            if self._is_busy():
                clock_failed("采集中无法校时，请停止采集后重试。")
                return
            time_text.configure(text="正在验证本次校时授权…", foreground=CYAN)
            def authorized_result(result):
                if not dialog.winfo_exists():
                    return
                if not isinstance(result, dict) or not result.get("success"):
                    clock_failed(result.get("detail", "系统密码验证失败。") if isinstance(result, dict) else "系统密码验证失败。")
                    return
                if self._is_busy():
                    clock_failed("采集已开始，本次未修改时间；停止采集后可重试。")
                    return
                time_text.configure(text="授权通过，正在校时…", foreground=CYAN)
                self._task(operation, lambda value: clock_result(value, operation, authorized=True), clock_failed)
            # Only this short-lived worker closure owns the password; preferences,
            # status messages and the window instance never retain it.
            self._task(lambda: self.controller.authorize_time(password), authorized_result, clock_failed)
        def change_time(manual=False):
            if self._is_busy() or clock_pending[0]:
                return
            if manual:
                value = manual_time.get().strip()
                try:
                    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
                        raise ValueError()
                except ValueError:
                    messagebox.showerror("日期格式", "请输入 YYYY-MM-DD HH:MM:SS，例如 2026-10-29 14:30:00。", parent=dialog)
                    return
                if not messagebox.askyesno("确认设置系统时间", "将本机时间设置为：\n" + value + "\n时区：" + timezone + "\n\n仅影响此后记录的时间；历史记录不会改写。确认设置？", parent=dialog):
                    return
                operation = lambda: self.controller.set_time(value)
            else:
                operation = self.controller.sync_time
            clock_pending[0] = True
            time_text.configure(text="正在校时…", foreground=CYAN)
            update_locks()
            self._task(operation, lambda result: clock_result(result, operation), clock_failed)
        manual_button = CachedTtkButton(time_tab, text="设置时间…", command=lambda: change_time(True))
        manual_button.grid(row=3, column=1, sticky="w", padx=10)
        sync_button = CachedTtkButton(time_tab, text="立即联网校时", command=change_time)
        sync_button.grid(row=3, column=2, sticky="e")
        CachedTtkLabel(time_tab, text="采集中禁止校时，避免记录时间跳变。手动设置不代表已联网校验。\n时间可信状态会随会话保存，原始采样时序不因校时改动。",
                  style="Muted.TLabel", wraplength=650, font=(self.family, 9)).grid(row=4, column=0, columnspan=3, sticky="w", pady=12)
        status = CachedTtkLabel(content, text="设置保存在本机，重启后保留。", style="Muted.TLabel", wraplength=470, font=(self.family, 9))
        status.grid(row=1, column=0, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(content)
        buttons.grid(row=1, column=0, sticky="e", pady=(12, 0))
        CachedTtkButton(buttons, text="取消", command=dialog.destroy, style="Quiet.TButton").pack(side="left", padx=(0, 8))
        def applied(result):
            self._apply_view_settings(result if isinstance(result, dict) else candidate[0])
            if dialog.winfo_exists():
                dialog.destroy()
        candidate = [{}]
        def save_failed(error):
            settings_pending[0] = False
            if dialog.winfo_exists():
                status.configure(text="保存失败：" + str(error), foreground=RED)
                update_locks()
        def apply():
            try:
                selected = self.vref if self._is_busy() else float(vars_["vref"].get())
                if not .1 <= selected <= 5:
                    raise ValueError()
            except ValueError:
                tabs.select(acquisition)
                messagebox.showerror("参考电压", "请输入 0.1～5 V 范围内的数值。", parent=dialog)
                return
            try:
                warn, stop = int(vars_["low_space_warn_mb"].get()), int(vars_["low_space_stop_mb"].get())
                if not 1 <= stop < warn:
                    raise ValueError()
            except ValueError:
                tabs.select(storage)
                messagebox.showerror("空间阈值", "请输入正整数，且自动停止阈值小于预警阈值。", parent=dialog)
                return
            if not vars_["export_dir"].get().strip():
                tabs.select(storage)
                messagebox.showerror("导出目录", "请选择或填写默认导出目录。", parent=dialog)
                return
            values = {key: value.get() for key, value in vars_.items()}
            values.update(vref=selected, display_seconds=int(values["display_seconds"].split()[0]),
                          display_mode=MODES[values["display_mode"]], low_space_warn_mb=warn, low_space_stop_mb=stop,
                          export_dir=str(Path(values["export_dir"].strip()).expanduser()))
            if self._is_busy():
                values["classification_enabled"] = self._settings["classification_enabled"]
            candidate[0] = values
            setter = getattr(self.controller, "update_settings", None)
            if callable(setter):
                settings_pending[0] = True
                status.configure(text="正在保存设置…", foreground=CYAN)
                update_locks()
                self._task(lambda: setter(values), applied, save_failed)
            else:
                applied(values)
        apply_button = CachedTtkButton(buttons, text="应用设置", command=apply, style="Start.TButton")
        apply_button.pack(side="left")
        def update_locks():
            if not dialog.winfo_exists():
                return
            locked = self._is_busy()
            reference.configure(state="disabled" if locked or settings_pending[0] else "normal")
            model.configure(state="disabled" if locked or settings_pending[0] else "normal")
            acquisition_note.configure(text="采集中：参考电压与分类开关暂不可修改。" if locked else "参考电压与分类开关应用于下一次采集。")
            for button, method in ((manual_button, "set_time"), (sync_button, "sync_time")):
                button.configure(state="disabled" if locked or clock_pending[0] or not callable(getattr(self.controller, method, None)) else "normal")
            apply_button.configure(state="disabled" if settings_pending[0] else "normal")
        def monitor_locks():
            if dialog.winfo_exists():
                update_locks()
                self.root.after(300, monitor_locks)
        monitor_locks()
        def show_disk(info):
            if dialog.winfo_exists() and isinstance(info, dict):
                estimate = info.get("estimated_recording_seconds")
                suffix = f" · 预计可记录 {float(estimate)/3600:.1f} 小时" if estimate is not None else ""
                disk_text.configure(text="剩余 " + _size(info.get("free_bytes")) + " / 总计 " + _size(info.get("total_bytes")) + suffix,
                                    foreground=AMBER if info.get("state") in ("warning", "critical") else CYAN)
        for name, callback in (("storage_status", show_disk), ("clock_status", show_clock)):
            operation = getattr(self.controller, name, None)
            if callable(operation):
                if name == "clock_status":
                    clock_pending[0] = True
                    update_locks()
                self._task(operation, callback)

    def show_history(self, session_id=None):
        dialog = tk.Toplevel(self.root)
        dialog.title("历史记录 · 导出与回收站")
        self._place_dialog(dialog, 776, 420)
        dialog.minsize(760, 400)
        dialog.configure(bg=BG)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        recycle = tk.BooleanVar(value=False)
        sessions, busy = {}, [False]
        tree = ttk.Treeview(frame, columns=("time", "source", "count", "size", "status", "id"), show="headings", selectmode="browse", height=5)
        for name, heading, width in zip(tree["columns"], ("开始时间", "来源", "点数", "大小", "状态", "会话编号"), (138, 100, 75, 75, 66, 220)):
            tree.heading(name, text=heading)
            tree.column(name, width=width, minwidth=50, stretch=name == "id")
        tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        selection_text = CachedTtkLabel(frame, text="选择一个会话可查看详情。", style="Muted.TLabel", wraplength=735, font=(self.family, 9))
        selection_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        message = CachedTtkLabel(frame, text="正在读取历史记录…", foreground=CYAN, wraplength=735, font=(self.family, 9))
        message.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions.columnconfigure(4, weight=1)
        def selected_row():
            selected = tree.selection()
            return sessions.get(selected[0]) if selected else None
        def describe(row):
            from measurement import owner_label
            return "会话：" + str(row["session_id"]) + "\n开始：" + _local_time(row.get("started_utc"), full=True) + " · " + f'{int(row.get("sample_count", 0)):,}' + " 点 · 归属：" + owner_label(row)
        def update_buttons(_=None):
            if not dialog.winfo_exists():
                return
            row = selected_row()
            allowed = row is not None and not busy[0] and not self._is_busy() and row.get("session_id") != (self._last_snapshot.get("session_id") if self._last_snapshot.get("running") else None)
            for button in (zip_button, csv_button, delete_button, restore_button):
                button.configure(state="normal" if allowed else "disabled")
            zip_button.configure(state="normal" if allowed and not recycle.get() else "disabled")
            csv_button.configure(state="normal" if allowed and not recycle.get() else "disabled")
            delete_button.configure(text="永久删除…" if recycle.get() else "移入回收站…")
            restore_button.configure(state="normal" if allowed and recycle.get() else "disabled")
            classification_button.configure(state="normal" if row is not None and not busy[0] and not recycle.get() else "disabled")
            summary_button.configure(state='normal' if allowed and not recycle.get() else 'disabled')
            refresh_button.configure(state="disabled" if busy[0] else "normal")
            for radio in radios:
                radio.configure(state="disabled" if busy[0] else "normal")
        def selection_changed(_=None):
            row = selected_row()
            if row:
                trusted = "时间已联网校验" if row.get("time_trusted") else "时间未联网校验"
                selection_text.configure(text=describe(row).replace("\n", " · ") + " · " + trusted)
            else:
                selection_text.configure(text="选择一个会话可查看详情。")
            update_buttons()
        def populated(items):
            if not dialog.winfo_exists():
                return
            busy[0] = False
            tree.delete(*tree.get_children())
            sessions.clear()
            for index, row in enumerate(items):
                iid = str(index)
                sessions[iid] = row
                tree.insert("", "end", iid=iid, values=(_local_time(row.get("started_utc")), SOURCE_NAMES.get(row.get("source"), row.get("source", "")),
                    f'{int(row.get("sample_count", 0)):,}', _size(row.get("size_bytes")),
                    "已删除" if recycle.get() else {"complete": "已保存", "recording": "记录中", "incomplete": "未完成", "error": "异常"}.get(row.get("status"), row.get("status", "")), row.get("session_id", "")))
                if session_id and row.get('session_id') == session_id:
                    tree.selection_set(iid)
                    tree.see(iid)
            message.configure(text=f"共 {len(items)} 个会话。" + ("回收站仍占空间；永久删除后无法恢复。" if recycle.get() else "完整 ZIP 包含波形、分析结果与会话信息；CSV 可单独导出。"), foreground=MUTED)
            selection_changed()
        def failed(error):
            busy[0] = False
            if dialog.winfo_exists():
                message.configure(text="操作未完成：" + str(error), foreground=RED)
                update_buttons()
        def refresh():
            if busy[0]:
                return
            busy[0] = True
            trashed = recycle.get()
            message.configure(text="正在读取回收站…" if trashed else "正在读取历史记录…", foreground=CYAN)
            update_buttons()
            def operation():
                try:
                    return self.controller.list_sessions(trashed=trashed)
                except TypeError:
                    if trashed:
                        return []
                    return self.controller.list_sessions()
            self._task(operation, populated, failed)
        def export(bundle=True):
            row = selected_row()
            if row is None or busy[0] or self._is_busy() or recycle.get():
                return
            sid = str(row["session_id"])
            extension = ".zip" if bundle else ".csv"
            path = filedialog.asksaveasfilename(parent=dialog, title="导出完整 ZIP" if bundle else "导出原始 CSV", initialdir=self._export_directory(),
                                              initialfile="ecg_" + sid + extension, defaultextension=extension,
                                              filetypes=[("完整会话 ZIP" if bundle else "原始波形 CSV", "*" + extension)])
            if not path:
                return
            include_raw = bool(self._settings["export_include_raw"])
            busy[0] = True
            message.configure(text="正在后台导出完整记录…", foreground=CYAN)
            update_buttons()
            def exported(result):
                busy[0] = False
                self._settings["last_export_dir"] = str(Path(path).parent)
                if dialog.winfo_exists():
                    message.configure(text="已导出：" + str(result or path), foreground=GREEN)
                    update_buttons()
            self._task(lambda: self.controller.export_bundle(sid, path, include_raw=include_raw) if bundle else self.controller.export_session(sid, path), exported, failed)
        def mutate(restore=False):
            row = selected_row()
            if row is None or busy[0] or self._is_busy():
                return
            sid = str(row["session_id"])
            if restore:
                operation = lambda: self.controller.restore_session(sid)
            elif recycle.get():
                if not messagebox.askyesno("永久删除会话", describe(row) + "\n\n将永久删除所有原始数据和分析结果。此操作不能恢复，继续？", parent=dialog, default="no"):
                    return
                if not messagebox.askyesno("再次确认永久删除", "请核对会话编号：\n" + sid + "\n\n确认已不再需要这些数据，永久删除？", parent=dialog, default="no"):
                    return
                operation = lambda: self.controller.purge_session(sid)
            else:
                if not messagebox.askyesno("移入回收站", describe(row) + "\n\n将此会话移入回收站？之后可恢复，当前不会释放空间。", parent=dialog, default="no"):
                    return
                operation = lambda: self.controller.trash_session(sid)
            busy[0] = True
            message.configure(text="正在恢复记录…" if restore else "正在处理选中会话…", foreground=CYAN)
            update_buttons()
            def done(_):
                busy[0] = False
                if dialog.winfo_exists():
                    refresh()
            self._task(operation, done, failed)
        radios = []
        for label, value in (("历史记录", False), ("回收站", True)):
            radio = ttk.Radiobutton(toolbar, text=label, variable=recycle, value=value, command=refresh)
            radio.pack(side="left", padx=(0, 18))
            radios.append(radio)
        refresh_button = CachedTtkButton(toolbar, text="刷新", command=refresh, style="Quiet.TButton")
        refresh_button.pack(side="right")
        def open_classification():
            row = selected_row()
            if row is not None and not recycle.get() and not busy[0]:
                self.show_classification_details(session_id=str(row["session_id"]))
        classification_button = CachedTtkButton(toolbar, text="分类详情", command=open_classification, style="Quiet.TButton")
        classification_button.pack(side="left", padx=(12, 0))
        summary_button=CachedTtkButton(toolbar,text='测量总结',command=lambda:self.show_measurement_summary(selected_row()['session_id']) if selected_row() else None,style='Quiet.TButton')
        summary_button.pack(side='left',padx=(8,0))
        zip_button = CachedTtkButton(actions, text="完整 ZIP", command=export, style="Start.TButton")
        zip_button.grid(row=0, column=0, padx=(0, 6))
        csv_button = CachedTtkButton(actions, text="原始 CSV", command=lambda: export(False))
        csv_button.grid(row=0, column=1, padx=(0, 6))
        restore_button = CachedTtkButton(actions, text="恢复", command=lambda: mutate(True))
        restore_button.grid(row=0, column=2, padx=(0, 6))
        delete_button = CachedTtkButton(actions, text="移入回收站…", command=mutate, style="Stop.TButton")
        delete_button.grid(row=0, column=3)
        CachedTtkButton(actions, text="打开导出目录", command=self._open_export_directory, style="Quiet.TButton").grid(row=0, column=4, sticky="e")
        CachedTtkButton(actions, text="关闭", command=dialog.destroy, style="Quiet.TButton").grid(row=0, column=5)
        tree.bind("<<TreeviewSelect>>", selection_changed)
        def monitor():
            if dialog.winfo_exists():
                update_buttons()
                self.root.after(300, monitor)
        monitor()
        refresh()

    def show_device(self):
        if self._device_dialog is not None and self._device_dialog.winfo_exists():
            self._device_dialog.lift()
            return
        dialog = self._device_dialog = tk.Toplevel(self.root)
        dialog.title('设备与更多操作')
        dialog.configure(bg=BG)
        self._place_dialog(dialog, 650, 420)
        content = ttk.Frame(dialog, padding=18)
        content.pack(fill='both', expand=True)
        content.columnconfigure(1, weight=1)
        CachedTtkLabel(content, text='设备状态', foreground=GREEN, font=(self.family, 14, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        labels = []
        for row, title in enumerate(('采集模块', '数据接收', '信号质量', '本地存储'), 1):
            CachedTtkLabel(content, text=title, style='Muted.TLabel').grid(row=row, column=0, sticky='w', pady=5)
            label = CachedTtkLabel(content, text='', wraplength=455)
            label.grid(row=row, column=1, sticky='w', padx=(16, 0))
            labels.append(label)
        CachedTtkLabel(content, text='数据来源', style='Muted.TLabel').grid(row=5, column=0, sticky='w', pady=(12, 6))
        source = ttk.Combobox(content, textvariable=self.source, values=list(SOURCES), state='readonly', width=16)
        source.grid(row=5, column=1, sticky='w', padx=(16, 0), pady=(12, 6))
        source.bind('<<ComboboxSelected>>', self._update_controls)
        CachedTtkLabel(content, text='采集端口', style='Muted.TLabel').grid(row=6, column=0, sticky='w')
        ports = ttk.Combobox(content, textvariable=self.port, state='readonly', width=40)
        ports.grid(row=6, column=1, sticky='ew', padx=(16, 0))
        ports.bind('<<ComboboxSelected>>', self._port_selected)
        replay = CachedTtkButton(content, text='选择回放 CSV…', command=self.select_replay, style='Quiet.TButton')
        replay.grid(row=7, column=1, sticky='w', padx=(16, 0), pady=6)
        actions = ttk.Frame(content)
        actions.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        exit_button = CachedTtkButton(actions, text='退出到命令行', command=self.close, style='Quiet.TButton')
        exit_button.pack(side='left')
        shutdown_button = CachedTtkButton(actions, text='安全关机…', command=self.shutdown, style='Stop.TButton')
        shutdown_button.pack(side='left', padx=10)
        CachedTtkButton(actions, text='返回', command=dialog.destroy).pack(side='right')
        supported = poweroff_supported()
        if not supported:
            CachedTtkLabel(content, text='笔记本预览：关机按钮仅在树莓派上启用', style='Muted.TLabel').grid(row=9, column=0, columnspan=2, sticky='w', pady=8)
        def update():
            if self._closed or not dialog.winfo_exists():
                return
            snap = self._last_snapshot
            active = bool(snap.get('running')) or self._action_pending or self._closing
            source.configure(state='disabled' if active else 'readonly')
            ports.configure(values=self.port_combo['values'], state='disabled' if active or SOURCES[self.source.get()] != 'serial' else 'readonly')
            replay.configure(state='disabled' if active else 'normal')
            shutdown_button.configure(state='normal' if supported and not self._closing else 'disabled')
            exit_button.configure(state='disabled' if self._closing else 'normal')
            labels[0].configure(text=('已识别：' + self.port.get()) if self._port_available() else self._ports_message or '正在检查…')
            labels[1].configure(text=snap.get('connection_text') or '正在准备' if snap.get('running') else '未采集 · 点击开始后接收数据')
            labels[2].configure(text=snap.get('signal_text') or '等待判断' if snap.get('running') else '未检查 · 需要开始采集')
            storage = snap.get('storage') or {}
            labels[3].configure(text=(storage.get('detail') or '可用空间 ' + _size(storage.get('free_bytes'))),
                                foreground=AMBER if storage.get('state') in ('warning', 'critical') else FG)
            self.root.after(500, update)
        update()

    def shutdown(self):
        if self._closing:
            return
        if not poweroff_supported():
            messagebox.showinfo('设备关机', '关机仅在树莓派上可用，笔记本不会关机。', parent=self.root)
            return
        if not messagebox.askyesno('安全关机', '将停止采集、保存记录并结束后台传输，然后关闭树莓派。\n未完成的云端任务会保留，供下次继续。\n确认关机？', parent=self.root):
            return
        self._shutdown_requested = True
        self.close()

    def _cancel_close(self, error):
        self._closing = self._shutdown_requested = self._poweroff_pending = False
        self._close_started = None
        if self.cloud is not None and self._cloud_stopping:
            self._cloud_resume_pending = True
        self._cloud_stopping = False
        self.controller.initialize_environment()
        self._control_state = None
        self._update_controls()
        self.status_label.configure(text=str(error), foreground=RED)

    def _advance_close(self):
        if not self._closing or self._poweroff_pending:
            return
        snap = self._last_snapshot
        self.status_label.configure(text='正在停止、保存并结束后台操作…', foreground=AMBER)
        if self._pending_tasks or self._action_pending or snap.get('running') or snap.get('state') == 'STOPPING':
            return
        if not self.controller.wait(0):
            return
        problem = save_problem(snap) if self._shutdown_requested else None
        if problem:
            self._cancel_close(problem)
            messagebox.showerror('未关机，请检查记录', problem, parent=self.root)
            return
        if not self.controller.shutdown_environment(timeout=0):
            self.status_label.configure(text='正在结束时间与存储检查，请稍候…', foreground=AMBER)
            return
        if self.cloud is not None:
            if not self._cloud_stopping:
                self.cloud.close()
                self._cloud_stopping = True
                self._close_started = time.monotonic()
            if not self.cloud.wait(0):
                self.status_label.configure(text='正在结束云端传输，本地记录已保留…', foreground=AMBER)
                if time.monotonic() - self._close_started > 30:
                    self._cancel_close('后台传输尚未结束，已取消退出。请稍后重试。')
                    messagebox.showerror('后台任务未结束', '尚未关机，数据已保留，请稍后重试。', parent=self.root)
                return
        def finished(_=None):
            self._closed = True
            # Tcl timers outlive destroyed widgets unless explicitly cancelled.
            for callback in self.root.tk.call('after', 'info'):
                self.root.after_cancel(callback)
            self.root.destroy()
        if self._shutdown_requested:
            self._poweroff_pending = True
            self.status_label.configure(text='正在关闭树莓派，请等待关机完成…', foreground=AMBER)
            self._task(request_poweroff, finished, self._cancel_close)
        else:
            finished()

    def close(self):
        if self._closing:
            return
        self._cloud_resume_pending = False
        self._closing = True
        self._frozen_wave = None
        self._frozen_classification = None
        self.stop()
        self._update_controls()
