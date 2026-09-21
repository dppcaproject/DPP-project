import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

                                                                                
FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ile-Alatau National Park"

                                                                            
BBOX = "76.50,43.00,77.85,43.33"

                                                                 
LAT_MIN, LAT_MAX = 43.00, 43.33
LNG_MIN, LNG_MAX = 76.50, 77.85

                                                                  
MIN_ELEVATION = 1200                                               

DATE_START = "2015-01-01"
DATE_END   = "2025-12-31"

PER_PAGE         = 250                             
BASE_DELAY       = 2.0                                        
YEAR_PAUSE       = 30                                                     
MAX_RETRIES      = 5                                       
FLICKR_MAX_ROWS  = 4000                                     

SCRAPE_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY            = datetime.now().strftime("%Y-%m-%d")

                                                                                
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

                                                      
        if lat >= 43.20:                      
            return 800
        elif lat >= 43.15:
            return 1100
        elif lat >= 43.10:
            return 1400
        elif lat >= 43.05:
            return 1800
        else:                              
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

                                                                            
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

                                      
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

                                            
    text_content = " ".join(filter(None, [title, tags])).strip()

                                      
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
        "estimated_elevation": estimated_elevation,             
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

                                                                                
print(f"\n{'='*60}")
print(f"Flickr Scraper — {PARK_NAME}")
print(f"Bounding box: {BBOX}")
print(f"Date range: {DATE_START} to {DATE_END}")
print(f"{'='*60}\n")

                                                         
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
                                          
    print(f"\nTotal is under {FLICKR_MAX_ROWS}. Running single query...")
    records, _ = collect_range(DATE_START, DATE_END, label="Full range:")
    all_records.extend(records)

else:
                                                              
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

                                                                                
print(f"\n{'='*60}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"])
    print(f"After deduplication: {len(df)} records (removed {before - len(df)} duplicates)")

                                                                                
    print(f"\n── Elevation Filtering ──────────────────────────────")
    before_elevation = len(df)
    df = df[df['estimated_elevation'] >= MIN_ELEVATION]
    removed_low = before_elevation - len(df)
    print(f"Removed {removed_low} low-elevation photos (< {MIN_ELEVATION}m)")
    print(f"Remaining: {len(df)} park-area photos")

                                                                                
    schema_columns = [
        "record_id", "platform", "platform_record_id",
        "content_type", "text_content", "media_url", "post_url",
        "user_id", "post_timestamp_raw", "post_year", "post_month",
        "latitude_raw", "longitude_raw", "estimated_elevation",                          
        "location_name_raw",
        "poi_id", "poi_name", "park_name",
        "likes_count", "comments_count", "rating_score",
        "detected_language", "scrape_timestamp",
        "tags_raw", "views_count", "spatial_confidence"
    ]
    df = df[schema_columns]

                                                                                
    filename_csv   = f"Flickr_IleAlatau_{TODAY}.csv"
    filename_excel = f"Flickr_IleAlatau_{TODAY}.xlsx"

    df.to_csv(filename_csv, index=False, encoding="utf-8-sig")
    df.to_excel(filename_excel, index=False)

    print(f"\nFiles saved:")
    print(f"  CSV:   {filename_csv}")
    print(f"  Excel: {filename_excel}")

                                                                                
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

                                                   
raw_df = pd.DataFrame(all_records)

                                  
filename_raw_excel = f"Flickr_IleAlatau_RAW_{TODAY}.xlsx"

                                 
raw_df.to_excel(filename_raw_excel, index=False)

print(f"Raw data (before deduplication and elevation filtering) saved to: {filename_raw_excel}")
print(f"Total raw records: {len(raw_df)}")
display(raw_df.head())

                                                        
filename_deduplicated_excel = f"Flickr_IleAlatau_Deduplicated_Filtered_{TODAY}.xlsx"

                                                                           
df.to_excel(filename_deduplicated_excel, index=False)

