import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import subprocess
import json

def is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def app_dir() -> str:
    return os.path.dirname(sys.executable) if is_frozen() else os.path.dirname(os.path.abspath(__file__))

def exe_path(name: str) -> str:
    return os.path.join(app_dir(), name)

def file_exists_or_warn(path: str, title="Missing file"):
    if not os.path.exists(path):
        messagebox.showerror(title, f"Not found:\n{path}")
        return False
    return True

def user_preset_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "RTCorrector")
    d = os.path.dirname(sys.executable)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "user_presets.json")

def load_user_presets() -> dict:
    path = user_preset_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_user_presets(presets: dict) -> None:
    path = user_preset_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)

def smart_number(s: str):
    s = str(s).strip()
    if s == "":
        return s
    try:
        if any(ch in s for ch in (".", "e", "E")):
            return float(s)
        return int(s)
    except Exception:
        return s

class Tooltip:
    def __init__(self, widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tipwindow = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, event=None):
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            font=("Arial", 9),
            wraplength=360
        )
        label.pack(ipadx=6, ipady=4)

    def _hide(self, event=None):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None

# Presets
def config_sets():
    return {
        "default": {
            "datatype": "msdial",
            "calculate_summary_data": False,
            "linearfit": False,
            "linear_r": 0.6,
            "min_peak": 5000,
            "dbscan_rt": 0.4,
            "dbscan_rt2": 0.2,
            "dbscan_mz": 0.02,
            "dbscan_mz_ppm": 15,
            "rt_max": 45,
            "min_col": 10,
            "min_col2": 5,
            "min_feature_pair": 5,
            "n_bins": 500,
            "it": 3,
            "loess_frac": 0.1,
            "max_rt_diff": 0.5,
            "interpolate_p": 0.6,
        },
        "Halo96": {
            "datatype": "msdial",
            "calculate_summary_data": False,
            "linearfit": True,
            "linear_r": 0.6,
            "min_peak": 5000,
            "dbscan_rt": 0.4,
            "dbscan_rt2": 0.2,
            "dbscan_mz": 0.02,
            "dbscan_mz_ppm": 15,
            "rt_max": 45,
            "min_col": 10,
            "min_col2": 5,
            "min_feature_pair": 5,
            "n_bins": 500,
            "it": 3,
            "loess_frac": 0.1,
            "max_rt_diff": 1.2,
            "interpolate_p": 0.6,
            "input_dir": r"E:\Halo_lipidomic_zhang\featurelist",
            "output_dir": r"E:\Halo_lipidomic_zhang\GUItest",
        }
    }

PRESET_CONFIGS = config_sets()
PRESET_CONFIGS.update(load_user_presets())

class ScrollableFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._bind_mousewheel(self.canvas)

    def _on_inner_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _bind_mousewheel(self, widget):
        def _on_mousewheel(e):
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        widget.bind_all("<MouseWheel>", _on_mousewheel)

