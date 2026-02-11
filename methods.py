import argparse
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="statsmodels")

import heapq
import os
import math
from collections import defaultdict
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from scipy.interpolate import interp1d
from scipy.stats import linregress
from formatting import extract_rt, extract_intensity, apply_extract_rt
from interpolate import custom_interpolate

#processing feature lists
def remove_isotopes(df, rt_tol=0.05, mz_tol=0.01, iso_mass_diff=1.003, max_iso=5):
    df = df.sort_values(by='mz').reset_index(drop=True)
    df['keep'] = True

    for idx, row in df.iterrows():
        if not df.at[idx, 'keep']:
            continue

        for k in range(1, max_iso + 1):
            target_mz = row['mz'] + iso_mass_diff * k

            cond = (
                    df['keep'] &
                    df['mz'].between(target_mz - mz_tol, target_mz + mz_tol) &
                    df['rt'].between(row['rt'] - rt_tol, row['rt'] + rt_tol)
            )

            candidates = df.loc[cond]
            if not candidates.empty:
                df.loc[candidates.index, 'keep'] = False

    return df[df['keep']].drop(columns='keep').reset_index(drop=True)


def remove_same_feature(filedata, rt_tol=0.2, mz_abs_tol=0.02, mz_ppm_tol=15):
    from sklearn.cluster import DBSCAN

    for col in ['rt', 'mz', 'intensity']:
        if col not in filedata.columns:
            raise ValueError(f"Missing required column: {col}")

    def custom_dist(a, b):
        drt = abs(a[0] - b[0]) / rt_tol
        mz1, mz2 = a[1], b[1]
        avg_mz = 0.5 * (mz1 + mz2)
        ppm_tol_val = avg_mz * (mz_ppm_tol / 1e6)
        tol = max(mz_abs_tol, ppm_tol_val)
        dmz = abs(mz1 - mz2) / tol
        return max(drt, dmz)

    df = filedata.copy()
    rt_mz = df[['rt', 'mz']].to_numpy()
    clustering = DBSCAN(eps=1.0, min_samples=1, metric=custom_dist).fit(rt_mz)

    filedata['cluster'] = clustering.labels_
    idx_to_keep = filedata.groupby('cluster')['intensity'].idxmax()
    filtered = filedata.loc[idx_to_keep].copy()
    filtered.drop(columns=['cluster'], inplace=True)

    return filtered

def process_single_feature_list(args):
    file, bk, qc, id_col, rt_col, mz_col, intensity_col, min_peak, sep,rt_unit = args

    filename = os.path.basename(file)
    datafile = pd.read_csv(file, sep=sep)
    filtered_datafile = datafile.iloc[:, [id_col, rt_col, mz_col, intensity_col]]
    filtered_datafile.columns = ['ID', 'rt', 'mz', 'intensity']
    filtered_datafile['mz'].values.astype(float)
    filtered_datafile = filtered_datafile[filtered_datafile['intensity'] > min_peak]
    if  str(rt_unit).strip().lower() not in ['minute', 'minutes','min']:
        filtered_datafile['rt'] = filtered_datafile['rt'].astype(float) / 60
    else:
        filtered_datafile['rt'] = filtered_datafile['rt'].astype(float)

    filtered_datafile=remove_isotopes(filtered_datafile)
    filtered_datafile = remove_same_feature(filtered_datafile)
    if filename in bk:
        label = "Blank"
    elif filename in qc:
        label = "QC"
    else:
        label = "Sample"
    return [filtered_datafile, os.path.basename(file), label]

def analyze_file(filelist, bk, qc, id_col, rt_col, mz_col, intensity_col, min_peak=10000, cpu=8, sep=",", rt_unit="minute"):
    from multiprocessing import Pool, cpu_count

    args_list = [(file, bk, qc, id_col, rt_col, mz_col, intensity_col, min_peak, sep, rt_unit) for file in filelist]
    with Pool(processes=min(cpu_count(), cpu)) as pool:
        exp_file_ls = pool.map(process_single_feature_list, args_list)
    return exp_file_ls

