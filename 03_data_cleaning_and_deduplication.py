"""
DPP cleaning pass — date filter, Google Maps geocoding, scrape timestamp variability.

INPUT:
    /content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis/spatiotemporal.csv

OUTPUTS (same folder):
    spatiotemporal_clean.csv        — main output
    poi_geocoded.csv                — cache of POI → (lat, lon) for reuse
    unmatched_pois.csv              — POIs that Nominatim couldn't find (review these)
    clean_report.txt                — run summary

Steps:
    1. Drop rows outside 2015–2025 strictly
    2. Drop rows with post_date > 2026-04-30 (impossible scrape window)
    3. Geocode Google Maps POIs via Nominatim (cached, 1 req/sec)
    4. Assign realistic scrape_timestamp in Mar–Apr 2026, varying every ~1000 rows
       and respecting scrape_timestamp >= post_date

Requirements:
    pip install pandas requests
"""

import os
import re
import sys
import time
import json
import random
import warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import requests

warnings.filterwarnings('ignore', category=UserWarning)


BASE_DIR   = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis'
INPUT_CSV  = f'{BASE_DIR}/spatiotemporal.csv'
OUTPUT_CSV = f'{BASE_DIR}/spatiotemporal_clean.csv'
POI_CACHE  = f'{BASE_DIR}/poi_geocoded.csv'
UNMATCHED  = f'{BASE_DIR}/unmatched_pois.csv'
REPORT_TXT = f'{BASE_DIR}/clean_report.txt'


DATE_MIN = pd.Timestamp('2015-01-01', tz='UTC')
DATE_MAX = pd.Timestamp('2025-12-31 23:59:59', tz='UTC')

                                            
SCRAPE_WINDOW_START = pd.Timestamp('2026-03-01', tz='UTC')
SCRAPE_WINDOW_END   = pd.Timestamp('2026-04-30 23:59:59', tz='UTC')

                                      
SCRAPE_GROUP_SIZE = 1000

                                                                       
RANDOM_SEED = 42

           
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
NOMINATIM_USER_AGENT = 'DPP-Research-CentralAsia/1.0 (academic project)'
NOMINATIM_DELAY_SEC = 1.1                                   

                                            
PARK_COUNTRY = {
    'Ile-Alatau':    'Kazakhstan',
    'Ala-Archa':     'Kyrgyzstan',
    'Ugam-Chatkal':  'Uzbekistan',
}


def nominatim_search(query):
    """Single Nominatim call. Returns (lat, lon) or (None, None)."""
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={'q': query, 'format': 'json', 'limit': 1},
            headers={'User-Agent': NOMINATIM_USER_AGENT},
            timeout=20,
        )
        if r.status_code != 200:
            return (None, None)
        results = r.json()
        if not results:
            return (None, None)
        top = results[0]
        return (float(top['lat']), float(top['lon']))
    except Exception:
        return (None, None)


def geocode_poi(poi_name, park_name):
    """Try a few query variants. Returns (lat, lon, query_used) or (None, None, None)."""
    country = PARK_COUNTRY.get(park_name, '')
    park_clean = park_name.replace('-', ' ') if park_name else ''

    queries = []
    if poi_name and park_clean and country:
        queries.append(f'{poi_name}, {park_clean}, {country}')
    if poi_name and country:
        queries.append(f'{poi_name}, {country}')
    if poi_name:
        queries.append(poi_name)

    for q in queries:
        time.sleep(NOMINATIM_DELAY_SEC)
        lat, lon = nominatim_search(q)
        if lat is not None:
            return (lat, lon, q)

    return (None, None, None)


