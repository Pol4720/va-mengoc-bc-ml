# Audit report — Post-marketing safety of VA-MENGOC-BC in Cuba (Paper 1)

2026-10-04 · English and Spanish · target journal: *Drug Safety* (alternatives: *Vaccine*,
*Pharmacoepidemiology and Drug Safety*)

## Verdict

As first drafted, the analysis would not have survived review: the hospitalisation model reported
odds ratios of 0 and infinity from a singular, separated design, several sentences stated results
that only held for one data set, and the public release allowed suppressed small counts to be
recovered by subtraction. All three classes of defect were corrected at their root (estimator,
wording generated from the results, disclosure-control rules). The manuscript now compiles to
zero diagnostics in both languages, every number and every result-dependent phrase is generated
from the disclosure-controlled release, and READUS-PV is satisfied item by item. **The numbers in
the current PDFs are synthetic**; the scientific claims can only be verified once the pipeline has
been run on the real data (see *Open issues*).

## Findings

### [Fatal] Hospitalisation model was not estimable
**What.** Adjusted odds ratios of exactly 0 or infinity for every term.
**Root cause.** The logistic design was singular — the three region dummies summed to the
intercept and `n_events` equalled the sum of the event indicators — and rare serious events
completely separated the outcome, so maximum likelihood diverged.
**Evidence.** `release/*/tables/p1_seriousness_logistic.csv` before commit `f0a94df`.
**Correction.** Exactly collinear terms are removed column by column (reported in notes); the
model is fitted by Firth's penalised likelihood (`analysis/stats_utils.firth_logit`, validated
against the Haldane-corrected 2×2 odds ratio and under complete separation); temporal-validation
predictions use the FLIC intercept correction. Methods updated in both languages.
**Consequence.** The odds-ratio table and the logistic test metrics are now meaningful; the
Discussion statement on the value of report-based triage is generated from the observed AUROC.

### [Major] Result-dependent statements written as facts
**What.** Sentences such as "calibration slopes below one indicate that predicted risks were too
extreme", "fever, the most frequent event", "high reporting rates indicate sensitivity" and "the
modest discrimination ... and weaker calibration" were true only for one synthetic run.
**Root cause.** Prose written from one set of results rather than generated from them.
**Correction.** Replaced by generated wording (`\POTrendWord`, `\PORateVsExpected`,
`\POTopEvents`, `\PODiscriminationWord`, `\POHospInterpretation`, signal lists split into expected
and emerging reactions) or by methodological statements that hold for any result.
**Consequence.** The text cannot contradict the tables when the real data are used.

### [Major] Disclosure control could be defeated by subtraction
**What.** A suppressed count could be recovered as "All − Other", as the age-group total minus the
visible age bands, as `N_target − b` in the 2×2 table, as a published annual total minus the
visible years, or from a percentage and its denominator.
**Root cause.** Primary suppression applied cell by cell without considering the linear relations
between released cells and tables.
**Correction.** `[c]` complementary suppression (distinct from `<5`), column-wise protection of
series with published totals, the "All" group and coarsened duplicates no longer released, `b`,
`c`, `d` replaced by design sizes, nested designs and cumulative counts withheld when they differ
by a small count, implied-count rule for percentages. Documented in `docs/DATA_GOVERNANCE.md`.
**Consequence.** No released figure changes, but some sensitivity-design cells now show `[c]`.

### [Major] Signal definition was "any method"
**What.** A signal was declared when any of four methods crossed its threshold, which inflates
false positives and is not a prespecified criterion.
**Correction.** Prespecified primary criterion IC025 > 0 with a ≥ 3 (configurable); the number of
methods meeting their thresholds is reported as concordance; "any method" counts are a sensitivity
column of Table 3.

### [Minor] READUS-PV items missing
Items 4a (study identified as a disproportionality analysis of ICSRs), 5a (custodian, number of
vaccines, coding), 5b (extraction date), 7d/10 (case-by-case analysis not performed), 11
(expected versus emerging reactions), 12a/12c (external validity, further designs) and 14d
(protocol registration) were added, with the abstract items 2a–2e and 4b. Extraction date and
custodian are configuration values printed as "authors to complete" until set.

### [Minor] Hard-coded study parameters in the text
Training/test years, LCA settings, infant age limit, minimum reports, ITS period and transition
were typed in the text; they are now macros generated from `configs/pipeline.yaml`.

### [Polish]
Flow diagram boxes overlapped (redrawn); forest-plot legend covered data (moved above); SHAP labels
used internal codes (bilingual labels); figure captions corrected to describe what each panel
shows; plural "Tables S4–S7"; p-values printed with their relation sign; years no longer formatted
with thousands separators.

## Claim ledger

| Claim (abstract / conclusions) | State | Evidence |
|---|---|---|
| Reporting rate and its comparison with the programme reference | Verified mechanically; numbers synthetic | `p1_rates_target.csv`, `\PORateVsExpected` generated from the CI |
| Trend of the reporting rate | Verified mechanically | quasi-Poisson model, `\POTrendWord` from the CI of the rate ratio |
| Number of signals, robust signals, expected vs emerging | Verified mechanically | `p1_disproportionality.csv`, prespecified criterion |
| Latent phenotypes and their stability | Verified mechanically | `p1_lca_selection.csv`, bootstrap ARI |
| Hospitalisation discrimination and interpretation | Corrected (Firth/FLIC) | `p1_seriousness_metrics.json` |
| "Disproportionality generates hypotheses, not risks" | Verified (design statement) | READUS-PV item 13 |

## Verification performed

- Compilation before/after: first build 3 overfull boxes and 2 BibTeX warnings; now 0 errors,
  0 warnings, 0 bad boxes, 0 undefined references in manuscript, supplement and checklist, both
  languages (`tools/latex_build.py`), all fonts embedded.
- Every number in the prose traced to a generated macro; no literal results remain in the source.
- Code read against Methods: comparator designs, ROR/PRR/IC/EBGM, MGPS prior, LCA prior and
  selection, temporal split, Firth/FLIC, PELT penalty, ITS segments, SDC rules.
- Bibliography: 80 PubMed records generated by `tools/bib_pubmed.py`; non-PubMed DOIs checked
  against Crossref (one wrong DOI corrected: Tracy et al. 1992). Load-bearing citations read in
  abstract form (Galindo 2012, Cruz-Rodríguez 2021, Sierra-González 2019, Nøkleby 2007, Holst 2009,
  Sheerin 2019, Rosenqvist 1998, READUS-PV).
- Abstract 325 words (Drug Safety allows up to 450 when a reporting guideline requires it).
- English–Spanish parity: same macros, tables, figures and labels by construction.

## Open issues

1. **Real data.** All claims must be re-verified on `release/public` after the Phase 1 run; the
   synthetic numbers prove only that the pipeline and the documents are consistent.
2. **Ethics approval, funding, CRediT roles, corresponding e-mail, extraction date and custodian**
   are printed as visible markers until the authors supply them (`python tools/check_submission.py
   --strict` fails while any remains).
3. Event indicators are not validated against Brighton definitions; a case-by-case review of the
   emerging signals by the national committee would strengthen the paper.
4. Doses by age, dose number and province are not available, so rates cannot be stratified.
