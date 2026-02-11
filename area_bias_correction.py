import os
import pickle
import sys

import pandas as pd
import numpy as np
import argparse

from scipy.interpolate import interp1d
from concurrent.futures import ProcessPoolExecutor
from methods import str2bool

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

def load_models(model_path: str) -> dict:
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def is_minutes(rt_unit: str) -> bool:
    s = str(rt_unit).strip().lower()
    return s in {"m", "min", "minute", "minutes"}

def create_inverse_model(model, x_range=(0.0, 45.0), num_points=500000):
    x = np.linspace(float(x_range[0]), float(x_range[1]), int(num_points))
    y = model([[xi] for xi in x])
    y = np.array(y, dtype=float).flatten()

    # Remove non-finite
    m = np.isfinite(x) & np.isfinite(y)
    x = x[m]
    y = y[m]

    # Sort by y for invertibility
    order = np.argsort(y)
    y_sorted = y[order]
    x_sorted = x[order]

    y_unique, idx = np.unique(y_sorted, return_index=True)
    x_unique = x_sorted[idx]

    if y_unique.size < 2:
        raise ValueError("Failed to build inverse model: not enough unique points in y.")

    return interp1d(y_unique, x_unique, bounds_error=False, fill_value="extrapolate")

def apply_inverse_model(inverse_model, corrected_rt_values, rt_unit: str):
    arr = np.asarray(corrected_rt_values, dtype=float)
    if is_minutes(rt_unit):
        rt_minutes = arr
    else:
        rt_minutes = arr / 60.0

    original_minutes = inverse_model(rt_minutes)
    return original_minutes if is_minutes(rt_unit) else original_minutes * 60.0


def reverse_area_from_center(
    inverse_model,
    rt_center_corr: float,
    area_corr: float,
    widths,
    rt_unit: str,
    rt_min: float,
    rt_max: float
):
    rc_in = float(rt_center_corr)
    rc_min = rc_in if is_minutes(rt_unit) else rc_in / 60.0
    rc_min = float(np.clip(rc_min, rt_min, rt_max))

    scales = []
    for w in widths:
        w = float(w)
        half = w / 2.0

        max_half_left = rc_min - rt_min
        max_half_right = rt_max - rc_min
        half_eff = min(half, max_half_left, max_half_right)

        if half_eff <= 0:
            continue

        left_corr_min = rc_min - half_eff
        right_corr_min = rc_min + half_eff

        left_ori_min = apply_inverse_model(inverse_model, left_corr_min, "min")
        right_ori_min = apply_inverse_model(inverse_model, right_corr_min, "min")

        den = (right_corr_min - left_corr_min)
        if den <= 0:
            continue

        scale = (right_ori_min - left_ori_min) / den
        scales.append(scale)

    if len(scales) == 0:
        return float(area_corr)

    return float(area_corr) * float(np.mean(scales))


def _normalize_name(s: str) -> str:
    s = str(s).strip().lower()
    s = s.replace(" ", "").replace("_", "").replace("-", "")
    return s

def _strip_suffixes(s: str, suffix) -> str:
    s0 = str(s)
    if not suffix:
        return s0

    suf = str(suffix)
    if s0.lower().endswith(suf.lower()):
        return s0[:-len(suf)]
    return s0


def _build_model_lookup(model_dict, model_suffixes):
    lookup = {}
    for k in model_dict.keys():
        k2 = _strip_suffixes(k, model_suffixes)
        nk = _normalize_name(k2)
        if nk and nk not in lookup:
            lookup[nk] = k
    return lookup

def _to_token(name: str, suffixes=None) -> str:
    s = _strip_suffixes(name, suffixes)
    return _normalize_name(s)

def match_model_key(query_name: str, model_dict: dict, model_suffixes, query_suffixes=None, model_lookup=None):
    if model_lookup is None:
        model_lookup = _build_model_lookup(model_dict, model_suffixes)

    q = _to_token(query_name, query_suffixes)

    return model_lookup.get(q)


