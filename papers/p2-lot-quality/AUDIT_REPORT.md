# Audit report — Lot release attributes and reactogenicity of VA-MENGOC-BC (Paper 2)

2026-10-04 · English and Spanish · target journal: *Vaccine* (alternatives: *Biologicals*,
*Drug Safety*)

## Verdict

Two defects would have invalidated results: the lot-level quasi-binomial model understated its
standard errors by a factor of roughly the square root of the mean lot size, and the capability
analysis compared production periods whose boundary had been chosen from the data. Both were
fixed in the code. The case-only design is now described with its assumption, unadjusted
estimates accompany adjusted ones, every statement that depends on the results (conformity,
direction of associations, negative control, consistency of sensitivity analyses) is generated
from them, and the abstract meets the 250-word limit of *Vaccine*. **The numbers in the current
PDFs are synthetic.**

## Findings

### [Fatal] Lot-level dispersion computed on the wrong scale
**What.** Quasi-binomial confidence intervals far too narrow (p-values of 0.000 everywhere).
**Root cause.** With a two-column (events, non-events) response, statsmodels' `scale="X2"` is
computed on the proportion scale, giving a dispersion of about 1/mean lot size.
**Evidence.** A simulation with pure binomial noise gave a dispersion of 0.05 instead of ≈1.
**Correction.** Refit on proportions with `var_weights` equal to the reports per lot; a unit test
asserts a dispersion between 0.5 and 2 under binomial sampling (commit `f0a94df`).
**Consequence.** Lot-level sensitivity intervals widen to plausible values.

### [Fatal] Data-chosen production periods
**What.** Capability by period used 2011–2017 versus 2018–2025, the year of the shift planted in
the synthetic data; on real data this would be a data-driven split.
**Correction.** Periods are fixed by the design: lots produced before versus during the
pharmacovigilance window (configurable, never derived from QC values); test added.

### [Major] Result-dependent statements
"All lots met their specifications", "the direction and size were consistent in the sensitivity
analyses", "linked and unlinked reports differed" and the negative-control sentence are now
generated (`\PTConformitySentence`, `\PTWithinSpecPhrase`, `\PTSensSentence`,
`\PTNegControlSentence`) or rewritten as conditional statements. Spanish direction phrases were
rephrased to avoid gender/number agreement errors.

### [Major] Unadjusted estimates absent (STROBE/RECORD-PE 16a)
Crude GEE estimates are now computed, reported next to the adjusted ones in Table 2 and kept
outside the false-discovery-rate family.

### [Major] Disclosure control
Percentages in the linkage-bias table implied counts below five (for example 2.4% of 167 = 4);
the implied-count rule now blanks them. Sensitivity subsets and yearly linkage complements that
differ from the primary by a small count are withheld.

### [Minor]
Forest-plot caption described models that the figure does not show (corrected: single-exposure
models with the minimum-detectable-effect band); linkage flow diagram added with exclusions;
abstract reduced from 271 to 235 words; table widths fixed (landscape sensitivity table, wrapped
columns), exploratory associations moved to a long table.

## Claim ledger

| Claim | State | Evidence |
|---|---|---|
| Lots within specification; capability below 1.0 for some attributes | Verified mechanically; numbers synthetic | `p2_capability.csv` |
| National and export lots equivalent | Verified mechanically | `p2_equivalence.csv` (TOST, HL, energy test) |
| Linkage rate | Verified mechanically | `p2_linkage_summary.json` |
| Number of FDR-significant associations, endotoxin–fever OR | Verified mechanically (planted OR recovered on synthetic data) | `p2_gee_primary.csv` |
| Negative control, incremental value | Verified mechanically | GEE negative control; permutation test |
| Feasibility of routine linkage | Verified (design statement) | — |

## Verification performed

- 0 errors, warnings, bad boxes and undefined references in manuscript, supplement and RECORD-PE
  checklist (both languages); fonts embedded.
- Methods checked against `analysis/qc_safety.py`, `spc.py`, `mspc.py`, `equivalence.py`,
  `changepoint.py` (standardisation over linked lots, exchangeable GEE with robust SEs, covariates,
  BH family, MDE formula with design effect, grouped CV and between-lot permutations).
- Literature on lot-dependent safety cited with its published critiques (Hviid 2023, Scott 2023).

## Open issues

1. Re-verify every claim on `release/public`.
2. Doses distributed per lot are not recorded; incidence per lot cannot be estimated.
3. Ethics approval, funding and CRediT roles are pending (visible markers).
4. Release tests describe lots at release, not after storage and distribution.
