import argparse
import pickle
import pandas as pd
import numpy as np
import os, sys
import multiprocessing as mp
from typing import List, Dict
from functools import partial

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


def normalize_unit(rt_unit: str) -> str:
    u = (rt_unit or "").strip().lower()
    if u in {"m", "min", "minute", "minutes"}:
        return "min"
    if u in {"s", "sec", "second", "seconds"}:
        return "sec"
    raise ValueError("Invalid --rt_unit. Use m/min/minute or s/sec/second.")


def process_single_file(
        file_path: str,
        model_dict: dict,
        output_dir: str,
        rt_columns: List[str],
        overwrite_original: bool = True,
        rt_unit: str = "min",   # 'min' or 'sec'
        round_digits: int = 4,
        input_suffix: str = "",
        model_suffix: str = ""
):
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]

    result = {
        'file_name': file_name,
        'success': False,
        'message': '',
        'stats': {}
    }

    try:
        model = None
        model_key = None

        #mapping file file_suffix to model key file_suffix
        input_suffix = (input_suffix or "").strip()
        model_suffix = (model_suffix or "").strip()
        mapped_key = None
        if input_suffix and model_suffix and file_name.endswith(input_suffix):
            mapped_key = file_name[:-len(input_suffix)] + model_suffix

        possible_keys = []
        if mapped_key:
            possible_keys.append(mapped_key)

        # default file_suffix
        possible_keys += [
            file_name,
            base_name,
            base_name + '_feature_list.txt',
            base_name + '.csv',
            base_name + '.txt'
        ]

        for key in possible_keys:
            if key in model_dict:
                model = model_dict[key]
                model_key = key
                break

        if model is None:
            result['message'] = f"No model found. Tried: {possible_keys}"
            return result

        # Read featurelist file
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_csv(file_path, sep='\t')

        existing_rt_cols = [col for col in rt_columns if col in df.columns]
        if not existing_rt_cols:
            result['message'] = f"No RT columns found. Available columns: {list(df.columns)}"
            return result

        original_rts = {col: df[col].copy() for col in existing_rt_cols}

        # conversion units
        unit = normalize_unit(rt_unit)
        in_scale = 1.0
        out_scale = 1.0
        if unit == "sec":
            in_scale = 1.0 / 60.0   # seconds -> minutes
            out_scale = 60.0        # minutes -> seconds

        def correct_rt_value(rt_val):
            if pd.isna(rt_val):
                return rt_val
            try:
                rt_float = float(rt_val)
                rt_for_model = rt_float * in_scale

                # model prediction
                corrected = model([[rt_for_model]])[0]
                if isinstance(corrected, (list, np.ndarray)):
                    corrected = corrected[0]

                # convert back to original unit
                corrected_out = float(corrected) * out_scale
                return round(corrected_out, round_digits)
            except Exception:
                return rt_val  # 静默处理错误

        for rt_col in existing_rt_cols:
            if overwrite_original:
                df[rt_col] = df[rt_col].apply(correct_rt_value)
            else:
                corrected_col = rt_col + '_corrected'
                df[corrected_col] = df[rt_col].apply(correct_rt_value)

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{base_name}{os.path.splitext(file_name)[1]}")

        if file_path.lower().endswith('.csv'):
            df.to_csv(output_path, index=False)
        else:
            df.to_csv(output_path, sep='\t', index=False)

        # collect statistics
        stats = {}
        for rt_col in existing_rt_cols:
            ori = original_rts[rt_col]
            corr = df[rt_col] if overwrite_original else df[rt_col + "_corrected"]

            pair = pd.DataFrame({"ori": ori, "corr": corr}).dropna()
            if len(pair) > 0:
                stats[rt_col] = {
                    "original_range": (pair["ori"].min(), pair["ori"].max()),
                    "corrected_range": (pair["corr"].min(), pair["corr"].max()),
                    "mean_correction": float((pair["corr"] - pair["ori"]).mean())
                }

        result['success'] = True
        result['message'] = f"Successfully processed with model: {model_key}"
        result['stats'] = stats
        result['output_path'] = output_path
        result['corrected_columns'] = existing_rt_cols

    except Exception as e:
        result['message'] = f"Error processing file: {str(e)}"

    return result


