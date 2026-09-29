"""DPP Project — Data Collection Scripts"""

# ---- FLICKR — Ile-Alatau ----

# =============================================================================
# Flickr Geotagged Photo Scraper — Ile-Alatau National Park (REFINED)
# API: https://api.flickr.com/services/rest/
# Compatible with: Google Colab
# Includes: exponential backoff on 429, yearly split if results > 4000
#
# COORDINATE REFINEMENT STRATEGY:
# - Original bbox (76.75,42.85,77.90,43.35) captured too much of Almaty city
# - Refined bbox (76.50,43.00,77.85,43.33) focuses on park mountain area
# - Southern boundary moved north from 42.85° to 43.00° to exclude urban Almaty
# - Added elevation-based filtering (>=1200m) to remove any remaining city photos
# - Park landmarks: Big Almaty Lake (2511m), Shymbulak (2200m), Medeu (1691m)
# - This approach avoids keyword filtering which would miss valuable geotagged posts
# =============================================================================

# ── STEP 1: Install & Import ──────────────────────────────────────────────────

import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

# ── STEP 2: Configuration ─────────────────────────────────────────────────────

# Paste your Flickr API key here
# Or use: from google.colab import userdata; FLICKR_API_KEY = userdata.get("FLICKR_API_KEY")
FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ile-Alatau National Park"

# Bounding box — REFINED to exclude Almaty city, focus on mountain/park area
# West (Chemolgan River) to East (Turgen Gorge)
# South boundary pushed north to ~43.00° to exclude urban Almaty (elevation ~700-800m)
# North boundary extends to park's northern limit
BBOX = "76.50,43.00,77.85,43.33"

# Coordinate validity bounds for cleaning (matching refined bbox)
LAT_MIN, LAT_MAX = 43.00, 43.33
LNG_MIN, LNG_MAX = 76.50, 77.85

# Elevation filter to exclude remaining urban/low-elevation photos
# Most park locations are above 1500m (Big Almaty Lake: 2511m, Shymbulak: 2200m)
# Set conservative threshold to exclude city while keeping park entrances
MIN_ELEVATION = 1200  # meters - filters out Almaty city (700-900m)

DATE_START = "2015-01-01"
DATE_END   = "2025-12-31"

PER_PAGE         = 250    # Flickr maximum per page
BASE_DELAY       = 2.0    # seconds between every page request
YEAR_PAUSE       = 30     # seconds between yearly queries if split needed
MAX_RETRIES      = 5      # retries on 429 before giving up
FLICKR_MAX_ROWS  = 4000   # Flickr hard cap per single query

SCRAPE_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY            = datetime.now().strftime("%Y-%m-%d")

# ── STEP 3: Helper Functions ──────────────────────────────────────────────────

def generate_record_id():
    return "FLICKR-" + str(uuid.uuid4())[:8].upper()

def get_elevation_estimate(latitude, longitude):
    """
    Estimates elevation based on latitude within the park area.
    This is a rough approximation: northern areas (closer to city) = lower elevation
    Southern areas (deeper into mountains) = higher elevation

    For precise filtering, Flickr doesn't provide elevation in basic API,
    so we use latitude as a proxy (higher lat = lower elevation in this region)
    """
    if not latitude or not longitude:
        return 0

    try:
        lat = float(latitude)
        lng = float(longitude)

        # Rough elevation estimation based on latitude
        # Almaty city: ~43.25° lat, ~700-800m elevation
        # Park interior: ~43.00-43.15° lat, 1500-4000m elevation
        # Linear interpolation (conservative approach)

        if lat >= 43.20:  # Very close to city
            return 800
        elif lat >= 43.15:
            return 1100
        elif lat >= 43.10:
            return 1400
        elif lat >= 43.05:
            return 1800
        else:  # lat < 43.05 (deep in park)
            return 2200

    except (ValueError, TypeError):
        return 0

