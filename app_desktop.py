"""
PPS Ocular Findings / GI Chart Review — desktop data entry app (Tkinter).

Same idea as app.py (Streamlit version), but as a plain desktop app with
no external dependencies — only the Python standard library (tkinter,
csv). Good for machines where installing Streamlit/pip packages isn't
convenient.

The form is generated automatically from the REDCap data dictionary
(data/data_dictionary.csv), and every saved record is written in the
exact column layout of the REDCap import template
(data/import_template.csv), so the export CSV can be uploaded directly
into REDCap via "Data Import Tool".

Run with:
    python3 app_desktop.py

(On Linux, Tkinter may need to be installed separately, e.g.
`sudo apt install python3-tk`. It ships built-in on Windows and macOS
python.org installers.)
"""

import csv
import os
import re
import sys
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DICT_PATH = os.path.join(BASE_DIR, "data", "data_dictionary.csv")
TEMPLATE_PATH = os.path.join(BASE_DIR, "data", "import_template.csv")
DATA_PATH = os.path.join(BASE_DIR, "data", "chart_review_data.csv")

FORM_LABELS = {
    "screening_demographics": "Screening & Demographics",
    "medication_information": "PPS / Medication History",
    "colonoscopy_genetic": "Colonoscopy & Genetic Testing",
    "ophtho_index": "Ophthalmology Visit — Index",
    "last_visit": "Last Available Visit",
    "oct_image_analysis": "Multimodal Image Analysis",
}
FORM_ORDER = list(FORM_LABELS.keys())

COMPLETE_CHOICES = [("0", "Incomplete"), ("1", "Unverified"), ("2", "Complete")]

FIELD_REF_RE = re.compile(r"\[(\w+)(?:\((\w+)\))?\]")
COND_RE = re.compile(r"\[(\w+)(?:\((\w+)\))?\]\s*(=|<>)\s*'([^']*)'")


# --------------------------------------------------------------------------
# Data dictionary / template loading
# --------------------------------------------------------------------------

