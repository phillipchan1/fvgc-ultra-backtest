"""Track C — Replay Simulator, Account Survival, Hypothesis Family, Film Room.

Deterministic replay of the program benchmark play (opening-window FVG short,
no protected_swing) per results/REPLAY_RULES.md. Reduced benchmark-only mode:
Track A returned a negative result, so there are no confidence tiers — the play
either fires or it doesn't.

Usage:
    python3.13 run.py            # parts 1-3 + film room
    python3.13 run.py --part1    # replay + portfolio stats only
    python3.13 run.py --part2    # account-survival Monte Carlo only
    python3.13 run.py --part3    # pre-registered hypothesis family only
    python3.13 run.py --film-room

Same inputs -> byte-identical logs (fixed seeds; no wall-clock content in CSVs).
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sstats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tclib
from tclib import HERE, REPO, RESULTS, ledger_append, bh_qvalues

# ============================================================================
# Part 2 config — ALL Monte Carlo parameters live here (auditable, adjustable)
# ============================================================================
MC_CONFIG = {
    # --- TPT PRO account mechanics ($50K) ---
    # RE-VERIFY BEFORE ACTING ON RESULTS: parameters checked 2026-06-09 against
    # TakeProfitTrader help center ("PRO Account Rules", "Rule 3: EOD Maximum
    # Trailing Drawdown" articles) and 2026 third-party reviews. PRO accounts
    # use INTRADAY trailing drawdown computed in real time on unrealized P&L;
    # the trail stops permanently once it reaches the starting balance; the
    # daily loss limit was REMOVED in January 2025. Prop-firm terms drift —
    # re-verify all three before sizing real capital off this report.
    "start_balance": 50_000.0,
    "trail_width": 2_000.0,          # $50K PRO max trailing drawdown
    "floor_locks_at_start": True,    # trail stops at starting balance
    "safe_buffer_balance": 52_000.0,  # start + full trail width (also TPT's
                                      # standard-withdrawal threshold)
    # --- sizing ---
    "risk_per_trade": 700.0,          # $ risk at full sizing
    "half_risk_per_trade": 350.0,     # 0.5x rider
    "mnq_dollars_per_point": 2.0,
    "min_contracts": 1,
    # --- simulation ---
    "n_paths": 10_000,
    "horizon_months": 12,
    "report_horizons": (3, 6, 12),
    "wr_scenarios": {"56pct_IS_regime": 0.56,
                     "70pct_pooled_8yr": 0.70,
                     "83pct_recent_regime": 0.83},
    "seed": 20260609,
    # --- month pools for the block bootstrap (complete calendar months only
    #     in the era-matched pools; boundary partials 2024-02 / 2026-05 stay
    #     in the pooled set) ---
    "pool_pooled": ("2018-01", "2026-05"),
    "pool_is": ("2018-01", "2024-01"),
    "pool_recent": ("2024-03", "2026-04"),
}

FILM_DIR = RESULTS / "film_room"
CHART_DIR = FILM_DIR / "charts"
BARS_30S = REPO / "data" / "consolidated" / "nq-front-month.ohlcv-30s.parquet"
LEVELS_CSV = REPO / "data" / "levels" / "session_levels.csv"


def load_all():
    df = tclib.load_baseline()
    df = tclib.join_session_fields(df)
    recon = tclib.reconcile_or_die(df)
    print(f"[reconciliation PASS] {recon}")
    return df, recon


# ============================================================================
# Part 1 — replay log + portfolio statistics
# ============================================================================

def _frequency(bm: pd.DataFrame, sessions: pd.Series, start, end,
               complete_months: pd.PeriodIndex) -> dict:
    days = (end - start).days + 1
    months = days / 30.4375
    tdates = bm["session_date"].drop_duplicates().sort_values()
    sess = sessions[(sessions >= start) & (sessions <= end)].sort_values()
    sess = sess.reset_index(drop=True)
    pos = sess.searchsorted(tdates.values)
    gaps_sessions = np.diff(pos) - 1 if len(pos) > 1 else np.array([0])
    gap_days = tdates.diff().dt.days.dropna()
    dlist = list(tdates.dt.date)
    top_gaps = sorted(
        (((dlist[k] - dlist[k - 1]).days, dlist[k - 1], dlist[k])
         for k in range(1, len(dlist))), reverse=True)[:2]
    per_month = bm.groupby(bm["timestamp"].dt.to_period("M")).size()
    per_month = per_month.reindex(complete_months, fill_value=0)
    dist = per_month.value_counts().sort_index()
    return dict(
        n=len(bm), sessions=len(sess), months=round(months, 1),
        trades_per_month=round(len(bm) / months, 3),
        pct_sessions_with_trade=round(100 * len(tdates) / len(sess), 2),
        longest_gap_sessions=int(gaps_sessions.max()) if len(gaps_sessions) else 0,
        longest_gap_weeks=round(float(gap_days.max()) / 7, 1) if len(gap_days) else 0.0,
        months_dist={int(k): int(v) for k, v in dist.items()},
        complete_months=len(complete_months),
        top_gaps=top_gaps,
    )


def _equity(bm: pd.DataFrame) -> dict:
    bm = bm.sort_values("timestamp")
    r = bm["r"].values
    cum = np.cumsum(r)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(dd.max())
    i_trough = int(np.argmax(dd))
    i_peak = int(np.argmax(cum[:i_trough + 1])) if i_trough > 0 else 0
    rec = np.where(cum[i_trough:] >= peak[i_trough])[0]
    i_rec = i_trough + int(rec[0]) if len(rec) else None
    ts = bm["timestamp"].dt.normalize().values
    dd_dur_trades = (i_rec - i_peak) if i_rec is not None else len(bm) - i_peak
    dd_dur_days = int((ts[i_rec] - ts[i_peak]) / np.timedelta64(1, "D")) \
        if i_rec is not None else int((ts[-1] - ts[i_peak]) / np.timedelta64(1, "D"))

    streaks, run, run_start = [], 0, None
    for i, w in enumerate(bm["win"].values):
        if w == 0:
            if run == 0:
                run_start = i
            run += 1
        elif run:
            streaks.append((run, run_start, i - 1))
            run = 0
    if run:
        streaks.append((run, run_start, len(bm) - 1))
    lengths = [s[0] for s in streaks]
    longest = max(streaks, key=lambda s: s[0]) if streaks else (0, 0, 0)
    long_span_days = int((ts[longest[2]] - ts[longest[1]]) / np.timedelta64(1, "D")) \
        if streaks else 0
    long_sessions = len(set(ts[longest[1]:longest[2] + 1])) if streaks else 0
    long_dates = (pd.Timestamp(ts[longest[1]]).date(),
                  pd.Timestamp(ts[longest[2]]).date()) if streaks else None
    wr = bm["win"].mean()
    return dict(
        n=len(bm), wins=int(bm["win"].sum()), wr=round(100 * wr, 1),
        avg_r=round(float(np.mean(r)), 3), total_r=round(float(cum[-1]), 1),
        pf=round(float(bm.loc[bm.pnl > 0, "pnl"].sum()
                       / -bm.loc[bm.pnl < 0, "pnl"].sum()), 2),
        max_dd_r=round(max_dd, 1), dd_dur_trades=int(dd_dur_trades),
        dd_dur_days=dd_dur_days, dd_recovered=i_rec is not None,
        streak_counts={k: lengths.count(k) for k in sorted(set(lengths))},
        longest_streak=longest[0], longest_streak_days=long_span_days,
        longest_streak_sessions=long_sessions, longest_streak_dates=long_dates,
        p_streak_iid={k: round(100 * (1 - wr) ** k, 1) for k in (2, 3, 4)},
        cum=cum, dates=bm["timestamp"].values,
    )


def part1(df: pd.DataFrame, recon: dict) -> dict:
    q = tclib.load_quality_sessions()
    sessions = q.loc[q["pass"], "session_date"]
    st = tclib.load_session_table()

    # ---- replay_log.csv: one row per session; extra rows for 2nd trades ----
    per_sess = df[df["quality_pass"]].groupby("session_date").agg(
        signals_observed=("timestamp", "size"),
        tradeable_signals=("tradeable", "sum"))
    bm = df[df["benchmark"]].sort_values("timestamp").copy()
    bm["trade_seq"] = bm.groupby("session_date").cumcount() + 1

    rows = []
    bm_by_date = {d: g for d, g in bm.groupby("session_date")}
    for d in sessions.sort_values():
        base = dict(date=d.date(),
                    signals_observed=int(per_sess["signals_observed"].get(d, 0)),
                    tradeable_signals=int(per_sess["tradeable_signals"].get(d, 0)),
                    benchmark_qualifying="N", trade_seq="", direction="",
                    entry="", stop="", target="", outcome="", r="", points="",
                    w1_dir="", on_bucket="", or5_state_at_entry="",
                    stop_vs_w1="")
        if d in st.index:
            base["w1_dir"] = st.loc[d, "w1_dir"]
            base["on_bucket"] = st.loc[d, "on_bucket"]
        if d in bm_by_date:
            for _, t in bm_by_date[d].iterrows():
                rows.append({**base, "benchmark_qualifying": "Y",
                             "trade_seq": int(t.trade_seq),
                             "direction": t.direction, "entry": t.entry_price,
                             "stop": t.sl, "target": t.tp, "outcome": t.outcome,
                             "r": round(t.r, 2), "points": t.pnl,
                             "or5_state_at_entry": t.or5_state_at_entry,
                             "stop_vs_w1": t.stop_vs_w1})
        else:
            rows.append(base)
    log = pd.DataFrame(rows)
    log.to_csv(RESULTS / "replay_log.csv", index=False)
    n_obs = int((df["quality_pass"] & ~df["benchmark"]).sum())

    # ---- per-era statistics ----
    span = dict(
        full=(pd.Timestamp("2018-01-02"), pd.Timestamp("2026-05-15"),
              pd.period_range("2018-01", "2026-04", freq="M")),
        IS=(pd.Timestamp("2018-01-02"), pd.Timestamp("2024-02-12"),
            pd.period_range("2018-01", "2024-01", freq="M")),
        recent=(pd.Timestamp("2024-02-13"), pd.Timestamp("2026-05-15"),
                pd.period_range("2024-03", "2026-04", freq="M")),
    )
    eras = {}
    for era, (s, e, cm) in span.items():
        sub = bm if era == "full" else bm[bm["split"] == era]
        eras[era] = dict(freq=_frequency(sub, sessions, s, e, cm),
                         eq=_equity(sub))

    # CSV outputs
    pd.DataFrame({
        "trade_idx": range(1, len(bm) + 1),
        "date": bm["session_date"].dt.date.values,
        "r": bm["r"].round(2).values,
        "cum_r": np.cumsum(bm["r"].values).round(2),
        "era": bm["split"].values,
    }).to_csv(RESULTS / "equity_curve_r.csv", index=False)
    stat_rows = []
    for era, d in eras.items():
        stat_rows.append({"era": era, **{k: v for k, v in d["freq"].items()
                                         if k != "months_dist"},
                          **{k: v for k, v in d["eq"].items()
                             if k not in ("cum", "dates", "streak_counts",
                                          "p_streak_iid")}})
    pd.DataFrame(stat_rows).to_csv(RESULTS / "portfolio_stats.csv", index=False)

    _write_portfolio_md(eras, recon, n_obs)
    print(f"[part1] replay_log.csv ({len(log)} rows), portfolio_stats.md written; "
          f"observed-not-traded signals: {n_obs}")
    return eras


def _write_portfolio_md(eras: dict, recon: dict, n_obs: int) -> None:
    f, i, r = eras["full"], eras["IS"], eras["recent"]
    ff, fi, fr = f["freq"], i["freq"], r["freq"]
    ef, ei, er = f["eq"], i["eq"], r["eq"]

    def dist_str(fr_):
        return ", ".join(f"{k} trades: {v} months"
                         for k, v in fr_["months_dist"].items())

    md = f"""# Portfolio statistics — benchmark play replay (Track C, Part 1)