#Filter data
def remove_outlier_features(
        matrix: pd.DataFrame,
        col_list: list[str],
        threshold: float,
) -> pd.DataFrame:

    missing = [c for c in col_list if c not in matrix.columns]
    if missing:
        raise ValueError(f"These columns are missing in DataFrame: {missing}")

    #get rt values
    values_matrix = []
    for row_idx in range(matrix.shape[0]):
        row_values = []
        for col_name in col_list:
            raw = matrix.iat[row_idx, matrix.columns.get_loc(col_name)]
            try:
                val = float(extract_rt(raw)) if not pd.isna(raw) else np.nan
            except Exception:
                val = np.nan
            row_values.append(val)
        values_matrix.append(row_values)

    rt_means = []
    variances = []
    variances_for_percentile = []
    max_adjacent_diffs = []
    diffs_for_percentile = []

    for row_values in values_matrix:
        valid_values = [v for v in row_values if not np.isnan(v)]

        if len(valid_values) > 0:
            mean_val = np.mean(valid_values)
            rt_means.append(mean_val)

            variance = np.sum([(v - mean_val) ** 2 for v in valid_values]) / len(valid_values)
            variances.append(variance)

            if len(valid_values) > 5:
                variances_for_percentile.append(variance)
        else:
            rt_means.append(np.nan)
            variances.append(0.0)

        if len(valid_values) >= 2:
            diffs = [
                abs(valid_values[i + 1] - valid_values[i])
                for i in range(len(valid_values) - 1)
            ]
            max_diff = max(diffs)
            max_adjacent_diffs.append(max_diff)
            diffs_for_percentile.append(max_diff)
        else:
            max_adjacent_diffs.append(0.0)

    #remove features with top 1% variance
    variance_threshold = np.percentile(variances_for_percentile, 99) if variances_for_percentile else np.inf
    adjacent_diff_threshold = np.percentile(diffs_for_percentile, 99.5) if diffs_for_percentile else np.inf
    features_to_drop = set()
    removed_rows = 0

    for row_idx in range(len(values_matrix)):
        row_values = values_matrix[row_idx]
        variance = variances[row_idx]
        mean_val = rt_means[row_idx]
        max_adj_diff = max_adjacent_diffs[row_idx]

        if np.isnan(mean_val):
            continue

        if variance >= variance_threshold and variance > 0:
            features_to_drop.add(row_idx)
            removed_rows+=1
            continue

        if max_adj_diff >= adjacent_diff_threshold:
            features_to_drop.add(row_idx)
            removed_rows += 1
            continue

        #remove features with large RT deviation to mean value
        for value in row_values:
            if not np.isnan(value):
                deviation = abs(value - mean_val)

                if deviation > threshold:
                    features_to_drop.add(row_idx)
                    removed_rows += 1
                    break


    #delete outlier features
    if features_to_drop:
        return matrix.drop(index=list(features_to_drop)).reset_index(drop=True)

    else:
        return matrix.copy()

def remove_low_occurrence_features(ori_matrix, sp_ls, min_col, min_col2, theoretical_max_rt, theoretical_min_rt, rt_col):
    # collect main features
    matrix = ori_matrix.copy()
    non_null_counts_main = matrix[sp_ls].notnull().sum(axis=1)
    mask_main = non_null_counts_main >= min_col
    aligned_main = matrix.loc[mask_main].copy().reset_index(drop=True)

    # collect RT edge features
    max_rt_main_initial = aligned_main[rt_col].max()
    min_rt_main_initial = aligned_main[rt_col].min()
    rt = matrix[rt_col]
    is_extra = (
        ((rt > max_rt_main_initial) & (rt <= theoretical_max_rt)) |
        ((rt < min_rt_main_initial) & (rt >= theoretical_min_rt))
    )
    extra_candidates = matrix.loc[is_extra].copy()

    non_null_counts_extra = extra_candidates[sp_ls].notnull().sum(axis=1)
    mask_extra = non_null_counts_extra >= min_col2
    aligned_extra = extra_candidates.loc[mask_extra].reset_index(drop=True)

    # combine features
    aligned_combined = pd.concat([aligned_main, aligned_extra], ignore_index=True).drop_duplicates()
    aligned_combined = aligned_combined.sort_values(rt_col).reset_index(drop=True)
    return aligned_combined

def filter_bin(ori_matrix, sample_list, rt_col, n_bins):
    # binning features by RT
    feature_coverage = ori_matrix[sample_list].notnull().sum(axis=1)
    matrix = ori_matrix.copy()
    matrix['_coverage'] = feature_coverage
    matrix['rt_bin'] = pd.cut(matrix[rt_col], bins=n_bins)

    # get the optimum feature in each bin
    keep_indices = []
    for bin_interval, group in matrix.groupby('rt_bin', observed=True):
        if group.empty:
            continue

        group_sorted = group.sort_values(
            by=['_coverage', 'avg_intensity'],
            ascending=[False, False]
        )

        main_idx = group_sorted.index[0]
        keep_indices.append(main_idx)
        selected_cols = set(group_sorted.loc[main_idx, sample_list][
                                group_sorted.loc[main_idx, sample_list].notnull()
                            ].index)

        # filling bins with complementary features
        for idx in group_sorted.index[1:]:
            row = group_sorted.loc[idx, sample_list]
            row_cols = set(row[row.notnull()].index)
            if selected_cols.isdisjoint(row_cols):
                keep_indices.append(idx)
                selected_cols.update(row_cols)

    binned_matrix = matrix.loc[keep_indices].drop(columns=['rt_bin', '_coverage']).reset_index(drop=True)

    return binned_matrix

