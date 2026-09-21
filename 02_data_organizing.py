"""
DPP merge & dedupe — Colab edition.

Combines same-platform same-park scrape files into one merged file each,
removing duplicates along the way.

PATHS are hardcoded below — edit ROOT/OUT if your Drive structure changes.
"""

import os
import re
import warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


ROOT = '/content/drive/MyDrive/Aisulu_project_data/Raw data'
OUT  = '/content/drive/MyDrive/Aisulu_project_data/Raw data/merged'


warnings.filterwarnings('ignore', message='.*Ignoring URL.*')
warnings.filterwarnings('ignore', message='.*highly fragmented.*')

PLATFORM_PATTERNS = [
    (re.compile(r'google[\s_-]*maps',  re.I), 'google_maps'),
    (re.compile(r'2[\s_-]*gis|2гис',    re.I), '2gis'),
    (re.compile(r'instagram',           re.I), 'instagram'),
    (re.compile(r'tiktok',              re.I), 'tiktok'),
    (re.compile(r'threads',             re.I), 'threads'),
    (re.compile(r'twitter|^x[\s_-]',    re.I), 'twitter'),
    (re.compile(r'flickr',              re.I), 'flickr'),
    (re.compile(r'strava',              re.I), 'strava'),
]

PARK_KEYWORDS = {
    'Ile-Alatau':   ['ile alatau', 'ile-alatau', 'ile_alatau', 'ilealatau',
                     'іле алатау', 'или-алатау', 'иле-алатау', 'иле алатау'],
    'Ala-Archa':    ['ala archa', 'ala-archa', 'ala_archa', 'alaarcha',
                     'ала-арча', 'ала арча', 'аларча'],
    'Ugam-Chatkal': ['ugam chatkal', 'ugam-chatkal', 'ugam_chatkal', 'ugamchatkal',
                     'угам-чатк', 'угам чатк', 'угам_чатк'],
}

DEDUP_KEYS = {
    'google_maps': ['review_link', 'author_title', 'review_text'],
    '2gis':        ['user_id', 'date', 'review_text'],
    'twitter':     ['Web_Page_URL', 'Tweet_Timestamp', 'Tweet_Content'],
    'instagram':   ['url', 'ownerId', 'caption'],
    'tiktok':      ['id', 'authorId', 'desc'],
    'threads':     ['id', 'author_id', 'text'],
    'flickr':      ['id', 'owner', 'datetaken'],
    'strava':      ['id', 'name'],
}

DATA_EXTENSIONS = {'.xlsx', '.xls', '.xlsm', '.csv', '.json', '.jsonl'}


def detect_platform(*texts):
    for text in texts:
        if not text:
            continue
        for pat, platform in PLATFORM_PATTERNS:
            if pat.search(text):
                return platform
    return None


def detect_park(*texts):
    for text in texts:
        if not text:
            continue
        text_l = text.lower()
        for park, aliases in PARK_KEYWORDS.items():
            for alias in aliases:
                if alias.lower() in text_l:
                    return park
    return None


def load_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in ('.xlsx', '.xls', '.xlsm'):
        return pd.read_excel(path)
    if suffix == '.csv':
        try:
            return pd.read_csv(path, encoding='utf-8')
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding='cp1251')
    if suffix == '.json':
        return pd.read_json(path)
    if suffix == '.jsonl':
        return pd.read_json(path, lines=True)
    raise ValueError(f'Unsupported file type: {suffix}')


def merge_dpp_scrapes(root: Path, out_dir: Path):
                                                                           
    os.makedirs(out_dir, exist_ok=True)

    report = []
    def log(msg):
        print(msg)
        report.append(msg)

    log(f'Walking: {root}')
    log('=' * 70)

                                                       
    groups = {}
    unmatched = []

    for f in root.rglob('*'):
        if not f.is_file():
            continue
        if f.suffix.lower() not in DATA_EXTENSIONS:
            continue
        if f.name.startswith('merged_'):
            continue
                                                            
        try:
            if out_dir in f.parents:
                continue
        except Exception:
            pass

        folder_name = f.parent.name
        file_name   = f.stem

        platform = detect_platform(folder_name, file_name)
        park     = detect_park(folder_name, file_name)

        if not platform or not park:
            unmatched.append((f, platform, park))
            continue

        groups.setdefault((platform, park), []).append(f)

    if unmatched:
        log(f'\n[WARN] {len(unmatched)} files could not be classified:')
        for f, p, pk in unmatched[:20]:
            try:
                rel = f.relative_to(root)
            except ValueError:
                rel = f
            log(f'   platform={p or "?":12s} park={pk or "?":12s} {rel}')
        if len(unmatched) > 20:
            log(f'   ... and {len(unmatched) - 20} more')
        log('   (add aliases to PARK_KEYWORDS or rename the files)')

    log(f'\nFound {len(groups)} (platform, park) groups')
    log('=' * 70)

                                        
    for (platform, park), files in sorted(groups.items()):
        log(f'\n[{platform} | {park}] {len(files)} files')

        frames = []
        for f in files:
            try:
                df = load_file(f)
                df = pd.concat([df, pd.DataFrame({'_source_file': [f.name] * len(df)})], axis=1)
                frames.append(df)
                try:
                    rel = f.relative_to(root)
                except ValueError:
                    rel = f
                log(f'   {len(df):>6} rows  {rel}')
            except Exception as e:
                log(f'   [ERR] {f.name}: {type(e).__name__}: {e}')

        if not frames:
            log('   [SKIP] no readable files in group')
            continue

        merged = pd.concat(frames, ignore_index=True, sort=False)
        before = len(merged)

        key_cols = [c for c in DEDUP_KEYS.get(platform, []) if c in merged.columns]
        if key_cols:
            merged = merged.drop_duplicates(subset=key_cols, keep='first')
            log(f'   Dedupe key: {key_cols}')
        else:
            cols = [c for c in merged.columns if c != '_source_file']
            merged = merged.drop_duplicates(subset=cols, keep='first')
            log(f'   [WARN] no platform dedup key matched columns; used row-wise dedup')

        after = len(merged)
        log(f'   Merged: {before} -> {after} rows ({before - after} duplicates removed)')

                                                                     
        out_name = f'merged_{platform}_{park}.xlsx'
        out_path = out_dir / out_name
        try:
            merged.to_excel(out_path, index=False, engine='openpyxl')
            log(f'   Wrote -> {out_path}')
        except Exception as e:
                                                                   
            out_path = out_dir / out_name.replace('.xlsx', '.csv')
            merged.to_csv(out_path, index=False, encoding='utf-8')
            log(f'   Excel write failed ({e}); wrote CSV -> {out_path}')

                  
    report_path = out_dir / 'merge_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('DPP Merge Report\n')
        f.write(f'Generated: {datetime.now(timezone.utc).isoformat()}\n')
        f.write(f'Root: {root}\n')
        f.write('=' * 70 + '\n')
        for line in report:
            f.write(line + '\n')

    print(f'\nReport -> {report_path}')
    print('Done.')


if __name__ == '__main__':
    merge_dpp_scrapes(Path(ROOT), Path(OUT))