def process_aligned_file(
    file_path,
    model_dict,
    sep,
    output_dir,
    rt_center_col,
    RTCenterWidths,
    rt_unit,
    rt_min,
    rt_max,
    inverse_points,
    model_suffixes
):
    df = pd.read_csv(file_path, sep=sep)

    if rt_center_col not in df.columns:
        print(f"[Error] RT center column '{rt_center_col}' not found: {file_path}")
        return

    rt_center = pd.to_numeric(df[rt_center_col], errors="coerce").to_numpy(dtype=float)

    model_lookup = _build_model_lookup(model_dict, model_suffixes)

    sample_cols = []
    col_to_modelkey = {}
    used_model_keys = set()

    for col in df.columns:
        if col == rt_center_col:
            continue
        mk = match_model_key(
            query_name=col,
            model_dict=model_dict,
            model_suffixes=model_suffixes,
            query_suffixes=model_suffixes,
            model_lookup=model_lookup
        )

        if mk is not None:
            sample_cols.append(col)
            col_to_modelkey[col] = mk
            used_model_keys.add(_normalize_name(_strip_suffixes(mk, model_suffixes)))

    unused_model_keys = set(model_lookup.keys()) - used_model_keys

    if unused_model_keys:
        print(f"Area column absent ({len(unused_model_keys)}):")
        for k in sorted(unused_model_keys):
            print("  -", k)

    if not sample_cols:
        print(f"No sample columns matched in aligned feature list: {file_path}")
        return

    inv_models = {}
    for col in sample_cols:
        mk = col_to_modelkey[col]
        inv_models[col] = create_inverse_model(
            model_dict[mk],
            x_range=(rt_min, rt_max),
            num_points=inverse_points
        )

    for col in sample_cols:
        inv = inv_models[col]
        area_vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        out = np.empty_like(area_vals, dtype=float)

        for i in range(len(area_vals)):
            a = area_vals[i]
            rc = rt_center[i]
            if not np.isfinite(a) or not np.isfinite(rc):
                out[i] = a
                continue

            out[i] = reverse_area_from_center(
                inv,
                rc,
                a,
                RTCenterWidths,
                rt_unit,
                rt_min=rt_min,
                rt_max=rt_max
            )

        df[col] = out

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, os.path.basename(file_path))
    df.to_csv(out_path, index=False, sep=sep)
    print(f"Bias corrected feature list saved: {out_path}")

def process_corrected_file(
    file_path, model_bytes, sep, output_dir,
    rt_left_col, rt_right_col, area_col,
    rt_unit,
    rt_max=45.0,
    rt_min=0.0,
    RTCenterOnly=False,
    RTCenterWidths=(0.2, 0.5, 1.0),
    rt_center_col=None,
    keep_original_values=True,
    rt_rev_suffix="_rev",
    area_rev_suffix="_rev",
    inverse_points=500000
):
    model = pickle.loads(model_bytes)
    df = pd.read_csv(file_path, sep=sep)

    cols = df.columns.tolist()

    def resolve_col(c):
        return cols[c] if isinstance(c, int) else c

    area_colname = resolve_col(area_col)
    if RTCenterOnly:
        if rt_center_col is None:
            raise ValueError("rt_center_col must be provided when RTCenterOnly=True")
        rt_center_colname = resolve_col(rt_center_col)
    else:
        if rt_left_col is None or rt_right_col is None:
            raise ValueError("rt edge columns must be provided when RTCenterOnly=True")
        rt_left_colname = resolve_col(rt_left_col)
        rt_right_colname = resolve_col(rt_right_col)


    need_cols = [area_colname]
    if RTCenterOnly:
        need_cols.append(rt_center_colname)
    else:
        need_cols.extend([rt_left_colname, rt_right_colname])

    missing = [c for c in need_cols if c not in df.columns]
    if missing:
        print(f"Missing columns {missing} in {file_path}")
        return

    inv = create_inverse_model(model, x_range=(rt_min, rt_max), num_points=inverse_points)

    if RTCenterOnly:
        rt_center_corr = pd.to_numeric(df[rt_center_colname], errors='coerce').to_numpy(dtype=float)
        area_corr = pd.to_numeric(df[area_colname], errors='coerce').to_numpy(dtype=float)

        rt_center_corr_min = rt_center_corr if is_minutes(rt_unit) else (rt_center_corr / 60.0)
        rt_center_corr_min_clamped = np.clip(rt_center_corr_min, rt_min, rt_max)

        rt_center_ori_min = apply_inverse_model(inv, rt_center_corr_min_clamped, "min")

        area_ori = np.empty_like(area_corr, dtype=float)
        for i in range(len(area_corr)):
            if not np.isfinite(rt_center_corr_min[i]) or not np.isfinite(area_corr[i]):
                area_ori[i] = area_corr[i]
                continue
            area_ori[i] = reverse_area_from_center(
                inv,
                rt_center_corr_min[i],
                area_corr[i],
                RTCenterWidths,
                "min",
                rt_min=rt_min,
                rt_max=rt_max
            )

        rt_center_ori = rt_center_ori_min if is_minutes(rt_unit) else (rt_center_ori_min * 60.0)

        if keep_original_values:
            df[f"{rt_center_colname}{rt_rev_suffix}"] = rt_center_ori
            df[f"{area_colname}{area_rev_suffix}"] = area_ori
        else:
            df[rt_center_colname] = rt_center_ori
            df[area_colname] = area_ori

    else:
        left_corr = pd.to_numeric(df[rt_left_colname], errors='coerce').to_numpy(dtype=float)
        right_corr = pd.to_numeric(df[rt_right_colname], errors='coerce').to_numpy(dtype=float)
        area_corr = pd.to_numeric(df[area_colname], errors='coerce').to_numpy(dtype=float)

        left_corr_min = left_corr if is_minutes(rt_unit) else (left_corr / 60.0)
        right_corr_min = right_corr if is_minutes(rt_unit) else (right_corr / 60.0)

        left_corr_min = np.clip(left_corr_min, rt_min, rt_max)
        right_corr_min = np.clip(right_corr_min, rt_min, rt_max)

        left_ori_min = apply_inverse_model(inv, left_corr_min, "min")
        right_ori_min = apply_inverse_model(inv, right_corr_min, "min")

        denom = (right_corr_min - left_corr_min)
        denom_safe = np.where(denom == 0, np.nan, denom)

        area_ori = area_corr * (right_ori_min - left_ori_min) / denom_safe
        area_ori = np.where(np.isnan(area_ori), area_corr, area_ori)

        left_ori = left_ori_min if is_minutes(rt_unit) else (left_ori_min * 60.0)
        right_ori = right_ori_min if is_minutes(rt_unit) else (right_ori_min * 60.0)

        if keep_original_values:
            df[f"{rt_left_colname}{rt_rev_suffix}"] = left_ori
            df[f"{rt_right_colname}{rt_rev_suffix}"] = right_ori
            df[f"{area_colname}{area_rev_suffix}"] = area_ori
        else:
            df[rt_left_colname] = left_ori
            df[rt_right_colname] = right_ori
            df[area_colname] = area_ori

    filename = os.path.basename(file_path)
    output_path = os.path.join(output_dir, filename)
    df.to_csv(output_path, index=False, sep=sep)
    print(f"Bias corrected feature list saved: {output_path}")