def filter_aligned_matrix(
    align_matrix,
    sp_list,
    qc_list,
    bk_list,
    all_sp_ls,
    min_sample,
    min_sample2,
    min_feature_pair,
    rt_range_min,
    rt_range_max,
    rt_bins=None,
    rt_col="median_rt",
    output_dir='./',
    prefix='.csv',
    linearfit=True,
    linear_r=0.7,
    if_corrected=False,
    summary_matrix: pd.DataFrame = None,
    max_rt_diff=0.2
):
    # basic analysis
    if if_corrected:
        align_matrix = update_corrected_matrix(align_matrix, summary_matrix, all_sp_ls)
        target_cols = set(sp_list + qc_list + bk_list)
        keep_cols = set(all_sp_ls)
        cols_to_drop = list(target_cols - keep_cols)
        align_matrix = align_matrix.drop(columns=cols_to_drop, errors='ignore')

    intensity_df = align_matrix[sp_list].apply(lambda col: col.map(extract_intensity))
    align_matrix['avg_intensity'] = intensity_df.mean(axis=1, skipna=True)
    align_matrix = align_matrix.sort_values('avg_intensity', ascending=False).reset_index(drop=True)
    align_matrix = align_matrix.sort_values(rt_col).reset_index(drop=True)

    # filter low occurrence feature
    aligned_combined = remove_low_occurrence_features(align_matrix, sp_list, min_sample, min_sample2, rt_range_max, rt_range_min, rt_col)

    # filter features with multiple identity within one sample
    contains_multiple = aligned_combined[all_sp_ls].map(
        lambda x: isinstance(x, str) and ';' in x
    )
    mask_single = ~contains_multiple.any(axis=1)
    aligned_single = aligned_combined.loc[mask_single].reset_index(drop=True)
    print("Primary feature: ", aligned_single.shape[0])

    aligned_filters, new_all_sample_list = reorder_columns_by_variation(
        aligned_single, all_sp_ls, linear_fit=linearfit, linear_r=linear_r,
        min_feature_pair=min_feature_pair, extract=True
    )

    aligned_filters = remove_outlier_features(aligned_filters, new_all_sample_list, max_rt_diff)
    print("Filtered rows based on: Top 1% variance threshold, Top 0.5% single outlier:", aligned_filters.shape[0])

    if rt_bins is not None and rt_bins > 0:
        aligned_filters = filter_bin(aligned_filters, new_all_sample_list, rt_col, rt_bins)
        print("Binned row: ", aligned_filters.shape[0])

    aligned_filters, new_all_sample_list = reorder_columns_by_variation(
        aligned_filters, new_all_sample_list, linear_fit=linearfit, linear_r=linear_r,
        min_feature_pair=min_feature_pair, extract=True
    )

    apply_extract_rt(aligned_filters, new_all_sample_list).to_csv(
        os.path.join(output_dir, prefix + "aligned_filtered_matrix.csv"), index=False)

    return aligned_filters, new_all_sample_list

def apply_models_to_big_data(df, models, decimal_places=4):
    def _apply_model(row):
        model = models.get(row['sample_id'], None)
        rt = row['rt']
        if model is not None and pd.notna(rt):
            try:
                corrected = model([rt])[0]
                return round(float(corrected), decimal_places)
            except Exception:
                return rt
        else:
            return rt
    df2 = df.copy()
    df2['rt'] = df2.apply(_apply_model, axis=1)
    return df2

