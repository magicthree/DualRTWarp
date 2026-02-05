import json
import os,sys
import pickle
import pandas as pd
import argparse
import multiprocessing as mp

from formatting import  apply_extract_rt
from methods import (
    analyze_file,
    dbscan_alignment,
    filter_aligned_matrix,
    apply_models_to_big_data,
    reorder_columns_by_variation,
    interpolate_and_heatmap, model_build, plot_correction_curves
)

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

def user_preset_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "RTCorrector")
    d = os.path.dirname(sys.executable)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "user_presets.json")

def load_user_presets() -> dict:
    path = user_preset_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_user_presets(presets: dict) -> None:
    path = user_preset_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)

def configsets():
    return {
    "default": {
        "datatype": "msdial",
        "calculate_summary_data": False,
        "linearfit": False,
        "linear_r": 0.6,
        "min_peak": 5000,
        "dbscan_rt": 0.4,
        "dbscan_rt2": 0.2,
        "dbscan_mz": 0.02,
        "dbscan_mz_ppm": 15,
        "rt_max": 45,
        "min_sample": 10,
        "min_sample2": 5,
        "min_feature_group": 5,
        "rt_bins": 500,
        "it": 3,
        "loess_frac": 0.1,
        "max_rt_diff": 0.5,
        "interpolate_p": 0.6
    },
    "Ha96": {
        "datatype": "msdial",
        "calculate_summary_data": False,
        "linearfit": True,
        "linear_r": 0.6,
        "min_peak": 5000,
        "dbscan_rt": 0.4,
        "dbscan_rt2": 0.2,
        "dbscan_mz": 0.02,
        "dbscan_mz_ppm": 15,
        "rt_max": 45,
        "min_sample": 10,
        "min_sample2": 5,
        "min_feature_group": 5,
        "rt_bins": 500,
        "it": 3,
        "loess_frac": 0.1,
        "max_rt_diff": 1.2,
        "interpolate_p": 0.6,
        "input_dir": r"E:\Halo_lipidomic_zhang\featurelist",
        "output_dir": r"E:\Halo_lipidomic_zhang\GUItest"
    }
}
PRESET_CONFIGS = configsets()
PRESET_CONFIGS.update(load_user_presets())

def parse_arguments():
    parser = argparse.ArgumentParser(description='RT Correction Pipeline')
    # Base parameters
    parser.add_argument('--config', type=str, default='default',
                        help='Preset configuration name')
    parser.add_argument('--input_dir', type=str,
                        help='Path of input feature lists')
    parser.add_argument('--output_dir', type=str,
                        help='Path of output files')
    parser.add_argument('--datatype', type=str, choices=['csv','tsv','msdial'],
                        help='Choose between "csv","tsv", and "msdial"')
    parser.add_argument('--calculate_summary_data', type=str,
                        help='If True, feature list collection is re-run even if previous results exist; if False, existing results are used.')
    parser.add_argument('--min_peak', type=int,
                        help='Minimum features intensity/area to be involved')
    parser.add_argument('--rt_max', type=float,
                        help='Maximum retention time of the dataset')
    # csv/tsv parameters
    parser.add_argument('--id_col', type=int,
                        help='ID column number in feature lists (for .csv/.tsv mode)')
    parser.add_argument('--mz_col', type=int,
                        help='Mz column number in feature lists (for .csv/.tsv mode)')
    parser.add_argument('--rt_col', type=int,
                        help='RT column number in feature lists (for .csv/.tsv mode)')
    parser.add_argument('--intensity_col', type=int,
                        help='Intensity/area column number in feature lists (for .csv/.tsv mode)')
    parser.add_argument('--time_format', type=str,
                        help='min or sec')
    parser.add_argument('--file_suffix', type=str,
                        help='.csv .txt etc')

    # DBSCAN
    parser.add_argument('--dbscan_rt', type=float,
                        help='DBSCAN RT tolerance for 1st round correction (min)')
    parser.add_argument('--dbscan_rt2', type=float,
                        help='DBSCAN RT tolerance for 2nd round correction (min)')
    parser.add_argument('--dbscan_mz', type=float,
                        help='DBSCAN absolute m/z threshold')
    parser.add_argument('--dbscan_mz_ppm', type=float,
                        help='DBSCAN m/z ppm threshold')
    # Filter
    parser.add_argument('--linearfit', type=str, default=False,
                        help="This function enables linear regression of feature RT as a function of sample order"
                        "Features with linear coefficient r lower than given threshold will be filtered"
                        "Recommended for one batch dataset where shows continuous RT shift along the sequence")
    parser.add_argument('--linear_r', type=float,
                        help='r threshold for linear fit. (0-1)')
    parser.add_argument('--max_rt_diff', type=float,
                        help='Maximum RT shifts expected, compared to medium value')

    parser.add_argument('--min_sample', type=int,
                        help='Minimum number of samples in which a feature should be present')
    parser.add_argument('--min_sample2', type=int,
                        help='Minimum number of samples in which a feature should be present. (For edge RT regions with fewer features)')
    parser.add_argument('--min_feature_group', type=int,
                        help='Minimum number of features required a sample')
    parser.add_argument('--rt_bins', type=int,
                        help='Number of rt bins used for grouping features')

    parser.add_argument('--it', type=int,
                        help='Number of iterations used for the LOESS fitting')
    parser.add_argument('--loess_frac', type=float,
                        help='Fraction of data points used for local LOESS fitting (0-1). Higher values produce smoother curve')
    parser.add_argument('--interpolate_f', type=float,
                        help='Controls interpolation strictness: higher values are more strict')
    parser.add_argument('--create_preset', type=str, metavar='Str',
                        help='Create a new preset with the given name from other arguments and exit')


    return parser.parse_args()

