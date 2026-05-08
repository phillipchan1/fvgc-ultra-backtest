# Sub-study C spot checks (first 5 qualifying trades per mid)

Manually verify each row against TradingView. The rejection wick should sit in the 10-min window BEFORE entry, within 3pt of the mid, with close on the away side of the approach direction.


## pd_hl_mid

- **2023-10-13 09:39:00** | long @ 15326.0 | pd_hl_mid=15342.50 | dist=16.50pt | outcome=win | MFE=2.43R MAE=17.58R | variant=no_fvg
- **2023-10-16 10:11:30** | long @ 15255.75 | pd_hl_mid=15214.50 | dist=41.25pt | outcome=win | MFE=3.24R MAE=1.75R | variant=no_fvg
- **2023-10-19 09:34:30** | short @ 15077.75 | pd_hl_mid=15101.50 | dist=23.75pt | outcome=win | MFE=13.01R MAE=3.02R | variant=bos
- **2023-10-31 09:40:30** | short @ 14336.0 | pd_hl_mid=14391.38 | dist=55.38pt | outcome=loss | MFE=1.24R MAE=8.39R | variant=no_fvg
- **2023-12-05 09:47:00** | long @ 15837.5 | pd_hl_mid=15803.50 | dist=34.00pt | outcome=win | MFE=6.09R MAE=0.4R | variant=no_fvg

## pd_va_mid

- **2023-10-09 10:10:30** | long @ 15038.25 | pd_va_mid=15013.50 | dist=24.75pt | outcome=loss | MFE=7.98R MAE=2.93R | variant=ifvg
- **2023-11-13 10:06:30** | long @ 15503.0 | pd_va_mid=15488.50 | dist=14.50pt | outcome=win | MFE=5.77R MAE=0.87R | variant=bos
- **2023-11-21 10:06:30** | long @ 15998.25 | pd_va_mid=15994.00 | dist=4.25pt | outcome=loss | MFE=1.78R MAE=5.75R | variant=bos
- **2023-12-05 09:47:00** | long @ 15837.5 | pd_va_mid=15838.50 | dist=1.00pt | outcome=win | MFE=6.09R MAE=0.4R | variant=no_fvg
- **2023-12-12 09:51:00** | long @ 16444.25 | pd_va_mid=16409.50 | dist=34.75pt | outcome=loss | MFE=11.27R MAE=1.43R | variant=no_fvg