def dbscan_alignment(all_data, rt_tol=0.5, mz_abs_tol=0.02, mz_ppm_tol=20):
    from sklearn.cluster import DBSCAN

    def custom_dist(a, b):
        drt = abs(a[0] - b[0]) / rt_tol
        mz1, mz2 = a[1], b[1]
        avg_mz = 0.5 * (mz1 + mz2)
        ppm_tol_val = avg_mz * (mz_ppm_tol / 1e6)
        tol = max(mz_abs_tol, ppm_tol_val)
        dmz = abs(mz1 - mz2) / tol
        return max(drt, dmz)

    df = all_data.copy()
    rt_mz = df[['rt', 'mz']].to_numpy()
    db = DBSCAN(eps=1.0, min_samples=1, metric=custom_dist).fit(rt_mz)
    df['cluster_label'] = db.labels_
    df = df[df['cluster_label'] != -1]

    # Remove mz outliers within each cluster
    def filter_mz_outliers(group):
        label = group.name
        if len(group) <= 2:
            out = group
        else:
            mz_median = group['mz'].median()
            mz_tol = np.maximum(mz_abs_tol, mz_median * mz_ppm_tol / 1e6)
            out = group[np.abs(group['mz'] - mz_median) <= mz_tol]
        out = out.copy()
        out['cluster_label'] = label
        return out

    df = df.groupby('cluster_label', group_keys=False).apply(filter_mz_outliers, include_groups=False).reset_index(drop=True)

    # Recompute feature_id from filtered clusters
    def make_rep_id(group: pd.DataFrame):
        idx_max_intensity = group['intensity'].idxmax()
        row = group.loc[idx_max_intensity]
        return f"{row['ID']}_{row['rt']:.3f}_{row['mz']:.3f}"

    rep_ids = df.groupby('cluster_label', group_keys=False).apply(make_rep_id, include_groups=False)
    df['feature_id'] = df['cluster_label'].map(rep_ids)

    df['value_str'] = df.apply(
        lambda r: f"{r['ID']}_{r['rt']:.4f}_{r['mz']:.6f}_{int(r['intensity'])}",
        axis=1
    )

    aligned = df.pivot_table(
        index='feature_id',
        columns='sample_id',
        values='value_str',
        aggfunc=lambda x: ';'.join(x)
    )

    rep_median = df.groupby('feature_id')[['rt', 'mz']].median()
    rep_median['rt'] = rep_median['rt'].round(4)
    rep_median['mz'] = rep_median['mz'].round(6)

    aligned = aligned.merge(rep_median, left_index=True, right_index=True)
    aligned.reset_index(inplace=True)
    aligned.rename(columns={'rt': 'median_rt', 'mz': 'median_mz'}, inplace=True)

    sample_cols = [c for c in aligned.columns if c not in ('feature_id', 'median_rt', 'median_mz')]
    aligned = aligned[['feature_id', 'median_rt', 'median_mz'] + sample_cols]

    return aligned


def update_corrected_matrix(aligned_matrix: pd.DataFrame,
                            bigdata: pd.DataFrame,
                            sp_ls: list) -> pd.DataFrame:

    bigdata_lookup = {
        (feature.ID, feature.sample_id): f"{feature.ID}_{feature.rt:.4f}_{feature.mz:.6f}_{int(feature.intensity)}"
        for feature in bigdata.itertuples(index=False)
    }

    def process_cell(cell: str, sample_name: str) -> str:
        if not isinstance(cell, str) or "_" not in cell:
            return cell
        items = cell.split(";")
        new_items = []
        for item in items:
            parts = item.split("_", 3)
            if len(parts) != 4:
                new_items.append(item)
                continue
            id_str, rt_str, mz_str, inten_str = parts
            try:
                id_int = int(id_str)
            except ValueError:
                new_items.append(item)
                continue
            key = (id_int, sample_name)
            if key in bigdata_lookup:
                new_items.append(bigdata_lookup[key])
            else:
                print(f"Warning: no match for ID={id_int} in sample='{sample_name}'")
                new_items.append(item)
        return ";".join(new_items)

    result = aligned_matrix.copy()
    for sample in sp_ls:
        result[sample] = result[sample].apply(lambda x: process_cell(x, sample))

    def extract_rts(cell: str) -> list:
        if not isinstance(cell, str):
            return []
        rts = []
        for item in cell.split(";"):
            parts = item.split("_")
            if len(parts) >= 3:
                try:
                    rts.append(float(parts[1]))
                except ValueError:
                    continue
        return rts

    median_rts = []
    for _, row in result.iterrows():
        rts = []
        for sample in sp_ls:
            rts.extend(extract_rts(row[sample]))
        if rts:
            median_rts.append(np.median(rts))
        else:
            median_rts.append(np.nan)

    result["median_rt"] = median_rts
    return result