def batch_reverse_feature_lists(
    folder_path, model_dict, sep, output_dir,
    input_suffixes, model_suffixes,
    rt_left_col, rt_right_col, area_col,
    rt_unit, n_workers=4,
    rt_max=45.0,
    rt_min=0.0,
    inverse_points=500000,
    RTCenterOnly=False,
    RTCenterWidths=(0.2, 0.5, 1.0),
    rt_center_col=None,
    keep_ori=True,
    rt_rev_suffix="_rev",
    area_rev_suffix="_rev",
    aligned_mode=False,
    aligned_rt_center_col=None
):
    os.makedirs(output_dir, exist_ok=True)

    if aligned_mode:
        if aligned_rt_center_col is None:
            raise ValueError("aligned_rt_center_col is required")

        if os.path.isfile(folder_path):
            files = [folder_path]
        else:
            files = [
                os.path.join(folder_path, fn)
                for fn in os.listdir(folder_path)
                if fn.lower().endswith(str(input_suffixes).lower())
            ]

        if not files:
            print("input files not found")
            return

        for fp in files:
            process_aligned_file(
                fp,
                model_dict,
                sep,
                output_dir,
                rt_center_col=aligned_rt_center_col,
                RTCenterWidths=RTCenterWidths,
                rt_unit=rt_unit,
                rt_min=rt_min,
                rt_max=rt_max,
                inverse_points=inverse_points,
                model_suffixes=model_suffixes
            )
        return

    model_lookup = _build_model_lookup(model_dict, model_suffixes)

    tasks = []
    for file_name in os.listdir(folder_path):
        if not file_name.lower().endswith(str(input_suffixes).lower()):
            continue

        file_path = os.path.join(folder_path, file_name)

        mk = match_model_key(
            query_name=file_name,
            model_dict=model_dict,
            model_suffixes=model_suffixes,
            query_suffixes=input_suffixes
        )

        if mk is None:
            print(f"No model for {file_name}")
            continue

        matched_model = model_dict[mk]
        model_bytes = pickle.dumps(matched_model)
        tasks.append((file_path, model_bytes))

    if not tasks:
        print("Model matching failed")
        print("Model key expamle:" + list(model_dict.keys())[0])

        return

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = []
        for file_path, model_bytes in tasks:
            futures.append(executor.submit(
                process_corrected_file,
                file_path, model_bytes, sep, output_dir,
                rt_left_col, rt_right_col, area_col,
                rt_unit,
                rt_max=rt_max,
                rt_min=rt_min,
                inverse_points=inverse_points,
                RTCenterOnly=RTCenterOnly,
                RTCenterWidths=RTCenterWidths,
                rt_center_col=rt_center_col,
                keep_original_values=keep_ori,
                rt_rev_suffix=rt_rev_suffix,
                area_rev_suffix=area_rev_suffix
            ))
        for f in futures:
            f.result()