def correct_feature_lists(
        featurelist_dir: str,
        model_dict: dict,
        output_dir: str,
        rt_columns: List[str] = None,
        overwrite_original: bool = True,
        n_workers: int = None,
        rt_unit: str = "min",
        round_digits: int = 4,
        input_suffix: str = "",
        model_suffix: str = ""
):
    # default settings
    file_extensions = ['.txt', '.csv', '.tsv']
    if rt_columns is None:
        rt_columns = ['RT (min)', 'rt', 'RT', 'retention_time']
    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)
    if input_suffix:
        file_extensions = [input_suffix]

    os.makedirs(output_dir, exist_ok=True)

    featurelist_files = []
    for ext in file_extensions:
        featurelist_files.extend([
            os.path.join(featurelist_dir, f) for f in os.listdir(featurelist_dir)
            if f.lower().endswith(ext.lower())
        ])

    if not featurelist_files:
        print(f"[Error] No featurelist files found in {featurelist_dir}")
        return

    print(f"Found {len(featurelist_files)} featurelist files")
    print(f"RT unit: {normalize_unit(rt_unit)}")

    process_func = partial(
        process_single_file,
        model_dict=model_dict,
        output_dir=output_dir,
        rt_columns=rt_columns,
        overwrite_original=overwrite_original,
        rt_unit=rt_unit,
        round_digits=round_digits,
        input_suffix=input_suffix,
        model_suffix=model_suffix
    )

    with mp.Pool(processes=n_workers) as pool:
        results = list(pool.imap(process_func, featurelist_files))

    successful = 0
    failed = 0

    print("PROCESSING SUMMARY:")

    for result in results:
        if result['success']:
            successful += 1
        else:
            failed += 1
            print(f"\n[FAIL] {result['file_name']}")
            print(f"  {result['message']}")

    print(f"TOTAL: {successful} successful, {failed} failed")


def parse_list_arg(s: str) -> List[str]:
    items = [x.strip() for x in (s or "").split(",") if x.strip()]
    return items


def main():
    parser = argparse.ArgumentParser(description="Batch RT correction for featurelist files using pre-trained models (model in minutes).")
    parser.add_argument("--featurelist_dir", required=True, help="Directory containing featurelist files (.txt/.csv)")
    parser.add_argument("--model_path", required=True, help="Path to model pickle (.pkl)")
    parser.add_argument("--output_dir", required=True, help="Directory to save corrected featurelists")
    parser.add_argument("--rt_columns", default="rt", help="Comma-separated RT column names, e.g. 'rt,RT (min),retention_time'")
    parser.add_argument("--overwrite_original", default="true", help="Overwrite original RT values when True; keep originals when False")
    parser.add_argument("--n_workers", type=int, default=None, help="Number of CPU processors (default: cpu_count-1)")
    parser.add_argument("--rt_unit", default="min", help="RT unit in input files: m/min/minute or s/sec/second (model expects minutes)")
    parser.add_argument("--round_digits", type=int, default=4, help="Round corrected RT to N digits (default: 4)")
    parser.add_argument("--input_suffix", default="", help="Suffix in featurelist filenames to replace, e.g. abc.csv")
    parser.add_argument("--model_suffix", default="", help="Suffix used in model keys, e.g. aab.tsv")

    args = parser.parse_args()

    if not os.path.isdir(args.featurelist_dir):
        print(f"[Error] featurelist_dir not found: {args.featurelist_dir}")
        sys.exit(1)

    if not os.path.isfile(args.model_path):
        print(f"[Error] model_path not found: {args.model_path}")
        sys.exit(1)

    models = load_models(args.model_path)
    print(f"Loaded {len(models)} models from {args.model_path}")

    overwrite = str(args.overwrite_original).strip().lower() in {"1", "true", "yes", "y", "t"}

    rt_cols = parse_list_arg(args.rt_columns)

    correct_feature_lists(
        featurelist_dir=args.featurelist_dir,
        model_dict=models,
        output_dir=args.output_dir,
        rt_columns=rt_cols,
        overwrite_original=overwrite,
        n_workers=args.n_workers,
        rt_unit=args.rt_unit,
        round_digits=args.round_digits,
        input_suffix=args.input_suffix,
        model_suffix=args.model_suffix
    )

def entrypoint():
    try:
        main()

    except SystemExit as e:
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

    finally:
        try:
            input("\nPress Enter to close...")
        except Exception:
            pass

if __name__ == '__main__':
    mp.freeze_support()
    entrypoint()

