# Studies

Each subfolder contains an independent analysis that uses the FVGC model.

## Structure

```
studies/
  _template/          # Copy this to start a new study
    run.py
    analysis.md
  day_of_week/        # Example: performance by day of week
    run.py
    analysis.md
```

## Creating a new study

1. Copy `_template/` to a new folder: `cp -r _template my_study`
2. Edit `run.py` — filter/group trades however you need
3. Run: `python studies/my_study/run.py`
4. Document findings in `analysis.md`

## Convention

- Always import from the `fvgc` package — never duplicate model logic.
- Use `fvgc.engine.summarize_results()` for consistent stats.
- Write findings to `analysis.md` in the same folder.
