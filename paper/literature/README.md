# Literature collection

Reference papers cited in `paper/lit-review.md`. Stored locally for
convenience; original sources linked below.

---

## ✅ Downloaded (open access PDF available)

| # | File | Citation | Why it matters for mlgg |
|---|------|----------|-------------------------|
| 02 | `02-Kapoor2023-leakage-reproducibility-arxiv.pdf` | Kapoor & Narayanan 2023, *Patterns* 4(9):100804 | **Closest conceptual prior art**. 8-type leakage taxonomy, 17 fields × 329 papers affected. Proposes voluntary "model info sheets" — mlgg implements the executable enforcement they call for. |
| 04 | `04-Varoquaux2022-methodological-failures-npjdm.pdf` | Varoquaux & Cheplygina 2022, *npj Digital Medicine* 5:48 | Review article documenting failure modes in medical imaging ML. mlgg's structural claim that "current peer review misses systematic issues" cites this. |
| 05 | `05-Oala2021-algorithm-auditing-qc-jmedsys.pdf` | Oala et al. 2021, *J Med Syst* 45(12):105 | Editorial calling for ML4H algorithm auditing. mlgg responds to this call with concrete tooling. |
| 06 | `06-Vasey2022-decide-ai-natmed.pdf` | Vasey et al. 2022, *Nat Med* 28:924–933 | DECIDE-AI checklist for early-stage clinical evaluation. Out of mlgg's pre-publication scope but cited as ecosystem context. |
| 08 | `08-Norgeot2020-mi-claim-natmed.pdf` | Norgeot et al. 2020, *Nat Med* 26:1320–1324 | MI-CLAIM minimum information checklist. One of the 11+ reporting checklists mlgg's executable validators map to. |

## ⚠️ Could not auto-download (Cloudflare / reCAPTCHA blocked)

These need to be opened in a real browser. URLs below.

### 01 — Liu et al. 2022 "The medical algorithmic audit"

> **Closest medical-domain prior art**. Procedural audit framework for deployed
> medical AI systems. mlgg extends from procedural to executable, and from
> post-deployment to pre-publication.

- **Lancet Digital Health (open access)**: https://www.thelancet.com/journals/landig/article/PIIS2589-7500(22)00003-6/fulltext
- **PDF direct**: https://www.thelancet.com/pdfs/journals/landig/PIIS2589-7500(22)00003-6.pdf
- **PubMed**: https://pubmed.ncbi.nlm.nih.gov/35396183/
- **Healthy ML group page**: https://healthyml.org/publication/liu-2022-medical/
- **Birmingham repository**: https://research.birmingham.ac.uk/en/publications/the-medical-algorithmic-audit/

**Authors to remember** (Liu, Glocker, McCradden, Ghassemi, Denniston, Oakden-Rayner): exactly the senior co-author candidate pool for mlgg.

### 03 — Collins et al. 2024 "TRIPOD+AI statement"

> **The canonical reporting guideline mlgg's gates map to** (27 items).

- **BMJ (open access)**: https://www.bmj.com/content/385/bmj-2023-078378
- **PDF direct**: https://www.bmj.com/content/bmj/385/bmj-2023-078378.full.pdf
- **PMC**: https://pmc.ncbi.nlm.nih.gov/articles/PMC11019967/
- **EQUATOR**: https://www.equator-network.org/reporting-guidelines/tripod-statement/
- **TRIPOD official**: https://www.tripod-statement.org/

### 07 — Tejani et al. 2024 "CLAIM update"

> Imaging-specific. **Out of mlgg's scope** but cited as ecosystem context.

- **Radiology AI**: https://pubs.rsna.org/doi/full/10.1148/ryai.240300
- **PMC**: https://pmc.ncbi.nlm.nih.gov/articles/PMC11304031
- **PubMed**: https://pubmed.ncbi.nlm.nih.gov/38809149/

---

## Other references mentioned in lit-review.md (not yet collected)

These are lower-priority for mlgg's introduction but worth bookmarking:

- **PROBAST-AI protocol** (Collins 2021 BMJ Open): https://bmjopen.bmj.com/content/11/7/e048008
- **CONSORT-AI** (Liu 2020 Nat Med 26:1364): https://www.nature.com/articles/s41591-020-1034-x
- **TRIPOD-LLM** (Gallifant 2024 Nat Med): https://www.nature.com/articles/s41591-024-03425-5
- **HAIRA governance maturity** (2026 npjDM): https://www.nature.com/articles/s41746-026-02418-7
- **KT-LLM auditable kidney transplant** (2025 npjDM): https://www.nature.com/articles/s41746-025-02323-5
- **General framework for AI/ML medical device governance** (2025 npjDM): https://www.nature.com/articles/s41746-025-01717-9
- **ReproAudit** (general-purpose competitor): https://reproaudit.com
- **TRIPOD-AI Checklist Agent (SciSpace)**: https://scispace.com/agents/tripod-ai-checklist-a70kfdk5
- **Princeton ML reproducibility taxonomy site**: https://reproducible.cs.princeton.edu/
- **Reddy et al. 2025 "Navigating the landscape of medical AI reporting guidelines"**: https://www.thelancet.com/journals/landig/article/PIIS2589-7500(25)00107-4/fulltext

---

## Reading order for mlgg author

If reading time is limited, prioritize:

1. **Kapoor 2023** (file 02): foundational problem statement; cite heavily.
2. **Liu 2022** (URL 01): closest medical-domain framework; potential senior co-authors.
3. **Collins 2024 TRIPOD+AI** (URL 03): the 27-item checklist mlgg maps to.
4. **Oala 2021** (file 05): the editorial mlgg responds to.
5. **Varoquaux 2022** (file 04): failure-mode review; supports the "problem is real" introduction paragraph.

The remaining 3 (Vasey DECIDE-AI, Norgeot MI-CLAIM, Tejani CLAIM) are
ecosystem context — useful to skim but not deep-read.
