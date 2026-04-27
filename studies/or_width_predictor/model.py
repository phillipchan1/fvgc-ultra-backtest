"""Ridge regression on log(or_45min_range) with bootstrap prediction
intervals. Pure numpy/pandas — no sklearn dependency.

Why ridge: features are correlated (atr_5d/10d/20d, or_5min/15min) and we
care about stability of coefficients more than squeezing the last drop of
fit. Ridge handles correlated features without coefficient explosion.

Why log target: or_45min_range is right-skewed (mean 130, std 75); log
transform makes residuals near-normal and lets us treat coefficients as
multiplicative drivers ("VIX z-score +1 → +12% wider OR").
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FittedRidge:
    feature_names: list[str]
    coef: np.ndarray            # standardized-space coefficients
    intercept: float            # in log space
    feat_mean: np.ndarray
    feat_std: np.ndarray
    resid_std: float            # in log space (for intervals)
    train_residuals: np.ndarray  # bootstrap pool

    def predict_log(self, X: pd.DataFrame) -> np.ndarray:
        Xs = self._standardize(X)
        return Xs @ self.coef + self.intercept

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.exp(self.predict_log(X))

    def predict_interval(
        self, X: pd.DataFrame, lower: float = 0.10, upper: float = 0.90
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (point, lo, hi) using empirical residual quantiles."""
        log_pt = self.predict_log(X)
        q_lo = np.quantile(self.train_residuals, lower)
        q_hi = np.quantile(self.train_residuals, upper)
        return np.exp(log_pt), np.exp(log_pt + q_lo), np.exp(log_pt + q_hi)

    def driver_contributions(self, x_row: pd.Series) -> pd.DataFrame:
        """For a single day, decompose the prediction into per-feature
        contributions in pts. Useful for the morning briefing.
        """
        x = x_row[self.feature_names].values.astype(float)
        xs = (x - self.feat_mean) / np.where(self.feat_std == 0, 1, self.feat_std)
        log_contrib = xs * self.coef       # per-feature log-pt impact
        baseline_pts = np.exp(self.intercept)
        full_log = self.intercept + log_contrib.sum()
        full_pts = np.exp(full_log)

        # Convert each log contribution into a pts delta vs baseline-only.
        # Use first-order: pts_delta_i ≈ full_pts * log_contrib_i / sum
        rows = []
        for name, lc, raw, z in zip(self.feature_names, log_contrib, x, xs):
            rows.append({
                'feature': name,
                'value': raw,
                'z': z,
                'log_contrib': lc,
                'pts_contrib': full_pts * lc,  # approximate marginal pts
            })
        df = pd.DataFrame(rows)
        df['abs_pts'] = df['pts_contrib'].abs()
        return df.sort_values('abs_pts', ascending=False), baseline_pts, full_pts

    def _standardize(self, X: pd.DataFrame) -> np.ndarray:
        x = X[self.feature_names].values.astype(float)
        std = np.where(self.feat_std == 0, 1, self.feat_std)
        return (x - self.feat_mean) / std


def fit_ridge(
    X: pd.DataFrame,
    y: pd.Series,
    feature_names: list[str],
    alpha: float = 1.0,
    use_log_target: bool = True,
) -> FittedRidge:
    """Closed-form ridge: beta = (X'X + alpha*I)^-1 X'y on standardized X.

    Drops rows where any feature or target is NaN.
    """
    df = X[feature_names].copy()
    df['_y'] = y
    df = df.dropna()
    Xv = df[feature_names].values.astype(float)
    yv = df['_y'].values.astype(float)
    if use_log_target:
        yv = np.log(yv)

    mu = Xv.mean(axis=0)
    sd = Xv.std(axis=0)
    sd_safe = np.where(sd == 0, 1, sd)
    Xs = (Xv - mu) / sd_safe

    y_mean = yv.mean()
    yc = yv - y_mean

    p = Xs.shape[1]
    beta = np.linalg.solve(Xs.T @ Xs + alpha * np.eye(p), Xs.T @ yc)
    intercept = y_mean

    yhat = Xs @ beta + intercept
    resid = yv - yhat

    return FittedRidge(
        feature_names=list(feature_names),
        coef=beta,
        intercept=intercept,
        feat_mean=mu,
        feat_std=sd,
        resid_std=resid.std(),
        train_residuals=resid,
    )


