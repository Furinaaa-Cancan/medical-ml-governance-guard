"""
Tools — training, data processing, reporting, and knowledge retrieval.

Major tools:
    train_select_evaluate.py   <- Full training pipeline (7.6K LOC, needs refactor)
    split_data.py              <- Patient-level train/valid/test splitting
    nhanes_codebook_lookup.py  <- NHANES Codebook RAG (hybrid retrieval)

Reporting:
    generate_audit_report.py, generate_compliance_certificate.py,
    export_latex.py, visualize_results.py, quick_summary.py

Project setup:
    init_project.py, init_guide.py, env_doctor.py, schema_preflight.py

Analysis:
    compare_runs.py, evidence_comparator.py, evidence_digest.py,
    gate_applicability.py, gate_coverage_matrix.py, gate_timeline.py,
    remediation_plan.py, threshold_sensitivity.py

External:
    fetch_papers.py, extract_paper_metadata.py, score_paper_metadata.py,
    batch_journal_review.py, peer_review_lookup.py
"""