def load_dictionary():
    with open(DICT_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fields = []
    for r in rows:
        name = (r.get("Variable / Field Name") or "").strip()
        if not name:
            continue
        fields.append(
            {
                "name": name,
                "form": (r.get("Form Name") or "").strip(),
                "section": (r.get("Section Header") or "").strip(),
                "type": (r.get("Field Type") or "").strip(),
                "label": (r.get("Field Label") or "").strip(),
                "choices_raw": (r.get("Choices, Calculations, OR Slider Labels") or "").strip(),
                "note": (r.get("Field Note") or "").strip(),
                "validation": (r.get("Text Validation Type OR Show Slider Number") or "").strip(),
                "vmin": (r.get("Text Validation Min") or "").strip(),
                "vmax": (r.get("Text Validation Max") or "").strip(),
                "branching": (r.get("Branching Logic (Show field only if...)") or "").strip(),
            }
        )
    return fields


def load_template_columns():
    with open(TEMPLATE_PATH, newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    return [c for c in header if c.strip() != ""]


def parse_choices(raw):
    """'1, Male | 2, Female' -> [('1','Male'), ('2','Female')]"""
    out = []
    if not raw:
        return out
    for part in raw.split("|"):
        part = part.strip()
        if not part:
            continue
        code, _, label = part.partition(",")
        out.append((code.strip(), label.strip()))
    return out


# --------------------------------------------------------------------------
# Scrollable frame helper
# --------------------------------------------------------------------------

class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.configure(yscrollcommand=vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self._win, width=event.width)

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _unbind_wheel(self, _):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(3, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class ChartReviewApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PPS Ocular Findings & GI — Chart Review (Desktop)")
        self.root.geometry("1200x800")

        self.fields = load_dictionary()
        self.field_by_name = {f["name"]: f for f in self.fields}
        self.template_cols = load_template_columns()

        self.vars = {}         # field name -> tk.StringVar (text/radio/dropdown/yesno)
        self.cb_vars = {}      # field name -> {code: tk.BooleanVar}
        self.text_widgets = {} # field name -> tk.Text (notes)
        self.label_maps = {}   # field name -> {label: code}  (radio/dropdown)
        self.containers = {}   # field name -> frame to show/hide
        self.dependents = {}   # trigger field name -> set(dependent field names)
        self.complete_vars = {}

        self.records = self.load_records()  # record_id -> row dict
        self.current_record_id = None
        self._suspend_trace = False

        self._build_ui()
        self._refresh_record_list()
        self.new_record()

    # ---------------- Persistence ----------------

    def load_records(self):
        records = {}
        if os.path.exists(DATA_PATH):
            with open(DATA_PATH, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rid = row.get("record_id", "")
                    if rid:
                        records[rid] = row
        return records

    def save_all_records(self):
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        with open(DATA_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.template_cols, extrasaction="ignore")
            writer.writeheader()
            for rid, row in self.records.items():
                writer.writerow({c: row.get(c, "") for c in self.template_cols})

    # ---------------- UI scaffolding ----------------

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(side="top", fill="x")

        ttk.Label(top, text="Record:").pack(side="left")
        self.record_combo = ttk.Combobox(top, state="readonly", width=40)
        self.record_combo.pack(side="left", padx=(4, 12))
        self.record_combo.bind("<<ComboboxSelected>>", self._on_record_selected)

        ttk.Button(top, text="New record", command=self.new_record).pack(side="left", padx=4)
        ttk.Button(top, text="Delete record", command=self.delete_record).pack(side="left", padx=4)

        ttk.Label(top, text="MRN:").pack(side="left", padx=(20, 4))
        self.mrn_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.mrn_var, width=20).pack(side="left")

        ttk.Button(top, text="Save record", command=self.save_record).pack(side="right", padx=4)
        ttk.Button(top, text="Open data folder", command=self.open_data_folder).pack(side="right", padx=4)

        self.study_id_label = ttk.Label(self.root, text="", font=("TkDefaultFont", 12, "bold"))
        self.study_id_label.pack(side="top", anchor="w", padx=8)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side="top", fill="both", expand=True, padx=8, pady=8)

        self.tab_scrollframes = {}
        for form_name in FORM_ORDER:
            sf = ScrollableFrame(self.notebook)
            self.notebook.add(sf, text=FORM_LABELS[form_name])
            self.tab_scrollframes[form_name] = sf
            self._build_form(sf.inner, form_name)

        self.status_var = tk.StringVar(value=f"{len(self.records)} record(s) saved.")
        ttk.Label(self.root, textvariable=self.status_var, padding=6).pack(side="bottom", fill="x")

    def _build_form(self, parent, form_name):
        by_section = []
        current_section = None
        bucket = []
        for f in self.fields:
            if f["form"] != form_name or f["name"] in ("record_id", "mrn"):
                continue
            if f["section"] and f["section"] != current_section:
                if bucket:
                    by_section.append((current_section, bucket))
                current_section = f["section"]
                bucket = [f]
            else:
                if current_section is None:
                    current_section = ""
                bucket.append(f)
        if bucket:
            by_section.append((current_section, bucket))

        for section, sec_fields in by_section:
            if section:
                box = ttk.LabelFrame(parent, text=section, padding=8)
            else:
                box = ttk.Frame(parent, padding=(8, 4))
            box.pack(fill="x", padx=6, pady=6, anchor="n")
            box.columnconfigure(0, weight=1)
            for row, f in enumerate(sec_fields):
                self._render_field(box, f, row)

        status_frame = ttk.Frame(parent, padding=8)
        status_frame.pack(fill="x", padx=6, pady=(10, 20))
        ttk.Label(status_frame, text="Form status:", font=("TkDefaultFont", 9, "bold")).pack(side="left")
        var = tk.StringVar(value="0")
        self.complete_vars[form_name] = var
        combo = ttk.Combobox(
            status_frame, state="readonly", width=15,
            values=[label for _, label in COMPLETE_CHOICES],
        )
        combo.current(0)

        def on_status_change(event, var=var, combo=combo):
            code = dict((label, code) for code, label in COMPLETE_CHOICES)[combo.get()]
            var.set(code)

        combo.bind("<<ComboboxSelected>>", on_status_change)
        combo.pack(side="left", padx=6)
        self._status_combos = getattr(self, "_status_combos", {})
        self._status_combos[form_name] = combo

    # ---------------- Field rendering ----------------

    def _register_dependency(self, field):
        for trigger, _code in FIELD_REF_RE.findall(field["branching"] or ""):
            self.dependents.setdefault(trigger, set()).add(field["name"])

    def _render_field(self, parent, field, row):
        name = field["name"]
        ftype = field["type"]
        label_text = field["label"] or name

        if ftype == "calc":
            return  # calculated by REDCap, never entered manually

        self._register_dependency(field)

        container = ttk.Frame(parent, padding=(2, 4))
        container.grid(row=row, column=0, sticky="ew", pady=2)
        self.containers[name] = container

        if ftype == "checkbox":
            ttk.Label(container, text=label_text, wraplength=850, justify="left").pack(anchor="w")
            choices = parse_choices(field["choices_raw"])
            grid = ttk.Frame(container)
            grid.pack(fill="x", padx=(16, 0))
            self.cb_vars[name] = {}
            for i, (code, clabel) in enumerate(choices):
                var = tk.BooleanVar(value=False)
                self.cb_vars[name][code] = var
                cb = ttk.Checkbutton(grid, text=clabel, variable=var,
                                      command=lambda n=name: self._on_change(n))
                cb.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)

        elif ftype in ("radio", "dropdown"):
            row = ttk.Frame(container)
            row.pack(fill="x", anchor="w")
            ttk.Label(row, text=label_text, wraplength=350, justify="left").pack(side="left")
            choices = parse_choices(field["choices_raw"])
            labels = ["— Not entered —"] + [c for _, c in choices]
            self.label_maps[name] = {"— Not entered —": ""}
            self.label_maps[name].update({clabel: code for code, clabel in choices})
            var = tk.StringVar(value="")
            self.vars[name] = var
            combo = ttk.Combobox(row, state="readonly", width=45, values=labels)
            combo.current(0)
            combo.pack(side="left", padx=8)

            def on_pick(event, name=name, combo=combo):
                code = self.label_maps[name].get(combo.get(), "")
                self.vars[name].set(code)
                self._on_change(name)

            combo.bind("<<ComboboxSelected>>", on_pick)
            self._combo_widgets = getattr(self, "_combo_widgets", {})
            self._combo_widgets[name] = combo

        elif ftype == "yesno":
            row = ttk.Frame(container)
            row.pack(fill="x", anchor="w")
            ttk.Label(row, text=label_text, wraplength=350, justify="left").pack(side="left")
            var = tk.StringVar(value="")
            self.vars[name] = var
            ttk.Radiobutton(row, text="Yes", value="1", variable=var,
                             command=lambda n=name: self._on_change(n)).pack(side="left", padx=6)
            ttk.Radiobutton(row, text="No", value="0", variable=var,
                             command=lambda n=name: self._on_change(n)).pack(side="left")

        elif ftype == "notes":
            ttk.Label(container, text=label_text, wraplength=850, justify="left").pack(anchor="w")
            txt = tk.Text(container, height=3, width=90, wrap="word")
            txt.pack(fill="x", padx=(16, 0), pady=(2, 0))
            self.text_widgets[name] = txt

        else:  # plain text (dates, numbers, free text)
            row = ttk.Frame(container)
            row.pack(fill="x", anchor="w")
            hint = ""
            if field["validation"] == "date_mdy":
                hint = "  (MM/DD/YYYY)"
            elif field["validation"] in ("number", "integer"):
                rng = ""
                if field["vmin"] or field["vmax"]:
                    rng = f" [{field['vmin'] or '?'}-{field['vmax'] or '?'}]"
                hint = f"  ({field['validation']}{rng})"
            ttk.Label(row, text=label_text + hint, wraplength=450, justify="left").pack(side="left")
            var = tk.StringVar(value="")
            self.vars[name] = var
            ttk.Entry(row, textvariable=var, width=30).pack(side="left", padx=8)

        if field["note"]:
            ttk.Label(container, text=field["note"], wraplength=850, justify="left",
                      foreground="#666666", font=("TkDefaultFont", 8)).pack(anchor="w", padx=(16, 0))

        self._eval_visibility(name)

    # ---------------- Branching logic ----------------

    def _get_value(self, field_name, code=None):
        if code is not None:
            return "1" if self.cb_vars.get(field_name, {}).get(code, tk.BooleanVar()).get() else "0"
        if field_name in self.vars:
            return self.vars[field_name].get()
        return ""

    def _eval_branching(self, logic):
        if not logic:
            return True

        def repl(m):
            field, code, op, val = m.groups()
            actual = self._get_value(field, code)
            result = (str(actual) == val)
            if op == "<>":
                result = not result
            return "True" if result else "False"

        expr = COND_RE.sub(repl, logic)
        try:
            return bool(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return True

    def _eval_visibility(self, field_name):
        field = self.field_by_name.get(field_name)
        container = self.containers.get(field_name)
        if not field or container is None:
            return
        if self._eval_branching(field["branching"]):
            container.grid()
        else:
            container.grid_remove()

    def _on_change(self, field_name):
        if self._suspend_trace:
            return
        for dependent in self.dependents.get(field_name, ()):
            self._eval_visibility(dependent)

    # ---------------- Record list / selection ----------------

    def _refresh_record_list(self):
        ids = sorted(self.records.keys(), key=lambda x: (len(x), x))
        display = []
        self._record_display_to_id = {}
        new_label = "+ New record"
        display.append(new_label)
        self._record_display_to_id[new_label] = "__new__"
        for rid in ids:
            mrn = self.records[rid].get("mrn", "")
            label = f"Record {rid}" + (f" (MRN {mrn})" if mrn else "")
            display.append(label)
            self._record_display_to_id[label] = rid
        self.record_combo["values"] = display

    def _next_record_id(self):
        nums = [int(r) for r in self.records if r.isdigit()]
        return str(max(nums, default=0) + 1)

    def _on_record_selected(self, event):
        label = self.record_combo.get()
        rid = self._record_display_to_id.get(label, "__new__")
        if rid == "__new__":
            self.new_record()
        else:
            self.load_record(rid)

    def new_record(self):
        self.current_record_id = self._next_record_id()
        self._clear_form()
        self.study_id_label.config(text=f"Study ID: {self.current_record_id}  (new record)")
        self.record_combo.set("+ New record")

    def load_record(self, rid):
        row = self.records.get(rid)
        if row is None:
            return
        self.current_record_id = rid
        self._suspend_trace = True
        self._clear_form(reset_status=False)
        self.mrn_var.set(row.get("mrn", ""))
        for f in self.fields:
            name = f["name"]
            ftype = f["type"]
            if name in ("record_id", "mrn") or ftype == "calc":
                continue
            if ftype == "checkbox":
                choices = parse_choices(f["choices_raw"])
                for code, _ in choices:
                    val = row.get(f"{name}___{code}", "") == "1"
                    if name in self.cb_vars and code in self.cb_vars[name]:
                        self.cb_vars[name][code].set(val)
            elif ftype == "notes":
                if name in self.text_widgets:
                    self.text_widgets[name].delete("1.0", "end")
                    self.text_widgets[name].insert("1.0", row.get(name, ""))
            else:
                val = row.get(name, "")
                if name in self.vars:
                    self.vars[name].set(val)
                if name in getattr(self, "_combo_widgets", {}):
                    inv = {v: k for k, v in self.label_maps[name].items()}
                    self._combo_widgets[name].set(inv.get(val, "— Not entered —"))
        for form_name in FORM_ORDER:
            code = row.get(f"{form_name}_complete", "0") or "0"
            self.complete_vars[form_name].set(code)
            label = dict(COMPLETE_CHOICES).get(code, "Incomplete")
            self._status_combos[form_name].set(label)
        self._suspend_trace = False
        for name in list(self.field_by_name.keys()):
            self._eval_visibility(name)
        self.study_id_label.config(text=f"Study ID: {rid}")
        label = f"Record {rid}" + (f" (MRN {row.get('mrn','')})" if row.get("mrn") else "")
        self.record_combo.set(label)

    def _clear_form(self, reset_status=True):
        self._suspend_trace = True
        self.mrn_var.set("")
        for var in self.vars.values():
            var.set("")
        for name, combo in getattr(self, "_combo_widgets", {}).items():
            combo.current(0)
        for cb_map in self.cb_vars.values():
            for var in cb_map.values():
                var.set(False)
        for txt in self.text_widgets.values():
            txt.delete("1.0", "end")
        if reset_status:
            for form_name in FORM_ORDER:
                self.complete_vars[form_name].set("0")
                self._status_combos[form_name].current(0)
        self._suspend_trace = False
        for name in list(self.field_by_name.keys()):
            self._eval_visibility(name)

    def delete_record(self):
        label = self.record_combo.get()
        rid = self._record_display_to_id.get(label, "__new__")
        if rid == "__new__":
            messagebox.showinfo("Nothing to delete", "This is a new, unsaved record.")
            return
        if not messagebox.askyesno("Delete record", f"Delete record {rid}? This cannot be undone."):
            return
        self.records.pop(rid, None)
        self.save_all_records()
        self._refresh_record_list()
        self.status_var.set(f"Record {rid} deleted. {len(self.records)} record(s) saved.")
        self.new_record()

    # ---------------- Save ----------------

    def _build_row(self):
        row = {c: "" for c in self.template_cols}
        row["record_id"] = self.current_record_id
        row["mrn"] = self.mrn_var.get()
        for f in self.fields:
            name = f["name"]
            ftype = f["type"]
            if name in ("record_id", "mrn") or ftype == "calc":
                continue
            if ftype == "checkbox":
                choices = parse_choices(f["choices_raw"])
                for code, _ in choices:
                    col = f"{name}___{code}"
                    if col in row:
                        row[col] = "1" if self.cb_vars.get(name, {}).get(code, tk.BooleanVar()).get() else "0"
            elif ftype == "notes":
                if name in row:
                    row[name] = self.text_widgets[name].get("1.0", "end-1c").strip()
            else:
                if name in row:
                    row[name] = self.vars.get(name, tk.StringVar()).get()
        for form_name in FORM_ORDER:
            row[f"{form_name}_complete"] = self.complete_vars[form_name].get() or "0"
        return row

    def save_record(self):
        if not self.current_record_id:
            self.current_record_id = self._next_record_id()
        row = self._build_row()
        self.records[self.current_record_id] = row
        self.save_all_records()
        self._refresh_record_list()
        label = f"Record {self.current_record_id}" + (f" (MRN {row.get('mrn','')})" if row.get("mrn") else "")
        self.record_combo.set(label)
        self.study_id_label.config(text=f"Study ID: {self.current_record_id}")
        self.status_var.set(f"Record {self.current_record_id} saved. {len(self.records)} record(s) saved.")

    # ---------------- Misc ----------------

    def open_data_folder(self):
        folder = os.path.dirname(DATA_PATH)
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception:
            messagebox.showinfo("Data folder", folder)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    ChartReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
