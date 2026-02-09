suppressPackageStartupMessages({
  library(xcms)
  library(MSnbase)
  library(reticulate)
})

# Python read model
.ensure_py_pkgs <- function(pkgs) {
  reticulate::py_config()
  for (p in pkgs) {
    if (!reticulate::py_module_available(p)) {
      reticulate::py_require(p, action = "add")
    }
  }
}


.load_py_models <- function(pkl_path) {
  pickle   <- reticulate::import("pickle", convert = FALSE)
  builtins <- reticulate::import("builtins", convert = FALSE)
  f <- builtins$open(pkl_path, "rb")
  on.exit(f$close(), add = TRUE)
  pickle$load(f)
}

.select_model_for_file <- function(py_models, file_path,
                                   input_suffix = ".mzML",
                                   model_suffix = ".txt") {
  fn  <- basename(file_path)
  base <- tools::file_path_sans_ext(fn)
  
  keys <- unique(c(
    paste0(base, model_suffix),
    paste0(base, "_feature_list", model_suffix),
    fn,
    base,
    paste0(base, ".txt"),
    paste0(base, ".csv")
  ))
  
  for (k in keys) {
    m <- tryCatch(py_models$get(k, NULL), error = function(e) NULL)
    if (!is.null(m)) return(m)
  }
  NULL
}

# Prediction
.predict_batch_min <- function(py_model, x_min) {
  inputs <- lapply(as.numeric(x_min), function(z) list(z))
  res <- py_model(inputs)
  r <- reticulate::py_to_r(res)
  
  if (is.null(r)) return(rep(NA_real_, length(x_min)))
  if (is.atomic(r)) return(as.numeric(r))
  if (is.matrix(r) || is.data.frame(r)) return(as.numeric(r[, 1]))
  if (is.list(r)) {
    return(vapply(r, function(el) as.numeric(el)[1], numeric(1)))
  }
  as.numeric(r)
}

# adjustedRtime builder
.build_adjustedRtime_from_models <- function(xdata, models_by_sample, verbose = TRUE) {
  
  raw_rt <- rtime(xdata, adjusted = FALSE)
  fd <- MSnbase::fData(xdata)
  
  map_col <- "fileIdx"
  file_map <- as.integer(fd[[map_col]])
  n_files  <- max(file_map, na.rm = TRUE)
  
  unit <- if (max(raw_rt, na.rm = TRUE) > 200) "sec" else "min"
  raw_min <- if (unit == "sec") raw_rt / 60 else raw_rt
  corr_min <- raw_min
  
  for (i in seq_len(n_files)) {
    idx <- which(file_map == i)
    if (!length(idx)) next
    m <- models_by_sample[[i]]
    if (is.null(m)) next
    
    pred <- .predict_batch_min(m, raw_min[idx])
    bad <- is.na(pred)
    pred[bad] <- raw_min[idx][bad]
    corr_min[idx] <- pred
    
    if (verbose) {
      delta <- pred - raw_min[idx]
      j <- which.max(abs(delta))
      max_delta <- delta[j]
      
      message(
        "[file ", i, "] max ΔRT (min): ",
        sprintf("%+.4f", max_delta)
      )
    }
  }
  
  corr_store <- if (unit == "sec") corr_min * 60 else corr_min
  scan_names <- rownames(fd)
  
  out <- vector("list", n_files)
  for (i in seq_len(n_files)) {
    idx <- which(file_map == i)
    v <- corr_store[idx]
    names(v) <- scan_names[idx]
    out[[i]] <- v
  }
  
  out
}

# MAIN FUNCTION
apply_RT_Corrector_XCMS <- function(xdata,
                                    model_pkl,
                                    input_suffix = ".mzML",
                                    model_suffix = ".txt",
                                    verbose = TRUE) {
  
  stopifnot(is(xdata, "XCMSnExp"))
  
  .ensure_py_pkgs(c("numpy", "scipy", "scikit-learn", "joblib"))
  
  py_models <- .load_py_models(model_pkl)
  
  files <- fileNames(xdata_peaks)
  models_by_sample <- vector("list", length(files))
  for (i in seq_along(files)) {
    models_by_sample[[i]] <-
      .select_model_for_file(py_models, files[[i]],
                             input_suffix, model_suffix)
  }
  
  adj_list   <- .build_adjustedRtime_from_models(xdata_peaks, models_by_sample, verbose)

  xdata_corr <- xdata
  
  adjustedRtime(xdata_corr) <- adj_list
  
  xdata_corr
}

export_corr_feature_lists <- function(
    xdata,
    outdir = ".",
    suffix = ".csv"
) {
  if (!dir.exists(outdir)) {
    dir.create(outdir, recursive = TRUE)
  }
  
  cp <- chromPeaks(xdata)
  cp_df <- as.data.frame(cp)
  
  cp_df$rt_min <- cp_df$rt / 60
  
  cp_df$sample_name <- basename(fileNames(xdata_corr))[cp_df$sample]
  
  cp_df <- cp_df[cp_df$into > 0 & !is.na(cp_df$into), ]
  
  cp_df$sample_name <- basename(cp_df$sample_name)
  cp_df$sample_name <- sub("\\.mzML$", "", cp_df$sample_name)
  cp_df$sample_name <- as.character(cp_df$sample_name)
  
  unique_names <- unique(cp_df$sample_name)
  print(unique_names)
  
  for (sn in unique_names) {
    idx   <- cp_df$sample_name == sn
    df_sn <- cp_df[idx, ]
    
    message("sample ", sn, " contains ", nrow(df_sn), " features")
    
    df_sn <- df_sn[, c("mz", "rt", "rt_min", "sn", "into")]
    
    out_csv <- file.path(
      outdir,
      paste0(sn, suffix)
    )
    
    write.csv(df_sn, out_csv, row.names = FALSE)
  }
  
  invisible(unique_names)
}
