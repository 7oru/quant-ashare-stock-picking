# Stock Pool CSV Schema

The project stock pool lives at `ai_stock_pool.csv`.

Required columns, in order:

```text
stock_code,stock_name,sector,sub_sector,exchange,list_date,market_cap,ai_exposure,recommended_logic
```

Field conventions:

- `stock_code`: six-digit ticker plus exchange suffix, such as `300476.SZ` or `600183.SH`.
- `stock_name`: official short Chinese company name.
- `sector`: project-level AI chain bucket, such as `上游-PCB/CCL` or `上游-存储器`.
- `sub_sector`: narrower business exposure.
- `exchange`: `是` for A-share listed candidates in this repo's current convention.
- `list_date`: `YYYY-MM-DD`.
- `market_cap`: coarse size bucket: `大盘`, `中盘`, or `小盘`.
- `ai_exposure`: qualitative AI linkage: `高`, `中`, or `低`.
- `recommended_logic`: one concise Chinese sentence. Use Chinese punctuation and avoid ASCII commas so the CSV stays simple.

Before adding rows:

- Check `stock_code` is not already present.
- Confirm the company is A-share listed.
- Keep `recommended_logic` focused on the upstream supply-chain path rather than short-term price action.
