# ppsm — PPS Ocular Findings & GI Chart Review

Internal Streamlit app for collecting chart review data for the PPS
maculopathy / GI study. The form is generated automatically from the
REDCap data dictionary, and every saved record is written in the exact
column layout of the REDCap import template, so the export CSV can be
uploaded directly into REDCap via **Data Import Tool**.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

This starts a local web server (default `http://localhost:8501`) that only
your machine can reach — nothing is sent anywhere else.

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

1. Use the sidebar to start a **+ New record** or select an existing one to
   edit.
2. Fill in the tabs (Screening & Demographics, PPS/Medication History,
   Colonoscopy & Genetic Testing, Ophthalmology Visit — Index, Last
   Available Visit, Multimodal Image Analysis). Fields with branching
   logic only appear once their trigger condition is met (e.g. "Pack-years"
   only appears if smoking history is "Former smoker").
3. Click **Save record**.
4. When ready, click **Download REDCap import CSV** in the sidebar and
   import that file into REDCap.

Calculated fields (e.g. BCVA LogMAR, PPS duration, cumulative dose) are
left blank — REDCap computes these itself from the raw fields once the
data is in the project.