def main():
    parser = argparse.ArgumentParser(
        description="Area bias correction for individual/aligned feature lists"
    )

    # load files
    parser.add_argument("--model_path", type=str,
                        default=r"E:\Halo_lipidomic_zhang\rtcorrection\rt_correction_models.pkl")
    parser.add_argument("--input", type=str,
                        default=r"E:\Halo_lipidomic_zhang\Feature_list_compare\Area_3_2026_02_06_14_18_18.txt",
                        help="Folder (feature lists) or file path (aligned feature list)")
    parser.add_argument("--output_dir", type=str,
                        default=r"E:\Halo_lipidomic_zhang\Feature_list_compare\Correction\reversed")

    parser.add_argument("--rt_max", type=float, default=45,help="Maximum retention time of the dataset (min) (default: 45)")
    parser.add_argument("--n_workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),help="Number of CPU processors (default: cpu_count-1)")

    parser.add_argument("--input_suffix", type=str, default=".txt",help="Suffix of feature list files")
    parser.add_argument("--model_suffix", type=str, default=".txt",help="Suffix used in model training file")

    # columns
    parser.add_argument("--rt_left_col", type=str, default="RT left(min)",help='Name of RT left boundary column (used when "rt_center_only=false")')
    parser.add_argument("--rt_right_col", type=str, default="RT right (min)",help='Name of RT right boundary column (used when "rt_center_only=false")')
    parser.add_argument("--rt_center_col", type=str, default="Average Rt(min)", help='Name of RT center column (used when "rt_center_only=true")')
    parser.add_argument("--area_col", type=str, default="Area")

    # modes
    parser.add_argument("--rt_center_only", type=str2bool, default="true",
                        help='"true": correct bias using RT center (recommended); "false": correct bias using RT left and right edge (default: true)')
    parser.add_argument("--aligned_mode", type=str2bool, default="true",
                        help='"true": input is one aligned feature list file; "false": inputs are individual feature lists (default: true)')
    parser.add_argument("--rt_unit", type=str, default="min",
                        help='RT unit in input files "min" or "sec" (default: min)')
    parser.add_argument("--keep_ori", type=str2bool, default="false",help="Keep original RT and area info (default: false)")


    args = parser.parse_args()

    models = load_models(args.model_path)
    if "csv" in args.input_suffix:
        sep = ","
    else:
        sep = "\t"
    batch_reverse_feature_lists(
        args.input,
        models,
        sep=sep,
        output_dir=args.output_dir,
        input_suffixes=args.input_suffix,
        model_suffixes=args.model_suffix,
        rt_left_col=args.rt_left_col,
        rt_right_col=args.rt_right_col,
        area_col=args.area_col,
        rt_unit=args.rt_unit,
        n_workers=args.n_workers,
        rt_min=0,
        rt_max=args.rt_max,
        inverse_points=10000,
        RTCenterOnly=args.rt_center_only,
        RTCenterWidths=(0.2, 0.5, 1.0),
        rt_center_col=args.rt_center_col,
        keep_ori=args.keep_ori,
        rt_rev_suffix="_rev",
        area_rev_suffix="_rev",
        aligned_mode=args.aligned_mode,
        aligned_rt_center_col=args.rt_center_col
    )

def entrypoint():
    try:
        main()

    except SystemExit as e:
        if e.code == 0:
            return
        print("\n[ERROR] Argument parsing caused exit.")
        print(f"SystemExit code: {e}")

    except Exception as e:
        import traceback
        print("\n[ERROR] Program failed, but it will NOT exit abruptly.")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {e}\n")

        tb = traceback.extract_tb(e.__traceback__)
        print("========== TRACEBACK (most recent call last) ==========")
        for frame in tb:
            print(
                f'File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
                f'  -> {frame.line}'
            )
        print("======================================================")

if __name__ == '__main__':
    entrypoint()