def reorder_columns_by_variation(matrix, all_samples, linear_fit=False, extract=True, min_feature_pair=5, linear_r=0.7):
    # remove samples with limited feature groups
    non_na_counts = matrix[all_samples].notna().sum()
    removed_cols = [col for col in all_samples if non_na_counts[col] < min_feature_pair]
    all_samples = [col for col in all_samples if col not in removed_cols]

    if len(removed_cols) > 0:
        matrix = matrix.drop(columns=removed_cols)
        print(f"Removed {len(removed_cols)} samples with < {min_feature_pair} candidate features:\n{removed_cols}")

    max_clusters = max(1, math.ceil(len(all_samples) / 10))

    def compute_offset_scores(samples, matrix, max_clusters, cluster_label=""):
        # calculate offset
        med_rt = matrix['median_rt'].astype(float)
        offset_dict = {}
        offset_matrix = pd.DataFrame(index=matrix.index, columns=samples)

        for sample in samples:
            valid = matrix[sample].notna() & med_rt.notna()
            rt_val = matrix.loc[valid, sample]
            if extract:
                rt_val = rt_val.apply(extract_rt).astype(float)
            else:
                rt_val = rt_val.astype(float)
            valid_m_rt = med_rt[valid]

            offsets = rt_val - valid_m_rt
            if len(offsets) > 0:
                lower = np.percentile(offsets, 5)
                upper = np.percentile(offsets, 95)
                trimmed_offsets = offsets[(offsets >= lower) & (offsets <= upper)]
                offset_dict[sample] = trimmed_offsets.mean() if len(trimmed_offsets) > 0 else 0
            else:
                offset_dict[sample] = 0

            offset_matrix.loc[valid, sample] = offsets

        if len(samples) <= 1 or max_clusters == 1:
            return sorted(samples, key=lambda c: offset_dict[c]), offset_dict

        # cluster based on offset
        clust_data = []
        for sample in samples:
            col_data = offset_matrix[sample].copy()
            clust_data.append(col_data.astype(float))

        df_clust = pd.DataFrame(clust_data).T
        df_clust.columns = samples
        df_clust = df_clust.fillna(0)

        # euclidean distance
        from scipy.spatial.distance import pdist
        condensed_dist = pdist(df_clust.T, metric='euclidean')

        # ward.D cluster
        from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
        Z = linkage(condensed_dist, method='ward')
        cluster_labels = fcluster(Z, max_clusters, criterion='maxclust')
        cluster_groups = {}
        group_offsets = {}
        for idx, sample in enumerate(samples):
            label = cluster_labels[idx]
            if label not in cluster_groups:
                cluster_groups[label] = []
                group_offsets[label] = 0
            cluster_groups[label].append(sample)
            group_offsets[label] += offset_dict[sample]

        for label in cluster_groups:
            group_offsets[label] /= len(cluster_groups[label])

        # visulized cluster
        # num_clusters = len(cluster_groups)
        # if num_clusters > 1:
        #     plt.figure(figsize=(12, 6))
        #     dendrogram(Z, labels=samples, orientation='top', leaf_rotation=90)
        #
        #     # 获取达到目标簇数的距离阈值
        #     if len(Z) > 0:
        #         # 找到达到最大簇数所需的距离阈值
        #         if max_clusters > 1 and len(Z) >= max_clusters:
        #             target_threshold = Z[-max_clusters + 1, 2]
        #         else:
        #             target_threshold = Z[-1, 2]
        #         plt.axhline(y=target_threshold, color='r', linestyle='--',
        #                     label=f'Max clusters threshold: {target_threshold:.2f} ({num_clusters} clusters)')
        #
        #     plt.title(f'Cluster Dendrogram ({cluster_label}) - Max clusters: {max_clusters}, Actual: {num_clusters}')
        #     plt.xlabel('Columns')
        #     plt.ylabel('Distance')
        #     plt.legend()
        #     plt.tight_layout()
        #     plt.show()

        # reorder by cluster and offset
        sorted_clusters = sorted(cluster_groups.keys(), key=lambda x: group_offsets[x])
        ordered_samples = []
        for label in sorted_clusters:
            group_samples = sorted(cluster_groups[label], key=lambda x: offset_dict[x])
            ordered_samples.extend(group_samples)

        return ordered_samples, offset_dict

    # reorder with cluster
    matrix = extract_center_nearest(matrix, all_samples, extract)
    ordered_1, offset_dict_1 = compute_offset_scores(all_samples, matrix, max_clusters, "First Pass")

    # renew matrix
    prefix_cols = [c for c in matrix.columns if c not in all_samples]
    new_order_s1 = prefix_cols + ordered_1
    matrix = matrix[new_order_s1]  # 实际更新列顺序
    matrix = extract_center_nearest(matrix, ordered_1, extract)

    # fiter features with linear shift
    if linear_fit:
        excluded_df=pd.DataFrame(columns=['1st rt', 'slope', 'r2'])
        def is_good_linear_fit(row, threshold=linear_r):
            if extract:
                row = row[ordered_1].apply(lambda x: extract_rt(x)).astype(float).dropna()
            else: row = row[ordered_1].astype(float).dropna()
            if len(row) < 2:
                return False
            x = np.arange(len(row))
            slope, intercept, r_value, p_value, std_err = linregress(x, row)
            exclude = slope >= 0 and r_value**2 >= threshold
            if not exclude:
                excluded_df.loc[len(excluded_df)] = [
                    round(row.iloc[0], 2),
                    round(slope, 2),
                    round(r_value ** 2, 2)
                ]

            return exclude

        good_mask = matrix[ordered_1].apply(is_good_linear_fit, axis=1)
        matrix_good = matrix.loc[good_mask].copy()
        if len(excluded_df) > 0:
            print("features after linear filter:",matrix_good.shape[0])

        matrix = matrix_good.copy()

        prefix_cols = [c for c in matrix.columns if c not in ordered_1]
        new_order_refit = prefix_cols + ordered_1
        matrix = matrix[new_order_refit]

        matrix = matrix.sort_values('median_rt').reset_index(drop=True)
        ordered_2, offset_dict_2 = compute_offset_scores(ordered_1, matrix, max_clusters, "Second Pass")

        prefix_cols = [c for c in matrix.columns if c not in all_samples]
        new_order_s2 = prefix_cols + ordered_2
        matrix = matrix[new_order_s2]
        matrix = extract_center_nearest(matrix, ordered_2, extract)
    else:
        ordered_2 = ordered_1

    return matrix, ordered_2