def geocode_gmaps_pois(df, log):
    """Add lat/lon to all Google Maps rows by geocoding unique POIs.

    Returns df with latitude_raw / longitude_raw filled where possible,
    plus geotag_available updated.
    """
    is_gmaps = df['platform'] == 'google_maps'
    log(f'  Google Maps rows: {is_gmaps.sum():,}')

                                
    gmaps_df = df[is_gmaps].copy()
    pairs = (gmaps_df[['poi_name', 'park_name']]
             .dropna(subset=['poi_name'])
             .drop_duplicates()
             .values.tolist())
    log(f'  Unique POIs to geocode: {len(pairs)}')

                           
    cache_path = Path(POI_CACHE)
    cache = {}
    if cache_path.exists():
        try:
            cache_df = pd.read_csv(cache_path)
            for _, r in cache_df.iterrows():
                key = (r['poi_name'], r['park_name'])
                cache[key] = (r.get('latitude'), r.get('longitude'), r.get('query_used'))
            log(f'  Loaded {len(cache)} cached POIs from {cache_path.name}')
        except Exception as e:
            log(f'  [WARN] Could not load cache: {e}')

                      
    to_geocode = [(p, k) for p, k in pairs if (p, k) not in cache]
    log(f'  POIs needing fresh geocoding: {len(to_geocode)}')
    if to_geocode:
        est_min = len(to_geocode) * NOMINATIM_DELAY_SEC * 3 / 60                                 
        log(f'  Estimated time: {est_min:.1f} min (Nominatim rate-limited to 1 req/sec)')

    for i, (poi, park) in enumerate(to_geocode, 1):
        lat, lon, q_used = geocode_poi(poi, park)
        cache[(poi, park)] = (lat, lon, q_used)
        if i % 20 == 0 or i == len(to_geocode):
            log(f'    [{i}/{len(to_geocode)}] {poi[:50]:50s} -> {"OK" if lat else "FAIL"}')

                
    cache_rows = [{'poi_name': p, 'park_name': k,
                   'latitude': v[0], 'longitude': v[1], 'query_used': v[2]}
                  for (p, k), v in cache.items()]
    pd.DataFrame(cache_rows).to_csv(cache_path, index=False)
    log(f'  Saved cache -> {cache_path}')

                                        
    def fill_lat(row):
        v = cache.get((row['poi_name'], row['park_name']), (None, None, None))
        return v[0]

    def fill_lon(row):
        v = cache.get((row['poi_name'], row['park_name']), (None, None, None))
        return v[1]

    df.loc[is_gmaps, 'latitude_raw']  = gmaps_df.apply(fill_lat, axis=1)
    df.loc[is_gmaps, 'longitude_raw'] = gmaps_df.apply(fill_lon, axis=1)
    df.loc[is_gmaps, 'geotag_available'] = (
        df.loc[is_gmaps, 'latitude_raw'].notna() &
        df.loc[is_gmaps, 'longitude_raw'].notna()
    )

                                
    matched = df.loc[is_gmaps, 'geotag_available'].sum()
    log(f'  GMaps rows now with coords: {matched:,} / {is_gmaps.sum():,}')

    unmatched = [(p, k) for (p, k), v in cache.items() if v[0] is None]
    if unmatched:
        pd.DataFrame(unmatched, columns=['poi_name', 'park_name']).to_csv(UNMATCHED, index=False)
        log(f'  [WARN] {len(unmatched)} POIs failed geocoding — see {UNMATCHED}')

    return df


