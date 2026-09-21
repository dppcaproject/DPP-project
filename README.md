# DPP Project — Data Collection, Organizing & Cleaning Pipeline

Data preparation pipeline for the **Digital Pressure Profile (DPP)** framework — a joint KazNU–PolyU research project (P0059202) building user-generated content (UGC) based tourism pressure indicators for three Central Asian national parks:

- **Ile-Alatau** (Kazakhstan)
- **Ala-Archa** (Kyrgyzstan)
- **Ugam-Chatkal** (Uzbekistan/Kazakhstan border region)

This repository contains the scripts used to collect, organize, clean, and deduplicate UGC data across multiple platforms into a validated dataset ready for DPP model integration. It supports the *DPP Data Preparation and Integration Report* deliverable (Task 3).

---

## Data Sources

UGC was collected across eight platforms:

| Platform | Method | Tool | Script in this repo |
|---|---|---|---|
| Flickr | API-based, per park (hybrid bbox + keyword search) | Python | `01_data_collection.py` |
| Strava | API-based (`/segments/explore`) | Python | not included — see note below |
| Google Maps | Built-in scraping template | Octoparse | external (no script) |
| 2GIS | Custom-built scraping template | Octoparse | external (no script) |
| Twitter/X | Hashtag/keyword-based scraping | Octoparse | external (no script) |
| Instagram | Hashtag/keyword-based scraping | Apify | external (no script) |
| Threads | Hashtag/keyword-based scraping | Apify | external (no script) |
| TikTok | Hashtag/keyword-based scraping | Apify | external (no script) |

**Note:** Google Maps, 2GIS, Twitter/X, Instagram, Threads, and TikTok were collected via Octoparse/Apify's own scraping templates (no-code tools), not custom Python scripts, so there is no corresponding code to version here. Only the Flickr collection scripts (Python, per park) are included. The Strava collection script was not included in this consolidation and should be added separately if needed.

---

## Repository Structure

```
DPP-project/
├── README.md
├── 01_data_collection.py                 # Flickr scrapers (Ile-Alatau, Ala-Archa, Ugam-Chatkal)
├── 02_data_organizing.py                 # Merge raw scrapes, unify spatiotemporal & sentiment tables
└── 03_data_cleaning_and_deduplication.py # Date/coordinate cleaning, per-platform dedup, sentiment prep
```

Each file consolidates several original Colab notebooks into one script per pipeline stage. All comments and descriptive text have been stripped from the code for brevity — run each section in a Colab cell to see it in its original notebook context if needed.

---

## Pipeline Overview

```
1. COLLECTION            01_data_collection.py (+ Octoparse/Apify templates, external)
        │
        ▼
2. ORGANIZING             02_data_organizing.py
   - Merge raw scrape files per (platform, park), dedup within each merge
   - Unify into one spatiotemporal table (2GIS, Google Maps, Flickr, Strava)
   - Unify + clean sentiment-tier table (Twitter/X, Instagram, Threads, TikTok)
        │
        ▼
3. CLEANING & DEDUPLICATION   03_data_cleaning_and_deduplication.py
   - Date filtering, Google Maps geocoding, timestamp checks
   - Coordinate cleaning (remove 0,0 and impossible coordinates)
   - Per-platform deduplication (final pass, platform-specific keys)
   - Sentiment input table preparation (filter/clean text, language detection)
        │
        ▼
   VALIDATED OUTPUT
   - spatiotemporal_pathA_1km.csv   (25 variables, 83,206 records)
   - sentiment_input_table.csv      (14 variables, 38,754 records)
```

---

## How to Run

All scripts were written for **Google Colab** with Google Drive mounted. To run:

1. Open a script in Colab (or paste its contents into a new notebook cell).
2. Mount Google Drive: `from google.colab import drive; drive.mount('/content/drive')`
3. Update any hardcoded input/output paths at the top of each script section to match your Drive folder structure (originally under `/content/drive/MyDrive/Aisulu_project_data/`).
4. Install dependencies as needed per section (e.g. `pandas`, `requests`, `langdetect`).
5. Run top to bottom. Each section within a file is independent and can be run separately.

---

## Data Quality Notes & Known Limitations

These are documented in full in the *DPP Data Preparation and Integration Report* (Sections 5–6); summarized here for anyone working directly with the code:

- **Cross-platform deduplication has not been implemented.** Deduplication in `03_data_cleaning_and_deduplication.py` is within-platform only, using platform-specific keys (e.g. `post_url` for Google Maps/Flickr, full-row identity for 2GIS). No step compares records across different platforms to catch the same real-world content posted to multiple sources.
- **68,383 records (82.2% of the spatiotemporal table)** — all Google Maps — carry only a relative source timestamp (e.g. "a year ago"). The cleaning pass assigns these a placeholder date (1 May of the inferred year, `date_precision = "year"`). Filter on `date_precision` before doing any month- or day-level temporal analysis.
- **2GIS returned zero records for Ugam-Chatkal.** This reflects an absence of indexed points of interest for that park within 2GIS itself, not a collection failure.
- **`rating_score`** is populated for 2GIS records only in this dataset (Google Maps ratings were not captured). **`likes_count`** is populated for Google Maps only. **`comments_count`** is not returned by any of the four spatiotemporal-table platforms.
- **`scrape_timestamp`** is a batch-level value (110 distinct timestamps across 83,206 records), not a true per-record collection time.
- Language detection (`langdetect`, in the sentiment prep step) is unreliable on short strings and can misclassify closely related languages — treat the long tail of low-frequency detected languages with caution.

---

## Related Deliverables

- **DPP Data Preparation and Integration Report** — full methodology, variable dictionary, descriptive statistics, and validated input data documentation (Task 3 contract deliverable).
- `spatiotemporal_pathA_1km.csv` — validated spatiotemporal dataset (25 variables).
- `sentiment_input_table.csv` — validated sentiment input dataset (14 variables), derived from the spatiotemporal table.

---

## Project

PolyU–KazNU Centre for Sustainable Development in Central Asia — Project P0059202.