def extract_center_nearest(matrix: pd.DataFrame, sample_col: list[str], extract: bool = False) -> pd.DataFrame:
    def parse_rt(val):
        if val in (None, '', 'nan') or pd.isna(val):
            return np.nan
        try:
            if extract:
                rt_str = extract_rt(val)
                if rt_str is None:
                    return np.nan
                return float(rt_str)
            else:
                return float(val)
        except (ValueError, TypeError):
            return np.nan

    if len(sample_col) <= 2:
        temp_df = matrix.copy()

        # directly use mean value as median rt
        #temp_df['median_rt'] = temp_df[sample_col].applymap(parse_rt).mean(axis=1, skipna=True)

        # reorder features
        original_len = len(temp_df)
        result_df = temp_df.dropna(subset=['median_rt']).sort_values(by='median_rt').reset_index(drop=True)
        dropped = original_len - len(result_df)
        if dropped > 0:
            print(f"Filtered rows with failed median rt calculation: {dropped}")

        return result_df

    # turn data into numeric
    n_rows, n_cols = len(matrix), len(sample_col)
    all_values = np.full((n_rows, n_cols), np.nan)
    for i, row in enumerate(matrix[sample_col].itertuples(index=False)):
        all_values[i] = [parse_rt(x) for x in row]

    # initialize
    center_sample_idx = (n_cols - 1) // 2
    result_vals = np.full(n_rows, np.nan)
    processed = np.zeros(n_rows, dtype=bool)
    neighbor_cache = defaultdict(list)
    attempt_count = np.zeros(n_rows, dtype=int)
    current_pri = np.zeros(n_rows)  # 记录每行当前优先级

    # initial center value -- already have value
    center_vals = all_values[:, center_sample_idx]
    mask_center = ~np.isnan(center_vals)
    result_vals[mask_center] = center_vals[mask_center]
    processed[mask_center] = True

    # estimate center RT by nearby features
    window_size = min(max(1, int(0.1 * n_rows)), 20)
    half_window = window_size // 2

    # priority calculation
    heap = []
    counter = 0
    def push(idx, pri):
        nonlocal counter
        heapq.heappush(heap, (-pri, counter, idx))
        current_pri[idx] = pri
        counter += 1

    for i in range(n_rows):
        if processed[i]: continue
        start, end = max(0, i - half_window), min(n_rows, i + half_window + 1)
        dists = []
        for j in range(start, end):
            if i != j and processed[j]:
                dist = abs(i - j)
                dists.append(dist)
                neighbor_cache[i].append((j, dist))
        # more neighbor, higher priority
        pri = (len(dists) / (np.mean(dists) + 1e-5)) if dists else 0.0
        push(i, pri)

    # estimating, start with feature groups riches in neighbor features
    while heap:
        _, _, i = heapq.heappop(heap)
        if processed[i]:
            continue

        estimates, weights = [], []
        for j, dist in neighbor_cache[i]:
            valid = ~np.isnan(all_values[i]) & ~np.isnan(all_values[j])
            if valid.any():
                diffs = all_values[i, valid] - all_values[j, valid]
                estimates.append(result_vals[j] + np.nanmean(diffs))
                weights.append(1.0 / (2**dist))

        if estimates:
            result_vals[i] = np.dot(estimates, weights) / np.sum(weights)
            processed[i] = True
            start, end = max(0, i - half_window), min(n_rows, i + half_window + 1)
            for k in range(start, end):
                if not processed[k] and k != i:
                    dist = abs(k - i)
                    neighbor_cache[k].append((i, dist))
                    dlist = [d for _, d in neighbor_cache[k]]
                    pri_k = len(dlist) / ((sum(dlist) / len(dlist)) + 1e-5)
                    new_pri = current_pri[k] + pri_k * 0.0001
                    push(k, new_pri)
                    push(k, pri_k)

        else:
            attempt_count[i] += 1
            if attempt_count[i] <= 5:
                tiny_pri = 1e-8 / attempt_count[i]
                push(i, tiny_pri)
            else:
                processed[i] = True  # 放弃
                result_vals[i] = np.nan

    matrix['median_rt'] = result_vals

    matrix = matrix.dropna(subset=['median_rt']).sort_values(by='median_rt').reset_index(drop=True)
    dropped = n_rows - matrix.shape[0]
    if dropped>0:
        print(f"Filter rows with failed median rt calculation: {matrix.shape[0]}")

    return matrix


