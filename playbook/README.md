# Playbook

Knowledge base for `tools/morning_briefing.py`. The briefing reads from this
folder (and from the latest outputs of the `studies/` and `analysis/` runs)
so that **adding new research upgrades the morning report without touching
any Python**.

## Files

| File | Role |
|------|------|
| `briefing_config.json` | Factor metadata, tuning knobs, manual one-liners. Hand-edited. |
| `README.md`            | This doc. |

## How the briefing learns

`tools/morning_briefing.py` pulls its edges from three places, in this order:

1. **`analysis/results/combo_top_results.txt`** — parsed fresh each run.
   - Top combos by WR / robust sample / AVOID list.
   - Re-run `python analysis/combo_permutation_test.py` to refresh.
2. **`studies/factor_importance/results/factor_importance_report.txt`** — parsed fresh each run.
   - Single-factor lifts vs baseline.
   - Re-run `python studies/factor_importance/run.py` to refresh.
3. **`playbook/briefing_config.json`** — human-curated overlay.
   - Classifies each factor as `pre_open`, `post_open`, `timing`, or `direction`.
   - Provides human-readable descriptions.
   - Optional manual one-liners keyed on factor combinations.
   - Day-of-week notes.

If you add a new study that invents a new factor name (e.g. `opex_friday`), do
two things:

1. Add the factor to `factors` in `briefing_config.json` with its `kind`
   (pre_open / post_open / timing / direction / calendar) and a short description.
2. Make sure the new factor shows up in the combo / factor-importance output
   files above (i.e. wire it into `studies/factor_importance/run.py` or the
   combo permutation test). The briefing will then automatically start matching
   it against today's context and surfacing relevant combos.

## Factor kinds

| kind | meaning | known at 6:15 AM PT? |
|------|---------|----------------------|
| `pre_open`  | Part of today's pre-open snapshot (gap, overnight, prior day, VIXY, news/calendar) | ✅ yes |
| `post_open` | Only knowable at or after 9:30 ET (9:30 candle, opening ranges, model variant) | ❌ no — becomes a *watch trigger* |
| `timing`    | A fixed time window that will occur today (macro_w1/w2/w3) | always on |
| `direction` | A filter on trade direction, not on the day | neutral — used for commentary |

## Manual one-liners

`manual_one_liners` in the config lets you write a sentence that prints
when a set of pre-open factors all match. Keep them short, actionable, and
grounded in a study you've actually run. They are the "this is one of those
days where…" lines.

```json
{
  "when_all": ["gap_down", "prior_day_down"],
  "say": "Gap-down on a weak prior close — classic short-bias setup. …"
}
```

Keep the primary numeric edges in the combo / factor_importance outputs;
use one-liners to translate those numbers into language you'll actually
remember at 6:15 AM.
