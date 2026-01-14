import numpy as np
import pandas as pd
np.set_printoptions(precision=4, suppress=True, linewidth=200)

def custom_interpolate(matrix: np.ndarray, p_thred=0.6, eps: float = 1e-12) -> np.ndarray:
    interpolated_matrix = matrix.copy().astype(float)
    m, n = interpolated_matrix.shape

    def count_valid_neighbors(i: int, j: int) -> int:
        count = 0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = i + di, j + dj
                if 0 <= ni < m and 0 <= nj < n and not np.isnan(interpolated_matrix[ni, nj]):
                    count += 1
        return count

    def find_nearby_candidates(i: int, j: int) -> list:
        candidates = []
        # Interpolate according to nearby values,
        # Left column (vertical 3-point)
        if 0 <= i-1 < m and 0 <= i+1 < m and 0 <= j-1 < n:
            v11 = interpolated_matrix[i-1, j-1]; v21 = interpolated_matrix[i  , j-1]; v31 = interpolated_matrix[i+1, j-1]
            v1t = interpolated_matrix[i-1, j];   v3t = interpolated_matrix[i+1, j]
            if (not np.isnan(v11) and not np.isnan(v21) and not np.isnan(v31)
                and not np.isnan(v1t) and not np.isnan(v3t)):
                candi_diff = v31 - v11
                diff = (v3t - v1t)
                p_range = candi_diff / diff if diff != 0 else 1
                p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                    p = (v21 - v11) / candi_diff
                    candidates.append(v1t + p * diff)

        # Right column (vertical 3-point)
        if 0 <= i-1 < m and 0 <= i+1 < m and 0 <= j+1 < n:
            v13 = interpolated_matrix[i-1, j+1]; v23 = interpolated_matrix[i  , j+1]; v33 = interpolated_matrix[i+1, j+1]
            v1t = interpolated_matrix[i-1, j];    v3t = interpolated_matrix[i+1, j]
            if (not np.isnan(v13) and not np.isnan(v23) and not np.isnan(v33)
                and not np.isnan(v1t) and not np.isnan(v3t)):
                candi_diff = v33 - v13
                diff = (v3t - v1t)
                p_range = candi_diff / diff if diff != 0 else 1
                p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                    p = (v23 - v13) / candi_diff
                    candidates.append(v1t + p * (diff))

        # Top row (horizontal 3-point)
        if 0 <= i-1 < m and 0 <= j-1 < n and 0 <= j+1 < n:
            u11 = interpolated_matrix[i-1, j-1]; u12 = interpolated_matrix[i-1, j  ]; u13 = interpolated_matrix[i-1, j+1]
            ut1 = interpolated_matrix[i  , j-1]; ut3 = interpolated_matrix[i  , j+1]
            if (not np.isnan(u11) and not np.isnan(u12) and not np.isnan(u13)
                and not np.isnan(ut1) and not np.isnan(ut3)):
                candi_diff = u13 - u11
                diff = (ut3 - ut1)
                p_range = candi_diff / diff if diff != 0 else 1
                p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                    p = (u12 - u11) / candi_diff
                    candidates.append(ut1 + p * (diff))

        # Bottom row (horizontal 3-point)
        if 0 <= i+1 < m and 0 <= j-1 < n and 0 <= j+1 < n:
            d11 = interpolated_matrix[i+1, j-1]; d12 = interpolated_matrix[i+1, j  ]; d13 = interpolated_matrix[i+1, j+1]
            dt1 = interpolated_matrix[i  , j-1]; dt3 = interpolated_matrix[i  , j+1]
            if (not np.isnan(d11) and not np.isnan(d12) and not np.isnan(d13)
                and not np.isnan(dt1) and not np.isnan(dt3)):
                candi_diff = d13 - d11
                diff = (dt3 - dt1)
                p_range = candi_diff / diff if diff != 0 else 1
                p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                    p = (d12 - d11) / candi_diff
                    candidates.append(dt1 + p * (diff))

        return candidates

    def find_bulk_candidates_by_row() -> int:
        filled = 0
        for i in range(m):
            j = 0
            while j < n:
                if np.isnan(interpolated_matrix[i, j]):
                    a = j
                    while j < n and np.isnan(interpolated_matrix[i, j]):
                        j += 1
                    b = j - 1
                    L, R = a - 1, b + 1

                    if not (0 <= L < n and 0 <= R < n):
                        continue
                    if np.isnan(interpolated_matrix[i, L]) or np.isnan(interpolated_matrix[i, R]):
                        continue

                    vals_list = []
                    diff = interpolated_matrix[i, R] - interpolated_matrix[i, L]

                    # Reference row above
                    if i - 1 >= 0:
                        ref = interpolated_matrix[i - 1]
                        if not np.isnan(ref[L:R + 1]).any():
                            candi_diff = ref[R] - ref[L]
                            p_range = candi_diff / diff if diff != 0 else 1
                            p_range_inv = diff / candi_diff if candi_diff != 0 else 1

                            if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                                tmp = []
                                for col in range(a, b + 1):
                                    p = (ref[col] - ref[L]) / candi_diff
                                    tmp.append(interpolated_matrix[i, L] + p * diff)
                                vals_list.append(tmp)

                    # Reference row below
                    if i + 1 < m:
                        ref = interpolated_matrix[i + 1]
                        if not np.isnan(ref[L:R + 1]).any():
                            candi_diff = ref[R] - ref[L]
                            p_range = candi_diff / diff if diff != 0 else 1
                            p_range_inv = diff / candi_diff if candi_diff != 0 else 1

                            if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                                tmp = []
                                for col in range(a, b + 1):
                                    p = (ref[col] - ref[L]) / candi_diff
                                    tmp.append(interpolated_matrix[i, L] + p * diff)
                                vals_list.append(tmp)

                    # Average candidate values
                    if vals_list:
                        for idx, col in enumerate(range(a, b + 1)):
                            candidates = [row_vals[idx] for row_vals in vals_list if not np.isnan(row_vals[idx])]
                            if candidates:
                                interpolated_matrix[i, col] = sum(candidates) / len(candidates)
                                filled += 1
                else:
                    j += 1
        return filled

    def find_bulk_candidates_by_col() -> int:
        filled = 0
        for j in range(n):
            i = 0
            while i < m:
                if np.isnan(interpolated_matrix[i, j]):
                    a = i
                    while i < m and np.isnan(interpolated_matrix[i, j]):
                        i += 1
                    b = i - 1
                    U, D = a - 1, b + 1

                    if not (0 <= U < m and 0 <= D < m):
                        continue
                    if np.isnan(interpolated_matrix[U, j]) or np.isnan(interpolated_matrix[D, j]):
                        continue

                    vals_list = []
                    diff = interpolated_matrix[D, j] - interpolated_matrix[U, j]

                    # Reference column left
                    if j - 1 >= 0:
                        ref = interpolated_matrix[:, j - 1]
                        if not np.isnan(ref[U:D + 1]).any():
                            candi_diff = ref[D] - ref[U]
                            p_range = candi_diff / diff if diff != 0 else 1
                            p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                            if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                                tmp = []
                                for row in range(a, b + 1):
                                    p = (ref[row] - ref[U]) / candi_diff
                                    tmp.append(interpolated_matrix[U, j] + p * diff)
                                vals_list.append(tmp)

                    # Reference column right
                    if j + 1 < n:
                        ref = interpolated_matrix[:, j + 1]
                        if not np.isnan(ref[U:D + 1]).any():
                            candi_diff = ref[D] - ref[U]
                            p_range = candi_diff / diff if diff != 0 else 1
                            p_range_inv = diff / candi_diff if candi_diff != 0 else 1
                            if abs(candi_diff) > eps and p_range > p_thred and p_range_inv > p_thred:
                                tmp = []
                                for row in range(a, b + 1):
                                    p = (ref[row] - ref[U]) / candi_diff
                                    tmp.append(interpolated_matrix[U, j] + p * diff)
                                vals_list.append(tmp)

                    # Average candidate values
                    if vals_list:
                        for idx, row in enumerate(range(a, b + 1)):
                            candidates = [row_vals[idx] for row_vals in vals_list if not np.isnan(row_vals[idx])]
                            if candidates:
                                interpolated_matrix[row, j] = sum(candidates) / len(candidates)
                                filled += 1
                else:
                    i += 1
        return filled

    # Candidate finding loop
    while True:
        total_filled = 0
        process=1
        while process > 0:
        # Row bulk interpolation
            process = find_bulk_candidates_by_row()
            total_filled += process

        process=1
        while process > 0:
            # Column bulk interpolation
            process = find_bulk_candidates_by_col()
            total_filled += process

        nan_positions = []
        for i in range(m):
            for j in range(n):
                if np.isnan(interpolated_matrix[i, j]):
                    neighbor_num = count_valid_neighbors(i, j)
                    nan_positions.append(((i, j), neighbor_num))
        if nan_positions:
            nan_positions.sort(key=lambda x: x[1], reverse=True)
            for (i, j), neigh_cnt in nan_positions:
                if np.isnan(interpolated_matrix[i, j]) and neigh_cnt > 0:
                    cands = find_nearby_candidates(i, j)
                    if cands:
                        interpolated_matrix[i, j] = np.mean(cands)
                        total_filled += 1

        # exit if no new points were filled
        if total_filled == 0:
            break

    return interpolated_matrix