def permutation_importance(
    model: FittedRidge,
    X: pd.DataFrame,
    y: pd.Series,
    n_repeats: int = 20,
    seed: int = 42,
) -> pd.DataFrame:
    """How much does shuffling each feature degrade prediction?
    Reports mean increase in MAE (in pts, after exp()).
    """
    rng = np.random.default_rng(seed)
    df = X[model.feature_names].copy()
    df['_y'] = y
    df = df.dropna()
    base_pred = model.predict(df)
    base_mae = np.mean(np.abs(base_pred - df['_y'].values))

    rows = []
    for f in model.feature_names:
        deltas = []
        for _ in range(n_repeats):
            shuffled = df.copy()
            shuffled[f] = rng.permutation(shuffled[f].values)
            pred = model.predict(shuffled)
            mae = np.mean(np.abs(pred - shuffled['_y'].values))
            deltas.append(mae - base_mae)
        rows.append({
            'feature': f,
            'mae_increase_pts': np.mean(deltas),
            'mae_increase_std': np.std(deltas),
        })
    return pd.DataFrame(rows).sort_values('mae_increase_pts', ascending=False)


def walk_forward_predict(
    df: pd.DataFrame,
    feature_names: list[str],
    target: str,
    date_col: str = 'date',
    test_years: tuple[int, ...] = (2023, 2024, 2025, 2026),
    alpha: float = 1.0,
    rolling_window: int | None = 504,
) -> pd.DataFrame:
    """For each test day, train on the prior `rolling_window` trading days
    (or all earlier days if rolling_window is None). Returns one row per
    test day with predicted + interval + actual.

    Why rolling: vol regimes shift (post-COVID 2021 ≈ 100 pt OR, 2022 ≈
    155, 2025 ≈ 168). A 2-year window adapts; expanding window biases.

    For efficiency, we refit the model once per test year, on the last
    `rolling_window` rows ending the day before the test year starts.
    Within a year the model is constant — close enough given regimes
    don't usually flip mid-year.
    """
    df = df.sort_values(date_col).copy()
    df['_year'] = pd.to_datetime(df[date_col]).dt.year
    out_frames = []
    for ty in test_years:
        train_full = df[df['_year'] < ty]
        test = df[df['_year'] == ty]
        if rolling_window is not None and len(train_full) > rolling_window:
            train_full = train_full.iloc[-rolling_window:]
        if len(test) == 0:
            continue
        train_clean = train_full[feature_names + [target]].dropna()
        if len(train_clean) < 100:
            continue
        model = fit_ridge(
            train_clean, train_clean[target], feature_names, alpha=alpha
        )
        test_clean = test.dropna(subset=feature_names).copy()
        if len(test_clean) == 0:
            continue
        pt, lo, hi = model.predict_interval(test_clean)
        test_clean = test_clean.assign(
            predicted=pt, pred_lo=lo, pred_hi=hi,
            actual=test_clean[target], test_year=ty,
        )
        out_frames.append(test_clean[[date_col, 'predicted', 'pred_lo', 'pred_hi',
                                      'actual', 'test_year']])
    if not out_frames:
        return pd.DataFrame()
    return pd.concat(out_frames, ignore_index=True)


def evaluate_predictions(pred_df: pd.DataFrame) -> dict:
    """MAE in pts, MAPE, R², 80% interval coverage."""
    if pred_df.empty:
        return {}
    err = pred_df['predicted'] - pred_df['actual']
    mae = np.mean(np.abs(err))
    mape = np.mean(np.abs(err) / pred_df['actual']) * 100
    ss_res = (err ** 2).sum()
    ss_tot = ((pred_df['actual'] - pred_df['actual'].mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    in_band = (
        (pred_df['actual'] >= pred_df['pred_lo']) &
        (pred_df['actual'] <= pred_df['pred_hi'])
    ).mean()
    # Spearman of pred vs actual — does the ranking work?
    from scipy.stats import spearmanr
    rho, _ = spearmanr(pred_df['predicted'], pred_df['actual'])
    return {
        'n': len(pred_df),
        'mae_pts': mae,
        'mape_pct': mape,
        'r2': r2,
        'spearman_rho': rho,
        'interval_coverage_80': in_band,
    }