class BaseRunnerTab:
    def __init__(self, master, title: str, scrollable_form: bool = False):
        self.master = master
        self.title = title

        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        master.rowconfigure(1, weight=0)

        self.form_container = ttk.Frame(master)
        self.form_container.grid(row=0, column=0, sticky="nsew")

        if scrollable_form:
            self._scroll = ScrollableFrame(self.form_container)
            self._scroll.pack(fill="both", expand=True)
            self.form = self._scroll.inner
        else:
            self._scroll = None
            self.form = ttk.Frame(self.form_container)
            self.form.pack(fill="both", expand=True)

        for col, w in enumerate((0, 1, 0)):
            self.form.columnconfigure(col, weight=w)

        self._row = 0
        self._build_header(title)

        self.footer = ttk.Frame(master)
        self.footer.grid(row=1, column=0, sticky="ew")
        self.footer.columnconfigure(0, weight=1)

        self._footer_row = 0
        self.runbar = ttk.Frame(self.footer)
        self.runbar.grid(row=self._footer_row, column=0, sticky="ew", padx=5, pady=(6, 3))
        self.runbar.columnconfigure(0, weight=1)
        self._footer_row += 1

        self.cmd_preview = self._build_log_box(height=10)
        self._last_input_widget = None

    def _build_header(self, text: str):
        lbl = ttk.Label(self.form, text=text, font=("Arial", 10, "bold"))
        lbl.grid(row=self._row, column=0, columnspan=3, sticky="w", padx=5, pady=(5, 8))
        self._row += 1

    def add_dir_field(self, label: str, default=""):
        var = tk.StringVar(value=default)
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(self.form, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="we", padx=5, pady=5)
        ttk.Button(self.form, text="...", command=lambda: self._pick_dir(var)).grid(row=self._row, column=2, padx=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_file_field(self, label: str, filetypes, default=""):
        var = tk.StringVar(value=default)
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(self.form, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="we", padx=5, pady=5)
        ttk.Button(self.form, text="...", command=lambda: self._pick_file(var, filetypes)).grid(row=self._row, column=2, padx=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_text_field(self, label: str, default=""):
        var = tk.StringVar(value=str(default))
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(self.form, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="we", padx=5, pady=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_int_field(self, label: str, default=0):
        var = tk.IntVar(value=int(default))
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(self.form, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="w", padx=5, pady=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_choice_field(self, label: str, values, default=None, on_change=None):
        var = tk.StringVar(value=(default if default is not None else values[0]))
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        cb = ttk.Combobox(self.form, textvariable=var, values=list(values), state="readonly")
        cb.grid(row=self._row, column=1, sticky="w", padx=5, pady=5)
        if on_change is not None:
            cb.bind("<<ComboboxSelected>>", lambda e: on_change(var.get()))
        self._last_input_widget = cb
        self._row += 1
        return var

    def add_bool_radiobuttons(self, label: str, default="true"):
        var = tk.StringVar(value=default)
        ttk.Label(self.form, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        frm = ttk.Frame(self.form)
        frm.grid(row=self._row, column=1, sticky="w", padx=5, pady=5)
        ttk.Radiobutton(frm, text="true", variable=var, value="true").pack(side="left")
        ttk.Radiobutton(frm, text="false", variable=var, value="false").pack(side="left")
        self._last_input_widget = frm
        self._row += 1
        return var

    def add_hint(self, text: str):
        w = getattr(self, "_last_input_widget", None)
        if w is not None:
            Tooltip(w, text)

    def add_group_title(self, text: str):
        ttk.Label(self.form, text=text, font=("Arial", 9, "bold")).grid(
            row=self._row, column=0, columnspan=3, sticky="w", padx=5, pady=(10, 2)
        )
        self._row += 1

    def add_text_field_in(self, frame, label: str, default=""):
        var = tk.StringVar(value=str(default))
        ttk.Label(frame, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(frame, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="we", padx=5, pady=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_int_field_in(self, frame, label: str, default=0):
        var = tk.IntVar(value=int(default))
        ttk.Label(frame, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(frame, textvariable=var)
        ent.grid(row=self._row, column=1, sticky="w", padx=5, pady=5)
        self._last_input_widget = ent
        self._row += 1
        return var

    def add_choice_field_in(self, frame, label: str, values, default=None, on_change=None):
        var = tk.StringVar(value=(default if default is not None else values[0]))
        ttk.Label(frame, text=label).grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        cb = ttk.Combobox(frame, textvariable=var, values=list(values), state="readonly")
        cb.grid(row=self._row, column=1, sticky="w", padx=5, pady=5)
        if on_change is not None:
            cb.bind("<<ComboboxSelected>>", lambda e: on_change(var.get()))
        self._last_input_widget = cb
        self._row += 1
        return var

    def add_run_button(self, text: str, command):
        ttk.Button(self.runbar, text=text, command=command).grid(row=0, column=0, sticky="e")

    def _build_log_box(self, height=10):
        lf = ttk.Frame(self.footer)
        lf.grid(row=self._footer_row, column=0, sticky="nsew", padx=5, pady=(0, 6))
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)

        ybar = ttk.Scrollbar(lf, orient="vertical")
        txt = tk.Text(lf, height=height, yscrollcommand=ybar.set)
        ybar.config(command=txt.yview)

        txt.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")

        self._footer_row += 1
        return txt

    def log(self, text: str):
        self.cmd_preview.insert("end", text)
        self.cmd_preview.see("end")

    def set_log(self, text: str):
        self.cmd_preview.delete("1.0", "end")
        self.cmd_preview.insert("end", text)
        self.cmd_preview.see("end")

    def _pick_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def _pick_file(self, var, filetypes):
        p = filedialog.askopenfilename(filetypes=filetypes)
        if p:
            var.set(p)

    def run_command(self, cmd, ok_msg="Done"):
        self.set_log("Command:\n" + " ".join(cmd) + "\n\nRunning...\n")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        def append(text: str):
            self.cmd_preview.insert("end", text)
            self.cmd_preview.see("end")

        def worker():
            try:
                p = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )

                def pump(stream, tag):
                    for line in iter(stream.readline, ""):
                        if not line:
                            break
                        if tag == "stderr":
                            self.master.after(0, lambda s=line: append("[stderr] " + s))
                        else:
                            self.master.after(0, lambda s=line: append(s))
                    try:
                        stream.close()
                    except Exception:
                        pass

                t_out = threading.Thread(target=pump, args=(p.stdout, "stdout"), daemon=True)
                t_err = threading.Thread(target=pump, args=(p.stderr, "stderr"), daemon=True)
                t_out.start()
                t_err.start()

                code = p.wait()
                t_out.join(timeout=0.2)
                t_err.join(timeout=0.2)

                if code == 0:
                    self.master.after(0, lambda: append("\nDone.\n"))
                    self.master.after(0, lambda: messagebox.showinfo("Success", ok_msg))
                else:
                    self.master.after(0, lambda: append(f"\n[ERROR] Process exited with code {code}\n"))
                    self.master.after(0, lambda: messagebox.showerror("Error", f"Process failed (exit code {code}), see log."))

            except UnicodeDecodeError:
                try:
                    p = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        encoding=None,
                        errors="replace",
                        env=env,
                    )

                    def pump(stream, tag):
                        for line in iter(stream.readline, ""):
                            if not line:
                                break
                            if tag == "stderr":
                                self.master.after(0, lambda s=line: append("[stderr] " + s))
                            else:
                                self.master.after(0, lambda s=line: append(s))
                        try:
                            stream.close()
                        except Exception:
                            pass

                    t_out = threading.Thread(target=pump, args=(p.stdout, "stdout"), daemon=True)
                    t_err = threading.Thread(target=pump, args=(p.stderr, "stderr"), daemon=True)
                    t_out.start()
                    t_err.start()

                    code = p.wait()
                    if code == 0:
                        self.master.after(0, lambda: append("\nDone.\n"))
                        self.master.after(0, lambda: messagebox.showinfo("Success", ok_msg))
                    else:
                        self.master.after(0, lambda: append(f"\n[ERROR] Process exited with code {code}\n"))
                        self.master.after(0, lambda: messagebox.showerror("Error", f"Process failed (exit code {code}), see log."))
                except Exception as e2:
                    self.master.after(0, lambda: append(f"\n[Exception]\n{repr(e2)}\n"))
                    self.master.after(0, lambda: messagebox.showerror("Error", repr(e2)))

            except Exception as e:
                self.master.after(0, lambda: append(f"\n[Exception]\n{repr(e)}\n"))
                self.master.after(0, lambda: messagebox.showerror("Error", repr(e)))

        threading.Thread(target=worker, daemon=True).start()

class RTCorrectionApp(BaseRunnerTab):
    def __init__(self, master):
        super().__init__(master, "RT Corrector model training", scrollable_form=True)

        ttk.Label(self.form, text="Preset config:").grid(row=self._row, column=0, sticky="w", padx=5, pady=5)
        presets = list(PRESET_CONFIGS.keys())
        self.preset_var = tk.StringVar(value=presets[0] if presets else "")
        self.preset_cb = ttk.Combobox(self.form, textvariable=self.preset_var, values=presets, state="readonly")
        self.preset_cb.grid(row=self._row, column=1, columnspan=2, sticky="we", padx=5, pady=5)
        self.preset_cb.bind("<<ComboboxSelected>>", lambda e: self.load_preset())
        self._row += 1

        self.add_group_title("Basic setting")
        self.datatype = self.add_choice_field(
            "datatype:",
            values=["msdial", "mzmine", "tsv", "csv"],
            default="msdial",
            on_change=self.on_datatype_change,
        )

        self.calculate_summary_data = self.add_bool_radiobuttons("calculate_summary_data:", default="false")
        self.add_hint(
            "If True, feature list collection is re-run even if previous results exist; if False, existing results are used.")

        self.min_peak = self.add_text_field("min_peak:", default="5000")
        self.add_hint("Minimum intensity of features to be involved.")

        self.rt_max = self.add_text_field("rt_max (min):", default="45")
        self.add_hint("Maximum retention time of the samples.")

        self.input_dir = self.add_dir_field("input_dir:")
        self.output_dir = self.add_dir_field("output_dir:")
        self._row += 1

        self.tsv_frame = ttk.Frame(self.form)
        self.tsv_frame.grid(row=self._row, column=0, columnspan=3, sticky="we")
        self._row += 1
        self._build_tsv_group(self.tsv_frame)

        self.add_group_title("DBSCAN")

        self.dbscan_rt = self.add_text_field("dbscan_rt (min):", default="0.4")
        self.add_hint("DBSCAN RT threshold for 1st round correction")

        self.dbscan_rt2 = self.add_text_field("dbscan_rt_2 (min):", default="0.2")
        self.add_hint("DBSCAN RT threshold for 2nd round correction")

        self.dbscan_mz = self.add_text_field("dbscan_mz:", default="0.02")
        self.add_hint("DBSCAN absolute m/z threshold")

        self.dbscan_mz_ppm = self.add_text_field("dbscan_mz_ppm:", default="15")
        self.add_hint("DBSCAN m/z ppm threshold")

        self.add_group_title("Feature filter")
        self.linearfit = self.add_bool_radiobuttons("linear_fit:", default="false")
        self.add_hint("This function enables linear modeling of RT values as a function of sample order and filters features accordingly,"
                      "recommended for one batch RT shifts in which RTs continuously shift forward or backward across samples")

        self.linear_r = self.add_text_field("linear_r:", default="0.6")
        self.add_hint("r threshold for linear fit")

        self.max_rt_diff = self.add_text_field("max_rt_diff:", default="0.5")
        self.add_hint("Maximum RT shifts observed (compared to medium value)")

        self.min_col = self.add_text_field("min_sample:", default="10")
        self.add_hint("Minimum number of samples in which a feature should be present.")

        self.min_col2 = self.add_text_field("min_sample_2:", default="5")
        self.add_hint("Minimum number of samples in which a feature should be present. This parameter is intended for edge RT regions with fewer features.")

        self.min_feature_pair = self.add_text_field("min_feature_group:", default="5")
        self.add_hint("Minimum number of features required a sample")

        self.n_bins = self.add_text_field("n_bins:", default="500")
        self.add_hint("Number of bins used for grouping final features.")

        self.add_group_title("Loess fit")
        self.it = self.add_text_field("iteration:", default="3")
        self.add_hint("Number of iterations used for the LOESS fitting.")

        self.loess_frac = self.add_text_field("loess_frac:", default="0.1")
        self.add_hint("Fraction of data points used for local LOESS fitting (0-1). Higher values produce smoother curve.")

        self.add_group_title("Interpolate")
        self.interpolate_p = self.add_text_field("interpolate_p:", default="0.6")
        self.add_hint("Controls interpolation strictness: higher values are more strict.")

        ttk.Button(self.runbar, text="Save preset", command=self.save_current_preset).grid(row=0, column=0, sticky="w")
        ttk.Button(self.runbar, text="Run", command=self.run).grid(row=0, column=1, sticky="e")
        self.runbar.columnconfigure(0, weight=0)
        self.runbar.columnconfigure(1, weight=1)

        self.load_preset()
        self.on_datatype_change(self.datatype.get())

    def _build_tsv_group(self, frame: ttk.Frame):
        frame.columnconfigure(0, weight=0)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=0)

        ttk.Label(frame, text="TSV/CSV Columns", font=("Arial", 9, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=5, pady=(10, 2)
        )

        r = 1

        self.id_col = tk.IntVar(value=1)
        ttk.Label(frame, text="id_col:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(frame, textvariable=self.id_col)
        ent.grid(row=r, column=1, sticky="w", padx=5, pady=5)
        Tooltip(ent, "Column index starts from 0")
        r += 1

        self.rt_col = tk.IntVar(value=2)
        ttk.Label(frame, text="rt_col:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.rt_col).grid(row=r, column=1, sticky="w", padx=5, pady=5)
        r += 1

        self.mz_col = tk.IntVar(value=3)
        ttk.Label(frame, text="mz_col:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.mz_col).grid(row=r, column=1, sticky="w", padx=5, pady=5)
        r += 1

        self.intensity_col = tk.IntVar(value=4)
        ttk.Label(frame, text="intensity_col:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.intensity_col).grid(row=r, column=1, sticky="w", padx=5, pady=5)
        r += 1

        self.file_ext = tk.StringVar(value=".csv")
        ttk.Label(frame, text="file_ext:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        ent = ttk.Entry(frame, textvariable=self.file_ext)
        ent.grid(row=r, column=1, sticky="w", padx=5, pady=5)
        Tooltip(ent, "File extension of the feature list")
        r += 1

        self.time_format = tk.StringVar(value="min")
        ttk.Label(frame, text="time_format:").grid(row=r, column=0, sticky="w", padx=5, pady=5)
        cb = ttk.Combobox(frame, textvariable=self.time_format, values=["min", "sec"], state="readonly")
        cb.grid(row=r, column=1, sticky="w", padx=5, pady=5)
        Tooltip(cb, "RT unit in the input file")

    def on_datatype_change(self, datatype_value: str):
        show = datatype_value in ("tsv", "csv")
        if show:
            self.tsv_frame.grid()
        else:
            self.tsv_frame.grid_remove()

    def get_current_config(self) -> dict:
        cfg = {
            "datatype": self.datatype.get(),
            "calculate_summary_data": (self.calculate_summary_data.get() == "true"),
            "linearfit": (self.linearfit.get() == "true"),

            "linear_r": smart_number(self.linear_r.get()),
            "min_peak": smart_number(self.min_peak.get()),
            "rt_max": smart_number(self.rt_max.get()),

            "dbscan_rt": smart_number(self.dbscan_rt.get()),
            "dbscan_rt2": smart_number(self.dbscan_rt2.get()),
            "dbscan_mz": smart_number(self.dbscan_mz.get()),
            "dbscan_mz_ppm": smart_number(self.dbscan_mz_ppm.get()),

            "min_col": smart_number(self.min_col.get()),
            "min_col2": smart_number(self.min_col2.get()),
            "min_feature_pair": smart_number(self.min_feature_pair.get()),
            "n_bins": smart_number(self.n_bins.get()),
            "max_rt_diff": smart_number(self.max_rt_diff.get()),

            "it": smart_number(self.it.get()),
            "loess_frac": smart_number(self.loess_frac.get()),
            "interpolate_p": smart_number(self.interpolate_p.get()),

            "input_dir": self.input_dir.get().strip(),
            "output_dir": self.output_dir.get().strip(),

            "id_col": int(self.id_col.get()),
            "rt_col": int(self.rt_col.get()),
            "mz_col": int(self.mz_col.get()),
            "intensity_col": int(self.intensity_col.get()),
            "file_ext": self.file_ext.get().strip(),
            "time_format": self.time_format.get(),
        }
        return cfg

    def save_current_preset(self):
        name = simpledialog.askstring("Save preset", "Preset name:")
        if not name:
            return
        name = name.strip()
        if not name:
            return

        user_presets = load_user_presets()

        if name in PRESET_CONFIGS:
            ok = messagebox.askyesno("Overwrite?", f'Preset "{name}" already exists. Overwrite?')
            if not ok:
                return

        cfg = self.get_current_config()
        user_presets[name] = cfg
        save_user_presets(user_presets)

        PRESET_CONFIGS[name] = cfg

        presets = list(PRESET_CONFIGS.keys())
        try:
            self.preset_cb.configure(values=presets)
        except Exception:
            pass

        self.preset_var.set(name)
        messagebox.showinfo("Saved", f'Preset "{name}" saved.')

    def load_preset(self):
        cfg = PRESET_CONFIGS.get(self.preset_var.get(), {})

        if "datatype" in cfg:
            self.datatype.set(str(cfg["datatype"]))
        if "calculate_summary_data" in cfg:
            self.calculate_summary_data.set("true" if cfg["calculate_summary_data"] else "false")
        if "linearfit" in cfg:
            self.linearfit.set("true" if cfg["linearfit"] else "false")

        for key, var in [
            ("linear_r", self.linear_r),
            ("min_peak", self.min_peak),
            ("rt_max", self.rt_max),
            ("dbscan_rt", self.dbscan_rt),
            ("dbscan_rt2", self.dbscan_rt2),
            ("dbscan_mz", self.dbscan_mz),
            ("dbscan_mz_ppm", self.dbscan_mz_ppm),
            ("min_col", self.min_col),
            ("min_col2", self.min_col2),
            ("min_feature_pair", self.min_feature_pair),
            ("n_bins", self.n_bins),
            ("max_rt_diff", self.max_rt_diff),
            ("it", self.it),
            ("loess_frac", self.loess_frac),
            ("interpolate_p", self.interpolate_p),
        ]:
            if key in cfg:
                var.set(str(cfg[key]))

        if "input_dir" in cfg:
            self.input_dir.set(str(cfg["input_dir"]))
        if "output_dir" in cfg:
            self.output_dir.set(str(cfg["output_dir"]))
        if "id_col" in cfg:
            self.id_col.set(int(cfg["id_col"]))
        if "rt_col" in cfg:
            self.rt_col.set(int(cfg["rt_col"]))
        if "mz_col" in cfg:
            self.mz_col.set(int(cfg["mz_col"]))
        if "intensity_col" in cfg:
            self.intensity_col.set(int(cfg["intensity_col"]))
        if "file_ext" in cfg:
            self.file_ext.set(str(cfg["file_ext"]))
        if "time_format" in cfg:
            self.time_format.set(str(cfg["time_format"]))

        self.on_datatype_change(self.datatype.get())

    def run(self):
        exe = exe_path("mzml_model_trainer.exe")
        if not file_exists_or_warn(exe, "Trainer executable missing"):
            return

        if not self.input_dir.get().strip() or not self.output_dir.get().strip():
            messagebox.showerror("Error", "Please fill input_dir / output_dir.")
            return

        cmd = [
            exe,
            f"--datatype={self.datatype.get()}",
            f"--calculate_summary_data={self.calculate_summary_data.get()}",
            f"--linearfit={self.linearfit.get()}",
            f"--linear_r={self.linear_r.get().strip()}",
            f"--min_peak={self.min_peak.get().strip()}",
            f"--rt_max={self.rt_max.get().strip()}",
            f"--input_dir={self.input_dir.get().strip()}",
            f"--output_dir={self.output_dir.get().strip()}",
            f"--dbscan_rt={self.dbscan_rt.get().strip()}",
            f"--dbscan_rt2={self.dbscan_rt2.get().strip()}",
            f"--dbscan_mz={self.dbscan_mz.get().strip()}",
            f"--dbscan_mz_ppm={self.dbscan_mz_ppm.get().strip()}",
            f"--min_col={self.min_col.get().strip()}",
            f"--min_col2={self.min_col2.get().strip()}",
            f"--min_feature_pair={self.min_feature_pair.get().strip()}",
            f"--n_bins={self.n_bins.get().strip()}",
            f"--max_rt_diff={self.max_rt_diff.get().strip()}",
            f"--it={self.it.get().strip()}",
            f"--loess_frac={self.loess_frac.get().strip()}",
            f"--interpolate_p={self.interpolate_p.get().strip()}",
        ]

        if self.datatype.get() in ("tsv", "csv"):
            cmd += [
                f"--id_col={int(self.id_col.get())}",
                f"--rt_col={int(self.rt_col.get())}",
                f"--mz_col={int(self.mz_col.get())}",
                f"--intensity_col={int(self.intensity_col.get())}",
                f"--time_format={self.time_format.get()}",
                f"--file_ext={self.file_ext.get()}"
            ]

        self.run_command(cmd, ok_msg="Trainer finished.")

class MzmlCorrectionApp(BaseRunnerTab):
    def __init__(self, master):
        super().__init__(master, "Apply model to .mzml", scrollable_form=False)

        self.mzml_dir = self.add_dir_field("mzml_dir:", default="E:/Halo_lipidomic_zhang/mzml")
        self.out_dir = self.add_dir_field("out_dir:", default="E:/Halo_lipidomic_zhang/corrected")
        self.model_path = self.add_file_field("model_path (.pkl):", [("Pickle model", "*.pkl"), ("All files", "*.*")], default="E:/Halo_lipidomic_zhang/GUItest/rt_correction_models.pkl")

        self.suffix = self.add_text_field("model suffix:", default="")
        self.add_hint('Suffix used to link model training files to raw data, e.g., "abc.csv" → "abc.mzML".')

        self.n_workers = self.add_int_field("n_workers:", default=16)
        self.add_hint("CPU number")

        self.add_run_button("Run", self.run)

    def run(self):
        exe = exe_path("mzml_correction.exe")
        if not file_exists_or_warn(exe, "mzml_correction executable missing"):
            return

        mzml_dir = self.mzml_dir.get().strip()
        out_dir = self.out_dir.get().strip()
        model_path = self.model_path.get().strip()
        if not (mzml_dir and out_dir and model_path):
            messagebox.showerror("Error", "Please fill mzml_dir / out_dir / model_path.")
            return

        cmd = [
            exe,
            f"--mzml_dir={mzml_dir}",
            f"--out_dir={out_dir}",
            f"--model_path={model_path}",
            f"--processes={int(self.n_workers.get())}",
            f"--suffix={self.suffix.get().strip()}",
        ]
        self.run_command(cmd, ok_msg="mzML correction finished.")

class ApplyModelFeaturelistApp(BaseRunnerTab):
    def __init__(self, master):
        super().__init__(master, "Apply model to feature lists", scrollable_form=False)

        self.featurelist_dir = self.add_dir_field("featurelist_dir:", default="E:/Halo_lipidomic_zhang/featurelist")
        self.model_path = self.add_file_field("model_path (.pkl):", [("Pickle model", "*.pkl"), ("All files", "*.*")], default="E:/Halo_lipidomic_zhang/GUItest/rt_correction_models.pkl")
        self.output_dir = self.add_dir_field("output_dir:", default="E:/Halo_lipidomic_zhang/corrected")

        self.rt_columns = self.add_text_field("rt_columns (comma):", default="RT (min)")
        self.add_hint("Use comma separate if there is multiple RT columns")

        self.input_suffix = self.add_text_field("input_suffix:", default="")
        self.add_hint("Suffix of feature list files")

        self.model_suffix = self.add_text_field("model_suffix:", default="")
        self.add_hint('Suffix used in model training files')

        self.rt_unit = self.add_choice_field("rt_unit:", values=["min", "sec"], default="min")

        self.overwrite = self.add_bool_radiobuttons("overwrite_original:", default="true")
        self.add_hint("Overwrite original RT values when True; keep originals when False.")

        self.n_workers = self.add_int_field("n_workers:", default=max(1, (os.cpu_count() or 2) - 1))
        self.add_hint("CPU numbers")

        self.round_digits = self.add_int_field("round_digits:", default=4)

        self.add_run_button("Run", self.run)

    def run(self):
        exe = exe_path("apply_model_featurelist.exe")
        if not file_exists_or_warn(exe, "apply_model_featurelist executable missing"):
            return

        featurelist_dir = self.featurelist_dir.get().strip()
        model_path = self.model_path.get().strip()
        output_dir = self.output_dir.get().strip()
        if not (featurelist_dir and model_path and output_dir):
            messagebox.showerror("Error", "Please fill featurelist_dir / model_path / output_dir.")
            return

        cmd = [
            exe,
            f"--featurelist_dir={featurelist_dir}",
            f"--model_path={model_path}",
            f"--output_dir={output_dir}",
            f"--rt_columns={self.rt_columns.get().strip()}",
            f"--overwrite_original={self.overwrite.get().strip()}",
            f"--n_workers={int(self.n_workers.get())}",
            f"--rt_unit={self.rt_unit.get().strip()}",
            f"--round_digits={int(self.round_digits.get())}",
            f"--input_suffix={self.input_suffix.get().strip()}",
            f"--model_suffix={self.model_suffix.get().strip()}",
        ]
        self.run_command(cmd, ok_msg="Featurelist correction finished.")

def main():
    root = tk.Tk()
    root.title("RT corrector")

    icon_path = os.path.join(app_dir(), "logo.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    tab1 = ttk.Frame(notebook)
    notebook.add(tab1, text="RT Corrector model training")
    RTCorrectionApp(tab1)

    tab2 = ttk.Frame(notebook)
    notebook.add(tab2, text="Apply model to .mzML")
    MzmlCorrectionApp(tab2)

    tab3 = ttk.Frame(notebook)
    notebook.add(tab3, text="Apply model to feature lists")
    ApplyModelFeaturelistApp(tab3)

    root.mainloop()

if __name__ == "__main__":
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass
    main()