"""
DPP unification script — spatio-temporal tier only.

Reads the merged per-(platform, park) files and produces ONE unified
spatiotemporal.csv with the canonical column schema.

Input files expected (any subset is fine — missing ones are skipped):
    merged_google_maps_Ile-Alatau.xlsx       merged_strava_Ile-Alatau.xlsx
    merged_google_maps_Ala-Archa.xlsx        merged_strava_Ala-Archa.xlsx
    merged_google_maps_Ugam-Chatkal.xlsx     merged_strava_Ugam-Chatkal.xlsx
    merged_flickr_Ile-Alatau.xlsx            2GIS overall Ile-Alatau.xlsx
    merged_flickr_Ala-Archa.xlsx             Overall Ala-Archa 2GIS.xlsx
    merged_flickr_Ugam-Chatkal.xlsx          (no Ugam-Chatkal 2GIS yet)

Output:
    spatiotemporal.csv
    unify_report.txt

PATHS — edit if needed:
"""

import os
import re
import ast
import hashlib
import warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np

warnings.filterwarnings('ignore', category=UserWarning)


INPUT_DIR  = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis'
OUTPUT_DIR = '/content/drive/MyDrive/Aisulu_project_data/Merged data for spatiotemporal analysis'

                                                                                 
SCRAPE_DATE = pd.Timestamp('2026-05-01', tz='UTC')


CANONICAL_COLS = [
    'record_id',
    'platform',
    'content_type',
    'text_content',
    'post_url',
    'post_timestamp_raw',
    'post_date',
    'post_year',
    'post_month',
    'date_precision',                                                                    
    'latitude_raw',
    'longitude_raw',
    'location_name_raw',
    'geotag_available',
    'poi_name',
    'park_name',
    'country',
    'media_type',
    'likes_count',
    'comments_count',
    'rating_score',
    'detected_language',
    'scraping_tool',
    'scrape_timestamp',
]

                        
PARK_COUNTRY = {
    'Ile-Alatau':    'Kazakhstan',
    'Ala-Archa':     'Kyrgyzstan',
    'Ugam-Chatkal':  'Uzbekistan',
}


def make_record_id(prefix: str, *parts) -> str:
    payload = '|'.join('' if (p is None or (isinstance(p, float) and pd.isna(p))) else str(p) for p in parts)
    h = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]
    return f'{prefix}_{h}'


RU_MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
    'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
}

def parse_2gis_date(s):
    """Parse '18 марта 2026', '23 апреля 2026, изменён', 'сегодня', 'вчера'."""
    if not isinstance(s, str):
        return pd.NaT
    s_clean = re.sub(r',?\s*изменён.*$', '', s).strip().lower()
    if s_clean == 'сегодня':
        return SCRAPE_DATE
    if s_clean == 'вчера':
        return SCRAPE_DATE - pd.Timedelta(days=1)
    parts = s_clean.split()
    if len(parts) != 3:
        return pd.NaT
    day_s, month_s, year_s = parts
    month = RU_MONTHS.get(month_s)
    if month is None:
        return pd.NaT
    try:
        return pd.Timestamp(year=int(year_s), month=month, day=int(day_s), tz='UTC')
    except (ValueError, TypeError):
        return pd.NaT


REL_RE = re.compile(r'(?:(a|an|\d+)\s+)?(second|minute|hour|day|week|month|year)s?\s+ago', re.IGNORECASE)

def parse_relative_date(s, anchor=SCRAPE_DATE):
    """'3 weeks ago' / 'a month ago' / '2 years ago' → (timestamp, precision)."""
    if not isinstance(s, str):
        return pd.NaT, None
    m = REL_RE.search(s.lower())
    if not m:
        return pd.NaT, None
    n_raw, unit = m.group(1), m.group(2)
    n = 1 if n_raw in (None, 'a', 'an') else int(n_raw)
    unit_days = {'second': 1/86400, 'minute': 1/1440, 'hour': 1/24,
                 'day': 1, 'week': 7, 'month': 30, 'year': 365}
    ts = anchor - pd.Timedelta(days=n * unit_days[unit])
                    
    if unit in ('second', 'minute', 'hour', 'day'):
        precision = 'day'
    elif unit == 'week':
        precision = 'day'
    elif unit == 'month':
        precision = 'month'
    else:        
        precision = 'year'
    return ts, precision


def derive_date_parts(ts_series):
    date_str = ts_series.dt.strftime('%Y-%m-%d').where(ts_series.notna())
    year = ts_series.dt.year.astype('Int64')
    month = ts_series.dt.month.astype('Int64')
    return date_str, year, month


def parse_latlng(s):
    """Parse '[42.83, 77.50]' or '(42.83, 77.50)' → (lat, lng) floats."""
    if not isinstance(s, str):
        return (None, None)
    try:
        v = ast.literal_eval(s)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return (float(v[0]), float(v[1]))
    except (ValueError, SyntaxError):
        pass
    return (None, None)


def empty_canonical(n):
    return pd.DataFrame({c: [pd.NA] * n for c in CANONICAL_COLS})


def finalize(df, park):
    """Fill park-level defaults, enforce schema."""
    for c in CANONICAL_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[CANONICAL_COLS].copy()
    df['park_name'] = df['park_name'].fillna(park)
    df['country'] = df['country'].fillna(PARK_COUNTRY.get(park, ''))
    df['scrape_timestamp'] = SCRAPE_DATE.isoformat()
    df['geotag_available'] = df['geotag_available'].astype('boolean')
    return df