def convert_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ['true', 't', 'yes', 'y', '1']:
            return True
        elif value.lower() in ['false', 'f', 'no', 'n', '0']:
            return False
    raise TypeError('Boolean value expected.')

def load_configuration(args):
    config = PRESET_CONFIGS.get(args.config).copy()
    if not config:
        raise ValueError(f"Preset '{args.config}' not found. Available presets: {list(PRESET_CONFIGS.keys())}")
    config = config.copy()

    for param in vars(args):
        value = getattr(args, param)
        if value is not None and param != 'config':
            if param in ['calculate_summary_data', 'linearfit']:
                config[param] = convert_bool(value)
            else:
                config[param] = value

    return config

def main():
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    pd.options.display.float_format = '{:.2f}'.format

    args = parse_arguments()
    if args.create_preset:
        preset_name = args.create_preset.strip()
        if not preset_name:
            print("[ERROR] Preset name for --create_preset cannot be empty.")
            return

        print(f"Creating preset: '{preset_name}'...")
        user_presets = load_user_presets()

        if preset_name in user_presets or preset_name in configsets():
            print(f"Warning: Preset '{preset_name}' already exists and will be overwritten.")

        new_config = {}
        # Populate new_config from provided arguments, falling back to defaults for unspecified ones.
        current_config_for_defaults = load_configuration(args)
        for key, default_value in current_config_for_defaults.items():
            arg_value = getattr(args, key, None)
            if arg_value is not None:
                new_config[key] = convert_bool(arg_value) if key in ['calculate_summary_data',
                                                                     'linearfit'] else arg_value
            else:
                new_config[key] = default_value

        user_presets[preset_name] = new_config
        save_user_presets(user_presets)
        print(f"Preset '{preset_name}' saved successfully to {user_preset_path()}")
        return

    config = load_configuration(args)

    datatype = config["datatype"]
    calculate_summary_data = config["calculate_summary_data"]
    linearfit = config["linearfit"]
    linear_r = config["linear_r"]
    min_peak = config["min_peak"]
    dbscan_rt = config["dbscan_rt"]
    dbscan_rt2 = config["dbscan_rt2"]
    dbscan_mz = config["dbscan_mz"]
    dbscan_mz_ppm = config["dbscan_mz_ppm"]
    rt_max = config["rt_max"]
    min_sample = config["min_sample"]
    min_sample2 = config["min_sample2"]
    min_feature_group = config["min_feature_group"]
    rt_bins = config["rt_bins"]
    max_rt_diff = config["max_rt_diff"]
    it = config["it"]
    loess_frac = config["loess_frac"]
    interpolate_f = config["interpolate_f"]
    input_dir = config["input_dir"]
    output_dir = config["output_dir"]
    if datatype == 'csv' or datatype == 'tsv':
        id_col = config["id_col"]
        rt_col = config["rt_col"]
        mz_col = config["mz_col"]
        intensity_col = config["intensity_col"]
        time_format = config["time_format"]
        file_suffix = config["file_suffix"]
        print(config["time_format"])

    if datatype == "mzmine":
        sep = ","
        id_col = 0
        rt_col = 1
        mz_col = 4
        intensity_col = 7
        time_format = "minute"
        file_suffix = ".csv"
    elif datatype == "msdial":
        sep = "\t"
        id_col = 0
        rt_col = 4
        mz_col = 6
        intensity_col = 7
        time_format = "minute"
        file_suffix = ".txt"
    elif datatype == "tsv":
        sep = "\t"
    elif datatype == "csv":
        sep = ","
    else:
        raise ValueError('Unsupported datatype: choose "msdial", "mzmine", "csv", or "tsv.')

    os.makedirs(output_dir, exist_ok=True)
    filelist = [
        os.path.join(input_dir, file)
        for file in os.listdir(input_dir)
        if file.endswith(file_suffix)
    ]

    print(f"Detected {len(filelist)} files in {input_dir}")
    if len(filelist) == 0:
        raise ValueError('No files to process.')

    bk_list = [i for i in os.listdir(input_dir) if "_bk" in i.lower() or "blank" in i.lower()]
    qc_list = [i for i in os.listdir(input_dir) if "_qc" in i.lower()]
    if calculate_summary_data or not os.path.exists(os.path.join(output_dir, "summary_data.csv")):
        print(f"Calculating summary feature lists")
        # Generate summary data from input files
        all_data_list = analyze_file(
            filelist=filelist,
            bk=bk_list,
            qc=qc_list,
            id_col=id_col,
            rt_col=rt_col,
            mz_col=mz_col,
            intensity_col=intensity_col,
            min_peak=min_peak,
            cpu=18,
            sep=sep,
            time_format=time_format
        )
        summary_data = pd.DataFrame()
        sp_list = []
        for df, sample_id, sample_type in all_data_list:
            df['sample_id'] = sample_id
            summary_data = pd.concat([summary_data, df], ignore_index=True)
            if sample_type == "Sample":
                sp_list.append(sample_id)
        summary_data.to_csv(os.path.join(output_dir, "summary_data.csv"), index=False)
    else:
        print(f"Load precomputed summary feature lists")
        summary_data = pd.read_csv(os.path.join(output_dir, "summary_data.csv"))
        sp_list = summary_data['sample_id'].unique().tolist()
        sp_list = [x for x in sp_list if x not in bk_list and x not in qc_list]

    all_list = sp_list + bk_list + qc_list

    align_df = dbscan_alignment(summary_data, rt_tol=dbscan_rt, mz_abs_tol=dbscan_mz, mz_ppm_tol=dbscan_mz_ppm)
    align_df.to_csv(os.path.join(output_dir, "1st_run_dbscan.csv"), index=False)

    aligned_matrix_filtered_single, new_all_sample_list = filter_aligned_matrix(
        align_df, sp_list, qc_list, bk_list, all_list,
        min_sample=min_sample, min_sample2=min_sample2, min_feature_pair=min_feature_group, rt_range_min=0, rt_range_max=rt_max,
        rt_bins=rt_bins, output_dir=output_dir, prefix="1st_run_",max_rt_diff=max_rt_diff,
        linearfit=linearfit,linear_r=linear_r
    )

    align_df_filter_RT = apply_extract_rt(aligned_matrix_filtered_single, new_all_sample_list)
    align_df_filter_RT_re_inter , new_all_sample_list = interpolate_and_heatmap(
        align_df_filter_RT, new_all_sample_list,
        interpolate_f=interpolate_f, save_path=os.path.join(output_dir, "1st_run_interpolate.png"), linear_fit=linearfit,linear_r=linear_r,
        min_feature_pair=min_feature_group,extract=False
    )

    models = model_build(
        align_df_filter_RT_re_inter, new_all_sample_list,
        ref_col="median_rt", feature_id_col="feature_id",
        output_csv=os.path.join(output_dir, "1st_corrected_rts.csv"),
        rt_max=rt_max,frac=loess_frac,it=it
    )


    plot_correction_curves(
        align_df_filter_RT_re_inter, models, new_all_sample_list,
        rt_max, 0, output_dir=os.path.join(output_dir, "rt_correction_plots"), suffix="_1st_run"
    )

    cor_summary_data = apply_models_to_big_data(summary_data, models, decimal_places=4)
    cor_summary_data.to_csv(os.path.join(output_dir, "corr_summary_data.csv"), index=False)

    cor_align_df = dbscan_alignment(cor_summary_data, rt_tol=dbscan_rt2, mz_abs_tol=dbscan_mz, mz_ppm_tol=dbscan_mz_ppm)
    cor_align_df.to_csv(os.path.join(output_dir, "corr_run_dbscan.csv"), index=False)

    sp_list = [x for x in sp_list if x in new_all_sample_list]
    qc_list = [x for x in qc_list if x in new_all_sample_list]
    bk_list = [x for x in bk_list if x in new_all_sample_list]

    cor_align_df_filter_single, new_all_sample_list = filter_aligned_matrix(
        cor_align_df, sp_list, qc_list, bk_list, new_all_sample_list,
        min_sample=min_sample, min_sample2=min_sample2, min_feature_pair=min_feature_group, rt_range_min=0, rt_range_max=rt_max,
        rt_bins=rt_bins, output_dir=output_dir, prefix="corr_",
        if_corrected=True, summary_matrix=summary_data,max_rt_diff=max_rt_diff,
        linearfit=linearfit,linear_r=linear_r
    )

    cor_recover_filter, new_all_sample_list = reorder_columns_by_variation(
        cor_align_df_filter_single, new_all_sample_list, linear_fit=linearfit,linear_r=linear_r, min_feature_pair=min_feature_group
    )
    cor_recover_filter = apply_extract_rt(cor_recover_filter, new_all_sample_list)
    cor_recover_filter_inter, new_all_sample_list = interpolate_and_heatmap(
        cor_recover_filter, new_all_sample_list,
        interpolate_f=interpolate_f, save_path=os.path.join(output_dir, "final_interpolate.png"),
        linear_fit=linearfit,linear_r=linear_r, min_feature_pair=min_feature_group,extract=False
    )

    # Final model build and save
    models2 = model_build(
        cor_recover_filter_inter, new_all_sample_list,
        ref_col="median_rt", feature_id_col="feature_id",
        output_csv=os.path.join(output_dir, "cor_filter_recover_inter_correct.csv"),
        rt_max=rt_max,frac=loess_frac,it=it
    )
    plot_correction_curves(
        cor_recover_filter_inter, models2, new_all_sample_list,
        rt_max, 0, output_dir=os.path.join(output_dir, "rt_correction_plots"), suffix='_final'
    )

    removed_cols = [col for col in sp_list + qc_list + bk_list if col not in new_all_sample_list]
    if len(removed_cols) > 0:
        print(f"{len(removed_cols)} were removed from for poor features groups: {removed_cols}")

    with open(os.path.join(output_dir, "rt_correction_models.pkl"), "wb") as f:
        pickle.dump(models2, f)

    with open(os.path.join(output_dir, "1st_run_rt_correction_models.pkl"), "wb") as f2:
        pickle.dump(models, f2)

    print("Saved models to 'rt_correction_models.pkl'")

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

    finally:
        try:
            input("\nPress Enter to close...")
        except Exception:
            pass

if __name__ == '__main__':
    mp.freeze_support()
    entrypoint()