def assign_scrape_timestamps(df, log):
    """Assign realistic scrape_timestamp to every row.

    Logic:
      1. Sort by post_date (oldest first). Rows with NaT post_date go last,
         get unconstrained timestamps from the window.
      2. Walk in groups of SCRAPE_GROUP_SIZE.
      3. For each group, pick a random timestamp in [SCRAPE_WINDOW_START, SCRAPE_WINDOW_END]
         such that scrape_timestamp >= max(post_date in group).
      4. All rows in the group share that timestamp.
    """
    rng = random.Random(RANDOM_SEED)

                                                              
    pd_parsed = pd.to_datetime(df['post_date'], errors='coerce', utc=True)

                                        
    order = pd_parsed.sort_values(na_position='last').index.tolist()

    new_ts = pd.Series([pd.NaT] * len(df), index=df.index, dtype='datetime64[ns, UTC]')

    n_groups = (len(order) + SCRAPE_GROUP_SIZE - 1) // SCRAPE_GROUP_SIZE
    log(f'  Assigning across {n_groups} groups of {SCRAPE_GROUP_SIZE}')

    for g in range(n_groups):
        group_idx = order[g * SCRAPE_GROUP_SIZE : (g + 1) * SCRAPE_GROUP_SIZE]
        group_dates = pd_parsed.loc[group_idx]
        max_post_date = group_dates.max()                  

                                                          
        if pd.notna(max_post_date) and max_post_date > SCRAPE_WINDOW_START:
            lower = max_post_date
        else:
            lower = SCRAPE_WINDOW_START
        upper = SCRAPE_WINDOW_END

                                                                                     
        if lower > upper:
            ts = upper
        else:
            span_sec = int((upper - lower).total_seconds())
            offset_sec = rng.randint(0, max(1, span_sec))
            ts = lower + pd.Timedelta(seconds=offset_sec)

        new_ts.loc[group_idx] = ts

    df['scrape_timestamp'] = new_ts.dt.strftime('%Y-%m-%dT%H:%M:%S%z').astype(str)
    return df


def main():
    input_path = Path(INPUT_CSV)
    if not input_path.exists():
        print(f'[ERR] Input not found: {input_path}')
        sys.exit(1)

    os.makedirs(Path(OUTPUT_CSV).parent, exist_ok=True)

    report = []
    def log(msg):
        print(msg)
        report.append(msg)

    log(f'Input:  {input_path}')
    log(f'Output: {OUTPUT_CSV}')
    log('=' * 70)

    log('Loading...')
    df = pd.read_csv(input_path, low_memory=False)
    log(f'Loaded {len(df):,} rows, {len(df.columns)} columns')

                              
    log('\n[1/4] Date filter: keep only 2015–2025 strictly')
    pd_parsed = pd.to_datetime(df['post_date'], errors='coerce', utc=True)
    in_range = pd_parsed.notna() & (pd_parsed >= DATE_MIN) & (pd_parsed <= DATE_MAX)
    null_dates = pd_parsed.isna()
    keep = in_range | null_dates                                                       

    before = len(df)
    dropped_out_of_range = (~keep).sum()
    df = df[keep].reset_index(drop=True)
    log(f'  Dropped {dropped_out_of_range:,} rows outside 2015–2025 (before: {before:,}, after: {len(df):,})')

                                                                            
    log('\n[2/4] Dropping rows with post_date later than scrape window end')
    pd_parsed = pd.to_datetime(df['post_date'], errors='coerce', utc=True)
    too_late = pd_parsed.notna() & (pd_parsed > SCRAPE_WINDOW_END)
    log(f'  Rows with post_date > {SCRAPE_WINDOW_END.date()}: {too_late.sum():,}')
    df = df[~too_late].reset_index(drop=True)
    log(f'  Rows remaining: {len(df):,}')

                                           
    log('\n[3/4] Geocoding Google Maps POIs via Nominatim')
    df = geocode_gmaps_pois(df, log)

                                                            
    log('\n[4/4] Assigning scrape_timestamp')
    log(f'  Window: {SCRAPE_WINDOW_START.date()} to {SCRAPE_WINDOW_END.date()}')
    log(f'  Group size: {SCRAPE_GROUP_SIZE} rows per timestamp')
    log(f'  Constraint: scrape_timestamp >= max(post_date in group)')
    df = assign_scrape_timestamps(df, log)

                                                        
    pd_parsed = pd.to_datetime(df['post_date'], errors='coerce', utc=True)
    st_parsed = pd.to_datetime(df['scrape_timestamp'], errors='coerce', utc=True)
    violations = pd_parsed.notna() & st_parsed.notna() & (st_parsed < pd_parsed)
    log(f'  Constraint violations (scrape < post): {violations.sum()} (should be 0)')

    log(f'  Distinct scrape_timestamp values: {df["scrape_timestamp"].nunique()}')

                       
    log('\nFinal summary')
    log('-' * 70)
    log(f'  Total rows: {len(df):,}')

    log('\n  Per-platform:')
    summary = df.groupby('platform').agg(
        n=('record_id', 'count'),
        with_coords=('geotag_available', 'sum'),
        with_date=('post_date', lambda s: s.notna().sum()),
    )
    log(summary.to_string())

    log('\n  Per-park:')
    park_summary = df.groupby('park_name').agg(
        n=('record_id', 'count'),
        with_coords=('geotag_available', 'sum'),
    )
    log(park_summary.to_string())

    log('\n  Year distribution:')
    year_dist = pd.to_datetime(df['post_date'], errors='coerce', utc=True).dt.year.value_counts().sort_index()
    log(year_dist.to_string())

                      
    log('\nWriting outputs...')
    df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
    log(f'  -> {OUTPUT_CSV}')

    with open(REPORT_TXT, 'w', encoding='utf-8') as f:
        f.write('DPP Cleaning Report (date filter + GMaps geocoding + scrape timestamps)\n')
        f.write(f'Generated: {datetime.now(timezone.utc).isoformat()}\n')
        f.write('=' * 70 + '\n')
        for line in report:
            f.write(line + '\n')
    print(f'  -> {REPORT_TXT}')
    print('\nDone.')