def normalize_gmaps(df_raw, park):
    """Google Maps via Octoparse — merged file.
    Two templates exist in the data: the dominant one uses lowercase columns
    (review_text, author_review_timestamp, etc.); a rare alternative uses
    Capitalized columns (Review, Review_time). Coalesce them.
    """
                                                                  
    if 'Review' in df_raw.columns:
        df_raw['review_text'] = df_raw['review_text'].fillna(df_raw.get('Review'))
    if 'Review_time' in df_raw.columns:
        df_raw['author_review_timestamp'] = df_raw['author_review_timestamp'].fillna(df_raw.get('Review_time'))
    if 'Likes' in df_raw.columns:
        df_raw['review_likes'] = df_raw['review_likes'].fillna(df_raw.get('Likes'))
    if 'Reviewer' in df_raw.columns:
        df_raw['author_title'] = df_raw['author_title'].fillna(df_raw.get('Reviewer'))
    if 'Address' in df_raw.columns:
        df_raw['_address'] = df_raw.get('Address')
    else:
        df_raw['_address'] = None

    n = len(df_raw)
    out = empty_canonical(n)

    out['platform'] = 'google_maps'
    out['content_type'] = 'review'
    out['text_content'] = df_raw['review_text']
    out['post_url'] = df_raw['review_link']
    out['post_timestamp_raw'] = df_raw['author_review_timestamp']

                                                   
    parsed = df_raw['author_review_timestamp'].apply(parse_relative_date)
    ts = pd.Series([p[0] for p in parsed])
    precision = pd.Series([p[1] for p in parsed])
    ts = pd.to_datetime(ts, utc=True, errors='coerce')
    out['post_date'], out['post_year'], out['post_month'] = derive_date_parts(ts)
    out['date_precision'] = precision

                                                                                       
    out['location_name_raw'] = df_raw['Input']
    out['poi_name'] = df_raw['name']

                                                         
    out['media_type'] = df_raw['review_img_url'].apply(
        lambda x: 'image' if (pd.notna(x) and str(x).strip()) else None)

                                                                                
    out['geotag_available'] = False
    out['latitude_raw'] = pd.NA
    out['longitude_raw'] = pd.NA

    out['likes_count'] = pd.to_numeric(df_raw['review_likes'], errors='coerce').astype('Int64')
    out['comments_count'] = pd.NA
    out['rating_score'] = pd.NA                                                             

    out['scraping_tool'] = 'octoparse'

    out['record_id'] = [
        make_record_id('gmaps',
                       df_raw.iloc[i].get('review_link'),
                       df_raw.iloc[i].get('author_title'),
                       df_raw.iloc[i].get('review_text'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_2gis(df_raw, park):
    """2GIS via Octoparse — columns differ slightly between files (POI_name vs
    'location POI' vs 'natpark_POI', 'rating' vs 'Rating', etc.). Coalesce."""
                                                  
    poi_col = next((c for c in ['POI_name', 'location POI', 'natpark_POI', 'POI']
                    if c in df_raw.columns), None)
                                      
    rating_col = next((c for c in ['rating', 'Rating'] if c in df_raw.columns), None)
                        
    coord_col = next((c for c in ['coordinates', 'Coordinates'] if c in df_raw.columns), None)

    n = len(df_raw)
    out = empty_canonical(n)

    out['platform'] = '2gis'
    out['content_type'] = 'review'
    out['text_content'] = df_raw['review_text']
    out['post_timestamp_raw'] = df_raw['date']

    ts = df_raw['date'].apply(parse_2gis_date)
    ts = pd.to_datetime(ts, utc=True, errors='coerce')
    out['post_date'], out['post_year'], out['post_month'] = derive_date_parts(ts)
    out['date_precision'] = 'day'                        

                 
    if coord_col:
        coords = df_raw[coord_col].fillna('').astype(str).str.strip("' \"")
        split = coords.str.split(',', expand=True)
        if split.shape[1] >= 2:
            out['latitude_raw']  = pd.to_numeric(split[0].str.strip(), errors='coerce')
            out['longitude_raw'] = pd.to_numeric(split[1].str.strip(), errors='coerce')
    out['geotag_available'] = out['latitude_raw'].notna() & out['longitude_raw'].notna()

    if poi_col:
        out['poi_name'] = df_raw[poi_col]
        out['location_name_raw'] = df_raw[poi_col]

    if rating_col:
        out['rating_score'] = pd.to_numeric(df_raw[rating_col], errors='coerce')

    out['scraping_tool'] = 'octoparse'

    out['record_id'] = [
        make_record_id('2gis',
                       df_raw.iloc[i].get('user_id'),
                       df_raw.iloc[i].get('date'),
                       df_raw.iloc[i].get('review_text'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_strava(df_raw, park):
    """Strava segments. No text content, no timestamps for individual efforts
    (only segment metadata). Contributes spatial density only.
    """
    n = len(df_raw)
    out = empty_canonical(n)

    out['platform'] = 'strava'
    out['content_type'] = 'segment'
    out['text_content'] = pd.NA                                                         
    out['location_name_raw'] = df_raw.get('name')
    out['poi_name'] = df_raw.get('name')

                                                                
    coords = df_raw['start_latlng'].apply(parse_latlng) if 'start_latlng' in df_raw.columns else pd.Series([(None, None)] * n)
    out['latitude_raw']  = pd.Series([c[0] for c in coords], dtype='float64')
    out['longitude_raw'] = pd.Series([c[1] for c in coords], dtype='float64')
    out['geotag_available'] = out['latitude_raw'].notna() & out['longitude_raw'].notna()

    out['post_url'] = df_raw.get('strava_url')
    out['post_timestamp_raw'] = pd.NA                             
    out['date_precision'] = pd.NA

    out['media_type'] = df_raw.get('activity_type')                        
    out['likes_count'] = pd.to_numeric(df_raw.get('points'), errors='coerce').astype('Int64')

    out['scraping_tool'] = 'strava_api'

    out['record_id'] = [
        make_record_id('strava',
                       df_raw.iloc[i].get('id'),
                       df_raw.iloc[i].get('name'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_flickr(df_raw, park):
    """Flickr — already partially normalized in the merged file. Just rename/fill."""
    n = len(df_raw)
    out = empty_canonical(n)

                                         
    out['record_id']          = df_raw.get('record_id')
    out['platform']           = 'flickr'                    
    out['content_type']       = df_raw.get('content_type', 'photo')
    out['text_content']       = df_raw.get('text_content')
    out['post_url']           = df_raw.get('post_url')
    out['post_timestamp_raw'] = df_raw.get('post_timestamp_raw')

                                                                    
    ts = pd.to_datetime(df_raw.get('post_timestamp_raw'), errors='coerce', utc=True)
    out['post_date'], year_derived, month_derived = derive_date_parts(ts)
                                                           
    out['post_year']  = df_raw.get('post_year').astype('Int64') if 'post_year' in df_raw.columns else year_derived
    out['post_month'] = df_raw.get('post_month').astype('Int64') if 'post_month' in df_raw.columns else month_derived
    out['date_precision'] = 'day'

    out['latitude_raw']      = pd.to_numeric(df_raw.get('latitude_raw'), errors='coerce')
    out['longitude_raw']     = pd.to_numeric(df_raw.get('longitude_raw'), errors='coerce')
    out['location_name_raw'] = df_raw.get('location_name_raw')
    out['geotag_available']  = out['latitude_raw'].notna() & out['longitude_raw'].notna()

    out['poi_name']  = df_raw.get('poi_name')
    out['media_type'] = 'image'
    out['likes_count']    = pd.to_numeric(df_raw.get('likes_count'), errors='coerce').astype('Int64')
    out['comments_count'] = pd.to_numeric(df_raw.get('comments_count'), errors='coerce').astype('Int64')
    out['rating_score']   = pd.to_numeric(df_raw.get('rating_score'), errors='coerce')
    out['detected_language'] = df_raw.get('detected_language')

    out['scraping_tool'] = 'flickr_api'

    return finalize(out, park)


FILE_ROUTES = [
    ('merged_google_maps_Ile-Alatau.xlsx',     normalize_gmaps,  'Ile-Alatau'),
    ('merged_google_maps_Ala-Archa.xlsx',      normalize_gmaps,  'Ala-Archa'),
    ('merged_google_maps_Ugam-Chatkal.xlsx',   normalize_gmaps,  'Ugam-Chatkal'),
    ('2GIS overall Ile-Alatau.xlsx',           normalize_2gis,   'Ile-Alatau'),
    ('Overall Ala-Archa 2GIS.xlsx',            normalize_2gis,   'Ala-Archa'),
    ('merged_strava_Ile-Alatau.xlsx',          normalize_strava, 'Ile-Alatau'),
    ('merged_strava_Ala-Archa.xlsx',           normalize_strava, 'Ala-Archa'),
    ('merged_strava_Ugam-Chatkal.xlsx',        normalize_strava, 'Ugam-Chatkal'),
    ('merged_flickr_Ile-Alatau.xlsx',          normalize_flickr, 'Ile-Alatau'),
    ('merged_flickr_Ala-Archa.xlsx',           normalize_flickr, 'Ala-Archa'),
    ('merged_flickr_Ugam-Chatkal.xlsx',        normalize_flickr, 'Ugam-Chatkal'),
]


def main():
    input_dir = Path(INPUT_DIR)
    output_dir = Path(OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    report = []
    log = lambda m: (print(m), report.append(m))

    log(f'Input:  {input_dir}')
    log(f'Output: {output_dir}')
    log(f'Scrape date anchor: {SCRAPE_DATE.date()}')
    log('=' * 70)

    frames = []
    for filename, normalizer, park in FILE_ROUTES:
        path = input_dir / filename
        if not path.exists():
            log(f'[SKIP] {filename} not found')
            continue
        try:
            df_raw = pd.read_excel(path)
            df_norm = normalizer(df_raw, park)
            frames.append(df_norm)
            log(f'[OK]   {filename:45s} {len(df_raw):>6} rows -> {len(df_norm):>6} normalized')
        except Exception as e:
            log(f'[ERR]  {filename}: {type(e).__name__}: {e}')

    if not frames:
        log('No files processed.')
        return

    df_all = pd.concat(frames, ignore_index=True)
    log('=' * 70)
    log(f'Combined: {len(df_all)} rows')

                                              
    before = len(df_all)
    df_all = df_all.drop_duplicates(subset=['record_id'], keep='first').reset_index(drop=True)
    log(f'Dedup by record_id: dropped {before - len(df_all)}')

                               
    log('\n--- Per-platform row counts ---')
    log(df_all['platform'].value_counts().to_string())

    log('\n--- Per-park row counts ---')
    log(df_all['park_name'].value_counts(dropna=False).to_string())

    log('\n--- Date precision distribution ---')
    log(df_all['date_precision'].value_counts(dropna=False).to_string())

    log('\n--- Geotag availability ---')
    log(df_all['geotag_available'].value_counts(dropna=False).to_string())

    log('\n--- Null rate per column (%) ---')
    null_pct = (df_all.isna().sum() / len(df_all) * 100).round(1)
    log(null_pct.to_string())

                      
    out_csv = output_dir / 'spatiotemporal.csv'
    df_all.to_csv(out_csv, index=False, encoding='utf-8')
    log(f'\nWrote {len(df_all)} rows -> {out_csv}')

    out_pq = output_dir / 'spatiotemporal.parquet'
    try:
        df_all.to_parquet(out_pq, index=False)
        log(f'Wrote parquet copy -> {out_pq}')
    except Exception as e:
        log(f'[parquet skipped: {e}]')

            
    report_path = output_dir / 'unify_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('DPP Unification Report (spatio-temporal tier)\n')
        f.write(f'Generated: {datetime.now(timezone.utc).isoformat()}\n')
        f.write(f'Scrape date anchor: {SCRAPE_DATE.isoformat()}\n')
        f.write('=' * 70 + '\n')
        for line in report:
            f.write(line + '\n')
    print(f'Report -> {report_path}')


if __name__ == '__main__':
    main()


"""
DPP sentiment-tier unifier + cleaner.

Reads merged per-(platform, park) sentiment files and produces ONE unified
sentiment.csv in canonical sentiment-tier schema.

Inputs (looked up by filename in INPUT_DIR):
    merged_instagram_Ile-Alatau.xlsx        merged_twitter_Ile-Alatau.xlsx
    merged_instagram_Ala-Archa.xlsx         merged_twitter_Ala-Archa.xlsx
    merged_instagram_Ugam-Chatkal.xlsx      merged_twitter_Ugam-Chatkal.xlsx
    merged_tiktok_Ile-Alatau.xlsx           merged_threads_Ile-Alatau.xlsx
    merged_tiktok_Ala-Archa.xlsx
    merged_tiktok_Ugam-Chatkal.xlsx

Outputs (same folder):
    sentiment.csv          — main unified output
    sentiment_report.txt   — run summary

Pipeline:
    1. Normalize each source to canonical schema
    2. Drop empty-text rows (no text → no sentiment)
    3. For Threads: STRICT park-keyword filter (drops Capitol Reef / Iowa / etc. noise)
    4. Date filter 2015–2025 strict (Twitter & Threads only)
    5. Strip emojis, URLs, mentions → text_clean
    6. Detect language (langdetect, confidence ≥ 0.85)
    7. Cross-source dedup
    8. Export

Requirements:
    pip install pandas openpyxl langdetect
"""

import os
import re
import sys
import hashlib
import warnings
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import numpy as np

warnings.filterwarnings('ignore', category=UserWarning)

try:
    from langdetect import detect_langs, DetectorFactory, LangDetectException
    DetectorFactory.seed = 0
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False
    print('[WARN] langdetect not installed. Run: pip install langdetect')


BASE_DIR    = '/content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis'
INPUT_DIR   = BASE_DIR
OUTPUT_CSV  = f'{BASE_DIR}/sentiment.csv'
REPORT_TXT  = f'{BASE_DIR}/sentiment_report.txt'


SCRAPE_TIMESTAMP = '2026-04-15T00:00:00+00:00'

                                                                     
DATE_MIN = pd.Timestamp('2015-01-01', tz='UTC')
DATE_MAX = pd.Timestamp('2025-12-31 23:59:59', tz='UTC')

                               
LANG_MIN_CHARS = 10
LANG_MIN_CONFIDENCE = 0.85

                
PARK_COUNTRY = {
    'Ile-Alatau':    'Kazakhstan',
    'Ala-Archa':     'Kyrgyzstan',
    'Ugam-Chatkal':  'Uzbekistan',
}

                                                                       
PARK_RELEVANCE_KEYWORDS = {
    'Ile-Alatau': [
        'ile alatau', 'ile-alatau', 'ilealatau', 'іле алатау', 'иле-алатау',
        'иле алатау', 'или-алатау', 'или алатау',
        'almaty', 'алматы', 'алмата',
        'issyk', 'есік', 'иссык',
        'kok zhailau', 'kokzhailau', 'көкжайлау', 'кок жайляу', 'кокжайляу',
        'medeu', 'медеу',
        'shymbulak', 'шымбулак', 'шымбұлақ',
        'big almaty lake', 'bao', 'большое алматинское',
        'ayusai', 'аюсай',
        'butakovka', 'бутаковка',
        'turgen', 'тургень', 'түрген',
        'assy', 'асы', 'ассы',
        'kaindy', 'каинды', 'каинди',
        'kolsai', 'кольсай', 'көлсай',
        'shamalgan',
    ],
    'Ala-Archa': [
        'ala archa', 'ala-archa', 'alaarcha', 'ала-арча', 'ала арча', 'аларча',
        'bishkek', 'бишкек',
        'kyrgyz', 'кыргыз', 'киргиз',
        'ratusha', 'ratzek',
        'ak-sai', 'ак-сай', 'аксай',
        'adygene', 'адыгене',
    ],
    'Ugam-Chatkal': [
        'ugam', 'угам',
        'chatkal', 'чатк', 'чаткал', 'чатқал',
        'chimgan', 'чимган', 'чимган', 'чимғон',
        'charvak', 'чарвак', 'чорвоқ',
        'beldersay', 'бельдерсай',
        'amirsoy', 'амирсай', 'амирсой',
        'gulkam', 'гулкам',
        'pulatkhan', 'пулатхан',
        'urungach', 'урунгач',
        'kumbel', 'кумбель',
        'uzbekistan', 'узбекистан',
        'tashkent', 'ташкент',
    ],
}


CANONICAL_COLS = [
    'record_id', 'platform', 'content_type',
    'text_content', 'text_clean', 'text_length', 'has_emoji',
    'post_url', 'post_timestamp_raw',
    'post_date', 'post_year', 'post_month',
    'place_tag', 'place_tag_source',
    'park_name', 'country',
    'media_type',
    'likes_count', 'comments_count',
    'detected_language', 'lang_confidence',
    'hashtags', 'has_hashtags',
    'scraping_tool', 'scrape_timestamp',
]


EMOJI_RE = re.compile(
    '['
    '\U0001F600-\U0001F64F'   '\U0001F300-\U0001F5FF'
    '\U0001F680-\U0001F6FF'   '\U0001F1E0-\U0001F1FF'
    '\U00002700-\U000027BF'   '\U0001F900-\U0001F9FF'
    '\U00002600-\U000026FF'   '\U0001FA70-\U0001FAFF'
    '\u200d\ufe0f'
    ']+', flags=re.UNICODE
)
URL_RE        = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
MENTION_RE    = re.compile(r'@\w+')
WHITESPACE_RE = re.compile(r'\s+')
HASHTAG_RE    = re.compile(r'#([\w\u0400-\u04FF\u0500-\u052F\u00C0-\u024F]+)', re.UNICODE)


def make_record_id(prefix, *parts):
    payload = '|'.join(
        '' if (p is None or (isinstance(p, float) and pd.isna(p))) else str(p)
        for p in parts
    )
    h = hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]
    return f'{prefix}_{h}'


def extract_hashtags(text):
    if not isinstance(text, str):
        return []
    return [m.lower() for m in HASHTAG_RE.findall(text)]


def has_any_emoji(text):
    if not isinstance(text, str):
        return False
    return bool(EMOJI_RE.search(text))


def clean_text(text):
    """Strip emojis, URLs, @mentions; normalize whitespace. Returns cleaned or None."""
    if not isinstance(text, str):
        return None
    t = URL_RE.sub('', text)
    t = MENTION_RE.sub('', t)
    t = EMOJI_RE.sub('', t)
    t = WHITESPACE_RE.sub(' ', t).strip()
    return t if t else None


def detect_language_safe(text):
    """Returns (lang_code, confidence) or (None, None)."""
    if not HAS_LANGDETECT or not isinstance(text, str):
        return (None, None)
    if len(text) < LANG_MIN_CHARS:
        return (None, None)
    try:
        results = detect_langs(text)
        if not results:
            return (None, None)
        top = results[0]
        if top.prob < LANG_MIN_CONFIDENCE:
            return (None, top.prob)
        return (top.lang, top.prob)
    except LangDetectException:
        return (None, None)


def is_threads_relevant(text, hashtags, all_keywords):
    """True if any park keyword appears in text or hashtags. Case-insensitive substring."""
    haystack_parts = []
    if isinstance(text, str):
        haystack_parts.append(text.lower())
    if isinstance(hashtags, list):
        haystack_parts.extend(h.lower() for h in hashtags)
    haystack = ' '.join(haystack_parts)
    if not haystack:
        return False
    return any(kw in haystack for kw in all_keywords)


def empty_canonical(n):
    return pd.DataFrame({c: [pd.NA] * n for c in CANONICAL_COLS})


def finalize(df, park):
    for c in CANONICAL_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[CANONICAL_COLS].copy()
    df['park_name'] = df['park_name'].fillna(park)
    df['country'] = df['country'].fillna(PARK_COUNTRY.get(park, ''))
    df['scrape_timestamp'] = SCRAPE_TIMESTAMP
    df['has_emoji'] = df['has_emoji'].astype('boolean')
    df['has_hashtags'] = df['has_hashtags'].astype('boolean')
    return df


def normalize_instagram(df_raw, park):
    """Instagram (Apify hashtag scraper). No timestamps, no coords."""
    n = len(df_raw)
    out = empty_canonical(n)

    out['platform']      = 'instagram'
    out['content_type']  = 'post'
    out['text_content']  = df_raw['caption']
    out['post_url']      = df_raw['url']
    out['likes_count']    = pd.to_numeric(df_raw['likesCount'], errors='coerce').astype('Int64')
    out['comments_count'] = pd.to_numeric(df_raw['commentsCount'], errors='coerce').astype('Int64')
    out['media_type']    = df_raw['displayUrl'].apply(lambda x: 'image' if pd.notna(x) else None)
    out['place_tag_source'] = 'hashtag'
    out['scraping_tool']    = 'apify'

                                       
    hashtags = df_raw['caption'].apply(extract_hashtags)
    out['hashtags']     = hashtags.apply(lambda lst: '|'.join(lst) if lst else None)
    out['has_hashtags'] = hashtags.apply(lambda lst: len(lst) > 0)

    out['record_id'] = [
        make_record_id('ig',
                       df_raw.iloc[i].get('url'),
                       df_raw.iloc[i].get('ownerId'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_tiktok(df_raw, park):
    """TikTok (Apify hashtag scraper). No timestamps, no coords."""
    n = len(df_raw)
    out = empty_canonical(n)

    out['platform']     = 'tiktok'
    out['content_type'] = 'video'
    out['text_content'] = df_raw['desc']
    out['post_url']     = df_raw['url']
    out['media_type']   = 'video'
    out['place_tag_source'] = 'hashtag'
    out['scraping_tool']    = 'apify'

    hashtags = df_raw['desc'].apply(extract_hashtags)
    out['hashtags']     = hashtags.apply(lambda lst: '|'.join(lst) if lst else None)
    out['has_hashtags'] = hashtags.apply(lambda lst: len(lst) > 0)

    out['record_id'] = [
        make_record_id('tiktok',
                       df_raw.iloc[i].get('id'),
                       df_raw.iloc[i].get('authorId'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_twitter(df_raw, park):
    """Twitter (Apify hashtag scraper). HAS timestamps."""
    n = len(df_raw)
    out = empty_canonical(n)

    out['platform']     = 'twitter'
    out['content_type'] = 'post'
    out['text_content'] = df_raw['Tweet_Content']
    out['post_url']     = df_raw['Web_Page_URL']
    out['post_timestamp_raw'] = df_raw['Tweet_Timestamp']
    out['place_tag']    = df_raw.get('Keyword')
    out['place_tag_source'] = 'hashtag'
    out['scraping_tool']    = 'apify'

                                                   
    ts = pd.to_datetime(df_raw['Tweet_Timestamp'],
                        format='%a %b %d %H:%M:%S %z %Y',
                        errors='coerce', utc=True)
    out['post_date']  = ts.dt.strftime('%Y-%m-%d').where(ts.notna())
    out['post_year']  = ts.dt.year.astype('Int64')
    out['post_month'] = ts.dt.month.astype('Int64')

                
    has_img = df_raw.get('Tweet_Image_URL', pd.Series([None]*n)).notna()
    has_vid = df_raw.get('Tweet_Video_URL', pd.Series([None]*n)).notna()
    out['media_type'] = np.where(has_vid, 'video', np.where(has_img, 'image', None))

    out['likes_count']    = pd.to_numeric(df_raw['Tweet_Number_of_Likes'], errors='coerce').astype('Int64')
                                                                                   
    out['comments_count'] = pd.to_numeric(df_raw['Tweet_Number_of_Reviews'], errors='coerce').astype('Int64')

                              
    hashtags = df_raw['Tweet_Content'].apply(extract_hashtags)
    out['hashtags']     = hashtags.apply(lambda lst: '|'.join(lst) if lst else None)
    out['has_hashtags'] = hashtags.apply(lambda lst: len(lst) > 0)

    out['record_id'] = [
        make_record_id('twitter',
                       df_raw.iloc[i].get('Web_Page_URL'),
                       df_raw.iloc[i].get('Tweet_Timestamp'))
        for i in range(n)
    ]
    return finalize(out, park)


def normalize_threads(df_raw, park):
    """Threads (Apify keyword scraper). HAS timestamps. 300-col file — ignore media/N/*."""
    n = len(df_raw)
    out = empty_canonical(n)

    out['platform']     = 'threads'
    out['content_type'] = 'post'
    out['text_content'] = df_raw['text']
    out['post_url']     = df_raw['url']
    out['post_timestamp_raw'] = df_raw['created_at']
    out['place_tag_source']   = 'keyword'
    out['scraping_tool']      = 'apify'

                         
    ts = pd.to_datetime(pd.to_numeric(df_raw['created_at'], errors='coerce'),
                        unit='s', utc=True, errors='coerce')
    out['post_date']  = ts.dt.strftime('%Y-%m-%d').where(ts.notna())
    out['post_year']  = ts.dt.year.astype('Int64')
    out['post_month'] = ts.dt.month.astype('Int64')

                                      
    if 'media/0/type' in df_raw.columns:
        out['media_type'] = df_raw['media/0/type']

    out['likes_count']    = pd.to_numeric(df_raw.get('like_count'), errors='coerce').astype('Int64')
    out['comments_count'] = pd.to_numeric(df_raw.get('reply_count'), errors='coerce').astype('Int64')

                                                          
    hashtag_cols = [c for c in df_raw.columns if re.match(r'^hashtags/\d+$', c)]
    if hashtag_cols:
        ht = df_raw[hashtag_cols].apply(
            lambda row: [str(x).lower() for x in row if pd.notna(x)], axis=1
        )
    else:
        ht = df_raw['text'].apply(extract_hashtags)
    out['hashtags']     = ht.apply(lambda lst: '|'.join(lst) if lst else None)
    out['has_hashtags'] = ht.apply(lambda lst: len(lst) > 0)
                                                                                     
    out['place_tag']    = ht.apply(lambda lst: ','.join(lst[:3]) if lst else None)

    out['record_id'] = [
        make_record_id('threads',
                       df_raw.iloc[i].get('id'),
                       df_raw.iloc[i].get('author_id'))
        for i in range(n)
    ]
    return finalize(out, park)


FILE_ROUTES = [
    ('merged_instagram_Ile-Alatau.xlsx',    normalize_instagram, 'Ile-Alatau'),
    ('merged_instagram_Ala-Archa.xlsx',     normalize_instagram, 'Ala-Archa'),
    ('merged_instagram_Ugam-Chatkal.xlsx',  normalize_instagram, 'Ugam-Chatkal'),
    ('merged_tiktok_Ile-Alatau.xlsx',       normalize_tiktok,    'Ile-Alatau'),
    ('merged_tiktok_Ala-Archa.xlsx',        normalize_tiktok,    'Ala-Archa'),
    ('merged_tiktok_Ugam-Chatkal.xlsx',     normalize_tiktok,    'Ugam-Chatkal'),
    ('merged_twitter_Ile-Alatau.xlsx',      normalize_twitter,   'Ile-Alatau'),
    ('merged_twitter_Ala-Archa.xlsx',       normalize_twitter,   'Ala-Archa'),
    ('merged_twitter_Ugam-Chatkal.xlsx',    normalize_twitter,   'Ugam-Chatkal'),
    ('merged_threads_Ile-Alatau.xlsx',      normalize_threads,   'Ile-Alatau'),
]


def main():
    input_dir = Path(INPUT_DIR)
    os.makedirs(Path(OUTPUT_CSV).parent, exist_ok=True)

    report = []
    def log(m):
        print(m)
        report.append(m)

    log(f'Input:  {input_dir}')
    log(f'Output: {OUTPUT_CSV}')
    log('=' * 70)

                                      
    log('\n[1/6] Normalizing per-platform files')
    frames = []
    for filename, normalizer, park in FILE_ROUTES:
        path = input_dir / filename
        if not path.exists():
            log(f'  [SKIP] {filename} not found')
            continue
        try:
            df_raw = pd.read_excel(path)
            df_norm = normalizer(df_raw, park)
            frames.append(df_norm)
            log(f'  [OK]   {filename:45s} {len(df_raw):>5} -> {len(df_norm):>5}')
        except Exception as e:
            log(f'  [ERR]  {filename}: {type(e).__name__}: {e}')

    if not frames:
        log('No files processed.')
        return

    df = pd.concat(frames, ignore_index=True)
    log(f'\nCombined: {len(df):,} rows')

                                       
    log('\n[2/6] Dropping empty-text rows')
    before = len(df)
    has_text = df['text_content'].notna() & (df['text_content'].astype(str).str.strip() != '')
    df = df[has_text].reset_index(drop=True)
    log(f'  Dropped {before - len(df):,} rows with empty text ({len(df):,} remain)')

                                                       
    log('\n[3/6] Threads strict relevance filter (drop noise)')
    is_threads = df['platform'] == 'threads'
    n_threads_before = is_threads.sum()
    log(f'  Threads rows before filter: {n_threads_before:,}')

                                
    all_keywords = []
    for park_kws in PARK_RELEVANCE_KEYWORDS.values():
        all_keywords.extend([kw.lower() for kw in park_kws])
    all_keywords = list(set(all_keywords))
    log(f'  Keyword set size: {len(all_keywords)}')

    def threads_keep_mask(row):
        if row['platform'] != 'threads':
            return True
        hashtags_list = row['hashtags'].split('|') if isinstance(row['hashtags'], str) else []
        return is_threads_relevant(row['text_content'], hashtags_list, all_keywords)

    keep = df.apply(threads_keep_mask, axis=1)
    dropped = (~keep).sum()
    df = df[keep].reset_index(drop=True)
    n_threads_after = (df['platform'] == 'threads').sum()
    log(f'  Threads rows dropped: {dropped:,}')
    log(f'  Threads rows kept:    {n_threads_after:,}')

                                                  
    log('\n[4/6] Date filter 2015–2025 (Twitter & Threads only)')
    ts = pd.to_datetime(df['post_date'], errors='coerce', utc=True)
    has_date = ts.notna()
    out_of_range = has_date & ((ts < DATE_MIN) | (ts > DATE_MAX))
    log(f'  Rows with parseable date: {has_date.sum():,}')
    log(f'  Dropping out-of-range (outside 2015–2025): {out_of_range.sum():,}')
    df = df[~out_of_range].reset_index(drop=True)
    log(f'  Rows remaining: {len(df):,}')

                                                                   
    log('\n[5/6] Cleaning text + detecting language')
    df['text_clean']  = df['text_content'].apply(clean_text)
    df['has_emoji']   = df['text_content'].apply(has_any_emoji).astype('boolean')
    df['text_length'] = df['text_clean'].apply(lambda x: len(x) if isinstance(x, str) else 0).astype('Int64')

                                                                              
    before = len(df)
    df = df[df['text_clean'].notna()].reset_index(drop=True)
    log(f'  Dropped {before - len(df):,} rows whose text was emoji/URL-only')

    if HAS_LANGDETECT:
        log(f'  Running langdetect (~{len(df):,} rows, ~{len(df)/400:.0f}s)...')
        from time import time
        t0 = time()
        langs, confs = [], []
        for i, txt in enumerate(df['text_clean'], 1):
            l, c = detect_language_safe(txt)
            langs.append(l)
            confs.append(c)
            if i % 2000 == 0:
                log(f'    {i:,}/{len(df):,} ({time()-t0:.0f}s)')
        df['detected_language'] = langs
        df['lang_confidence']   = confs
        log(f'  Detected: {df["detected_language"].notna().sum():,}')
        log('  Top languages:')
        for lang, n in df['detected_language'].value_counts().head(8).items():
            log(f'    {lang}: {n:,}')
    else:
        log('  Skipped (langdetect not installed)')

                        
    log('\n[6/6] Cross-source dedup')
    before = len(df)
    df = df.drop_duplicates(subset=['record_id'], keep='first').reset_index(drop=True)
    log(f'  By record_id: dropped {before - len(df):,}')

    before = len(df)
    df = df.drop_duplicates(subset=['platform', 'text_content', 'park_name'], keep='first').reset_index(drop=True)
    log(f'  By (platform, text, park): dropped {before - len(df):,}')

                       
    log('\n' + '=' * 70)
    log(f'FINAL: {len(df):,} rows')
    log('\nPer-platform:')
    log(df['platform'].value_counts().to_string())
    log('\nPer-park:')
    log(df['park_name'].value_counts().to_string())
    log('\nLanguage distribution (top 10):')
    log(df['detected_language'].value_counts(dropna=False).head(10).to_string())
    log('\nRows with hashtags: ' + str(df['has_hashtags'].sum()))
    log('Rows with emoji: ' + str(df['has_emoji'].sum()))
    log('Year distribution (Twitter/Threads only):')
    log(df[df['post_year'].notna()]['post_year'].astype(int).value_counts().sort_index().to_string())

                      
    log('\nWriting output...')
    df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
    log(f'  -> {OUTPUT_CSV}')

    with open(REPORT_TXT, 'w', encoding='utf-8') as f:
        f.write('DPP Sentiment Tier Report\n')
        f.write(f'Generated: {datetime.now(timezone.utc).isoformat()}\n')
        f.write('=' * 70 + '\n')
        for line in report:
            f.write(line + '\n')
    print(f'  -> {REPORT_TXT}')
    print('\nDone.')


if __name__ == '__main__':
    main()


"""
Merge sentiment files into one table: sentiment_merged_raw1.

Each platform (Instagram / TikTok / Twitter / Threads) uses DIFFERENT column
names, so a naive concat scatters data across non-matching columns. This script
maps every platform onto ONE common schema first, then concatenates, so all the
text ends up in a single `text_content` column, etc.

Run in Google Colab with Drive mounted.
"""

import os, re, glob
import pandas as pd

                                                                             
FOLDER = "/content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis"
OUT_XLSX = os.path.join(FOLDER, "sentiment_merged_raw1.xlsx")
OUT_CSV  = os.path.join(FOLDER, "sentiment_merged_raw1.csv")

PLATFORMS = ["instagram", "tiktok", "twitter", "threads"]
PARKS = ["Ile-Alatau", "Ala-Archa", "Ugam-Chatkal"]

                                                                    
CANON = [
    "platform", "park", "post_id", "author", "text_content",
    "post_url", "post_timestamp_raw", "likes_count", "comments_count",
    "hashtags", "source_file",
]

def detect_platform(name):
    low = name.lower()
    for p in PLATFORMS:
        if p in low:
            return p
    return "unknown"

def detect_park(name):
    for park in PARKS:
        if re.search(park.lower().replace("-", "[-_ ]?"), name.lower()):
            return park
    return "unknown"

def col(df, *candidates):
    """Return the first candidate column that exists in df, else NA series."""
    for c in candidates:
        if c in df.columns:
            return df[c]
    return pd.Series([pd.NA] * len(df))

def collect_hashtags(df):
    """Threads spreads hashtags across hashtags/0..N; join them into one string."""
    htag_cols = [c for c in df.columns if str(c).startswith("hashtags/")]
    if not htag_cols:
                                                                     
        return pd.Series([pd.NA] * len(df))
    def join_row(row):
        vals = [str(row[c]).strip() for c in htag_cols
                if pd.notna(row[c]) and str(row[c]).strip().lower() != "nan"]
        return " ".join(vals) if vals else pd.NA
    return df[htag_cols].apply(join_row, axis=1)

                                                                             
def norm_instagram(df, platform, park, name):
    out = pd.DataFrame()
    out["platform"] = [platform] * len(df)
    out["park"] = park
    out["post_id"] = col(df, "ownerId", "id")
    out["author"] = col(df, "ownerUsername")
    out["text_content"] = col(df, "caption")
    out["post_url"] = col(df, "url")
    out["post_timestamp_raw"] = col(df, "timestamp", "taken_at")                
    out["likes_count"] = col(df, "likesCount")
    out["comments_count"] = col(df, "commentsCount")
    out["hashtags"] = pd.NA
    out["source_file"] = name
    return out

def norm_tiktok(df, platform, park, name):
    out = pd.DataFrame()
    out["platform"] = [platform] * len(df)
    out["park"] = park
    out["post_id"] = col(df, "id")
    out["author"] = col(df, "nickname", "author")
    out["text_content"] = col(df, "desc")
    out["post_url"] = col(df, "url")
    out["post_timestamp_raw"] = col(df, "createTime", "createTimeISO")                
    out["likes_count"] = col(df, "diggCount", "likesCount")
    out["comments_count"] = col(df, "commentCount", "commentsCount")
    out["hashtags"] = pd.NA
    out["source_file"] = name
    return out

def norm_twitter(df, platform, park, name):
    out = pd.DataFrame()
    out["platform"] = [platform] * len(df)
    out["park"] = park
    out["post_id"] = col(df, "Web_Page_URL")
    out["author"] = col(df, "Author_Name")
    out["text_content"] = col(df, "Tweet_Content")
    out["post_url"] = col(df, "Web_Page_URL", "Tweet_Website")
    out["post_timestamp_raw"] = col(df, "Tweet_Timestamp")
    out["likes_count"] = col(df, "Tweet_Number_of_Likes")
    out["comments_count"] = col(df, "Tweet_Number_of_Reviews")               
    out["hashtags"] = col(df, "Keyword")                        
    out["source_file"] = name
    return out

def norm_threads(df, platform, park, name):
    out = pd.DataFrame()
    out["platform"] = [platform] * len(df)
    out["park"] = park
    out["post_id"] = col(df, "id", "pk", "code")
    out["author"] = col(df, "author", "author_name")
    out["text_content"] = col(df, "text", "caption", "caption_text")
    out["post_url"] = col(df, "url", "permalink")
    out["post_timestamp_raw"] = col(df, "created_at", "taken_at")
    out["likes_count"] = col(df, "like_count", "likes")
    out["comments_count"] = col(df, "reply_count", "replies")
    out["hashtags"] = collect_hashtags(df)
    out["source_file"] = name
    return out

NORMALIZERS = {
    "instagram": norm_instagram,
    "tiktok": norm_tiktok,
    "twitter": norm_twitter,
    "threads": norm_threads,
}

                                                                             
files = sorted(glob.glob(os.path.join(FOLDER, "merged_*.xlsx")))
files = [f for f in files if os.path.basename(f) != "sentiment_merged_raw1.xlsx"]

print(f"Found {len(files)} files.\n")
frames, report = [], []

for f in files:
    name = os.path.basename(f)
    platform = detect_platform(name)
    park = detect_park(name)
    df = pd.read_excel(f)
    norm = NORMALIZERS.get(platform)
    if norm is None:
        print(f"  !! no normalizer for {name} (platform={platform}); skipped")
        continue
    out = norm(df, platform, park, name)
                            
    out = out.reindex(columns=CANON)
    frames.append(out)
                                                               
    text_ok = out["text_content"].notna().sum()
    report.append((name, platform, park, len(out), text_ok))

merged = pd.concat(frames, ignore_index=True, sort=False)
merged = merged.reindex(columns=CANON)

                                                                             
merged.to_csv(OUT_CSV, index=False)
try:
    merged.to_excel(OUT_XLSX, index=False)
except Exception as e:
    print(f"(xlsx write skipped: {e}) -- CSV still written")

                                                                             
print("\n==================== MERGE REPORT ====================")
print(f"{'file':38s} {'platform':10s} {'park':13s} {'rows':>6s} {'w/text':>7s}")
print("-" * 80)
for name, platform, park, n, t in report:
    print(f"{name:38s} {platform:10s} {park:13s} {n:>6d} {t:>7d}")
print("-" * 80)
print(f"{'TOTAL':38s} {'':10s} {'':13s} {len(merged):>6d} {merged['text_content'].notna().sum():>7d}")

print("\nColumns:", list(merged.columns))
print("\nRows by platform:")
print(merged["platform"].value_counts().to_string())
print("\nSample (text_content first 60 chars):")
for _, r in merged.groupby("platform").head(1).iterrows():
    txt = str(r["text_content"])[:60].replace("\n", " ")
    print(f"  [{r['platform']:9s}] {txt}")
print(f"\nSaved:\n  {OUT_CSV}\n  {OUT_XLSX}")


"""
Stack all merged sentiment files into one master CSV.

Reads every merged_*.xlsx in INPUT_DIR (skips merge_report.txt and any
non-xlsx file), extracts platform + park from the filename, adds them
as columns, stacks everything into one DataFrame.

Since the source files have different column sets (Instagram has 'caption',
TikTok has 'desc', etc.), this uses an outer join — missing columns become
NaN. That's fine if you just want one combined view.

Input/Output:
    /content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis/

Output file:
    all_sentiment_stacked.xlsx   (in the same folder)
"""

import os
import re
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


INPUT_DIR  = '/content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis'
OUTPUT_XLSX = '/content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis/all_sentiment_stacked.xlsx'
OUTPUT_CSV  = '/content/drive/MyDrive/Aisulu_project_data/Merged data for sentiment analysis/all_sentiment_stacked.csv'


FILENAME_RE = re.compile(r'^merged_(?P<platform>[a-z_]+)_(?P<park>[A-Za-z-]+)\.xlsx$',
                         re.IGNORECASE)


def main():
    input_dir = Path(INPUT_DIR)
    if not input_dir.exists():
        print(f'[ERR] Folder not found: {input_dir}')
        return

                                  
    files = sorted([f for f in input_dir.iterdir()
                    if f.is_file() and f.suffix.lower() == '.xlsx'
                    and f.name.startswith('merged_')])

    if not files:
        print(f'No merged_*.xlsx files found in {input_dir}')
        return

    print(f'Found {len(files)} files to stack')
    print('=' * 70)

    frames = []
    for f in files:
        m = FILENAME_RE.match(f.name)
        if not m:
            print(f'[SKIP] {f.name} — filename pattern not recognized')
            continue

        platform = m.group('platform').lower()
        park     = m.group('park')

        try:
            df = pd.read_excel(f)
            n = len(df)
                                                                               
                                                                          
            df.insert(0, 'park', park)
            df.insert(0, 'platform', platform)
            frames.append(df)
            print(f'  {n:>6} rows  | {platform:10s} | {park:13s} | {f.name}')
        except Exception as e:
            print(f'[ERR] {f.name}: {type(e).__name__}: {e}')

    if not frames:
        print('No data loaded.')
        return

                                      
    df_all = pd.concat(frames, ignore_index=True, sort=False)
    print('=' * 70)
    print(f'TOTAL: {len(df_all):,} rows | {len(df_all.columns)} columns')

    print('\nPer-platform counts:')
    print(df_all['platform'].value_counts().to_string())

    print('\nPer-park counts:')
    print(df_all['park'].value_counts().to_string())

    print('\nPer-(platform, park) breakdown:')
    print(df_all.groupby(['platform', 'park']).size().to_string())

                                 
    print('\nWriting outputs...')
    try:
        df_all.to_excel(OUTPUT_XLSX, index=False, engine='openpyxl')
        print(f'  -> {OUTPUT_XLSX}')
    except Exception as e:
        print(f'  [WARN] Excel write failed ({e}); skipping xlsx')

    df_all.to_csv(OUTPUT_CSV, index=False, encoding='utf-8')
    print(f'  -> {OUTPUT_CSV}')

    print('\nDone.')


if __name__ == '__main__':
    main()
