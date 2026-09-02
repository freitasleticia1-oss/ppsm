# ppsm — PPS Ocular Findings & GI Chart Review

Internal apps for collecting chart review data for the PPS maculopathy /
GI study. Both versions generate their form automatically from the
REDCap data dictionary, and save every record in the exact column layout
of the REDCap import template, so the export CSV can be uploaded directly
into REDCap via **Data Import Tool**. Pick whichever fits your machine:

- **`app_desktop.py`** — plain desktop app (Tkinter). No installation
  besides Python itself; nothing runs in a browser.
- **`app.py`** — Streamlit version, runs as a local web page.

## Multiple reviewers at the same time

If several people are reviewing charts in parallel, **each person should
save to their own CSV file** — one shared file being written by multiple
people at once will overwrite each other's records.

- **Desktop app**: by default it picks a file named after your OS login
  (e.g. `data/chart_review_data_maria.csv`), shown at the top of the
  window next to "Saving to:". Click **Change data file...** to create a
  new file (e.g. `chart_review_data_joao.csv`) or open an existing one.
  Your choice is remembered for next time you open the app.
- **Streamlit app**: set the `PPSM_DATA_FILE` environment variable before
  launching so each reviewer's browser session points at their own file,
  e.g. `PPSM_DATA_FILE=data/chart_review_data_maria.csv streamlit run app.py`.

Once everyone is done, combine everyone's `chart_review_data_*.csv` files
(e.g. by concatenating the data rows — they all share the same header) into
one file before importing into REDCap.

## Desktop app (Tkinter)

Requires only Python 3 — no `pip install` needed. On Windows/macOS
python.org installers, Tkinter is already included. On Linux, install it
once if missing:

```bash
sudo apt install python3-tk   # Debian/Ubuntu
```

Run:

```bash
python3 app_desktop.py
```

This opens a native window — nothing is sent anywhere, everything stays
on your machine.

## Streamlit app (browser-based)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

This starts a local web server (default `http://localhost:8501`) that only
your machine can reach.

## How it works

- `data/data_dictionary.csv` — the REDCap data dictionary. Drives which
  fields, choices, and section headers appear in the form, and which
  fields are conditionally shown (branching logic).
- `data/import_template.csv` — the REDCap import template. Its header row
  defines the exact column order/names used when saving data.
- `data/chart_review_data.csv` — created automatically the first time you
  save a record. This is your working dataset; it accumulates one row per
  chart reviewed, in import-template format.

In the app:

1. Start a **+ New record** or select an existing one to edit.
2. Fill in the tabs (Screening & Demographics, PPS/Medication History,
   Colonoscopy & Genetic Testing, Ophthalmology Visit — Index, Last
   Available Visit, Multimodal Image Analysis). Fields with branching
   logic only appear once their trigger condition is met (e.g. "Pack-years"
   only appears if smoking history is "Former smoker").
3. Click **Save record**.
4. When ready, use `data/chart_review_data.csv` (desktop app: **Open data
   folder** button; Streamlit app: **Download REDCap import CSV** button)
   and import that file into REDCap.

Calculated fields (e.g. BCVA LogMAR, PPS duration, cumulative dose) are
left blank — REDCap computes these itself from the raw fields once the
data is in the project.