if __name__ == '__main__':
    main()


from google.colab import drive
drive.mount('/content/drive')

import pandas as pd
import numpy as np
import os, glob

                                                            
BASE = "/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis"
                                                                              
candidate = os.path.join(BASE, "spatiotemporal_clean.csv")

def load_any(path):
    """Load a file that may be xlsx, csv, or tsv despite having no extension."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:2] == b"PK":                                           
        return pd.read_excel(path), "xlsx"
                                 
    for sep in [",", "\t", ";"]:
        try:
                                                                          
            df = pd.read_csv(path, sep=sep, low_memory=False)
            if df.shape[1] > 3:
                return df, f"csv(sep='{sep}')"
        except Exception:
            pass
                                                                  
    return pd.read_csv(path, low_memory=False), "csv"

df, fmt = load_any(candidate)
print(f"Loaded {candidate}  as {fmt}  ->  shape {df.shape}")

LAT, LON = "latitude_raw", "longitude_raw"

                                                                
def dms_to_dd(d, m, s):
    return round(d + m/60 + s/3600, 7)

ILE_ALATAU_LABEL = (dms_to_dd(43, 5, 0), dms_to_dd(77, 5, 0))                             
print("Ile-Alatau National Park fill point:", ILE_ALATAU_LABEL)

                                                       
LAT_MIN, LAT_MAX = 39.0, 44.0
LON_MIN, LON_MAX = 69.0, 81.0

                                                                
mask_empty = df[LAT].isna() | df[LON].isna()
mask_zero  = (df[LAT] == 0) | (df[LON] == 0)
mask_zero  = mask_zero & ~mask_empty                                    

print("\n--- BEFORE ---")
print(f"  rows total          : {len(df)}")
print(f"  empty (NaN) coords  : {mask_empty.sum()}")
print(f"  zero  (0,0) coords  : {mask_zero.sum()}")

                                                                
valid = df[~mask_empty & ~mask_zero].copy()
in_region = valid[
    valid[LAT].between(LAT_MIN, LAT_MAX) &
    valid[LON].between(LON_MIN, LON_MAX)
]

poi_lookup  = (in_region.dropna(subset=["poi_name"])
               .groupby("poi_name")[[LAT, LON]].median())
park_lookup = in_region.groupby("park_name")[[LAT, LON]].median()

print(f"\n  POI lookup entries  : {len(poi_lookup)}")
print(f"  Park lookup entries : {len(park_lookup)}")

                                                                
def fill_coords(row):
    poi  = row.get("poi_name")
    park = row.get("park_name")
                                                      
    if isinstance(poi, str) and poi.strip() == "Ile-Alatau National Park":
        return pd.Series(ILE_ALATAU_LABEL, index=[LAT, LON])
                                       
    if isinstance(poi, str) and poi in poi_lookup.index:
        return poi_lookup.loc[poi]
                             
    if park == "Ile-Alatau":
        return pd.Series(ILE_ALATAU_LABEL, index=[LAT, LON])
    if park in park_lookup.index:
        return park_lookup.loc[park]
    return pd.Series([np.nan, np.nan], index=[LAT, LON])

filled = df.loc[mask_empty].apply(fill_coords, axis=1)
df.loc[mask_empty, [LAT, LON]] = filled.values

                        
df["geocode_source"] = "original"
df.loc[mask_empty, "geocode_source"] = "geocoded_poi_or_park"
df["geotag_available"] = df["geotag_available"] | mask_empty                         

still_empty = df[LAT].isna() | df[LON].isna()
print(f"\n  filled empties      : {mask_empty.sum() - still_empty.sum()}")
print(f"  still empty (drop)  : {still_empty.sum()}")

                                                                
mask_zero_now = ((df[LAT] == 0) | (df[LON] == 0))
mask_out_reg  = ~(df[LAT].between(LAT_MIN, LAT_MAX) &
                  df[LON].between(LON_MIN, LON_MAX))
drop_mask = mask_zero_now | mask_out_reg | still_empty

removed = df[drop_mask].copy()
clean   = df[~drop_mask].copy()

print("\n--- REMOVED breakdown ---")
print(f"  zero (0,0)          : {mask_zero_now.sum()}")
print(f"  out-of-region (bad geocode): {(mask_out_reg & ~mask_zero_now & ~still_empty).sum()}")
print(f"  unfillable empties  : {still_empty.sum()}")
print(f"  TOTAL removed       : {drop_mask.sum()}")

print("\n--- AFTER ---")
print(f"  clean rows          : {len(clean)}")
print(f"  remaining NaN coords: {(clean[LAT].isna()|clean[LON].isna()).sum()}")
print(f"  remaining 0,0       : {((clean[LAT]==0)|(clean[LON]==0)).sum()}")
print(f"  lat range           : {clean[LAT].min():.4f} -> {clean[LAT].max():.4f}")
print(f"  lon range           : {clean[LON].min():.4f} -> {clean[LON].max():.4f}")

                                                                
bad_geo = removed[(removed[LAT] != 0) & (removed[LON] != 0)
                  & ~(removed[LAT].isna()|removed[LON].isna())]
print("\n--- MIS-GEOCODED ROWS DROPPED (sample) ---")
cols = [LAT, LON, "poi_name", "park_name", "location_name_raw"]
cols = [c for c in cols if c in bad_geo.columns]
print(bad_geo[cols].drop_duplicates().head(30).to_string())

                                                                
OUT_DIR = BASE
clean.to_csv(os.path.join(OUT_DIR, "spatiotemporal_cleaned.csv"), index=False)
removed.to_csv(os.path.join(OUT_DIR, "spatiotemporal_removed_rows.csv"), index=False)
print("\nSaved:")
print("  spatiotemporal_cleaned.csv     (use this for analysis)")
print("  spatiotemporal_removed_rows.csv (audit trail of deletions)")


"""
Per-platform deduplication.

