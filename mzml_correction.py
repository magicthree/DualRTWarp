import argparse
import os
import re
import sys
import pickle
import numpy as np
import pandas as pd
import multiprocessing as mp
import traceback
from functools import partial
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pyopenms")

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

MODELS = {}

def rt_lines():
    return re.compile(
        r'(<cvParam\b[^>]*\baccession="(?:MS:1000892|MS:1000016)"[^>]*\bvalue=")'
        r'([\d.]+)'
        r'(\")'
        r'(?=[^>]*\bunitAccession="UO:(0000010|0000031)")',
        flags=re.IGNORECASE
    )
CVPARAM_PATTERN = rt_lines()

def init_worker(models_dict):
    global MODELS
    MODELS = models_dict

def load_models(model_path: str):
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def parse_suffixes_arg(s: str):
    if not s:
        return None
    items = [x.strip() for x in s.split(",") if x.strip()]
    return items if items else None

def correct_rt_for_mzml(mzml_dir: str, out_dir: str, fname: str, suffixes):
    input_path = os.path.join(mzml_dir, fname)
    model = None

    for suffix in suffixes:
        sample_key = fname.replace('.mzML', suffix).replace('.mzml', suffix)
        model = MODELS.get(sample_key)
        if model is not None:
            break

    if model is None:
        print("No model found for {} with model key: ".format(fname)+suffix)
        return

    text = open(input_path, 'r', encoding='utf-8').read()

    # collect RTs in mzml
    matches = []
    inputs = []
    for m in CVPARAM_PATTERN.finditer(text):
        rt_str, unit_code = m.group(2), m.group(4)
        start, end = m.span(2)
        ori_rt = float(rt_str)
        decimals = max(len(rt_str.split('.')[-1]) if '.' in rt_str else 0, 5)

        # model expects minutes
        minute_val = ori_rt / 60.0 if unit_code == '0000010' else ori_rt
        matches.append((start, end, unit_code, decimals))
        inputs.append([minute_val])

    if not matches:
        return

    try:
        outputs = model(inputs)
    except Exception as e:
        print(f"[Error] Model prediction for {fname}: {e}")
        return

    # rewrite RT
    parts = []
    last_idx = 0
    for (start, end, unit_code, decimals), out_val in zip(matches, outputs):
        parts.append(text[last_idx:start])
        corrected = float(out_val[0]) * (60.0 if unit_code == '0000010' else 1.0)
        parts.append(f"{{:.{decimals}f}}".format(corrected))
        last_idx = end
    parts.append(text[last_idx:])
    new_text = ''.join(parts)

    out_mzml = fname.replace('.mzML', '_RTcorrected.mzML')
    with open(os.path.join(out_dir, out_mzml), 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"[OK] {out_mzml}")

def main():
    parser = argparse.ArgumentParser(
        description="Batch RT correction for mzML files using pre-trained models."
    )
    parser.add_argument("--mzml_dir", required=True,
                        help="Input .mzML directory")
    parser.add_argument("--out_dir", required=True,
                        help="Output directory for corrected files")
    parser.add_argument("--model_path", required=True,
                        help="Path to rt_correction_models.pkl")
    parser.add_argument("--n_workers", type=int, default=16,
                        help="Number of CPU processors (default: cpu_count-1)")
    parser.add_argument("--model_suffix", default="",
                        help='Model file_suffix for matching .mzml file. '
                             'Example: input ".txt" means abc.txt correspond to abc.mzml. '
                             'If empty, use built-in defaults.')

    args = parser.parse_args()

    mzml_dir, out_dir, model_path = args.mzml_dir, args.out_dir, args.model_path
    if not os.path.isdir(mzml_dir):
        print(f"[Error] Input directory not found: {mzml_dir}")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    default_suffixes = [
        ".txt",
        ".csv",
        "_correct.txt",
        "_modified.txt",
        "_correct_modified.txt",
        ".mzML_chromatograms_resolved1_decon.csv"
    ]
    user_suffixes = parse_suffixes_arg(args.model_suffix)
    suffixes = user_suffixes if user_suffixes else default_suffixes

    files = [f for f in os.listdir(mzml_dir) if f.lower().endswith('.mzml')]
    if not files:
        print(f"[Warning] No .mzML files in {mzml_dir}")
        return
    models = load_models(model_path)

    pool = mp.Pool(
        processes=args.n_workers or mp.cpu_count()-1,
        initializer=init_worker,
        initargs=(models,)
    )
    pool.map(partial(correct_rt_for_mzml, mzml_dir, out_dir, suffixes=suffixes), files)
    pool.close()
    pool.join()

def entrypoint():
    try:
        main()

    except SystemExit as e:
        if e.code == 0:
            return
        print("\n[ERROR] Argument parsing caused exit.")
        print(f"SystemExit code: {e}")

    except Exception as e:
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
    mp.freeze_support()
    entrypoint()