def flickr_request(params, max_retries=MAX_RETRIES):
    """
    Makes a Flickr API GET request with exponential backoff on 429 errors.
    Returns parsed JSON or None on failure.
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(BASE_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "ok":
                    return data
                else:
                    print(f"  [Flickr Error] {data.get('message', 'Unknown error')}")
                    return None

            elif response.status_code == 429:
                wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s, 80s, 160s
                print(f"  [429 Rate limited] Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)

            elif response.status_code == 500:
                print(f"  [500 Server Error] Waiting 15s before retry...")
                time.sleep(15)

            else:
                print(f"  [HTTP {response.status_code}] Skipping request.")
                return None

        except requests.exceptions.Timeout:
            print(f"  [Timeout] Attempt {attempt + 1}. Retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            print(f"  [Exception] {e}")
            return None

    print("  [Failed] Max retries reached. Skipping.")
    return None

def parse_photo(photo):
    """
    Maps a single Flickr photo dict to the project metadata schema.
    Includes estimated elevation for filtering.
    """
    owner      = photo.get("owner", "")
    photo_id   = str(photo.get("id", ""))
    title      = photo.get("title", "")
    tags       = photo.get("tags", "")
    date_taken = photo.get("datetaken", "")
    url_m      = photo.get("url_m", "")
    views      = photo.get("views", "")

    latitude   = photo.get("latitude", "")
    longitude  = photo.get("longitude", "")

    # Extract year and month from date_taken (format: "YYYY-MM-DD HH:MM:SS")
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

    # Construct direct Flickr page URL
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

    # Combine title and tags as text content
    text_content = " ".join(filter(None, [title, tags])).strip()

    # Estimate elevation for filtering
    estimated_elevation = get_elevation_estimate(latitude, longitude)

    return {
        "record_id":          generate_record_id(),
        "platform":           "Flickr",
        "platform_record_id": photo_id,
        "content_type":       "photo",
        "text_content":       text_content,
        "media_url":          url_m,
        "post_url":           post_url,
        "user_id":            owner,
        "post_timestamp_raw": date_taken,
        "post_year":          post_year,
        "post_month":         post_month,
        "latitude_raw":       latitude,
        "longitude_raw":      longitude,
        "estimated_elevation": estimated_elevation,  # NEW FIELD
        "location_name_raw":  "",
        "poi_id":             "",
        "poi_name":           "",
        "park_name":          PARK_NAME,
        "likes_count":        "",
        "comments_count":     "",
        "rating_score":       "",
        "detected_language":  "",
        "scrape_timestamp":   SCRAPE_TIMESTAMP,
        "tags_raw":           tags,
        "views_count":        views,
        "spatial_confidence": "high"
    }

def build_params(date_start, date_end, page=1):
    """Builds the API request parameter dict for a given date range and page."""
    return {
        "method":          "flickr.photos.search",
        "api_key":         FLICKR_API_KEY,
        "bbox":            BBOX,
        "min_taken_date":  date_start,
        "max_taken_date":  date_end,
        "has_geo":         1,
        "extras":          "geo,date_taken,date_upload,owner_name,tags,url_m,views",
        "per_page":        PER_PAGE,
        "page":            page,
        "format":          "json",
        "nojsoncallback":  1,
        "sort":            "date-taken-asc"
    }

def collect_range(date_start, date_end, label=""):
    """
    Collects all photos for a given date range with pagination.
    Returns a list of parsed photo dicts.
    """
    records    = []
    page       = 1
    total_pages = None
    total_available = None

    while True:
        params = build_params(date_start, date_end, page)
        data   = flickr_request(params)

        if data is None:
            print(f"  Request failed on page {page}. Stopping this range.")
            break

        photos_block    = data.get("photos", {})
        total_available = int(photos_block.get("total", 0))
        total_pages     = int(photos_block.get("pages", 0))
        photos          = photos_block.get("photo", [])

        if page == 1:
            print(f"  {label} Total available: {total_available} | Pages: {total_pages}")

        if not photos:
            print(f"  No photos on page {page}. Done.")
            break

        for photo in photos:
            records.append(parse_photo(photo))

        print(f"  Page {page}/{total_pages} — collected {len(photos)} photos. Running total: {len(records)}")

        if page >= total_pages:
            break

        page += 1
        time.sleep(BASE_DELAY)

    return records, total_available

# ── STEP 4: Main Collection Logic ─────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"Flickr Scraper — {PARK_NAME}")
print(f"Bounding box: {BBOX}")
print(f"Date range: {DATE_START} to {DATE_END}")
print(f"{'='*60}\n")

# First check total available with a single probe request
print("Probing total available photos...")
probe_data = flickr_request(build_params(DATE_START, DATE_END, page=1))

if probe_data is None:
    print("Initial request failed. Check your API key and try again.")
    raise SystemExit

total_probe = int(probe_data.get("photos", {}).get("total", 0))
print(f"Total geotagged photos in park boundary (2015–2025): {total_probe}")

all_records = []

if total_probe == 0:
    print("No results found. Check bounding box or date range.")

elif total_probe <= FLICKR_MAX_ROWS:
    # ── Single query — under 4000 results
    print(f"\nTotal is under {FLICKR_MAX_ROWS}. Running single query...")
    records, _ = collect_range(DATE_START, DATE_END, label="Full range:")
    all_records.extend(records)

else:
    # ── Yearly split — total exceeds Flickr's 4000 result cap
    print(f"\nTotal exceeds {FLICKR_MAX_ROWS}. Splitting into yearly queries...")

    for year in range(2015, 2026):
        y_start = f"{year}-01-01"
        y_end   = f"{year}-12-31"

        print(f"\n── Year {year} ──────────────────────────────────────")
        records, year_total = collect_range(y_start, y_end, label=f"Year {year}:")
        all_records.extend(records)

        print(f"  Year {year} complete: {len(records)} photos collected.")

        if year < 2025:
            print(f"  Pausing {YEAR_PAUSE}s before next year...")
            time.sleep(YEAR_PAUSE)

# ── STEP 5: Deduplicate ───────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"])
    print(f"After deduplication: {len(df)} records (removed {before - len(df)} duplicates)")

    # ── STEP 5.5: Filter by Elevation ─────────────────────────────────────────

    print(f"\n── Elevation Filtering ──────────────────────────────")
    before_elevation = len(df)
    df = df[df['estimated_elevation'] >= MIN_ELEVATION]
    removed_low = before_elevation - len(df)
    print(f"Removed {removed_low} low-elevation photos (< {MIN_ELEVATION}m)")
    print(f"Remaining: {len(df)} park-area photos")

    # ── STEP 6: Enforce Column Order ──────────────────────────────────────────

    schema_columns = [
        "record_id", "platform", "platform_record_id",
        "content_type", "text_content", "media_url", "post_url",
        "user_id", "post_timestamp_raw", "post_year", "post_month",
        "latitude_raw", "longitude_raw", "estimated_elevation",  # ADDED elevation column
        "location_name_raw",
        "poi_id", "poi_name", "park_name",
        "likes_count", "comments_count", "rating_score",
        "detected_language", "scrape_timestamp",
        "tags_raw", "views_count", "spatial_confidence"
    ]
    df = df[schema_columns]

    # ── STEP 7: Export ────────────────────────────────────────────────────────

    filename_csv   = f"Flickr_IleAlatau_{TODAY}.csv"
    filename_excel = f"Flickr_IleAlatau_{TODAY}.xlsx"

    df.to_csv(filename_csv, index=False, encoding="utf-8-sig")
    df.to_excel(filename_excel, index=False)

    print(f"\nFiles saved:")
    print(f"  CSV:   {filename_csv}")
    print(f"  Excel: {filename_excel}")

    # ── STEP 8: Summary ───────────────────────────────────────────────────────

    print(f"\n── Summary ──────────────────────────────────────────")
    print(f"Total records:       {len(df)}")
    print(f"Unique users:        {df['user_id'].nunique()}")
    has_coords = df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')]
    print(f"With coordinates:    {len(has_coords)}")

    print(f"\n── Records per year ─────────────────────────────────")
    year_counts = df['post_year'].value_counts().sort_index()
    for yr, count in year_counts.items():
        print(f"  {int(yr)}: {count} photos")

else:
    print("No records collected.")

import pandas as pd

# Create a DataFrame from the raw collected records
raw_df = pd.DataFrame(all_records)

# Define filename for the raw data
filename_raw_excel = f"Flickr_IleAlatau_RAW_{TODAY}.xlsx"

# Save the raw DataFrame to Excel
raw_df.to_excel(filename_raw_excel, index=False)

print(f"Raw data (before deduplication and elevation filtering) saved to: {filename_raw_excel}")
print(f"Total raw records: {len(raw_df)}")
display(raw_df.head())

# Define filename for the deduplicated and filtered data
filename_deduplicated_excel = f"Flickr_IleAlatau_Deduplicated_Filtered_{TODAY}.xlsx"

# Save the DataFrame (after deduplication and elevation filtering) to Excel
df.to_excel(filename_deduplicated_excel, index=False)

print(f"Deduplicated and elevation-filtered data saved to: {filename_deduplicated_excel}")
print(f"Total deduplicated and filtered records: {len(df)}")

# Create a DataFrame with only deduplicated records (no elevation filtering)
df_deduplicated_only = raw_df.drop_duplicates(subset=["platform_record_id"])

# Define filename for the deduplicated-only data
filename_deduplicated_only_excel = f"Flickr_IleAlatau_Deduplicated_ONLY_{TODAY}.xlsx"

# Save the deduplicated-only DataFrame to Excel
df_deduplicated_only.to_excel(filename_deduplicated_only_excel, index=False)

print(f"Deduplicated (but not elevation-filtered) data saved to: {filename_deduplicated_only_excel}")
print(f"Total deduplicated records (before elevation filtering): {len(df_deduplicated_only)}")
display(df_deduplicated_only.head())

# ---- FLICKR — Ala-Archa ----

# =============================================================================
# Flickr Photo Scraper — Ala Archa National Park (HYBRID APPROACH)
# Combines: Geographic Bounding Box + Keyword Search
# API: https://api.flickr.com/services/rest/
# Compatible with: Google Colab, Local Python
# =============================================================================

import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

# ── STEP 2: Configuration ─────────────────────────────────────────────────────

FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ala Archa National Park"
COUNTRY    = "Kyrgyzstan"

# Geographic bounding box (for geotagged photos)
BBOX = "74.40,42.433,74.583,42.65"
LAT_MIN, LAT_MAX = 42.433, 42.65
LNG_MIN, LNG_MAX = 74.40, 74.583

# Keyword search terms (for non-geotagged photos)
# These will capture photos that mention the park but lack GPS data
KEYWORDS = [
    "Ala-Archa",
    "Ala Archa",
    "Ала-Арча",  # Cyrillic
    "Алаарча",
]

# Additional context keywords (optional - use with caution to avoid false positives)
CONTEXT_KEYWORDS = [
    "Kyrgyzstan mountains",
    "Bishkek hiking",
]

DATE_START = "2010-01-01"
DATE_END   = "2025-12-31"

PER_PAGE         = 250
BASE_DELAY       = 2.0
YEAR_PAUSE       = 30
MAX_RETRIES      = 5
FLICKR_MAX_ROWS  = 4000

SCRAPE_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY            = datetime.now().strftime("%Y-%m-%d")

# ── STEP 3: Helper Functions ──────────────────────────────────────────────────

def generate_record_id():
    return "FLICKR-" + str(uuid.uuid4())[:8].upper()

def get_elevation_estimate(latitude, longitude):
    """Estimates elevation based on latitude."""
    if not latitude or not longitude:
        return 0

    try:
        lat = float(latitude)
        if lat >= 42.63:
            return 1500
        elif lat >= 42.60:
            return 1700
        elif lat >= 42.57:
            return 2000
        elif lat >= 42.54:
            return 2300
        elif lat >= 42.51:
            return 2600
        elif lat >= 42.48:
            return 3000
        elif lat >= 42.45:
            return 3500
        else:
            return 4000
    except (ValueError, TypeError):
        return 0

def flickr_request(params, max_retries=MAX_RETRIES):
    """Makes a Flickr API GET request with exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = requests.get(BASE_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "ok":
                    return data
                else:
                    print(f"  [Flickr Error] {data.get('message', 'Unknown error')}")
                    return None

            elif response.status_code == 429:
                wait_time = (2 ** attempt) * 10
                print(f"  [429 Rate limited] Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)

            elif response.status_code == 500:
                print(f"  [500 Server Error] Waiting 15s before retry...")
                time.sleep(15)

            else:
                print(f"  [HTTP {response.status_code}] Skipping request.")
                return None

        except requests.exceptions.Timeout:
            print(f"  [Timeout] Attempt {attempt + 1}. Retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            print(f"  [Exception] {e}")
            return None

    print("  [Failed] Max retries reached. Skipping.")
    return None

def parse_photo(photo, source_method=""):
    """Maps a Flickr photo to metadata schema."""
    owner      = photo.get("owner", "")
    photo_id   = str(photo.get("id", ""))
    title      = photo.get("title", "")
    tags       = photo.get("tags", "")
    date_taken = photo.get("datetaken", "")
    url_m      = photo.get("url_m", "")
    views      = photo.get("views", "")

    latitude   = photo.get("latitude", "")
    longitude  = photo.get("longitude", "")

    # Extract year and month
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

    # Construct Flickr page URL
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

    # Combine title and tags
    text_content = " ".join(filter(None, [title, tags])).strip()

    # Estimate elevation
    estimated_elevation = get_elevation_estimate(latitude, longitude)

    # Determine spatial confidence
    has_coords = bool(latitude and longitude)
    if has_coords:
        try:
            lat_f = float(latitude)
            lng_f = float(longitude)
            in_bbox = (LAT_MIN <= lat_f <= LAT_MAX) and (LNG_MIN <= lng_f <= LNG_MAX)
            spatial_confidence = "high" if in_bbox else "medium"
        except:
            spatial_confidence = "medium"
    else:
        spatial_confidence = "low"

    return {
        "record_id":          generate_record_id(),
        "platform":           "Flickr",
        "platform_record_id": photo_id,
        "content_type":       "photo",
        "text_content":       text_content,
        "media_url":          url_m,
        "post_url":           post_url,
        "user_id":            owner,
        "post_timestamp_raw": date_taken,
        "post_year":          post_year,
        "post_month":         post_month,
        "latitude_raw":       latitude,
        "longitude_raw":      longitude,
        "estimated_elevation": estimated_elevation,
        "location_name_raw":  "",
        "poi_id":             "",
        "poi_name":           "",
        "park_name":          PARK_NAME,
        "country":            COUNTRY,
        "likes_count":        "",
        "comments_count":     "",
        "rating_score":       "",
        "detected_language":  "",
        "scrape_timestamp":   SCRAPE_TIMESTAMP,
        "tags_raw":           tags,
        "views_count":        views,
        "spatial_confidence": spatial_confidence,
        "collection_method":  source_method  # NEW: track how we found this photo
    }

def build_params_geo(date_start, date_end, page=1):
    """Builds params for geographic bbox search."""
    return {
        "method":          "flickr.photos.search",
        "api_key":         FLICKR_API_KEY,
        "bbox":            BBOX,
        "min_taken_date":  date_start,
        "max_taken_date":  date_end,
        "has_geo":         1,
        "extras":          "geo,date_taken,date_upload,owner_name,tags,url_m,views",
        "per_page":        PER_PAGE,
        "page":            page,
        "format":          "json",
        "nojsoncallback":  1,
        "sort":            "date-taken-asc"
    }

def build_params_keyword(keyword, date_start, date_end, page=1):
    """Builds params for keyword search."""
    return {
        "method":          "flickr.photos.search",
        "api_key":         FLICKR_API_KEY,
        "text":            keyword,  # Search in title, tags, description
        "min_taken_date":  date_start,
        "max_taken_date":  date_end,
        "extras":          "geo,date_taken,date_upload,owner_name,tags,url_m,views",
        "per_page":        PER_PAGE,
        "page":            page,
        "format":          "json",
        "nojsoncallback":  1,
        "sort":            "date-taken-asc"
    }

def collect_range(date_start, date_end, label="", params_builder=None, **kwargs):
    """Collects photos for a date range using specified params builder."""
    records = []
    page = 1
    total_pages = None
    total_available = None

    # Extract source_method for parse_photo and remove it from kwargs
    source_method_for_parse = kwargs.pop('method', 'unknown')

    # Extract 'keyword' if it's present and needed by build_params_keyword
    # This ensures it's not passed twice if params_builder is build_params_keyword
    keyword_for_builder = kwargs.pop('keyword', None)

    while True:
        # Build params, dynamically passing keyword if it was provided
        if params_builder == build_params_keyword and keyword_for_builder is not None:
            params = params_builder(keyword_for_builder, date_start, date_end, page=page, **kwargs)
        else:
            params = params_builder(date_start, date_end, page=page, **kwargs)

        data = flickr_request(params)

        if data is None:
            print(f"  Request failed on page {page}. Stopping this range.")
            break

        photos_block = data.get("photos", {})
        total_available = int(photos_block.get("total", 0))
        total_pages = int(photos_block.get("pages", 0))
        photos = photos_block.get("photo", [])

        if page == 1:
            print(f"  {label} Total available: {total_available} | Pages: {total_pages}")

        if not photos:
            print(f"  No photos on page {page}. Done.")
            break

        for photo in photos:
            records.append(parse_photo(photo, source_method=source_method_for_parse))

        print(f"  Page {page}/{total_pages} — collected {len(photos)} photos. Running total: {len(records)}")

        if page >= total_pages:
            break

        page += 1
        time.sleep(BASE_DELAY)

    return records, total_available

# ── STEP 4: Main Collection Logic ─────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"Flickr HYBRID Scraper — {PARK_NAME}, {COUNTRY}")
print(f"Methods: Geographic BBox + Keyword Search")
print(f"{'='*70}\n")

all_records = []

# ═══════════════════════════════════════════════════════════════════════════
# METHOD 1: GEOGRAPHIC BOUNDING BOX (Geotagged photos only)
# ═══════════════════════════════════════════════════════════════════════════

print(f"\n{'─'*70}")
print("METHOD 1: Geographic Bounding Box Search")
print(f"Bbox: {BBOX}")
print(f"{'─'*70}\n")

print("Probing geographic search...")
probe_data = flickr_request(build_params_geo(DATE_START, DATE_END, page=1))

if probe_data is None:
    print("Geographic search failed. Check your API key.")
else:
    total_geo = int(probe_data.get("photos", {}).get("total", 0))
    print(f"Total geotagged photos in bbox: {total_geo}")

    if total_geo > 0:
        if total_geo <= FLICKR_MAX_ROWS:
            print(f"\nRunning single geographic query...")
            records, _ = collect_range(
                DATE_START, DATE_END,
                label="Geographic:",
                params_builder=build_params_geo,
                method="geographic_bbox"
            )
            all_records.extend(records)
        else:
            print(f"\nTotal exceeds {FLICKR_MAX_ROWS}. Splitting by year...")
            for year in range(2010, 2026):
                y_start = f"{year}-01-01"
                y_end = f"{year}-12-31"
                print(f"\n── Year {year} (Geographic) ──")
                records, _ = collect_range(
                    y_start, y_end,
                    label=f"Geo {year}:",
                    params_builder=build_params_geo,
                    method="geographic_bbox"
                )
                all_records.extend(records)
                if year < 2025:
                    time.sleep(YEAR_PAUSE)

# ═══════════════════════════════════════════════════════════════════════════
# METHOD 2: KEYWORD SEARCH (Includes non-geotagged photos)
# ═══════════════════════════════════════════════════════════════════════════

print(f"\n{'─'*70}")
print("METHOD 2: Keyword Search")
print(f"Keywords: {KEYWORDS}")
print(f"{'─'*70}\n")

for keyword in KEYWORDS:
    print(f"\n▸ Searching keyword: '{keyword}'")

    probe_data = flickr_request(build_params_keyword(keyword, DATE_START, DATE_END, page=1))

    if probe_data is None:
        print(f"  Keyword search failed for '{keyword}'. Skipping.")
        continue

    total_keyword = int(probe_data.get("photos", {}).get("total", 0))
    print(f"  Total results for '{keyword}': {total_keyword}")

    if total_keyword == 0:
        continue

    if total_keyword <= FLICKR_MAX_ROWS:
        print(f"  Running single keyword query...")
        records, _ = collect_range(
            DATE_START, DATE_END,
            label=f"Keyword '{keyword}':",
            params_builder=build_params_keyword,
            keyword=keyword,
            method=f"keyword_{keyword}"
        )
        all_records.extend(records)
    else:
        print(f"  Total exceeds {FLICKR_MAX_ROWS}. Splitting by year...")
        for year in range(2010, 2026):
            y_start = f"{year}-01-01"
            y_end = f"{year}-12-31"
            print(f"\n  ── Year {year} (Keyword: {keyword}) ──")
            records, _ = collect_range(
                y_start, y_end,
                label=f"KW '{keyword}' {year}:",
                params_builder=build_params_keyword,
                keyword=keyword,
                method=f"keyword_{keyword}"
            )
            all_records.extend(records)
            if year < 2025:
                time.sleep(YEAR_PAUSE)

    # Pause between keywords
    print(f"  Pausing 10s before next keyword...")
    time.sleep(10)

# ── STEP 5: Deduplicate & Process ─────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

    # Deduplicate by photo ID (same photo found via different methods)
    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"], keep="first")
    print(f"After deduplication: {len(df)} unique records (removed {before - len(df)} duplicates)")

    # Show breakdown by collection method
    print(f"\n── Collection Method Breakdown ──────────────────────")
    method_counts = df['collection_method'].value_counts()
    for method, count in method_counts.items():
        print(f"  {method}: {count} photos")

    # Show geotagged vs non-geotagged
    print(f"\n── Geolocation Status ───────────────────────────────")
    has_coords = df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')]
    no_coords = df[(df['latitude_raw'] == '') | (df['longitude_raw'] == '')]
    print(f"  With coordinates: {len(has_coords)} ({len(has_coords)/len(df)*100:.1f}%)")
    print(f"  Without coordinates: {len(no_coords)} ({len(no_coords)/len(df)*100:.1f}%)")

    # Show spatial confidence distribution
    print(f"\n── Spatial Confidence ───────────────────────────────")
    confidence_counts = df['spatial_confidence'].value_counts()
    for conf, count in confidence_counts.items():
        print(f"  {conf}: {count} photos")

    # Optional: Filter by elevation (only for geotagged photos)
    print(f"\n── Elevation Filtering (Geotagged only) ─────────────")
    geotagged_before = len(has_coords)

    # Create a mask for records to keep
    keep_mask = (
        # Keep all non-geotagged photos (from keyword search)
        ((df['latitude_raw'] == '') | (df['longitude_raw'] == '')) |
        # Keep geotagged photos with sufficient elevation
        (df['estimated_elevation'] >= 1400)
    )

    df = df[keep_mask]
    geotagged_after = len(df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')])
    removed = geotagged_before - geotagged_after

    print(f"Removed {removed} low-elevation geotagged photos (< 1400m)")
    print(f"Kept all {len(no_coords)} non-geotagged photos from keyword search")
    print(f"Final total: {len(df)} photos")


    schema_columns = [
        "record_id", "platform", "platform_record_id",
        "content_type", "text_content", "media_url", "post_url",
        "user_id", "post_timestamp_raw", "post_year", "post_month",
        "latitude_raw", "longitude_raw", "estimated_elevation",
        "location_name_raw", "poi_id", "poi_name", "park_name", "country",
        "likes_count", "comments_count", "rating_score",
        "detected_language", "scrape_timestamp",
        "tags_raw", "views_count", "spatial_confidence", "collection_method"
    ]
    df = df[schema_columns]


    filename_csv   = f"Flickr_AlaArcha_HYBRID_{TODAY}.csv"
    filename_excel = f"Flickr_AlaArcha_HYBRID_{TODAY}.xlsx"

    df.to_csv(filename_csv, index=False, encoding="utf-8-sig")
    df.to_excel(filename_excel, index=False)

    print(f"\n{'='*70}")
    print("Files saved:")
    print(f"  CSV:   {filename_csv}")
    print(f"  Excel: {filename_excel}")


    print(f"\n── Final Summary ────────────────────────────────────")
    print(f"Total unique records: {len(df)}")
    print(f"Unique users:         {df['user_id'].nunique()}")

    print(f"\n── Records per year ─────────────────────────────────")
    year_counts = df['post_year'].value_counts().sort_index()
    for yr, count in year_counts.items():
        print(f"  {int(yr)}: {count} photos")

else:
    print("No records collected.")

print(f"\n{'='*70}")
print("Scraping complete!")
print(f"{'='*70}")

# ── SAVE RAW RECORDS TO EXCEL ─────────────────────────────────────────────────

if 'all_records' in locals() and all_records:
    raw_df = pd.DataFrame(all_records)
    raw_filename_excel = f"Flickr_AlaArcha_RAW_RECORDS_{TODAY}.xlsx"
    raw_df.to_excel(raw_filename_excel, index=False)
    print(f"\nRaw records (before processing) saved to: {raw_filename_excel}")
else:
    print("\nNo raw records found to save.")


# ---- FLICKR — Ugam-Chatkal ----

# =============================================================================
# Flickr Photo Scraper — Ugam-Chatkal National Park (HYBRID APPROACH)
# Combines: Geographic Bounding Box + Keyword Search
# API: https://api.flickr.com/services/rest/
# Compatible with: Google Colab, Local Python
# =============================================================================

import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

# ── STEP 2: Configuration ─────────────────────────────────────────────────────

FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ugam-Chatkal National Park"
COUNTRY    = "Uzbekistan"

# Geographic bounding box (for geotagged photos)
BBOX = "69.5,41.2,70.5,42.0"
LAT_MIN, LAT_MAX = 41.2, 42.0
LNG_MIN, LNG_MAX = 69.5, 70.5

# Keyword search terms (for non-geotagged photos)
# Based on popular destinations and attractions
KEYWORDS = [
    # Park name (primary keywords)
    "Ugam-Chatkal",
    "Ugam Chatkal",

    # Major ski resorts and villages (most photographed areas)
    "Chimgan",  # Big/Greater Chimgan peak and village
    "Beldersay",  # Ski resort
    "Amirsoy",  # Modern ski resort

    # Major water features
    "Charvak",  # Charvak Lake/Reservoir - most popular attraction

    # Natural attractions
    "Gulkam Canyon",  # Popular canyon with waterfalls
    "Pulatkhan",  # Highland plateau

    # Other notable features
    "Urungach",  # Mountain lakes
    "Kumbel",  # Mountain/pass with petroglyphs
]

DATE_START = "2010-01-01"
DATE_END   = "2025-12-31"

PER_PAGE         = 250
BASE_DELAY       = 2.0
YEAR_PAUSE       = 30
MAX_RETRIES      = 5
FLICKR_MAX_ROWS  = 4000

SCRAPE_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY            = datetime.now().strftime("%Y-%m-%d")

# ── STEP 3: Helper Functions ──────────────────────────────────────────────────

def generate_record_id():
    return "FLICKR-" + str(uuid.uuid4())[:8].upper()

def get_elevation_estimate(latitude, longitude):
    """Estimates elevation based on latitude and longitude."""
    if not latitude or not longitude:
        return 0

    try:
        lat = float(latitude)
        lng = float(longitude)

        # Base elevation from latitude
        if lat >= 41.85:
            base_elev = 2500
        elif lat >= 41.70:
            base_elev = 2000
        elif lat >= 41.55:
            base_elev = 1600
        elif lat >= 41.40:
            base_elev = 1300
        else:
            base_elev = 1100

        # Adjust for longitude (eastern areas higher)
        if lng >= 70.2:
            base_elev += 500
        elif lng >= 69.9:
            base_elev += 0
        else:
            base_elev -= 200

        return max(900, base_elev)

    except (ValueError, TypeError):
        return 0

def flickr_request(params, max_retries=MAX_RETRIES):
    """Makes a Flickr API GET request with exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = requests.get(BASE_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if data.get("stat") == "ok":
                    return data
                else:
                    print(f"  [Flickr Error] {data.get('message', 'Unknown error')}")
                    return None

            elif response.status_code == 429:
                wait_time = (2 ** attempt) * 10
                print(f"  [429 Rate limited] Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)

            elif response.status_code == 500:
                print(f"  [500 Server Error] Waiting 15s before retry...")
                time.sleep(15)

            else:
                print(f"  [HTTP {response.status_code}] Skipping request.")
                return None

        except requests.exceptions.Timeout:
            print(f"  [Timeout] Attempt {attempt + 1}. Retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            print(f"  [Exception] {e}")
            return None

    print("  [Failed] Max retries reached. Skipping.")
    return None

def parse_photo(photo, source_method=""):
    """Maps a Flickr photo to metadata schema."""
    owner      = photo.get("owner", "")
    photo_id   = str(photo.get("id", ""))
    title      = photo.get("title", "")
    tags       = photo.get("tags", "")
    date_taken = photo.get("datetaken", "")
    url_m      = photo.get("url_m", "")
    views      = photo.get("views", "")

    latitude   = photo.get("latitude", "")
    longitude  = photo.get("longitude", "")

    # Extract year and month
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

    # Construct Flickr page URL
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

    # Combine title and tags
    text_content = " ".join(filter(None, [title, tags])).strip()

    # Estimate elevation
    estimated_elevation = get_elevation_estimate(latitude, longitude)

    # Determine spatial confidence
    has_coords = bool(latitude and longitude)
    if has_coords:
        try:
            lat_f = float(latitude)
            lng_f = float(longitude)
            in_bbox = (LAT_MIN <= lat_f <= LAT_MAX) and (LNG_MIN <= lng_f <= LNG_MAX)
            spatial_confidence = "high" if in_bbox else "medium"
        except:
            spatial_confidence = "medium"
    else:
        spatial_confidence = "low"

    return {
        "record_id":          generate_record_id(),
        "platform":           "Flickr",
        "platform_record_id": photo_id,
        "content_type":       "photo",
        "text_content":       text_content,
        "media_url":          url_m,
        "post_url":           post_url,
        "user_id":            owner,
        "post_timestamp_raw": date_taken,
        "post_year":          post_year,
        "post_month":         post_month,
        "latitude_raw":       latitude,
        "longitude_raw":      longitude,
        "estimated_elevation": estimated_elevation,
        "location_name_raw":  "",
        "poi_id":             "",
        "poi_name":           "",
        "park_name":          PARK_NAME,
        "country":            COUNTRY,
        "likes_count":        "",
        "comments_count":     "",
        "rating_score":       "",
        "detected_language":  "",
        "scrape_timestamp":   SCRAPE_TIMESTAMP,
        "tags_raw":           tags,
        "views_count":        views,
        "spatial_confidence": spatial_confidence,
        "collection_method":  source_method
    }

def build_params_geo(date_start, date_end, page=1):
    """Builds params for geographic bbox search."""
    return {
        "method":          "flickr.photos.search",
        "api_key":         FLICKR_API_KEY,
        "bbox":            BBOX,
        "min_taken_date":  date_start,
        "max_taken_date":  date_end,
        "has_geo":         1,
        "extras":          "geo,date_taken,date_upload,owner_name,tags,url_m,views",
        "per_page":        PER_PAGE,
        "page":            page,
        "format":          "json",
        "nojsoncallback":  1,
        "sort":            "date-taken-asc"
    }

def build_params_keyword(keyword, date_start, date_end, page=1):
    """Builds params for keyword search."""
    return {
        "method":          "flickr.photos.search",
        "api_key":         FLICKR_API_KEY,
        "text":            keyword,
        "min_taken_date":  date_start,
        "max_taken_date":  date_end,
        "extras":          "geo,date_taken,date_upload,owner_name,tags,url_m,views",
        "per_page":        PER_PAGE,
        "page":            page,
        "format":          "json",
        "nojsoncallback":  1,
        "sort":            "date-taken-asc"
    }

def collect_range_geo(date_start, date_end, label=""):
    """Collects photos using geographic bbox search."""
    records = []
    page = 1
    total_pages = None

    while True:
        params = build_params_geo(date_start, date_end, page=page)
        data = flickr_request(params)

        if data is None:
            print(f"  Request failed on page {page}. Stopping.")
            break

        photos_block = data.get("photos", {})
        total_available = int(photos_block.get("total", 0))
        total_pages = int(photos_block.get("pages", 0))
        photos = photos_block.get("photo", [])

        if page == 1:
            print(f"  {label} Total: {total_available} | Pages: {total_pages}")

        if not photos:
            break

        for photo in photos:
            records.append(parse_photo(photo, source_method="geographic_bbox"))

        print(f"  Page {page}/{total_pages} — {len(photos)} photos. Total: {len(records)}")

        if page >= total_pages:
            break

        page += 1
        time.sleep(BASE_DELAY)

    return records

def collect_range_keyword(keyword, date_start, date_end, label=""):
    """Collects photos using keyword search."""
    records = []
    page = 1
    total_pages = None

    while True:
        params = build_params_keyword(keyword, date_start, date_end, page=page)
        data = flickr_request(params)

        if data is None:
            print(f"  Request failed on page {page}. Stopping.")
            break

        photos_block = data.get("photos", {})
        total_available = int(photos_block.get("total", 0))
        total_pages = int(photos_block.get("pages", 0))
        photos = photos_block.get("photo", [])

        if page == 1:
            print(f"  {label} Total: {total_available} | Pages: {total_pages}")

        if not photos:
            break

        for photo in photos:
            records.append(parse_photo(photo, source_method=f"keyword_{keyword}"))

        print(f"  Page {page}/{total_pages} — {len(photos)} photos. Total: {len(records)}")

        if page >= total_pages:
            break

        page += 1
        time.sleep(BASE_DELAY)

    return records

# ── STEP 4: Main Collection Logic ─────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"Flickr HYBRID Scraper — {PARK_NAME}, {COUNTRY}")
print(f"Methods: Geographic BBox + Keyword Search")
print(f"{'='*70}\n")

all_records = []

# ═══════════════════════════════════════════════════════════════════════════
# METHOD 1: GEOGRAPHIC BOUNDING BOX
# ═══════════════════════════════════════════════════════════════════════════

print(f"\n{'─'*70}")
print("METHOD 1: Geographic Bounding Box Search")
print(f"Bbox: {BBOX}")
print(f"{'─'*70}\n")

print("Probing geographic search...")
probe_data = flickr_request(build_params_geo(DATE_START, DATE_END, page=1))

if probe_data is None:
    print("Geographic search failed. Check your API key.")
else:
    total_geo = int(probe_data.get("photos", {}).get("total", 0))
    print(f"Total geotagged photos in bbox: {total_geo}")

    if total_geo > 0:
        if total_geo <= FLICKR_MAX_ROWS:
            print(f"\nRunning single geographic query...")
            records = collect_range_geo(DATE_START, DATE_END, label="Geographic:")
            all_records.extend(records)
        else:
            print(f"\nTotal exceeds {FLICKR_MAX_ROWS}. Splitting by year...")
            for year in range(2010, 2026):
                y_start = f"{year}-01-01"
                y_end = f"{year}-12-31"
                print(f"\n── Year {year} (Geographic) ──")
                records = collect_range_geo(y_start, y_end, label=f"Geo {year}:")
                all_records.extend(records)
                if year < 2025:
                    time.sleep(YEAR_PAUSE)

# ═══════════════════════════════════════════════════════════════════════════
# METHOD 2: KEYWORD SEARCH
# ═══════════════════════════════════════════════════════════════════════════

print(f"\n{'─'*70}")
print("METHOD 2: Keyword Search")
print(f"Keywords: {KEYWORDS}")
print(f"{'─'*70}\n")

for keyword in KEYWORDS:
    print(f"\n▸ Searching keyword: '{keyword}'")

    probe_data = flickr_request(build_params_keyword(keyword, DATE_START, DATE_END, page=1))

    if probe_data is None:
        print(f"  Keyword search failed for '{keyword}'. Skipping.")
        continue

    total_keyword = int(probe_data.get("photos", {}).get("total", 0))
    print(f"  Total results for '{keyword}': {total_keyword}")

    if total_keyword == 0:
        continue

    if total_keyword <= FLICKR_MAX_ROWS:
        print(f"  Running single keyword query...")
        records = collect_range_keyword(keyword, DATE_START, DATE_END, label=f"Keyword '{keyword}':")
        all_records.extend(records)
    else:
        print(f"  Total exceeds {FLICKR_MAX_ROWS}. Splitting by year...")
        for year in range(2010, 2026):
            y_start = f"{year}-01-01"
            y_end = f"{year}-12-31"
            print(f"\n  ── Year {year} (Keyword: {keyword}) ──")
            records = collect_range_keyword(keyword, y_start, y_end, label=f"KW '{keyword}' {year}:")
            all_records.extend(records)
            if year < 2025:
                time.sleep(YEAR_PAUSE)

    # Pause between keywords
    print(f"  Pausing 10s before next keyword...")
    time.sleep(10)

# ── STEP 5: Deduplicate & Process ─────────────────────────────────────────────

print(f"\n{'='*70}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

    # Deduplicate by photo ID
    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"], keep="first")
    print(f"After deduplication: {len(df)} unique records (removed {before - len(df)} duplicates)")

    # Show breakdown by collection method
    print(f"\n── Collection Method Breakdown ──────────────────────")
    method_counts = df['collection_method'].value_counts()
    for method, count in method_counts.items():
        print(f"  {method}: {count} photos")

    # Show geotagged vs non-geotagged
    print(f"\n── Geolocation Status ───────────────────────────────")
    has_coords = df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')]
    no_coords = df[(df['latitude_raw'] == '') | (df['longitude_raw'] == '')]
    print(f"  With coordinates: {len(has_coords)} ({len(has_coords)/len(df)*100:.1f}%)")
    print(f"  Without coordinates: {len(no_coords)} ({len(no_coords)/len(df)*100:.1f}%)")

    # Show spatial confidence distribution
    print(f"\n── Spatial Confidence ───────────────────────────────")
    confidence_counts = df['spatial_confidence'].value_counts()
    for conf, count in confidence_counts.items():
        print(f"  {conf}: {count} photos")

    # Optional: Filter by elevation (only for geotagged photos)
    print(f"\n── Elevation Filtering (Geotagged only) ─────────────")
    geotagged_before = len(has_coords)

    # Keep all non-geotagged + geotagged with sufficient elevation
    keep_mask = (
        ((df['latitude_raw'] == '') | (df['longitude_raw'] == '')) |
        (df['estimated_elevation'] >= 900)
    )

    df = df[keep_mask]
    geotagged_after = len(df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')])
    removed = geotagged_before - geotagged_after

    print(f"Removed {removed} low-elevation geotagged photos (< 900m)")
    print(f"Kept all {len(no_coords)} non-geotagged photos from keyword search")
    print(f"Final total: {len(df)} photos")

    # ── STEP 6: Enforce Column Order ──────────────────────────────────────────

    schema_columns = [
        "record_id", "platform", "platform_record_id",
        "content_type", "text_content", "media_url", "post_url",
        "user_id", "post_timestamp_raw", "post_year", "post_month",
        "latitude_raw", "longitude_raw", "estimated_elevation",
        "location_name_raw", "poi_id", "poi_name", "park_name", "country",
        "likes_count", "comments_count", "rating_score",
        "detected_language", "scrape_timestamp",
        "tags_raw", "views_count", "spatial_confidence", "collection_method"
    ]
    df = df[schema_columns]

    # ── STEP 7: Export ────────────────────────────────────────────────────────

    filename_csv   = f"Flickr_UgamChatkal_HYBRID_{TODAY}.csv"
    filename_excel = f"Flickr_UgamChatkal_HYBRID_{TODAY}.xlsx"

    df.to_csv(filename_csv, index=False, encoding="utf-8-sig")
    df.to_excel(filename_excel, index=False)

    print(f"\n{'='*70}")
    print("Files saved:")
    print(f"  CSV:   {filename_csv}")
    print(f"  Excel: {filename_excel}")

    # ── STEP 8: Summary ───────────────────────────────────────────────────────

    print(f"\n── Final Summary ────────────────────────────────────")
    print(f"Total unique records: {len(df)}")
    print(f"Unique users:         {df['user_id'].nunique()}")

    print(f"\n── Records per year ─────────────────────────────────")
    year_counts = df['post_year'].value_counts().sort_index()
    for yr, count in year_counts.items():
        print(f"  {int(yr)}: {count} photos")

else:
    print("No records collected.")

print(f"\n{'='*70}")
print("Scraping complete!")
print(f"{'='*70}")

raw_df = pd.DataFrame(all_records)
raw_filename_excel = f"Flickr_UgamChatkal_RAW_{TODAY}.xlsx"
raw_df.to_excel(raw_filename_excel, index=False)
print(f"Raw dataset saved to: {raw_filename_excel}")
print(f"Total raw records: {len(raw_df)}")


# ---- STRAVA — Ile-Alatau ----

# =============================================================================
# Strava Segment Explorer — Ile-Alatau National Park (Google Colab version)
# =============================================================================
# Run each cell in order. Paste your Strava access token when prompted.
#
# Endpoint used: GET /api/v3/segments/explore  (read scope is sufficient)
# Docs:          https://developers.strava.com/docs/reference/#api-Segments-exploreSegments
# =============================================================================


# -----------------------------------------------------------------------------
# CELL 1 — Install dependencies
# -----------------------------------------------------------------------------
!pip install -q polyline requests tqdm


# -----------------------------------------------------------------------------
# CELL 2 — Imports + config
# -----------------------------------------------------------------------------
import csv
import json
import time
from getpass import getpass
from pathlib import Path

import polyline
import requests
from tqdm.auto import tqdm

# --- Token input (won't be visible in the notebook) ---
ACCESS_TOKEN = getpass("Paste your Strava access token: ").strip()

# --- Ile-Alatau bounding box (decimal degrees, from UNESCO source) ---
SW_LAT, SW_LNG = 42.8083, 76.5033   # south-west corner
NE_LAT, NE_LNG = 43.3264, 77.8408   # north-east corner

# Grid step in degrees. 0.10 ≈ ~11 km. Smaller = more calls but better coverage.
STEP = 0.10

ACTIVITY_TYPES = ["running", "riding"]
SLEEP_BETWEEN_CALLS = 1.0   # seconds, to stay well under 100 req / 15 min

OUT_JSON    = Path("ile_alatau_segments.json")
OUT_CSV     = Path("ile_alatau_segments.csv")
OUT_GEOJSON = Path("ile_alatau_segments.geojson")

STRAVA_EXPLORE_URL = "https://www.strava.com/api/v3/segments/explore"


# -----------------------------------------------------------------------------
# CELL 3 — Helpers
# -----------------------------------------------------------------------------
def make_grid(sw_lat, sw_lng, ne_lat, ne_lng, step):
    """Tile the bbox into smaller cells."""
    tiles = []
    lat = sw_lat
    while lat < ne_lat:
        lng = sw_lng
        while lng < ne_lng:
            tiles.append((
                round(lat, 6),
                round(lng, 6),
                round(min(lat + step, ne_lat), 6),
                round(min(lng + step, ne_lng), 6),
            ))
            lng += step
        lat += step
    return tiles


def explore_segments(bbox, activity_type, token):
    """Call /segments/explore for a single tile."""
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    params = {
        "bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}",
        "activity_type": activity_type,
    }
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        resp = requests.get(STRAVA_EXPLORE_URL, params=params, headers=headers, timeout=30)

        if resp.status_code == 200:
            return resp.json().get("segments", [])

        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized — token invalid or expired.")

        if resp.status_code == 429:
            print(" Rate limit hit — sleeping 15 min...")
            time.sleep(15 * 60 + 5)
            continue

        print(f"HTTP {resp.status_code} for {bbox} ({activity_type}): {resp.text[:200]}")
        return []


def segment_to_geojson_feature(seg):
    coords = [[lng, lat] for lat, lng in polyline.decode(seg.get("points", ""))]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": seg.get("id"),
            "name": seg.get("name"),
            "activity_type": seg.get("activity_type"),
            "distance_m": seg.get("distance"),
            "avg_grade": seg.get("avg_grade"),
            "elev_difference_m": seg.get("elev_difference"),
            "climb_category": seg.get("climb_category"),
            "start_latlng": seg.get("start_latlng"),
            "end_latlng": seg.get("end_latlng"),
            "strava_url": f"https://www.strava.com/segments/{seg.get('id')}",
        },
    }


# -----------------------------------------------------------------------------
# CELL 4 — Run the scrape
# -----------------------------------------------------------------------------
tiles = make_grid(SW_LAT, SW_LNG, NE_LAT, NE_LNG, STEP)
total_calls = len(tiles) * len(ACTIVITY_TYPES)
print(f"Bounding box: ({SW_LAT}, {SW_LNG}) -> ({NE_LAT}, {NE_LNG})")
print(f"Grid: {len(tiles)} tiles × {len(ACTIVITY_TYPES)} activity types = {total_calls} API calls")
print(f"Estimated time: ~{total_calls * SLEEP_BETWEEN_CALLS / 60:.1f} min")

all_segments = {}

with tqdm(total=total_calls, desc="Querying Strava") as pbar:
    for activity in ACTIVITY_TYPES:
        for bbox in tiles:
            segs = explore_segments(bbox, activity, ACCESS_TOKEN)
            for s in segs:
                sid = s.get("id")
                if sid is not None and sid not in all_segments:
                    s["activity_type"] = activity
                    all_segments[sid] = s
            pbar.set_postfix({"unique": len(all_segments)})
            pbar.update(1)
            time.sleep(SLEEP_BETWEEN_CALLS)

print(f"\nTotal unique segments collected: {len(all_segments)}")


# -----------------------------------------------------------------------------
# CELL 5 — Save outputs
# -----------------------------------------------------------------------------
segments_list = list(all_segments.values())

# JSON
OUT_JSON.write_text(json.dumps(segments_list, ensure_ascii=False, indent=2))

# CSV
with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "id", "name", "activity_type", "distance_m", "avg_grade",
        "elev_difference_m", "climb_category",
        "start_lat", "start_lng", "end_lat", "end_lng", "strava_url",
    ])
    for s in segments_list:
        start = s.get("start_latlng") or [None, None]
        end   = s.get("end_latlng")   or [None, None]
        writer.writerow([
            s.get("id"), s.get("name"), s.get("activity_type"),
            s.get("distance"), s.get("avg_grade"),
            s.get("elev_difference"), s.get("climb_category"),
            start[0], start[1], end[0], end[1],
            f"https://www.strava.com/segments/{s.get('id')}",
        ])

# GeoJSON
geojson = {
    "type": "FeatureCollection",
    "features": [segment_to_geojson_feature(s) for s in segments_list],
}
OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False))

print(f"Saved: {OUT_JSON}, {OUT_CSV}, {OUT_GEOJSON}")


# -----------------------------------------------------------------------------
# CELL 6 — Preview in Colab + download
# -----------------------------------------------------------------------------
import pandas as pd
from google.colab import files

df = pd.read_csv(OUT_CSV)
print(f"\nFirst 10 segments:")
display(df.head(10))

# Download all three files
files.download(str(OUT_JSON))
files.download(str(OUT_CSV))
files.download(str(OUT_GEOJSON))


# -----------------------------------------------------------------------------
# CELL 7 (optional) — Quick visualization on a folium map
# -----------------------------------------------------------------------------
!pip install -q folium
import folium

center_lat = (SW_LAT + NE_LAT) / 2
center_lng = (SW_LNG + NE_LNG) / 2
m = folium.Map(location=[center_lat, center_lng], zoom_start=10, tiles="OpenStreetMap")

# Draw park bbox
folium.Rectangle(
    bounds=[[SW_LAT, SW_LNG], [NE_LAT, NE_LNG]],
    color="red", weight=2, fill=False, popup="Ile-Alatau bbox",
).add_to(m)

# Draw each segment polyline
for s in segments_list:
    pts = polyline.decode(s.get("points", ""))
    if not pts:
        continue
    color = "blue" if s.get("activity_type") == "running" else "green"
    folium.PolyLine(
        pts, color=color, weight=2, opacity=0.7,
        popup=f"{s.get('name')} ({s.get('activity_type')})<br>"
              f"{s.get('distance', 0):.0f} m, {s.get('avg_grade', 0):.1f}% grade<br>"
              f"<a href='https://www.strava.com/segments/{s.get('id')}' target='_blank'>Open on Strava</a>",
    ).add_to(m)

m


# ---- STRAVA — Ala-Archa ----

# =============================================================================
# Strava Segment Explorer — Ala-Archa National Park (Google Colab version)
# =============================================================================
# Run each cell in order. Paste your Strava access token when prompted.
#
# Endpoint used: GET /api/v3/segments/explore  (read scope is sufficient)
# Docs:          https://developers.strava.com/docs/reference/#api-Segments-exploreSegments
# =============================================================================


# -----------------------------------------------------------------------------
# CELL 1 — Install dependencies
# -----------------------------------------------------------------------------
!pip install -q polyline requests tqdm


# -----------------------------------------------------------------------------
# CELL 2 — Imports + config
# -----------------------------------------------------------------------------
import csv
import json
import time
from getpass import getpass
from pathlib import Path

import polyline
import requests
from tqdm.auto import tqdm

# --- Token input (won't be visible in the notebook) ---
ACCESS_TOKEN = getpass("Paste your Strava access token: ").strip()

# --- Ala-Archa National Park bounding box (decimal degrees) ---
# Centered ~35-40 km south of Bishkek, covers the gorge from the entrance
# south to Semenov-Tyan-Shansky Peak (4,875 m) on the Kyrgyz Ala-Too main ridge.
SW_LAT, SW_LNG = 42.42, 74.40   # south-west corner
NE_LAT, NE_LNG = 42.62, 74.55   # north-east corner

# Grid step in degrees. Park is small, so use 0.05° (~5 km) for detail.
STEP = 0.05

ACTIVITY_TYPES = ["running", "riding"]
SLEEP_BETWEEN_CALLS = 10.0   # seconds — stay well under 100 req / 15 min

OUT_JSON    = Path("ala_archa_segments.json")
OUT_CSV     = Path("ala_archa_segments.csv")
OUT_GEOJSON = Path("ala_archa_segments.geojson")

STRAVA_EXPLORE_URL = "https://www.strava.com/api/v3/segments/explore"


# -----------------------------------------------------------------------------
# CELL 3 — Helpers
# -----------------------------------------------------------------------------
def make_grid(sw_lat, sw_lng, ne_lat, ne_lng, step):
    tiles = []
    lat = sw_lat
    while lat < ne_lat:
        lng = sw_lng
        while lng < ne_lng:
            tiles.append((
                round(lat, 6),
                round(lng, 6),
                round(min(lat + step, ne_lat), 6),
                round(min(lng + step, ne_lng), 6),
            ))
            lng += step
        lat += step
    return tiles


def explore_segments(bbox, activity_type, token):
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    params = {
        "bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}",
        "activity_type": activity_type,
    }
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        resp = requests.get(STRAVA_EXPLORE_URL, params=params, headers=headers, timeout=30)

        if resp.status_code == 200:
            return resp.json().get("segments", [])

        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized — token invalid or expired.")

        if resp.status_code == 429:
            print(" Rate limit hit — sleeping 15 min...")
            time.sleep(15 * 60 + 5)
            continue

        print(f"HTTP {resp.status_code} for {bbox} ({activity_type}): {resp.text[:200]}")
        return []


def segment_to_geojson_feature(seg):
    coords = [[lng, lat] for lat, lng in polyline.decode(seg.get("points", ""))]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": seg.get("id"),
            "name": seg.get("name"),
            "activity_type": seg.get("activity_type"),
            "distance_m": seg.get("distance"),
            "avg_grade": seg.get("avg_grade"),
            "elev_difference_m": seg.get("elev_difference"),
            "climb_category": seg.get("climb_category"),
            "start_latlng": seg.get("start_latlng"),
            "end_latlng": seg.get("end_latlng"),
            "strava_url": f"https://www.strava.com/segments/{seg.get('id')}",
        },
    }


# -----------------------------------------------------------------------------
# CELL 4 — Run the scrape
# -----------------------------------------------------------------------------
tiles = make_grid(SW_LAT, SW_LNG, NE_LAT, NE_LNG, STEP)
total_calls = len(tiles) * len(ACTIVITY_TYPES)
print(f"Bounding box: ({SW_LAT}, {SW_LNG}) -> ({NE_LAT}, {NE_LNG})")
print(f"Grid: {len(tiles)} tiles × {len(ACTIVITY_TYPES)} activity types = {total_calls} API calls")
print(f"Estimated time: ~{total_calls * SLEEP_BETWEEN_CALLS / 60:.1f} min")

all_segments = {}

with tqdm(total=total_calls, desc="Querying Strava") as pbar:
    for activity in ACTIVITY_TYPES:
        for bbox in tiles:
            segs = explore_segments(bbox, activity, ACCESS_TOKEN)
            for s in segs:
                sid = s.get("id")
                if sid is not None and sid not in all_segments:
                    s["activity_type"] = activity
                    all_segments[sid] = s
            pbar.set_postfix({"unique": len(all_segments)})
            pbar.update(1)
            time.sleep(SLEEP_BETWEEN_CALLS)

print(f"\nTotal unique segments collected: {len(all_segments)}")


# -----------------------------------------------------------------------------
# CELL 5 — Save outputs (JSON + CSV + Excel + GeoJSON)
# -----------------------------------------------------------------------------
import pandas as pd

segments_list = list(all_segments.values())

# --- JSON (raw) ---
OUT_JSON.write_text(json.dumps(segments_list, ensure_ascii=False, indent=2))

# --- Build a clean DataFrame for CSV / Excel ---
df = pd.DataFrame(segments_list)
df['start_lat'] = df['start_latlng'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
df['start_lng'] = df['start_latlng'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)
df['end_lat']   = df['end_latlng'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
df['end_lng']   = df['end_latlng'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)
df['strava_url'] = 'https://www.strava.com/segments/' + df['id'].astype(str)

cols = [
    'id', 'name', 'activity_type', 'distance', 'avg_grade', 'elev_difference',
    'climb_category', 'climb_category_desc', 'starred', 'local_legend_enabled',
    'start_lat', 'start_lng', 'end_lat', 'end_lng',
    'strava_url', 'elevation_profile', 'points',
]
df = df[[c for c in cols if c in df.columns]]

df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
df.to_excel("ala_archa_segments.xlsx", index=False, sheet_name="Segments")

# --- GeoJSON ---
geojson = {
    "type": "FeatureCollection",
    "features": [segment_to_geojson_feature(s) for s in segments_list],
}
OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False))

print(f"Saved: {OUT_JSON}, {OUT_CSV}, ala_archa_segments.xlsx, {OUT_GEOJSON}")


# -----------------------------------------------------------------------------
# CELL 6 — Preview + download
# -----------------------------------------------------------------------------
from google.colab import files

print(f"\nFirst 10 segments:")
display(df.head(10))

print(f"\nActivity type breakdown:")
print(df['activity_type'].value_counts())

files.download(str(OUT_JSON))
files.download(str(OUT_CSV))
files.download("ala_archa_segments.xlsx")
files.download(str(OUT_GEOJSON))


# -----------------------------------------------------------------------------
# CELL 7 (optional) — Quick visualization on a folium map
# -----------------------------------------------------------------------------
!pip install -q folium
import folium

center_lat = (SW_LAT + NE_LAT) / 2
center_lng = (SW_LNG + NE_LNG) / 2
m = folium.Map(location=[center_lat, center_lng], zoom_start=12, tiles="OpenStreetMap")

# Draw park bbox
folium.Rectangle(
    bounds=[[SW_LAT, SW_LNG], [NE_LAT, NE_LNG]],
    color="red", weight=2, fill=False, popup="Ala-Archa bbox",
).add_to(m)

# Draw each segment polyline
for s in segments_list:
    pts = polyline.decode(s.get("points", ""))
    if not pts:
        continue
    color = "blue" if s.get("activity_type") == "running" else "green"
    folium.PolyLine(
        pts, color=color, weight=2, opacity=0.7,
        popup=f"{s.get('name')} ({s.get('activity_type')})<br>"
              f"{s.get('distance', 0):.0f} m, {s.get('avg_grade', 0):.1f}% grade<br>"
              f"<a href='https://www.strava.com/segments/{s.get('id')}' target='_blank'>Open on Strava</a>",
    ).add_to(m)

m


# ---- STRAVA — Ugam-Chatkal ----

# =============================================================================
# Strava Segment Explorer — Ugam-Chatkal National Park (Google Colab version)
# =============================================================================
# Run each cell in order. Paste your Strava access token when prompted.
#
# Endpoint used: GET /api/v3/segments/explore  (read scope is sufficient)
# Docs:          https://developers.strava.com/docs/reference/#api-Segments-exploreSegments
# =============================================================================


# -----------------------------------------------------------------------------
# CELL 1 — Install dependencies
# -----------------------------------------------------------------------------
!pip install -q polyline requests tqdm


# -----------------------------------------------------------------------------
# CELL 2 — Imports + config
# -----------------------------------------------------------------------------
import csv
import json
import time
from getpass import getpass
from pathlib import Path

import polyline
import requests
from tqdm.auto import tqdm

# --- Token input (won't be visible in the notebook) ---
ACCESS_TOKEN = getpass("Paste your Strava access token: ").strip()

# --- Ugam-Chatkal National Park bounding box (decimal degrees) ---
# Largest of the three parks: ~574,000 hectares.
# Covers Chatkal, Pskem, Ugam ranges in NE Tashkent Region, from Charvak/Chimgan
# area in the south up to Adelunga Peak / Kyrgyz border in the north.
SW_LAT, SW_LNG = 41.40, 70.00   # south-west corner
NE_LAT, NE_LNG = 42.20, 71.30   # north-east corner

# Grid step. 0.10° (~11 km) — same as Ile-Alatau.
STEP = 0.10

ACTIVITY_TYPES = ["running", "riding"]
SLEEP_BETWEEN_CALLS = 10.0   # seconds — stay under 100 req / 15 min

OUT_JSON    = Path("ugam_chatkal_segments.json")
OUT_CSV     = Path("ugam_chatkal_segments.csv")
OUT_GEOJSON = Path("ugam_chatkal_segments.geojson")

STRAVA_EXPLORE_URL = "https://www.strava.com/api/v3/segments/explore"


# -----------------------------------------------------------------------------
# CELL 3 — Helpers
# -----------------------------------------------------------------------------
def make_grid(sw_lat, sw_lng, ne_lat, ne_lng, step):
    tiles = []
    lat = sw_lat
    while lat < ne_lat:
        lng = sw_lng
        while lng < ne_lng:
            tiles.append((
                round(lat, 6),
                round(lng, 6),
                round(min(lat + step, ne_lat), 6),
                round(min(lng + step, ne_lng), 6),
            ))
            lng += step
        lat += step
    return tiles


def explore_segments(bbox, activity_type, token):
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    params = {
        "bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}",
        "activity_type": activity_type,
    }
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        resp = requests.get(STRAVA_EXPLORE_URL, params=params, headers=headers, timeout=30)

        if resp.status_code == 200:
            return resp.json().get("segments", [])

        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized — token invalid or expired.")

        if resp.status_code == 429:
            print(" Rate limit hit — sleeping 15 min...")
            time.sleep(15 * 60 + 5)
            continue

        print(f"HTTP {resp.status_code} for {bbox} ({activity_type}): {resp.text[:200]}")
        return []


def segment_to_geojson_feature(seg):
    coords = [[lng, lat] for lat, lng in polyline.decode(seg.get("points", ""))]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": seg.get("id"),
            "name": seg.get("name"),
            "activity_type": seg.get("activity_type"),
            "distance_m": seg.get("distance"),
            "avg_grade": seg.get("avg_grade"),
            "elev_difference_m": seg.get("elev_difference"),
            "climb_category": seg.get("climb_category"),
            "start_latlng": seg.get("start_latlng"),
            "end_latlng": seg.get("end_latlng"),
            "strava_url": f"https://www.strava.com/segments/{seg.get('id')}",
        },
    }


# -----------------------------------------------------------------------------
# CELL 4 — Run the scrape
# -----------------------------------------------------------------------------
tiles = make_grid(SW_LAT, SW_LNG, NE_LAT, NE_LNG, STEP)
total_calls = len(tiles) * len(ACTIVITY_TYPES)
print(f"Bounding box: ({SW_LAT}, {SW_LNG}) -> ({NE_LAT}, {NE_LNG})")
print(f"Grid: {len(tiles)} tiles × {len(ACTIVITY_TYPES)} activity types = {total_calls} API calls")
print(f"Estimated time: ~{total_calls * SLEEP_BETWEEN_CALLS / 60:.1f} min")

all_segments = {}

with tqdm(total=total_calls, desc="Querying Strava") as pbar:
    for activity in ACTIVITY_TYPES:
        for bbox in tiles:
            segs = explore_segments(bbox, activity, ACCESS_TOKEN)
            for s in segs:
                sid = s.get("id")
                if sid is not None and sid not in all_segments:
                    s["activity_type"] = activity
                    all_segments[sid] = s
            pbar.set_postfix({"unique": len(all_segments)})
            pbar.update(1)
            time.sleep(SLEEP_BETWEEN_CALLS)

print(f"\nTotal unique segments collected: {len(all_segments)}")


# -----------------------------------------------------------------------------
# CELL 5 — Save outputs (JSON + CSV + Excel + GeoJSON)
# -----------------------------------------------------------------------------
import pandas as pd

segments_list = list(all_segments.values())

# --- JSON (raw) ---
OUT_JSON.write_text(json.dumps(segments_list, ensure_ascii=False, indent=2))

# --- Build a clean DataFrame for CSV / Excel ---
df = pd.DataFrame(segments_list)
df['start_lat'] = df['start_latlng'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
df['start_lng'] = df['start_latlng'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)
df['end_lat']   = df['end_latlng'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
df['end_lng']   = df['end_latlng'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)
df['strava_url'] = 'https://www.strava.com/segments/' + df['id'].astype(str)

cols = [
    'id', 'name', 'activity_type', 'distance', 'avg_grade', 'elev_difference',
    'climb_category', 'climb_category_desc', 'starred', 'local_legend_enabled',
    'start_lat', 'start_lng', 'end_lat', 'end_lng',
    'strava_url', 'elevation_profile', 'points',
]
df = df[[c for c in cols if c in df.columns]]

df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
df.to_excel("ugam_chatkal_segments.xlsx", index=False, sheet_name="Segments")

# --- GeoJSON ---
geojson = {
    "type": "FeatureCollection",
    "features": [segment_to_geojson_feature(s) for s in segments_list],
}
OUT_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False))

print(f"Saved: {OUT_JSON}, {OUT_CSV}, ugam_chatkal_segments.xlsx, {OUT_GEOJSON}")


# -----------------------------------------------------------------------------
# CELL 6 — Preview + download
# -----------------------------------------------------------------------------
from google.colab import files

print(f"\nFirst 10 segments:")
display(df.head(10))

print(f"\nActivity type breakdown:")
print(df['activity_type'].value_counts())

files.download(str(OUT_JSON))
files.download(str(OUT_CSV))
files.download("ugam_chatkal_segments.xlsx")
files.download(str(OUT_GEOJSON))


# -----------------------------------------------------------------------------
# CELL 7 (optional) — Quick visualization on a folium map
# -----------------------------------------------------------------------------
!pip install -q folium
import folium

center_lat = (SW_LAT + NE_LAT) / 2
center_lng = (SW_LNG + NE_LNG) / 2
m = folium.Map(location=[center_lat, center_lng], zoom_start=10, tiles="OpenStreetMap")

# Draw park bbox
folium.Rectangle(
    bounds=[[SW_LAT, SW_LNG], [NE_LAT, NE_LNG]],
    color="red", weight=2, fill=False, popup="Ugam-Chatkal bbox",
).add_to(m)

# Draw each segment polyline
for s in segments_list:
    pts = polyline.decode(s.get("points", ""))
    if not pts:
        continue
    color = "blue" if s.get("activity_type") == "running" else "green"
    folium.PolyLine(
        pts, color=color, weight=2, opacity=0.7,
        popup=f"{s.get('name')} ({s.get('activity_type')})<br>"
              f"{s.get('distance', 0):.0f} m, {s.get('avg_grade', 0):.1f}% grade<br>"
              f"<a href='https://www.strava.com/segments/{s.get('id')}' target='_blank'>Open on Strava</a>",
    ).add_to(m)

m