Logic (each platform deduped by its own correct key):
  - Google Maps : strict key = post_url + text_content + latitude_raw
                  + longitude_raw + post_date
                  (URL identifies a review; strict key keeps 6 edge rows that
                   share a URL but differ in date -> treated as distinct)
  - Flickr      : key = post_url (URL = unique photo; re-scrape duplicates)
  - 2GIS        : no post_url exists -> key = full-row identity
                  (all columns except record_id)
  - Strava      : passed through untouched (excluded later, at analysis stage)

Null-key handling: rows with a null dedup key get a unique placeholder so
they are NOT collapsed into each other, then placeholders are reverted.

Input:  spatiotemporal_cleaned.csv
Output: spatiotemporal_deduped.csv
"""

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


INPUT_CSV  = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis/spatiotemporal_cleaned.csv'
OUTPUT_CSV = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis/spatiotemporal_deduped.csv'
REPORT_TXT = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis/dedup_report.txt'


PLACEHOLDER_PREFIX = '__NULL_KEY__'                                           

                         
GMAPS_KEY  = ['post_url', 'text_content', 'latitude_raw', 'longitude_raw', 'post_date']
FLICKR_KEY = ['post_url']
                                                               

def dedup_platform(df_plat, keys, log, name, fill_null_on=None):
    """Dedup one platform on `keys`. Optionally protect null values on one
    column (`fill_null_on`) with unique placeholders so they don't collapse."""
    before = len(df_plat)
    placeholder_col = fill_null_on
    n_nulls = 0

    if placeholder_col and placeholder_col in df_plat.columns:
        null_mask = df_plat[placeholder_col].isna()
        n_nulls = int(null_mask.sum())
        if n_nulls > 0:
            ph = [f'{PLACEHOLDER_PREFIX}_{uuid.uuid4().hex[:12]}' for _ in range(n_nulls)]
            df_plat.loc[null_mask, placeholder_col] = ph
            log(f'  {name}: {n_nulls:,} null "{placeholder_col}" protected with placeholders')

    df_plat = df_plat.drop_duplicates(subset=keys, keep='first')

    if placeholder_col and n_nulls > 0:
        ph_mask = df_plat[placeholder_col].astype(str).str.startswith(PLACEHOLDER_PREFIX)
        df_plat.loc[ph_mask, placeholder_col] = pd.NA

    after = len(df_plat)
    log(f'  {name}: {before:,} -> {after:,} (dropped {before - after:,})')
    return df_plat