def interpolate_and_heatmap(ori_matrix, all_sample_cols, interpolate_f, save_path='interpolated_heatmap.png', linear_fit=True, linear_r=0.7, min_feature_pair=5, extract=False):
    import seaborn as sns
    from matplotlib.colors import LinearSegmentedColormap
    matrix = ori_matrix.copy()

    #data preparation
    matrix,all_sample_cols=reorder_columns_by_variation(matrix, all_sample_cols, linear_fit=linear_fit, extract=extract,
                                                        min_feature_pair=min_feature_pair, linear_r=linear_r)

    matrix_selected = matrix[['median_rt'] + all_sample_cols]
    matrix_selected = matrix_selected.set_index('median_rt').sort_index()
    median_rt_vals = matrix_selected.index.to_numpy()
    num_matrix = matrix_selected.to_numpy(dtype=float)

    #interporlate
    interpolated_matrix = custom_interpolate(num_matrix, interpolate_f)
    interpolated_df = pd.DataFrame(
        interpolated_matrix,
        index=median_rt_vals,
        columns=all_sample_cols
    ).reset_index().rename(columns={'index': 'median_rt'})

    non_sample_cols = [col for col in matrix.columns if col not in all_sample_cols and col != 'median_rt']
    if non_sample_cols:
        non_sample_data = matrix[['median_rt'] + non_sample_cols].dropna(subset=['median_rt'])
        non_sample_data = non_sample_data.groupby('median_rt')[non_sample_cols].first().sort_index().reset_index()
        interpolated_df = interpolated_df.merge(
            non_sample_data,
            on='median_rt',
            how='left'
        )

    final_cols = ['feature_id'] + ['median_rt'] + ['median_mz'] + all_sample_cols
    interpolated_df = interpolated_df.loc[:, final_cols]
    interpolated_df = extract_center_nearest(interpolated_df, all_sample_cols)

    # calculate RT shift matrix
    sample_data = interpolated_df[all_sample_cols].to_numpy(dtype=float)
    median_rt_vals = interpolated_df['median_rt'].to_numpy()
    grid_z_offset = sample_data - median_rt_vals[:, np.newaxis]
    max_abs_val = np.nanmax(np.abs(grid_z_offset))
    yticks_formatted = [f"{v:.2f}" for v in median_rt_vals]

    def format_value(val):
        if np.isnan(val):
            return ""
        else:
            return f"{abs(val):.2f}"

    # visualize RT shift matrix
    annot_array = np.vectorize(format_value)(grid_z_offset)
    plt.figure(figsize=(max(4, len(all_sample_cols) / 2), max(4, len(median_rt_vals) / 2)))
    sns.heatmap(
        grid_z_offset,
        xticklabels=all_sample_cols,
        yticklabels=yticks_formatted,
        cmap=LinearSegmentedColormap.from_list("blue_gray_red", ["blue", "#f6f6f6", "red"]),
        cbar_kws={'label': 'Deviation from Median RT',
                  'aspect': 30,},
        vmin=-max_abs_val,
        vmax=max_abs_val,
        annot=annot_array,
        fmt="",
        annot_kws={
            "fontsize": 8,
            "ha": "center",
            "va": "center"
        },
        linewidths=0.5,
        linecolor='lightgray'
    )
    plt.title('Interpolated Heatmap')
    plt.xlabel('Samples')
    plt.ylabel('Median RT')

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    plt.close()

    print(f"Interpolated heatmap saved to: {save_path}")
    return interpolated_df, all_sample_cols


def loess_slope_iterative_adjust(
    x, y,
    frac=0.3,
    it=3,
    min_slope=0.0,
    max_slope=3.0,
    x_left=None, y_left=None,
    x_right=None, y_right=None
):
    from statsmodels.nonparametric.smoothers_lowess import lowess

    order = np.argsort(x)
    xs, ys = x[order], y[order]

    # LOESS fit
    lo = lowess(ys, xs, frac=frac, it=it, return_sorted=True)
    x_lo, y_lo = lo[:, 0], lo[:, 1]

    # constrain the curve
    if x_left is not None and y_left is not None:
        x_lo = np.concatenate([[x_left], x_lo])
        y_lo = np.concatenate([[y_left], y_lo])
    if x_right is not None and y_right is not None:
        x_lo = np.concatenate([x_lo, [x_right]])
        y_lo = np.concatenate([y_lo, [y_right]])

    idx = np.argsort(x_lo)
    x_lo, y_lo = x_lo[idx], y_lo[idx]

    y_adj = np.empty_like(y_lo)
    y_adj[0] = y_lo[0]
    dx = np.diff(x_lo)
    for i in range(len(dx)):
        dy_raw = y_lo[i + 1] - y_adj[i]
        min_dy = min_slope * dx[i]
        max_dy = max_slope * dx[i]
        y_adj[i + 1] = y_adj[i] + np.clip(dy_raw, min_dy, max_dy)

    return interp1d(
        x_lo, y_adj,
        kind='linear',
        bounds_error=False,
        fill_value=(y_adj[0], y_adj[-1])
    )