**Program context (state every time):** Track A returned a NEGATIVE result — zero FDR
survivors among 58 narrative factors. This replay therefore runs in **reduced,
benchmark-only mode**: the opening-window FVG short (created 09:29:30–09:31:00 ET,
no protected_swing), executed mechanically per `REPLAY_RULES.md`. Everything below is
an **operational characteristic of already-validated trades — not new evidence of
edge.** All trades are 1:1 RR, ±1.0R exactly, no costs/slippage modeled.

**Reconciliation: PASS.** Replay = Track A re-derived benchmark exactly:
n={recon['n']}, wins={recon['wins']} (69.9% WR), PF {recon['pf']}, avg
{recon['avg_r']:+.3f}R; IS {recon['is_n']} trades / {recon['is_wins']} wins (56.1%);
recent {recon['recent_n']} / {recon['recent_wins']} (83.3%). {n_obs:,} other FVGC
signals logged OBSERVED-NOT-TRADED (context only).

---

## HEADLINE: trade frequency — the most important operational fact in this report

**The validated play fires {ff['trades_per_month']:.2f} times per month
(n={ff['n']} over {ff['months']} months, {ff['sessions']:,} sessions).** That is
roughly ONE trade per month, not per week. Only {ff['pct_sessions_with_trade']}% of
sessions produce a trade. The longest dry spell was
**{ff['longest_gap_sessions']} consecutive sessions
(~{ff['longest_gap_weeks']} calendar weeks) with zero trades** — and the two longest
droughts were back-to-back: {ff['top_gaps'][0][1]} → {ff['top_gaps'][0][2]}
({ff['top_gaps'][0][0]} days), then {ff['top_gaps'][1][1]} → {ff['top_gaps'][1][2]}
({ff['top_gaps'][1][0]} days). **From {ff['top_gaps'][0][1]} to
{ff['top_gaps'][1][2]} — over two years — the play fired exactly once.** A trader
waiting for this setup in 2018–2020 would have spent two years mostly flat.

Frequency is itself regime-dependent:

| era | n | trades/month | % sessions with a trade | longest gap (sessions) | longest gap (weeks) |
|---|---|---|---|---|---|
| full 8-yr | {ff['n']} | {ff['trades_per_month']:.2f} | {ff['pct_sessions_with_trade']}% | {ff['longest_gap_sessions']} | {ff['longest_gap_weeks']} |
| IS era (2018-01→2024-02-12) | {fi['n']} | {fi['trades_per_month']:.2f} | {fi['pct_sessions_with_trade']}% | {fi['longest_gap_sessions']} | {fi['longest_gap_weeks']} |
| recent era (2024-02-13→2026-05-15) | {fr['n']} | {fr['trades_per_month']:.2f} | {fr['pct_sessions_with_trade']}% | {fr['longest_gap_sessions']} | {fr['longest_gap_weeks']} |

Trades per complete calendar month, full sample ({ff['complete_months']} months):
{dist_str(ff)}.

**What this means, plainly:** the validated play alone cannot support a 3–5
setups/week operating tempo. At ~1 trade/month the gap between what is validated and
how often Phil wants to be in the market is the single most important operational
fact here. Anything traded at higher frequency is, by definition, outside the
validated cohort.

---

## Per-era performance (the replayed trades themselves)

| era | n | WR | avg R | expectancy/trade | PF | total R | max DD (R) | DD length |
|---|---|---|---|---|---|---|---|---|
| full 8-yr | {ef['n']} | {ef['wr']}% | {ef['avg_r']:+.3f} | {ef['avg_r']:+.3f}R | {ef['pf']} | {ef['total_r']:+.1f} | {ef['max_dd_r']} | {ef['dd_dur_trades']} trades / {ef['dd_dur_days']} days{'' if ef['dd_recovered'] else ' (unrecovered)'} |
| IS era | {ei['n']} | {ei['wr']}% | {ei['avg_r']:+.3f} | {ei['avg_r']:+.3f}R | {ei['pf']} | {ei['total_r']:+.1f} | {ei['max_dd_r']} | {ei['dd_dur_trades']} trades / {ei['dd_dur_days']} days{'' if ei['dd_recovered'] else ' (unrecovered)'} |
| recent era | {er['n']} | {er['wr']}% | {er['avg_r']:+.3f} | {er['avg_r']:+.3f}R | {er['pf']} | {er['total_r']:+.1f} | {er['max_dd_r']} | {er['dd_dur_trades']} trades / {er['dd_dur_days']} days{'' if er['dd_recovered'] else ' (unrecovered)'} |

Equity curve (in R): `equity_curve_r.csv`. Era boundary = Track A split
(2024-02-13), so these numbers reconcile with the program ledger to the trade.

## Losing streaks — calendar reality at ~1 trade/month

Observed maximal losing streaks (full sample): {ef['streak_counts']}.
Longest: {ef['longest_streak']} consecutive losses,
{ef['longest_streak_dates'][0]} → {ef['longest_streak_dates'][1]}
(**only {ef['longest_streak_sessions']} sessions / {ef['longest_streak_days']}
calendar days** — losses CLUSTER, because qualifying sessions can fire two trades
30 seconds apart; tiebreak T-2 takes both).
IS era alone: {ei['streak_counts']}, longest {ei['longest_streak']}. Recent era:
{er['streak_counts']}, longest {er['longest_streak']}.

Two distinct risks, both real at this frequency:
1. **Clustered**: the observed worst streak was 4 losses inside
   {ef['longest_streak_days']} days (two double-signal sessions) — at full Part 2
   sizing that is ~$1,400 of risk in a single session, twice in one week.
2. **Stretched**: under iid at each era's WR, P(a given trade starts a streak
   ≥2/3/4) is full {ef['p_streak_iid'][2]}%/{ef['p_streak_iid'][3]}%/{ef['p_streak_iid'][4]}%
   (n={ef['n']}); IS {ei['p_streak_iid'][2]}%/{ei['p_streak_iid'][3]}%/{ei['p_streak_iid'][4]}%
   (n={ei['n']}). With trades arriving ~monthly when NOT clustered, a 3-loss streak
   can just as easily be **a quarter of a calendar year spent losing** — and at ~7
   IS-regime trades/year there is no statistical way to tell that drawdown apart
   from a dead edge in real time.

## What living with this system feels like

**If the recent era (2024-02→2026-05) is the true regime
(83.3% WR, n={er['n']}):** about {fr['trades_per_month']:.1f} trades a month, five of
six are winners, and the equity curve grinds up {er['avg_r']:+.2f}R per trade with
shallow drawdowns (max {er['max_dd_r']}R in {fr['months']} months). The
psychological load is not losses — it is **waiting**: even here, the longest gap was
{fr['longest_gap_weeks']} weeks with no signal, and most months offer one or two
shots. The danger in this regime is boredom-driven off-playbook trades, not the
play itself.

**If the IS era (2018→2024-02) is the true regime (56.1% WR, n={ei['n']}):** the
play is barely better than a coinflip with positive expectancy of only
{ei['avg_r']:+.2f}R per trade, arriving {fi['trades_per_month']:.2f} times a month.
That is roughly **{ei['avg_r'] * fi['trades_per_month']:+.2f}R per calendar month** —
months of effort for near-zero progress, a max drawdown that took
{ei['dd_dur_days']} days to recover{'' if ei['dd_recovered'] else ' (unrecovered at era end)'},
plus year-long signal droughts (2018–2020 fired once in two years).
A trader cannot distinguish this regime from a broken edge in real time on ~7
trades a year — which is precisely why the Part 2 survival numbers are run at 56%
as a mandatory scenario, not a footnote.