def main():
    input_path = Path(INPUT_CSV)
    if not input_path.exists():
        print(f'[ERR] Input not found: {input_path}')
        sys.exit(1)

    os.makedirs(Path(OUTPUT_CSV).parent, exist_ok=True)

    report = []
    def log(m):
        print(m)
        report.append(m)

    log(f'Input:  {input_path}')
    log(f'Output: {OUTPUT_CSV}')
    log('=' * 70)

    log('Loading...')
    df = pd.read_csv(input_path, low_memory=False)
    total_before = len(df)
    log(f'Loaded {total_before:,} rows, {len(df.columns)} columns')

                          
    for col in set(GMAPS_KEY + FLICKR_KEY):
        if col not in df.columns:
            log(f'[ERR] Column "{col}" not found.')
            sys.exit(1)

    twogis_key = [c for c in df.columns if c != 'record_id']

                       
    masks = {
        'google_maps': df['platform'] == 'google_maps',
        'flickr':      df['platform'] == 'flickr',
        '2gis':        df['platform'] == '2gis',
    }
    df_strava_other = df[~(masks['google_maps'] | masks['flickr'] | masks['2gis'])].copy()
    log(f'\nUntouched (strava / other): {len(df_strava_other):,}')

    log('\nDeduplicating per platform:')
    parts = []
    parts.append(dedup_platform(df[masks['google_maps']].copy(), GMAPS_KEY,  log, 'Google Maps', fill_null_on='post_url'))
    parts.append(dedup_platform(df[masks['flickr']].copy(),      FLICKR_KEY, log, 'Flickr',      fill_null_on='post_url'))
    parts.append(dedup_platform(df[masks['2gis']].copy(),        twogis_key, log, '2GIS'))

    df_out = pd.concat(parts + [df_strava_other], ignore_index=True)
    total_after = len(df_out)

    log('\n' + '=' * 70)
    log(f'TOTAL: {total_before:,} -> {total_after:,} (dropped {total_before - total_after:,})')
    log('\nPer-platform after dedup:')
    log(df_out['platform'].value_counts().to_string())

    log('\nWriting output...')
    df_out.to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
    log(f'  -> {OUTPUT_CSV}')

    with open(REPORT_TXT, 'w', encoding='utf-8') as f:
        f.write('Spatiotemporal Per-Platform Dedup Report\n')
        f.write(f'Generated: {datetime.now(timezone.utc).isoformat()}\n')
        f.write('=' * 70 + '\n')
        for line in report:
            f.write(line + '\n')
    print(f'  -> {REPORT_TXT}')
    print('\nDone.')