print(f"Deduplicated and elevation-filtered data saved to: {filename_deduplicated_excel}")
print(f"Total deduplicated and filtered records: {len(df)}")

                                                                            
df_deduplicated_only = raw_df.drop_duplicates(subset=["platform_record_id"])

                                                
filename_deduplicated_only_excel = f"Flickr_IleAlatau_Deduplicated_ONLY_{TODAY}.xlsx"

                                               
df_deduplicated_only.to_excel(filename_deduplicated_only_excel, index=False)

print(f"Deduplicated (but not elevation-filtered) data saved to: {filename_deduplicated_only_excel}")
print(f"Total deduplicated records (before elevation filtering): {len(df_deduplicated_only)}")
display(df_deduplicated_only.head())


import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

                                                                                
FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ala Archa National Park"
COUNTRY    = "Kyrgyzstan"

                                                
BBOX = "74.40,42.433,74.583,42.65"
LAT_MIN, LAT_MAX = 42.433, 42.65
LNG_MIN, LNG_MAX = 74.40, 74.583

                                                 
KEYWORDS = [
    "Ala-Archa",
    "Ala Archa",
    "Ала-Арча",            
    "Алаарча",
]

                                                                                    
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

                            
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

                               
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

                            
    text_content = " ".join(filter(None, [title, tags])).strip()

                        
    estimated_elevation = get_elevation_estimate(latitude, longitude)

                                  
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

def collect_range(date_start, date_end, label="", params_builder=None, **kwargs):
    """Collects photos for a date range using specified params builder."""
    records = []
    page = 1
    total_pages = None
    total_available = None

                                                                     
    source_method_for_parse = kwargs.pop('method', 'unknown')

                                                                          
    keyword_for_builder = kwargs.pop('keyword', None)

    while True:
                                                                      
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

                                                                                
print(f"\n{'='*70}")
print(f"Flickr HYBRID Scraper — {PARK_NAME}, {COUNTRY}")
print(f"Methods: Geographic BBox + Keyword Search")
print(f"{'='*70}\n")

all_records = []

                                                                             
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

                            
    print(f"  Pausing 10s before next keyword...")
    time.sleep(10)

                                                                                