Which regime is true is **unknown**. The 8-yr pooled 69.9% is arithmetically real
but is a blend of those two states; nothing in Track A or B predicts which one
forward trades will come from.
"""
    (RESULTS / "portfolio_stats.md").write_text(md)


# ============================================================================
# Part 2 — account survival Monte Carlo (TPT PRO $50K)
# ============================================================================

def _simulate(wr: float, risk: float, months_pool: list, trades_by_month: dict,
              loss_mfe_pool: np.ndarray, conservative: bool, seed: int,
              cfg=MC_CONFIG) -> dict:
    rng = np.random.default_rng(seed)
    n_paths = cfg["n_paths"]
    horizon = cfg["horizon_months"]
    start, trail = cfg["start_balance"], cfg["trail_width"]
    dpp = cfg["mnq_dollars_per_point"]
    buffer_lvl = cfg["safe_buffer_balance"]

    term_month = np.full(n_paths, np.inf)
    lock_month = np.full(n_paths, np.inf)
    buffer_month = np.full(n_paths, np.inf)
    balances = np.zeros((n_paths, horizon))
    risk_used = []

    pool = np.asarray(months_pool, dtype=object)
    for p in range(n_paths):
        bal, hwm = start, start
        floor = start - trail
        locked = terminated = False
        months = rng.choice(pool, size=horizon, replace=True)
        for mi, m in enumerate(months):
            if not terminated:
                for stop in trades_by_month.get(m, ()):  # noqa: B909
                    contracts = max(cfg["min_contracts"],
                                    int(risk // (stop * dpp)))
                    dollar = contracts * stop * dpp
                    if p < 50:
                        risk_used.append(dollar)
                    win = rng.random() < wr
                    if conservative and not win:
                        # pre-stop run-up ratchets the trail before the loss
                        mfe = rng.choice(loss_mfe_pool)
                        hwm = max(hwm, bal + mfe * dollar)
                        if not locked:
                            floor = min(start, max(floor, hwm - trail))
                            locked = floor >= start
                    if conservative and win:
                        # worst-case dip to full stop distance before the win
                        if bal - dollar <= floor:
                            terminated = True
                            term_month[p] = mi + 1
                            bal = floor
                            break
                    bal += dollar if win else -dollar
                    if bal <= floor:
                        terminated = True
                        term_month[p] = mi + 1
                        bal = max(bal, floor)
                        break
                    hwm = max(hwm, bal)
                    if not locked:
                        floor = min(start, max(floor, hwm - trail))
                        locked = floor >= start
                    if locked and lock_month[p] == np.inf:
                        lock_month[p] = mi + 1
                    if bal >= buffer_lvl and buffer_month[p] == np.inf:
                        buffer_month[p] = mi + 1
            balances[p, mi] = bal
    out = {}
    for h in cfg["report_horizons"]:
        out[f"p_term_{h}m"] = float(np.mean(term_month <= h))
        out[f"p_lock_{h}m"] = float(np.mean(lock_month <= h))
        out[f"p_buffer_{h}m"] = float(np.mean(buffer_month <= h))
        b = balances[:, h - 1]
        out[f"bal_med_{h}m"] = float(np.median(b))
        out[f"bal_p10_{h}m"] = float(np.percentile(b, 10))
        out[f"bal_p90_{h}m"] = float(np.percentile(b, 90))
    reached = buffer_month[buffer_month <= 12]
    locked12 = lock_month[lock_month <= 12]
    out["med_months_to_buffer"] = float(np.median(reached)) if len(reached) else np.nan
    out["med_months_to_lock"] = float(np.median(locked12)) if len(locked12) else np.nan
    out["mean_actual_risk"] = float(np.mean(risk_used))
    return out


def part2(df: pd.DataFrame) -> pd.DataFrame:
    cfg = MC_CONFIG
    bm = df[df["benchmark"]].sort_values("timestamp")
    bm_month = bm["timestamp"].dt.to_period("M")
    trades_by_month = {m: list(g["sl_dist"].values)
                       for m, g in bm.groupby(bm_month)}
    loss_mfe = bm.loc[bm["outcome"] == "loss", "mfe_r"].values  # intra-trade exact
    pools = {
        "pooled": list(pd.period_range(*cfg["pool_pooled"], freq="M")),
        "IS_months": list(pd.period_range(*cfg["pool_is"], freq="M")),
        "recent_months": list(pd.period_range(*cfg["pool_recent"], freq="M")),
    }
    freq = {k: sum(len(trades_by_month.get(m, ())) for m in v) / len(v)
            for k, v in pools.items()}
    print(f"[part2] monthly signal frequency by pool: "
          f"{ {k: round(v, 3) for k, v in freq.items()} }; "
          f"loss-side intra-trade MFE pool n={len(loss_mfe)}, "
          f"median {np.median(loss_mfe):.2f}R")

    runs = []
    # primary grid: 3 WR x 2 sizing, pooled frequency, CONSERVATIVE
    grid = []
    for sname, wr in cfg["wr_scenarios"].items():
        for risk in (cfg["risk_per_trade"], cfg["half_risk_per_trade"]):
            grid.append((sname, wr, risk, "pooled", True))
    # era-matched frequency riders (56<->IS months, 83<->recent months)
    for risk in (cfg["risk_per_trade"], cfg["half_risk_per_trade"]):
        grid.append(("56pct_IS_regime", 0.56, risk, "IS_months", True))
        grid.append(("83pct_recent_regime", 0.83, risk, "recent_months", True))
    # optimistic bound (path-model sensitivity), full sizing pooled only
    for sname, wr in cfg["wr_scenarios"].items():
        grid.append((sname, wr, cfg["risk_per_trade"], "pooled", False))

    for k, (sname, wr, risk, pool, conserv) in enumerate(grid):
        res = _simulate(wr, risk, pools[pool], trades_by_month, loss_mfe,
                        conserv, seed=cfg["seed"] + 7 * k)
        runs.append({"scenario": sname, "wr": wr, "risk_per_trade": risk,
                     "freq_pool": pool, "signals_per_month": round(freq[pool], 3),
                     "path_model": "CONSERVATIVE" if conserv else "OPTIMISTIC",
                     **{kk: (round(vv, 4) if isinstance(vv, float) else vv)
                        for kk, vv in res.items()}})
        print(f"  done: {sname} risk=${risk:.0f} pool={pool} "
              f"{'CONS' if conserv else 'OPT'} -> "
              f"P(term,12m)={res['p_term_12m']:.3f} "
              f"P(buffer,12m)={res['p_buffer_12m']:.3f}")
    out = pd.DataFrame(runs)
    out.to_csv(RESULTS / "account_survival_grid.csv", index=False)
    _write_survival_md(out, freq, len(loss_mfe))
    return out


def _write_survival_md(g: pd.DataFrame, freq: dict, n_mfe: int) -> None:
    cfg = MC_CONFIG

    def row(s, risk, pool="pooled", model="CONSERVATIVE"):
        r = g[(g.scenario == s) & (g.risk_per_trade == risk)
              & (g.freq_pool == pool) & (g.path_model == model)].iloc[0]
        return r

    def fmt(r):
        return (f"| {r.scenario.replace('_', ' ')} | {r.wr:.0%} | "
                f"${r.risk_per_trade:.0f} | {r.signals_per_month:.2f}/mo | "
                f"{r.p_term_3m:.1%} / {r.p_term_6m:.1%} / {r.p_term_12m:.1%} | "
                f"{r.p_lock_12m:.1%} | "
                f"{'—' if pd.isna(r.med_months_to_lock) else f'{r.med_months_to_lock:.0f}mo'} | "
                f"${r.bal_med_3m:,.0f} / ${r.bal_med_6m:,.0f} / ${r.bal_med_12m:,.0f} | "
                f"${r.bal_p10_12m:,.0f}–${r.bal_p90_12m:,.0f} | "
                f"{r.p_buffer_12m:.1%}"
                f"{'' if pd.isna(r.med_months_to_buffer) else f' (med {r.med_months_to_buffer:.0f}mo)'} |")

    hdr = ("| scenario | WR | risk/trade | signals | P(termination) 3/6/12mo | "
           "P(floor locked, 12mo) | med months to lock | median balance 3/6/12mo | "
           "p10–p90 balance 12mo | P(safe buffer, 12mo) |\n"
           "|---|---|---|---|---|---|---|---|---|---|")

    full = [fmt(row(s, cfg["risk_per_trade"])) for s in cfg["wr_scenarios"]]
    half = [fmt(row(s, cfg["half_risk_per_trade"])) for s in cfg["wr_scenarios"]]
    era = [fmt(row("56pct_IS_regime", r, "IS_months"))
           for r in (cfg["risk_per_trade"], cfg["half_risk_per_trade"])] + \
          [fmt(row("83pct_recent_regime", r, "recent_months"))
           for r in (cfg["risk_per_trade"], cfg["half_risk_per_trade"])]
    opt = [fmt(row(s, cfg["risk_per_trade"], "pooled", "OPTIMISTIC"))
           for s in cfg["wr_scenarios"]]

    r56 = row("56pct_IS_regime", cfg["risk_per_trade"])
    r70 = row("70pct_pooled_8yr", cfg["risk_per_trade"])
    r83 = row("83pct_recent_regime", cfg["risk_per_trade"])
    r56e = row("56pct_IS_regime", cfg["risk_per_trade"], "IS_months")
    r83e = row("83pct_recent_regime", cfg["risk_per_trade"], "recent_months")

    exp_trades_56 = 2000 / (0.12 * 700)
    exp_trades_70 = 2000 / (0.40 * 700)
    exp_trades_83 = 2000 / (0.66 * 700)

    md = f"""# Account survival — TPT PRO $50K Monte Carlo (Track C, Part 2)