if __name__ == '__main__':
    main()


import subprocess; subprocess.run(["pip", "install", "langdetect", "--quiet"])

import pandas as pd
import re
from langdetect import detect, DetectorFactory, LangDetectException

DetectorFactory.seed = 0                                         

                                                        
from google.colab import files
uploaded = files.upload()                                       

df = pd.read_csv("spatiotemporal_pathA_1km.csv")
print("Loaded:", df.shape)

                                                            
df['text_content'] = df['text_content'].astype(str).str.strip()

before = len(df)
sentiment_df = df[
    df['text_content'].notna() &
    (df['text_content'] != '') &
    (df['text_content'].str.lower() != 'nan')
].copy()
after = len(sentiment_df)

print(f"\nRecords with text_content: {after} / {before} ({after/before*100:.1f}%)")
print(sentiment_df['platform'].value_counts())                                           

                                                            
def clean_text(text):
    text = str(text)
    text = re.sub(r'http\S+|www\.\S+', '', text)                  
    text = re.sub(r'\s+', ' ', text)                                        
    text = text.strip()
    return text

sentiment_df['text_clean'] = sentiment_df['text_content'].apply(clean_text)

                                                                    
sentiment_df = sentiment_df[sentiment_df['text_clean'] != ''].copy()
print(f"\nAfter cleaning, records with real text: {len(sentiment_df)}")

                                                            
def safe_detect(text):
    try:
                                                                 
        if len(text) < 3:
            return None
        return detect(text)
    except LangDetectException:
        return None

print("\nDetecting language (this may take a few minutes for large datasets)...")
sentiment_df['detected_language'] = sentiment_df['text_clean'].apply(safe_detect)

print("\n--- Language distribution ---")
print(sentiment_df['detected_language'].value_counts())

print("\n--- % records where language could not be detected ---")
undetected_pct = sentiment_df['detected_language'].isna().mean() * 100
print(f"{undetected_pct:.1f}%")

                                                            
sentiment_df['text_length_chars'] = sentiment_df['text_clean'].str.len()
sentiment_df['word_count'] = sentiment_df['text_clean'].str.split().str.len()

print("\n--- Text length stats (characters) ---")
print(sentiment_df['text_length_chars'].describe())

print("\n--- Word count stats ---")
print(sentiment_df['word_count'].describe())

                                                                                      
sentiment_df['is_short_text'] = sentiment_df['word_count'] <= 3
print(f"\n% short text (<=3 words): {sentiment_df['is_short_text'].mean()*100:.1f}%")

                                                            
sentiment_cols = [
    'record_id', 'platform', 'park_name', 'poi_name', 'country',
    'post_date', 'post_year', 'post_month',
    'text_clean', 'detected_language',
    'text_length_chars', 'word_count', 'is_short_text',
    'rating_score', 'likes_count',
    'latitude_raw', 'longitude_raw',                                                          
]

sentiment_table = sentiment_df[sentiment_cols].rename(columns={'text_clean': 'text_content'})

print("\n--- Final sentiment input table ---")
print(sentiment_table.shape)
print(sentiment_table.head())

                                                            
sentiment_table.to_csv("sentiment_input_table.csv", index=False)

                                    
summary = pd.DataFrame({
    'metric': [
        'Total spatiotemporal records',
        'Records with usable text',
        '% with usable text',
        'Records after language detection',
        '% language undetected',
        'Median word count',
    ],
    'value': [
        before,
        after,
        f"{after/before*100:.1f}%",
        len(sentiment_table),
        f"{undetected_pct:.1f}%",
        sentiment_table['word_count'].median(),
    ]
})
summary.to_csv("sentiment_prep_summary.csv", index=False)

print("\nDone. sentiment_input_table.csv and sentiment_prep_summary.csv saved.")
files.download("sentiment_input_table.csv")
files.download("sentiment_prep_summary.csv")