print(f"\n{'='*70}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

                                                                      
    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"], keep="first")
    print(f"After deduplication: {len(df)} unique records (removed {before - len(df)} duplicates)")

                                         
    print(f"\n── Collection Method Breakdown ──────────────────────")
    method_counts = df['collection_method'].value_counts()
    for method, count in method_counts.items():
        print(f"  {method}: {count} photos")

                                     
    print(f"\n── Geolocation Status ───────────────────────────────")
    has_coords = df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')]
    no_coords = df[(df['latitude_raw'] == '') | (df['longitude_raw'] == '')]
    print(f"  With coordinates: {len(has_coords)} ({len(has_coords)/len(df)*100:.1f}%)")
    print(f"  Without coordinates: {len(no_coords)} ({len(no_coords)/len(df)*100:.1f}%)")

                                          
    print(f"\n── Spatial Confidence ───────────────────────────────")
    confidence_counts = df['spatial_confidence'].value_counts()
    for conf, count in confidence_counts.items():
        print(f"  {conf}: {count} photos")

                                                               
    print(f"\n── Elevation Filtering (Geotagged only) ─────────────")
    geotagged_before = len(has_coords)

                                       
    keep_mask = (
                                                             
        ((df['latitude_raw'] == '') | (df['longitude_raw'] == '')) |
                                                         
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

                                                                                
if 'all_records' in locals() and all_records:
    raw_df = pd.DataFrame(all_records)
    raw_filename_excel = f"Flickr_AlaArcha_RAW_RECORDS_{TODAY}.xlsx"
    raw_df.to_excel(raw_filename_excel, index=False)
    print(f"\nRaw records (before processing) saved to: {raw_filename_excel}")
else:
    print("\nNo raw records found to save.")


import requests
import pandas as pd
import time
import uuid
from datetime import datetime, timezone

print("Libraries loaded.")

                                                                                
FLICKR_API_KEY = "f9538091611e71a63aea52e462ef2cbd"

BASE_URL   = "https://api.flickr.com/services/rest/"
PARK_NAME  = "Ugam-Chatkal National Park"
COUNTRY    = "Uzbekistan"

                                                
BBOX = "69.5,41.2,70.5,42.0"
LAT_MIN, LAT_MAX = 41.2, 42.0
LNG_MIN, LNG_MAX = 69.5, 70.5

                                                 
KEYWORDS = [
                                  
    "Ugam-Chatkal",
    "Ugam Chatkal",

                                                              
    "Chimgan",                                        
    "Beldersay",              
    "Amirsoy",                     

                          
    "Charvak",                                                    

                         
    "Gulkam Canyon",                                  
    "Pulatkhan",                    

                            
    "Urungach",                  
    "Kumbel",                                  
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

                                                                                
def generate_record_id():
    return "FLICKR-" + str(uuid.uuid4())[:8].upper()

def get_elevation_estimate(latitude, longitude):
    """Estimates elevation based on latitude and longitude."""
    if not latitude or not longitude:
        return 0

    try:
        lat = float(latitude)
        lng = float(longitude)

                                      
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

                            
    post_year, post_month = None, None
    if date_taken:
        try:
            dt = datetime.strptime(date_taken[:10], "%Y-%m-%d")
            post_year  = dt.year
            post_month = dt.month
        except Exception:
            pass

                               
    post_url = f"https://www.flickr.com/photos/{owner}/{photo_id}" if owner and photo_id else ""

                            
    text_content = " ".join(filter(None, [title, tags])).strip()

                        
    estimated_elevation = get_elevation_estimate(latitude, longitude)

                                  
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

                                                                                
print(f"\n{'='*70}")
print(f"Flickr HYBRID Scraper — {PARK_NAME}, {COUNTRY}")
print(f"Methods: Geographic BBox + Keyword Search")
print(f"{'='*70}\n")

all_records = []

                                                                             
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

                            
    print(f"  Pausing 10s before next keyword...")
    time.sleep(10)

                                                                                
print(f"\n{'='*70}")
print(f"Raw records collected: {len(all_records)}")

if all_records:
    df = pd.DataFrame(all_records)

                             
    before = len(df)
    df = df.drop_duplicates(subset=["platform_record_id"], keep="first")
    print(f"After deduplication: {len(df)} unique records (removed {before - len(df)} duplicates)")

                                         
    print(f"\n── Collection Method Breakdown ──────────────────────")
    method_counts = df['collection_method'].value_counts()
    for method, count in method_counts.items():
        print(f"  {method}: {count} photos")

                                     
    print(f"\n── Geolocation Status ───────────────────────────────")
    has_coords = df[(df['latitude_raw'] != '') & (df['longitude_raw'] != '')]
    no_coords = df[(df['latitude_raw'] == '') | (df['longitude_raw'] == '')]
    print(f"  With coordinates: {len(has_coords)} ({len(has_coords)/len(df)*100:.1f}%)")
    print(f"  Without coordinates: {len(no_coords)} ({len(no_coords)/len(df)*100:.1f}%)")

                                          
    print(f"\n── Spatial Confidence ───────────────────────────────")
    confidence_counts = df['spatial_confidence'].value_counts()
    for conf, count in confidence_counts.items():
        print(f"  {conf}: {count} photos")

                                                               
    print(f"\n── Elevation Filtering (Geotagged only) ─────────────")
    geotagged_before = len(has_coords)

                                                                  
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

                                                                                
    filename_csv   = f"Flickr_UgamChatkal_HYBRID_{TODAY}.csv"
    filename_excel = f"Flickr_UgamChatkal_HYBRID_{TODAY}.xlsx"

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

raw_df = pd.DataFrame(all_records)
raw_filename_excel = f"Flickr_UgamChatkal_RAW_{TODAY}.xlsx"
raw_df.to_excel(raw_filename_excel, index=False)
print(f"Raw dataset saved to: {raw_filename_excel}")
print(f"Total raw records: {len(raw_df)}")
