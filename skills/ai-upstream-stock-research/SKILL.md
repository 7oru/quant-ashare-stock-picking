---
name: ai-upstream-stock-research
description: Use this skill when expanding an A-share stock pool from recent AI infrastructure news, especially when the user asks for hot upstream industries, supplier-of-supplier ideas, GPU server supply chains, HBM/flash/storage supply chains, or CSV-ready candidates for ai_stock_pool.csv.
---

# AI Upstream Stock Research

## Overview

Use this skill to turn recent AI infrastructure news into A-share stock-pool candidates that can be fed into the repo's quant ranking and backtest loop. The focus is upstream exposure: not only direct AI beneficiaries, but also suppliers to the suppliers of GPU servers, HBM, NAND, SSDs, data-center power, cooling, optical networking, and semiconductor manufacturing.

This skill is research support only. It does not produce investment advice and should always flag uncertainty around news quality, supply-chain claims, and valuation.

## Workflow

1. Set the news window.
   - Default to the latest 7 calendar days.
   - State exact start and end dates in the final note.
   - Browse current sources because news heat, company claims, and market narratives change quickly.

2. Build the hot-theme map.
   - Start from recent AI infrastructure catalysts: GPU/ASIC demand, AI servers, HBM, NAND/SSD, advanced packaging, PCB/CCL, copper foil, glass fiber cloth, optical modules, power equipment, liquid cooling, and semiconductor materials/equipment.
   - Look for second-order upstream links. Examples:
     - GPU server demand -> accelerator board and switch board demand -> high-layer PCB -> high-speed CCL -> copper foil/resin/glass fiber cloth.
     - AI training/inference storage demand -> SSD and memory modules -> NAND/DRAM/HBM packaging and testing -> precursors, photoresist, specialty gases, and substrate materials.
     - AI data-center buildout -> power delivery and thermal load -> transformers, UPS, switchgear, liquid-cooling components, and precision temperature control.

3. Convert themes into A-share candidates.
   - Include only listed A-share companies.
   - Verify stock code, exchange suffix, company name, list date, and whether the company is already in `ai_stock_pool.csv`.
   - Prefer companies with clear upstream purity, multiple evidence points, and explicit AI/data-center/semiconductor storage linkage.
   - Avoid adding a candidate when the chain is purely conceptual or the only support is price movement.

4. Score candidates qualitatively before editing the CSV.
   - News heat: recent articles, announcements, sector research, or repeated market coverage.
   - Upstream depth: supplier-of-supplier exposure beats broad "AI+" narratives.
   - AI exposure: direct revenue/product linkage is stronger than loose thematic linkage.
   - Evidence quality: company filings and reliable financial media beat unsourced reposts.
   - Pool fit: diversify across sub-sectors and avoid overloading one narrow trade.

5. Update the stock pool.
   - Preserve the exact CSV schema from `references/csv-schema.md`.
   - Keep CSV fields comma-safe by using Chinese punctuation inside text fields.
   - Add concise `recommended_logic` text that explains the supply-chain path and the AI relevance.
   - Do not include source URLs inside CSV fields; summarize sources in the final response or a separate note.

6. Verify after editing.
   - Check the CSV loads cleanly.
   - Check there are no duplicate `stock_code` values.
   - If sector names are new, add matching entries to `src/config.py` industry adjustments when useful.
   - Run the repo's lightweight validation command before committing.

## Output Standard

When presenting candidates before or after updating the CSV, use this shape:

| stock_code | stock_name | sector | sub_sector | ai_exposure | reason |
| --- | --- | --- | --- | --- | --- |

Then separately include the exact CSV rows if the user wants to review them.

## References

- `references/csv-schema.md`: required `ai_stock_pool.csv` schema and field conventions.
