# Production model diagnostic report

## 1. Executive summary

The selected artifact remains the existing `RandomForestRegressor` with the `daylight_model_night_zero` strategy. This audit does not tune, replace, or overwrite it. The current LOSO mean is MAE 0.1442, RMSE 0.1997, and R2 0.4855.

The current `merge_asof(direction=nearest)` produced 0.00% future matches in this dataset. Maximum and mean absolute offsets are reported in `diagnostics/temporal_matching.csv`. A zero value here is evidence about these hourly files only; `nearest` remains potentially non-causal for off-grid timestamps.

## 2. Temporal integrity and weather matching

The audit checked duplicate `(system_id, timestamp, ac_power_W)` rows, ordering, effective hourly frequencies, gaps, and matching offsets. See `temporal_matching.csv`. Training should be described as nearest historical archive matching, not as a strictly past-only predictor.

## 3. Timezone and DST

Official timezones, coordinates, geometry, DST-localization results, spring/autumn samples, and UTC ordering are in `solar_quality.csv`. The implementation currently resolves ambiguous local timestamps with `ambiguous=False` and nonexistent timestamps with `nonexistent=shift_forward`; these are explicit assumptions and should be reviewed against the PVDAQ timestamp convention.

## 4. Solar and POA validation

`poa_quality.csv` contains per-system distribution statistics and negative-value rates for GHI, DNI, DHI, solar position, total POA, and POA components. The implementation clips negative irradiance inputs and negative POA outputs to zero, so this audit cannot distinguish a raw negative sensor value from a clipped feature without the raw weather payload.

## 5. Tracker 1430

The tracker uses `axis_tilt=0`, `axis_azimuth=official azimuth`, `max_angle=90`, `backtrack=True`, and `gcr=0.4`. Only axis azimuth is from the official catalog. Backtracking, GCR, max angle, and axis tilt are model assumptions unless separately documented by the owner. Representative angle, POA, and power values are in `tracker_1430_diagnostics.csv`; sensitivity results are in `sensitivity_analysis.csv`.

## 6. Target and power quality

`power_quality.csv` reports normalized target and raw AC-power ranges, including negative, over-capacity, >1.1 and >1.2 fractions. No observations were removed by this audit.

## 7. Residuals and strategy comparison

`residual_summary.csv` reports bias, spread, correlations, low/high POA behavior, and daylight/night bias per fold. `night_strategy_comparison.csv` compares the two requested strategies by fold and day/night metrics.

## 8. Generalization

LOSO covers four systems only. Systems 10 and 1430 are both in Colorado, so the 1430 fold is not an unseen geographic region. `domain_shift.csv` reports fold-specific train ranges and test medians; it does not justify claims beyond these four sites.

## 9. Physical baseline and sensitivity

`physical_baseline_metrics.csv` calibrates a POA factor on training rows inside each fold. `sensitivity_analysis.csv` records night thresholds, tracker assumptions, and matching tolerances. These are diagnostics, not model selection.

## 10. Leakage audit

`leakage_audit.csv` checks that system ID, AC power, historical PVDAQ POA, and full-data preprocessing are not part of the production feature contract. Fold fitting and baseline calibration are training-only.

## 11. Inference validation

`inference_validation.csv` exercises fixed systems 10, 34, 1239, tracker 1430, and night/day/dawn/dusk cases. It also verifies the four output fields required by the inference contract.

## 12. Historical comparison

The existing `model_comparison.csv` is retained. Its legacy comparison is not algorithm-only: it also changes the feature representation by using historical PVDAQ POA and PolynomialFeatures.

## 13. Limitations and recommendations

The principal limitations are nearest matching that may use future weather, four-site LOSO, a Colorado region represented twice, assumed tracker parameters, and local timestamp DST resolution. Before any next-phase model experiments, document the operational weather availability policy, validate tracker metadata with the system owner, and decide whether causal matching is required. No model alternative or tuning was performed in this phase.

## 14. Cleanup

`inventory_before_cleanup.csv` records the audited files and conservative classifications. No production, metadata, test, requirements, legacy comparison, or reproducibility artifact was deleted or moved automatically.