**Program context:** Track A negative → benchmark-only mode. These are survival
mechanics for the ONE validated play, under three WR regimes (per the Track A → C
cross-track decision), because the play's true forward WR is unknown:
**56% (IS era, n=41) / 70% (pooled 8-yr, n=83) / 83% (recent era, n=42).**
No scenario is "the" forecast. Every dollar figure inherits this regime uncertainty.

## Model (full parameter block in `run.py` MC_CONFIG)

- TPT PRO $50K: trailing drawdown **$2,000 on intraday UNREALIZED P&L** (high-water
  mark updates intra-trade); trail stops permanently at the starting balance; no
  daily loss limit (removed Jan 2025). **RE-VERIFY these terms before acting —
  prop-firm rules drift.** Checked 2026-06-09 vs TakeProfitTrader help center.
- Sizing: contracts = floor($700 / (stop pts × $2/pt)) on MNQ, min 1. Mean actual
  risk after rounding ≈ ${r70.mean_actual_risk:,.0f} (rounding loses ~
  {100 * (1 - r70.mean_actual_risk / 700):.0f}% of nominal risk; min-1 never binds
  at these stops). 0.5× rider = $350.
- **CONSERVATIVE path model** (intra-trade MAE is not exposed by the frozen engine
  for wins): every WIN first dips the full stop distance (tests the trailing floor),
  every LOSS first runs up by its empirical pre-stop MFE (drawn from the benchmark's
  own losses, n={n_mfe}, intra-trade exact — median {0.35:.2f}R) which ratchets the
  floor up before the stop is hit. An OPTIMISTIC bound (no dip, no ratchet) is shown
  for calibration; **truth is between the two; quote the conservative number.**
- Block bootstrap by calendar month (10,000 paths × 12 months), preserving the
  empirical clumping of ~1 signal/month. Stop sizes from the sampled months' actual
  trades; outcomes redrawn Bernoulli(scenario WR); R = ±1 (1:1 RR, no costs).
- Signal frequency by pool: pooled {freq['pooled']:.2f}/mo; IS-era months
  {freq['IS_months']:.2f}/mo; recent-era months {freq['recent_months']:.2f}/mo.