def plot_correction_curves(matrix, models, all_sample_list, rt_max, rt_min, ref_col='median_rt', output_dir='rt_correction_plots', suffix=''):
    os.makedirs(output_dir, exist_ok=True)

    for samp in all_sample_list:
        model = models.get(samp)
        plt.figure(figsize=(6, 6))

        # Extract and convert sample and reference RT values
        samp_vals = pd.to_numeric(matrix[samp], errors='coerce').values.astype(float)
        ref_vals = pd.to_numeric(matrix[ref_col], errors='coerce').values.astype(float)
        valid_mask = (~np.isnan(samp_vals)) & (~np.isnan(ref_vals))

        x_valid = samp_vals[valid_mask]
        y_valid = ref_vals[valid_mask]-x_valid

        # If model exists, plot the fit curve
        if model is not None:
            x_line = np.linspace(rt_max, rt_min, 200)
            y_pred_line = model(x_line)
            y_residual_line = y_pred_line - x_line
            plt.plot(x_line, y_residual_line, color='red', linewidth=2,
                     label='Residuals: predicted RT – raw RT (min)')
            plt.axhline(0, color='green', linestyle='--', linewidth=2, label='Zero line')
            plt.scatter(x_valid, y_valid, s=5, color='blue', alpha=0.3, label='Original')
            plt.xlabel(f"{len(x_valid)} Raw RT")
            plt.ylabel("Residual (Predict – Raw RT)")
            plt.title(f"{samp}")
            plt.legend(loc='best')
            plt.tight_layout()
            filename = f"{samp}{suffix}.png" if suffix else f"{samp}.png"
            plt.savefig(os.path.join(output_dir, filename))
            plt.close()
        else:
            print(samp + " has no model")

def model_build(matrix_rt, all_samples,
                ref_col="median_rt",
                mz_col="median_mz",
                feature_id_col="feature_id",
                output_csv="corrected_loess.csv",
                rt_max=None,
                frac=0.1,
                it=3,
                min_slope=0.33,
                max_slope=3):

    models = {}
    corrected_dict = {ref_col: matrix_rt[ref_col].values}

    if rt_max is None:
        rt_max = matrix_rt[ref_col].max()

    for samp in all_samples:
        tmp = matrix_rt[[samp, ref_col]].dropna(subset=[samp, ref_col])
        if tmp.shape[0] < 2:
            models[samp] = None
            corrected_dict[f"{samp}_corrected"] = np.full(matrix_rt.shape[0], np.nan)
            continue

        # generate input for model fit
        x = np.round(tmp[samp].astype(float).values, 3)
        y = np.round(tmp[ref_col].astype(float).values, 3)


        f_lo = loess_slope_iterative_adjust(x, y,
                                    frac=frac, it=it,
                                    min_slope=min_slope,
                                    max_slope=max_slope,x_left=0, y_left=0, x_right=rt_max, y_right=rt_max)

        models[samp] = f_lo

        samp_vals = pd.to_numeric(matrix_rt[samp], errors='coerce').values.astype(float)
        corrected = np.where(np.isnan(samp_vals),
                             np.nan,
                             f_lo(samp_vals))
        corrected_dict[f"{samp}_corrected"] = corrected

    # generate correction results for each sample
    df_out = pd.DataFrame({
        feature_id_col: matrix_rt[feature_id_col].values,
        ref_col:        matrix_rt[ref_col].values,
        mz_col:         matrix_rt[mz_col].values,
    })

    combined_cols = {}
    for samp in all_samples:
        orig_key = f"{samp}_orig"
        combined_cols[orig_key] = pd.to_numeric(matrix_rt[samp], errors='coerce')

        corr_key = f"{samp}_corrected"
        combined_cols[corr_key] = corrected_dict[corr_key]

    alt_df = pd.DataFrame(combined_cols)

    alt_columns = []
    for samp in all_samples:
        alt_columns.append(f"{samp}_orig")
        alt_columns.append(f"{samp}_corrected")

    alt_df = alt_df[alt_columns]
    df_out = pd.concat([df_out, alt_df], axis=1)

    df_out.to_csv(output_csv, index=False)
    print(f"Correction result saved as: {output_csv}")
    return models

def str2bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    raise argparse.ArgumentTypeError("Boolean expected (true/false).")