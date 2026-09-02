"""
PPS Ocular Findings / GI Chart Review — internal data entry app.

Renders a data-entry form dynamically from the REDCap data dictionary
(data/data_dictionary.csv) and saves each record as a row matching the
exact column layout of the REDCap import template
(data/import_template.csv), so the resulting CSV can be uploaded straight
into REDCap via "Data Import Tool".

Run locally with:
    pip install -r requirements.txt
    streamlit run app.py
"""

import csv
import os
import re
from datetime import date

import pandas as pd
import streamlit as st

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

COMPLETE_CHOICES = {"0": "Incomplete", "1": "Unverified", "2": "Complete"}


# --------------------------------------------------------------------------
# Data dictionary / template loading
# --------------------------------------------------------------------------

@st.cache_data
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


@st.cache_data
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
# Branching logic evaluation (subset of REDCap syntax used in this dictionary)
# --------------------------------------------------------------------------

COND_RE = re.compile(r"\[(\w+)(?:\((\w+)\))?\]\s*(=|<>)\s*'([^']*)'")


def eval_branching(logic):
    if not logic:
        return True

    def repl(m):
        field, code, op, val = m.groups()
        if code is not None:
            selected = st.session_state.get(f"cb_{field}", [])
            actual = "1" if code in selected else "0"
        else:
            actual = st.session_state.get(f"w_{field}", "")
        result = (str(actual) == val)
        if op == "<>":
            result = not result
        return "True" if result else "False"

    expr = COND_RE.sub(repl, logic)
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return True


# --------------------------------------------------------------------------
# Field rendering
# --------------------------------------------------------------------------

CALC_FIELDS = set()  # filled in main() once dictionary is loaded


def render_field(field):
    name = field["name"]
    ftype = field["type"]
    label = field["label"] or name
    note = field["note"]

    if not eval_branching(field["branching"]):
        return

    if ftype == "calc":
        return  # calculated by REDCap, never entered manually

    key = f"w_{name}"

    if ftype == "checkbox":
        choices = parse_choices(field["choices_raw"])
        options = [c for c, _ in choices]
        labels = {c: l for c, l in choices}
        st.multiselect(
            label,
            options=options,
            format_func=lambda c: labels.get(c, c),
            key=f"cb_{name}",
            help=note or None,
        )
        return

    if ftype == "radio" or ftype == "dropdown":
        choices = parse_choices(field["choices_raw"])
        options = [""] + [c for c, _ in choices]
        labels = {c: l for c, l in choices}
        labels[""] = "— Not entered —"
        widget = st.selectbox if ftype == "dropdown" else st.radio
        widget(
            label,
            options=options,
            format_func=lambda c: labels.get(c, c),
            key=key,
            help=note or None,
        )
        return

    if ftype == "yesno":
        options = ["", "1", "0"]
        labels = {"": "— Not entered —", "1": "Yes", "0": "No"}
        st.radio(label, options=options, format_func=lambda c: labels[c], key=key, help=note or None)
        return

    if ftype == "notes":
        st.text_area(label, key=key, help=note or None)
        return

    # plain text field, possibly date / number / integer validated
    if field["validation"] == "date_mdy":
        use_date = st.checkbox(f"Enter date for: {label}", key=f"chk_{name}",
                                value=bool(st.session_state.get(key)))
        if use_date:
            default = date.today()
            st.date_input(label, key=f"d_{name}", value=default, format="MM/DD/YYYY")
            st.session_state[key] = st.session_state[f"d_{name}"].strftime("%m/%d/%Y")
        else:
            st.session_state[key] = ""
        return

    if field["validation"] in ("number", "integer"):
        help_txt = note or ""
        rng = ""
        if field["vmin"] or field["vmax"]:
            rng = f" (range {field['vmin'] or '?'}–{field['vmax'] or '?'})"
        st.text_input(label + rng, key=key, help=(help_txt or None))
        return

    st.text_input(label, key=key, help=note or None)


def render_form(fields, form_name):
    by_section = []
    current_section = None
    bucket = []
    for f in fields:
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

    complete_key = f"w_{form_name}_complete"
    if complete_key not in st.session_state:
        st.session_state[complete_key] = "0"

    for section, sec_fields in by_section:
        if section:
            st.subheader(section)
        for f in sec_fields:
            render_field(f)
        st.divider()

    st.selectbox(
        "Form status",
        options=list(COMPLETE_CHOICES.keys()),
        format_func=lambda c: COMPLETE_CHOICES[c],
        key=complete_key,
    )


# --------------------------------------------------------------------------
# Record persistence
# --------------------------------------------------------------------------

def load_records():
    if os.path.exists(DATA_PATH):
        return pd.read_csv(DATA_PATH, dtype=str, keep_default_na=False)
    cols = load_template_columns()
    return pd.DataFrame(columns=cols)


def save_records(df):
    cols = load_template_columns()
    df = df.reindex(columns=cols, fill_value="")
    df.to_csv(DATA_PATH, index=False)