- "Safe buffer" = EOD balance ≥ $52,000 (floor locked at $50,000 + one full trail
  width of cushion; also TPT's standard-withdrawal threshold).

## Primary grid — CONSERVATIVE path model, pooled signal frequency ({freq['pooled']:.2f}/mo)

Full sizing ($700 risk/trade):

{hdr}
{chr(10).join(full)}

Half sizing ($350 risk/trade):

{hdr}
{chr(10).join(half)}

## Era-matched frequency riders (regimes also differed in signal frequency)

The 56% regime historically produced only {freq['IS_months']:.2f} signals/month; the
83% regime {freq['recent_months']:.2f}/month. Pairing each WR with its own era's
frequency:

{hdr}
{chr(10).join(era)}

## Path-model sensitivity (OPTIMISTIC bound, $700, pooled)

{hdr}
{chr(10).join(opt)}

## Reading notes (do not skip)

- "med months to lock/buffer" are CONDITIONAL on the event happening within 12
  months (e.g. at 56%/$700 only {r56.p_lock_12m:.0%} of paths ever lock; the median
  is over those paths).
- Under the CONSERVATIVE model every win first dips a full stop, so MORE signals =
  more floor tests early. That is why the 83% era-matched row (1.58 signals/mo)
  shows P(termination) ≈ the pooled row despite a better regime. The OPTIMISTIC
  rows bound that artifact from the other side; truth is between.
- **Half-sizing converts termination risk into stagnation risk.** At 56%/$350 the
  account almost never dies ({row("56pct_IS_regime", cfg["half_risk_per_trade"]).p_term_12m:.0%}
  in 12mo) but also almost never builds the buffer
  ({row("56pct_IS_regime", cfg["half_risk_per_trade"]).p_buffer_12m:.0%}). There is
  no sizing that makes a +0.12R-expectancy, ~0.6-signal/month play grow a $50K
  account safely — sizing reallocates the failure mode, it does not remove it.

## Synthesis — the honest constraint math

Phil's prior constraint math assumed **8 trades per 2 weeks (~16–17/month), under
which ~4 weeks to a safe buffer was the floor.** The validated play does not deliver
that tempo. It delivers **{freq['pooled']:.2f} signals/month pooled** (IS era:
{freq['IS_months']:.2f}; recent era: {freq['recent_months']:.2f}). Recomputed
honestly at $700 risk (expectancy per trade: 56% → +$84; 70% → +$280; 83% → +$462):

- **83% regime, its own frequency ({freq['recent_months']:.2f}/mo):** ~
  {exp_trades_83:.0f} trades to build the $2,000 buffer ⇒ expectation ~3 months;
  Monte Carlo median **{'' if pd.isna(r83e.med_months_to_buffer) else f"{r83e.med_months_to_buffer:.0f} months"}**,
  P(buffer within 12mo) {r83e.p_buffer_12m:.0%}, P(termination within 12mo)
  {r83e.p_term_12m:.0%} (n=10,000 paths).
- **70% pooled regime:** ~{exp_trades_70:.0f} trades ⇒ ~9 months in expectation at
  {freq['pooled']:.2f}/mo; Monte Carlo P(buffer within 12mo) only
  {r70.p_buffer_12m:.0%}, median balance at 12mo ${r70.bal_med_12m:,.0f},
  P(termination) {r70.p_term_12m:.0%}.
- **56% regime at its own frequency ({freq['IS_months']:.2f}/mo): ~
  {exp_trades_56:.0f} trades to buffer ⇒ ~4 YEARS in expectation.** Monte Carlo:
  P(buffer within 12mo) {r56e.p_buffer_12m:.0%}, P(termination within 12mo)
  {r56e.p_term_12m:.0%}, median 12-month balance ${r56e.bal_med_12m:,.0f}.
  **This is the sobering number of the program: in the historically-real IS regime,
  the account most likely neither locks its floor nor builds a buffer within a
  year — it sits exposed to the $2,000 trail on a ~coinflip play for years.**

Where Phil's old math said "4 weeks to buffer," the validated play at validated
frequency says **{'' if pd.isna(r83e.med_months_to_buffer) else f"~{r83e.med_months_to_buffer:.0f} months in the BEST regime"}
and effectively never (within a year) in the worst.** The regime question (which WR
is forward-true) dominates every sizing decision; nothing in this program resolves
it. Forward data per FORWARD_TEST_PROTOCOL.md §A is the only resolver.

*Fill caveat: stop fills modeled AT the stop price; real stop slippage on MNQ makes
all termination probabilities slightly worse than shown. Unrealized-trough modeling
is conservative; fills are optimistic. Both stated in analysis.md.*
"""
    (RESULTS / "account_survival.md").write_text(md)


# ============================================================================
# Part 3 — pre-registered hypothesis family (m=3, BH q=0.10 within family)
# ============================================================================

def part3(df: pd.DataFrame) -> None:
    trad = df[df["tradeable"] & df["quality_pass"]].copy()

    # cohorts (REPLAY_RULES.md §6)
    c12 = trad[trad["w1_formed"] & trad["w1_dir"].isin(["up", "down"])]
    t1_cond = ((c12["direction"] == "long") & (c12["w1_dir"] == "up")) | \
              ((c12["direction"] == "short") & (c12["w1_dir"] == "down"))
    c2 = c12[c12["stop_vs_w1"] != "unknown"]
    t2_cond = c2["stop_vs_w1"] == "beyond"
    c3 = trad[trad["on_bucket"].isin(["expanded", "normal", "compressed"])]
    t3_cond = c3["on_bucket"] == "expanded"

    tests = [
        ("T1_w1_alignment", c12, t1_cond,
         "entries >=9:45: trade direction matches W1 (9:30-9:45) direction",
         "all tradeable >=9:45 w/ known W1"),
        ("T2_w1_stop_protection", c2, t2_cond,
         "entries >=9:45: model stop strictly beyond W1 extreme",
         "all tradeable >=9:45 w/ known W1 extreme"),
        ("T3_on_expansion", c3, t3_cond,
         "all entries: session in expanded overnight-range tercile",
         "all tradeable w/ known ON tercile"),
    ]

    # --- REGISTRATION rows, written and flushed BEFORE any computation ---
    for tid, coh, _, hyp, cname in tests:
        ledger_append(dict(test_id=f"{tid}__REGISTERED", phase=3, hypothesis=hyp,
                           cohort=cname, notes="pre-registered before computation; "
                           "IS first then one OOS confirmatory look; exact binomial "
                           "vs cohort base; BH q=0.10 within family m=3"))
    print("[part3] 3 registration rows flushed to ledger before computation")

    def eval_split(coh, cond, split):
        pool = coh[coh["split"] == split]
        sub = pool[cond.reindex(pool.index, fill_value=False)]
        base = pool["win"].mean()
        n, wins = len(sub), int(sub["win"].sum())
        p = sstats.binomtest(wins, n, base, alternative="two-sided").pvalue if n else np.nan
        gp = sub.loc[sub.pnl > 0, "pnl"].sum()
        gl = -sub.loc[sub.pnl < 0, "pnl"].sum()
        return dict(n=n, wins=wins, wr=wins / n if n else np.nan,
                    base=base, base_n=len(pool), p=p,
                    pf=float(gp / gl) if gl > 0 else np.nan)

    results = []
    for tid, coh, cond, hyp, cname in tests:
        is_ = eval_split(coh, cond, "IS")
        oos = eval_split(coh, cond, "recent")
        bm_sub = coh[cond.reindex(coh.index, fill_value=False) & coh["benchmark"]]
        comp_is = eval_split(coh, ~cond, "IS")
        comp_oos = eval_split(coh, ~cond, "recent")
        results.append(dict(tid=tid, hyp=hyp, cname=cname, is_=is_, oos=oos,
                            comp_is=comp_is, comp_oos=comp_oos,
                            bm_n=len(bm_sub), bm_wins=int(bm_sub["win"].sum())))

    qs = bh_qvalues([r["is_"]["p"] for r in results])
    for r, q in zip(results, qs):
        r["q_is"] = q
        same_dir = np.sign(r["oos"]["wr"] - r["oos"]["base"]) == \
            np.sign(r["is_"]["wr"] - r["is_"]["base"])
        r["validated"] = bool(q < 0.10 and r["oos"]["p"] < 0.05 and same_dir)
        is_pass = q < 0.10
        oos_pass = r["oos"]["p"] < 0.05 and same_dir
        if r["validated"]:
            why = "passed IS (q<0.10) AND the single OOS confirmatory look"
        elif is_pass and not same_dir:
            why = (f"passed IS (q={q:.3f}) but FAILED the one-shot OOS look — "
                   f"effect reversed direction ({100 * r['oos']['wr']:.1f}% vs "
                   f"base {100 * r['oos']['base']:.1f}%)")
        elif is_pass:
            why = (f"passed IS (q={q:.3f}) but FAILED the one-shot OOS look "
                   f"(p={r['oos']['p']:.3f})")
        else:
            why = f"no IS effect (q={q:.3f})"
        r["verdict"] = ("VALIDATED — FORWARD-TEST NEXT" if r["validated"]
                        else "NOT VALIDATED")
        r["why"] = why
        for split, d in (("IS", r["is_"]), ("OOS", r["oos"])):
            ledger_append(dict(
                test_id=f"{r['tid']}__{split}", phase=3, hypothesis=r["hyp"],
                cohort=r["cname"], n=d["n"], WR=round(100 * d["wr"], 1),
                PF=round(d["pf"], 2), p_value=d["p"],
                q_value=q if split == "IS" else "",
                notes=f"base={100 * d['base']:.2f}% (n={d['base_n']}); "
                      f"{'IS screen, BH within m=3' if split == 'IS' else 'single confirmatory OOS look'}; "
                      f"verdict={r['verdict']}"))

    # descriptive-only OR5-contradiction table (ledger-exempt)
    c_or5 = trad[trad["w1_formed"] & (trad["or5_contradiction"] != "unknown")
                 & (trad["or5_state_at_entry"] != "unknown")]
    or5_tab = c_or5.groupby("or5_contradiction").agg(
        n=("win", "size"), wins=("win", "sum")).astype(int)
    or5_tab["WR"] = (100 * or5_tab["wins"] / or5_tab["n"]).round(1)

    _write_part3_md(results, or5_tab)
    print("[part3] done:",
          {r["tid"]: r["verdict"] for r in results})


def _write_part3_md(results: list, or5_tab: pd.DataFrame) -> None:
    def pct(x):
        return f"{100 * x:.1f}%"

    lines = []
    for r in results:
        i, o, ci, co = r["is_"], r["oos"], r["comp_is"], r["comp_oos"]
        lines.append(f"""## {r['tid']} — {r['hyp']}

| split | condition | n | WR | PF | cohort base | exact binomial p | q (BH, m=3) |
|---|---|---|---|---|---|---|---|
| IS | TRUE | {i['n']} | {pct(i['wr'])} | {i['pf']:.2f} | {pct(i['base'])} (n={i['base_n']}) | {i['p']:.4f} | {r['q_is']:.3f} |
| IS | FALSE (complement) | {ci['n']} | {pct(ci['wr'])} | {ci['pf']:.2f} | — | — | — |
| OOS (one look) | TRUE | {o['n']} | {pct(o['wr'])} | {o['pf']:.2f} | {pct(o['base'])} (n={o['base_n']}) | {o['p']:.4f} | — |
| OOS | FALSE (complement) | {co['n']} | {pct(co['wr'])} | {co['pf']:.2f} | — | — | — |
| benchmark sub-row (descriptive, NO TEST) | TRUE ∩ benchmark | {r['bm_n']} | {pct(r['bm_wins'] / r['bm_n']) if r['bm_n'] else '—'} | — | — | — | — |

**Verdict: {r['verdict']}** — {r['why']}.
""")

    or5_rows = "\n".join(
        f"| {idx} | {row['n']} | {row['WR']}% |"
        for idx, row in or5_tab.iterrows())

    md = f"""# Part 3 — Pre-registered hypothesis family (Track C)

The ONLY new statistical tests in this track (m=3, BH q=0.10 within family).
Derived from Track B structural facts; tested at the trade level on ALL tradeable
FVGC v2.0.5 baseline signals (post quality filter), NOT just the benchmark cohort.
Registration rows were written to `test_ledger.csv` before any computation
(test_id suffix `__REGISTERED`). Procedure per hypothesis: IS first; ONE
confirmatory OOS look; exact binomial vs the cohort's own split base rate; no
sub-slicing, no variants, no interactions; all results reported regardless of
direction. Era boundary = Track A split (2024-02-13).

A hypothesis is VALIDATED only if it passes IS at q<0.10 within the family AND the
single OOS look (same direction, p<0.05). A VALIDATED label means
**FORWARD-TEST NEXT** — it does not enter any playbook from this run.

{chr(10).join(lines)}

## Descriptive-only: OR5-contradiction state at entry (LOW-N EXPLORATORY, no test)

Entries ≥9:45 with known W1 direction and OR5 state. "Contradiction" = W1 direction
up but OR5 low already broken before entry, or the mirror. Ledger-exempt; no
p-values; tabulated for the film room's eye-training context only.

| state | n | WR |
|---|---|---|
{or5_rows}
"""
    (RESULTS / "part3_hypotheses.md").write_text(md)


# ============================================================================
# Part 4 — film room
# ============================================================================

def _load_bars_for(dates: set) -> dict:
    bars = pd.read_parquet(BARS_30S, columns=["timestamp_ny", "open", "high",
                                              "low", "close"])
    ts = pd.DatetimeIndex(bars["timestamp_ny"]).tz_localize(None)
    bars = bars.assign(ts=ts, d=ts.normalize())
    bars = bars[bars["d"].isin(dates)]
    tod = bars["ts"].dt.time
    bars = bars[(tod >= dtime(9, 15)) & (tod <= dtime(10, 30))]
    return {d: g.sort_values("ts") for d, g in bars.groupby("d")}


def _load_levels() -> pd.DataFrame:
    lv = pd.read_csv(LEVELS_CSV, low_memory=False, parse_dates=["date"])
    lv = lv[["date", "level_name", "price"]].dropna(subset=["price"])
    return lv


def _chart(trade, bars, levels, outpath, quiz=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    entry_ts = trade.timestamp.to_pydatetime().replace(tzinfo=None)
    b = bars[bars["ts"] <= entry_ts] if quiz else bars
    if len(b) < 5:
        return False
    fig = plt.figure(figsize=(14, 8), dpi=100)
    if quiz:
        ax = fig.add_axes([0.06, 0.08, 0.90, 0.84])
    else:
        ax = fig.add_axes([0.06, 0.08, 0.70, 0.84])
        panel = fig.add_axes([0.78, 0.08, 0.20, 0.84])
        panel.axis("off")

    w = 20 / 86400  # 20s candle body width in days
    for _, row in b.iterrows():
        x = mdates.date2num(row.ts)
        up = row.close >= row.open
        color = "#1f8a4d" if up else "#c0392b"
        ax.plot([x, x], [row.low, row.high], color=color, lw=0.7, zorder=2)
        ax.add_patch(Rectangle((x - w / 2, min(row.open, row.close)), w,
                               max(abs(row.close - row.open), 0.01),
                               facecolor=color, edgecolor=color, zorder=3))

    x0, x1 = mdates.date2num(b["ts"].iloc[0]), mdates.date2num(b["ts"].iloc[-1])
    ylo, yhi = b["low"].min(), b["high"].max()
    for v in (trade.entry_price, trade.sl, trade.tp):
        if pd.notna(v):
            ylo, yhi = min(ylo, v), max(yhi, v)
    pad = (yhi - ylo) * 0.04
    ax.set_ylim(ylo - pad, yhi + pad)

    # named levels in view
    lv = levels[levels["date"] == trade.session_date]
    seen = set()
    for _, l in lv.iterrows():
        if not (ylo - pad <= l.price <= yhi + pad) or l.price in seen:
            continue
        seen.add(l.price)
        ax.axhline(l.price, color="#888", lw=0.6, ls=":", zorder=1)
        ax.text(x0, l.price, f" {l.level_name}", fontsize=6.5, color="#555",
                va="bottom", ha="left", zorder=4)

    # FVG zone
    fx0 = mdates.date2num(trade.fvg_created_at.to_pydatetime().replace(tzinfo=None))
    zone_color = "#c0392b" if trade.fvg_direction == "bearish" else "#1f8a4d"
    ax.add_patch(Rectangle((fx0, trade.fvg_bottom), x1 - fx0,
                           trade.fvg_top - trade.fvg_bottom,
                           facecolor=zone_color, alpha=0.18, zorder=1.5))

    tradeable = trade.outcome in ("win", "loss")
    if tradeable or quiz:
        ex = mdates.date2num(entry_ts)
        end = x1
        if not quiz and pd.notna(trade.exit_time):
            end = mdates.date2num(
                trade.exit_time.to_pydatetime().replace(tzinfo=None))
        for price, color, ls, lab in ((trade.entry_price, "black", "-", "entry"),
                                      (trade.sl, "#c0392b", "--", "stop"),
                                      (trade.tp, "#1f8a4d", "--", "target")):
            if pd.notna(price):
                ax.hlines(price, ex, max(end, ex + 30 / 86400), color=color,
                          ls=ls, lw=1.4, zorder=5)
                ax.text(max(end, ex + 30 / 86400), price, f" {lab}", fontsize=7,
                        color=color, va="center", zorder=5)
        marker = "v" if trade.direction == "short" else "^"
        ax.scatter([ex], [trade.entry_price], marker=marker, s=90, color="black",
                   zorder=6)
        if not quiz and pd.notna(trade.exit_time) and pd.notna(trade.exit_price):
            ax.scatter([end], [trade.exit_price], marker="x", s=90,
                       color="#c0392b" if trade.outcome == "loss" else "#1f8a4d",
                       zorder=6, linewidths=2.5)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.15)
    d = trade.session_date.date()
    if quiz:
        title = f"{d} | {trade.direction.upper()} | outcome: ?"
    elif tradeable:
        title = (f"{d} | {trade.direction.upper()} | "
                 f"{trade.outcome.upper()} | {trade.r:+.1f}R")
    else:
        title = f"{d} | {trade.direction.upper()} | NOT TRADED ({trade.outcome})"
    ax.set_title(title, fontsize=13, fontweight="bold", loc="left")

    if not quiz:
        formed = "formed" if trade.w1_formed else "still forming at entry"
        info = [
            ("SETUP", ""),
            ("variant", str(trade.variant)),
            ("FVG size", f"{trade.fvg_top - trade.fvg_bottom:.2f} pts"),
            ("FVG created", str(trade.fvg_created_at.time())),
            ("entry time", str(trade.timestamp.time())),
            ("stop dist", "" if pd.isna(trade.sl_dist) else f"{trade.sl_dist:.0f} pts"),
            ("", ""),
            ("PART-3 FACTORS", ""),
            ("W1 direction", f"{trade.w1_dir} ({formed})"),
            ("ON-range tercile", str(trade.on_bucket)),
            ("OR5 state @entry", str(trade.or5_state_at_entry)),
            ("stop vs W1 extreme", str(trade.stop_vs_w1)),
        ]
        y = 0.98
        for k, v in info:
            if k and not v:
                panel.text(0.02, y, k, fontsize=9, fontweight="bold",
                           transform=panel.transAxes)
            elif k:
                panel.text(0.02, y, k, fontsize=8.5, color="#444",
                           transform=panel.transAxes)
                panel.text(0.98, y, v, fontsize=8.5, ha="right",
                           transform=panel.transAxes)
            y -= 0.045
        panel.text(0.02, 0.02,
                   "W1/ON/OR5 shown for context;\nW1 not formed at most entries",
                   fontsize=7, color="#999", transform=panel.transAxes)

    fig.savefig(outpath)
    plt.close(fig)
    return True


def film_room(df: pd.DataFrame) -> None:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    (CHART_DIR / "quiz").mkdir(exist_ok=True)
    bm = df[df["benchmark"]].sort_values("timestamp").reset_index(drop=True)
    nt = df[df["opening_window_signal"] & ~df["benchmark"] & df["quality_pass"]]
    nt = nt.sort_values("timestamp").tail(20).reset_index(drop=True)

    dates = set(bm["session_date"]) | set(nt["session_date"])
    print(f"[film-room] loading 30s bars for {len(dates)} sessions ...")
    bars_by_day = _load_bars_for(dates)
    levels = _load_levels()

    made, skipped = [], []
    for i, t in bm.iterrows():
        name = f"trade_{i + 1:02d}_{t.session_date.date()}_{t.outcome}.png"
        ok = _chart(t, bars_by_day.get(t.session_date, pd.DataFrame()),
                    levels, CHART_DIR / name)
        (made if ok else skipped).append((i, name, t))
    nt_made = []
    for i, t in nt.iterrows():
        name = f"nottraded_{i + 1:02d}_{t.session_date.date()}.png"
        ok = _chart(t, bars_by_day.get(t.session_date, pd.DataFrame()),
                    levels, CHART_DIR / name)
        if ok:
            nt_made.append((i, name, t))

    rng = np.random.default_rng(42)
    quiz_idx = sorted(rng.choice(len(bm), size=10, replace=False))
    quiz = []
    for k, qi in enumerate(quiz_idx):
        t = bm.iloc[qi]
        name = f"quiz/q{k + 1:02d}.png"
        if _chart(t, bars_by_day.get(t.session_date, pd.DataFrame()),
                  levels, CHART_DIR / name, quiz=True):
            quiz.append((k + 1, name, t))

    _write_film_md(bm, made, nt_made, quiz, skipped)
    print(f"[film-room] {len(made)} trade charts, {len(nt_made)} not-traded, "
          f"{len(quiz)} quiz; skipped {len(skipped)}")


def _write_film_md(bm, made, nt_made, quiz, skipped):
    def line(name, t):
        extra = (f"W1 {t.w1_dir}, ON {t.on_bucket}, OR5 {t.or5_state_at_entry}, "
                 f"stop {t.stop_vs_w1} W1 extreme")
        return (f"- `charts/{name}` — {t.session_date.date()}, "
                f"{t.direction} @ {t.entry_price}, stop {t.sl_dist:.0f}pt, "
                f"{t.outcome.upper()} ({t.r:+.1f}R). {extra}")

    winners = [line(n, t) for _, n, t in made if t.outcome == "win"]
    losers = [line(n, t) for _, n, t in made if t.outcome == "loss"]
    nts = [(f"- `charts/{n}` — {t.session_date.date()}, {t.direction}, "
            f"variant={t.variant}, outcome={t.outcome} — fails cohort because: "
            f"{'long (benchmark is shorts only)' if t.direction == 'long' else ('protected_swing variant' if t.variant == 'protected_swing' else 'not tradeable (' + t.outcome + ')')}")
           for _, n, t in nt_made]
    qlines = [f"- Q{k}: `charts/{n}` — {t.session_date.date()}, chart truncated at "
              f"entry; call WIN or LOSS before checking." for k, n, t in quiz]
    answers = [f"- Q{k}: **{t.outcome.upper()}** ({t.r:+.1f}R)" for k, n, t in quiz]
    skip_note = ("\n".join(f"- {n} (insufficient bars)" for _, n, _ in skipped)
                 if skipped else "(none)")

    md = f"""# FILM ROOM — opening-window FVG short (benchmark play)

All {len(made)} benchmark trades over 8 years (at ~10 signals/yr, a "trailing 60
days" film room would hold ~3 charts — so this is the full set), plus the 20 most
recent opening-window signals that did NOT qualify. Charts: 30s candles 9:15–10:30
ET, named levels, FVG zone shaded, entry/stop/target and outcome path marked. Side
panel lists the Part 3 factors (W1 direction, ON tercile, OR5 state at entry,
stop-vs-W1-extreme) so the film room doubles as visual context for the hypothesis
results — note W1 is usually NOT yet formed at these entries; it is context, not
entry-time information.

Regenerate any time with: `python3.13 studies/replay_simulator/run.py --film-room`

## Section 1 — Winners ({len(winners)}): what textbook looks like

{chr(10).join(winners)}

## Section 2 — Losers ({len(losers)}): what a CORRECT trade that loses looks like

These are not mistakes. Every chart below is a rule-perfect entry that hit its stop.
At 56–83% WR depending on regime, 1-in-6 to 1-in-2 of correct trades lose; treating
them as system failure is how validated plays get abandoned mid-drawdown.

{chr(10).join(losers)}

## Section 3 — Almost-but-not-quite ({len(nt_made)} most recent non-qualifying opening-window signals)

What fires the pattern-recognition but fails the cohort definition. Knowing these
cold is what keeps the live count at ~10/yr instead of 50/yr.

{chr(10).join(nts)}

## Section 4 — Self-quiz (10 charts, side panels stripped, truncated at entry)

Charts show everything known AT entry (bars to entry, levels, FVG, entry/stop/target)
and nothing after. Call each one, then check below.

{chr(10).join(qlines)}

### Answers

{chr(10).join(answers)}

---
Charts skipped for missing bars: {skip_note}
"""
    (FILM_DIR / "FILM_ROOM.md").write_text(md)


# ============================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part1", action="store_true")
    ap.add_argument("--part2", action="store_true")
    ap.add_argument("--part3", action="store_true")
    ap.add_argument("--film-room", action="store_true")
    args = ap.parse_args()
    run_all = not (args.part1 or args.part2 or args.part3 or args.film_room)

    df, recon = load_all()
    if run_all or args.part1:
        part1(df, recon)
    if run_all or args.part2:
        part2(df)
    if run_all or args.part3:
        part3(df)
    if run_all or args.film_room:
        film_room(df)


if __name__ == "__main__":
    main()