def clear_field_widget_state(fields):
    for f in fields:
        for prefix in ("w_", "cb_", "d_", "chk_"):
            st.session_state.pop(f"{prefix}{f['name']}", None)
    for form_name in FORM_ORDER:
        st.session_state.pop(f"w_{form_name}_complete", None)


def load_record_into_widgets(fields, row):
    for f in fields:
        name = f["name"]
        ftype = f["type"]
        if ftype == "checkbox":
            choices = parse_choices(f["choices_raw"])
            selected = [c for c, _ in choices if row.get(f"{name}___{c}", "") == "1"]
            st.session_state[f"cb_{name}"] = selected
        elif ftype == "calc":
            continue
        else:
            val = row.get(name, "")
            st.session_state[f"w_{name}"] = val
            if f["validation"] == "date_mdy":
                st.session_state[f"chk_{name}"] = bool(val)
                if val:
                    try:
                        m, d, y = [int(x) for x in val.split("/")]
                        st.session_state[f"d_{name}"] = date(y, m, d)
                    except Exception:
                        pass
    for form_name in FORM_ORDER:
        st.session_state[f"w_{form_name}_complete"] = row.get(f"{form_name}_complete", "0")


def build_row_from_widgets(fields, record_id, mrn_value):
    row = {}
    row["record_id"] = record_id
    for f in fields:
        name = f["name"]
        ftype = f["type"]
        if name == "record_id":
            continue
        if ftype == "checkbox":
            choices = parse_choices(f["choices_raw"])
            selected = st.session_state.get(f"cb_{name}", [])
            for c, _ in choices:
                row[f"{name}___{c}"] = "1" if c in selected else "0"
        elif ftype == "calc":
            continue
        else:
            row[name] = st.session_state.get(f"w_{name}", "")
    for form_name in FORM_ORDER:
        row[f"{form_name}_complete"] = st.session_state.get(f"w_{form_name}_complete", "0")
    if mrn_value is not None:
        row["mrn"] = mrn_value
    return row


# --------------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="PPS Chart Review", layout="wide")
    st.title("PPS Ocular Findings & GI — Chart Review Data Entry")
    st.caption(
        "Internal tool for collecting chart review data. Records are saved locally "
        "and can be exported as a CSV ready for REDCap's Data Import Tool."
    )

    fields = load_dictionary()
    global CALC_FIELDS
    CALC_FIELDS = {f["name"] for f in fields if f["type"] == "calc"}

    df = load_records()

    # ---- Sidebar: record selection ----
    st.sidebar.header("Records")
    existing_ids = df["record_id"].tolist() if not df.empty else []
    labels = {"__new__": "+ New record"}
    for rid in existing_ids:
        mrn = ""
        if not df.empty:
            match = df.loc[df["record_id"] == rid, "mrn"]
            if len(match):
                mrn = match.iloc[0]
        labels[rid] = f"Record {rid}" + (f" (MRN {mrn})" if mrn else "")

    choice = st.sidebar.selectbox(
        "Select or create a record",
        options=list(labels.keys()),
        format_func=lambda k: labels[k],
        key="record_choice",
    )

    if "loaded_record" not in st.session_state:
        st.session_state["loaded_record"] = None

    if choice == "__new__":
        if st.session_state["loaded_record"] != "__new__":
            clear_field_widget_state(fields)
            st.session_state["loaded_record"] = "__new__"
        next_id = str(max([int(i) for i in existing_ids if i.isdigit()], default=0) + 1)
        st.sidebar.info(f"New record will be saved as Study ID **{next_id}**")
        active_record_id = next_id
    else:
        if st.session_state["loaded_record"] != choice:
            row = df.loc[df["record_id"] == choice].iloc[0].to_dict()
            clear_field_widget_state(fields)
            load_record_into_widgets(fields, row)
            st.session_state["loaded_record"] = choice
        active_record_id = choice

    if st.sidebar.button("Delete this record", disabled=(choice == "__new__")):
        df = df.loc[df["record_id"] != choice]
        save_records(df)
        st.session_state["loaded_record"] = None
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("Export")
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "rb") as fh:
            st.sidebar.download_button(
                "Download REDCap import CSV",
                data=fh.read(),
                file_name="PPSOcularFindingsGI_import.csv",
                mime="text/csv",
            )
    st.sidebar.caption(f"{len(df)} record(s) saved so far.")

    # ---- Main form ----
    st.subheader(f"Study ID: {active_record_id}")
    tabs = st.tabs([FORM_LABELS[f] for f in FORM_ORDER])
    for tab, form_name in zip(tabs, FORM_ORDER):
        with tab:
            if form_name == "screening_demographics":
                st.text_input("Medical Record Number (MRN)", key="w_mrn")
            render_form(fields, form_name)

    if st.button("Save record", type="primary"):
        row = build_row_from_widgets(fields, active_record_id, st.session_state.get("w_mrn", ""))
        if not df.empty and (df["record_id"] == active_record_id).any():
            df.loc[df["record_id"] == active_record_id, :] = pd.NA
            df = df.loc[df["record_id"] != active_record_id]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        save_records(df)
        st.session_state["loaded_record"] = active_record_id
        st.success(f"Record {active_record_id} saved.")
        st.rerun()


if __name__ == "__main__":
    main()
