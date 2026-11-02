"""
Automated Metric Identity and Arithmetic Integrity Verification Tests.
Ensures that all benchmark evaluation reports satisfy exact mathematical identities,
partition reconciliations, and strict micro/macro averaging designations.
"""

import os
import json
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLBACK_REPORT_PATH = os.path.join(BASE_DIR, "benchmark", "evaluation_report_fallback.json")
_BENCH_CANDIDATE = os.path.join(BASE_DIR, "datasets", "bns_synthetic_benchmark_50.json")
BENCHMARK_PATH = _BENCH_CANDIDATE if os.path.exists(_BENCH_CANDIDATE) else os.path.join(BASE_DIR, "benchmark", "bns_synthetic_benchmark_50.json")


@pytest.fixture
def fallback_report():
    assert os.path.exists(FALLBACK_REPORT_PATH), f"Report not found at {FALLBACK_REPORT_PATH}"
    with open(FALLBACK_REPORT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def benchmark_data():
    assert os.path.exists(BENCHMARK_PATH), f"Benchmark file not found at {BENCHMARK_PATH}"
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_fallback_prediction_identities(fallback_report):
    """Verifies TP + FP == Total Predictions and Micro Precision/Recall across all partitions."""
    partitions = [
        ("Overall", fallback_report["overall_metrics"]),
        ("Dev", fallback_report["split_metrics"]["development_set_35"]),
        ("Holdout", fallback_report["split_metrics"]["held_out_set_15_previously_inspected"]),
    ]
    for lang, l_data in fallback_report["by_language"].items():
        partitions.append((f"Lang_{lang}", l_data))

    for name, p in partitions:
        cnts = p["counts_and_denominators"]
        # Identity 1: TP + FP == Total Predictions
        assert cnts["true_positives"] + cnts["false_positives"] == cnts["total_predictions"], (
            f"[{name}] Identity violation: TP + FP != Total Predictions"
        )

        # Identity 2: Micro Precision == TP / Total Predictions
        if cnts["total_predictions"] > 0:
            exp_prec = round(cnts["true_positives"] / cnts["total_predictions"], 4)
            assert abs(p["final_prediction_precision_micro"] - exp_prec) <= 0.0001, (
                f"[{name}] Micro Precision mismatch"
            )

        # Identity 3: Micro Recall == Relevant Recovered / Total Ground Truth
        if cnts["ground_truth_relevant_sections"] > 0:
            exp_rec = round(cnts["relevant_sections_retrieved_in_final"] / cnts["ground_truth_relevant_sections"], 4)
            assert abs(p["final_prediction_recall_micro"] - exp_rec) <= 0.0001, (
                f"[{name}] Micro Recall mismatch"
            )

        # Identity 4: Micro F1 formula
        pval = p["final_prediction_precision_micro"]
        rval = p["final_prediction_recall_micro"]
        if (pval + rval) > 0:
            exp_f1 = round(2 * pval * rval / (pval + rval), 4)
            assert abs(p["final_prediction_f1_micro"] - exp_f1) <= 0.0001, (
                f"[{name}] Micro F1 mismatch"
            )

        # Identity 5: Unsupported Rate + Micro Precision == 1.0
        if cnts["total_predictions"] > 0:
            exp_unsup = round(cnts["false_positives"] / cnts["total_predictions"], 4)
            assert abs(p["unsupported_section_rate"] - exp_unsup) <= 0.0001
            assert abs((p["final_prediction_precision_micro"] + p["unsupported_section_rate"]) - 1.0) <= 0.0001


def test_candidate_precision_denominators(fallback_report):
    """Verifies that candidate precision uses documented dynamic and fixed denominators."""
    o = fallback_report["overall_metrics"]
    cnts = o["counts_and_denominators"]

    # Snapshot of the fallback report after the 2026-10-20 corpus integrity migration (restoring Sections 111
    # and 120 changed BM25 corpus statistics: @10 denominator 457 -> 456, @3 numerator 38 -> 37).
    # Dynamic returned candidate denominators: 144, 237, 371, 456
    assert cnts["candidate_total_at_3"] == 144
    assert cnts["candidate_total_at_5"] == 237
    assert cnts["candidate_total_at_8"] == 371
    assert cnts["candidate_total_at_10"] == 456

    # Fixed theoretical slot denominators: K * 50 = 150, 250, 400, 500
    assert cnts["fixed_slot_candidate_total_at_3"] == 150
    assert cnts["fixed_slot_candidate_total_at_5"] == 250
    assert cnts["fixed_slot_candidate_total_at_8"] == 400
    assert cnts["fixed_slot_candidate_total_at_10"] == 500

    # Numerators: 37, 46, 53, 57
    assert cnts["candidate_tp_at_3"] == 37
    assert cnts["candidate_tp_at_5"] == 46
    assert cnts["candidate_tp_at_8"] == 53
    assert cnts["candidate_tp_at_10"] == 57

    # Precision ratios
    assert abs(o["candidate_precision_at_3"] - round(37 / 144, 4)) <= 0.0001
    assert abs(o["candidate_precision_fixed_k_n_at_3"] - round(37 / 150, 4)) <= 0.0001
    assert abs(o["candidate_precision_at_10"] - round(57 / 456, 4)) <= 0.0001
    assert abs(o["candidate_precision_fixed_k_n_at_10"] - round(57 / 500, 4)) <= 0.0001


def test_partition_reconciliation(fallback_report):
    """Verifies exact additive reconciliation: Overall == Dev + Holdout == English + Hindi + Hinglish."""
    o_cnt = fallback_report["overall_metrics"]["counts_and_denominators"]
    d_cnt = fallback_report["split_metrics"]["development_set_35"]["counts_and_denominators"]
    h_cnt = fallback_report["split_metrics"]["held_out_set_15_previously_inspected"]["counts_and_denominators"]
    by_lang = fallback_report["by_language"]

    check_fields = [
        "total_predictions", "true_positives", "false_positives",
        "ground_truth_relevant_sections", "relevant_sections_retrieved_in_final",
        "retrieval_hits_at_3", "retrieval_hits_at_5", "retrieval_hits_at_8", "retrieval_hits_at_10",
        "candidate_tp_at_3", "candidate_total_at_3", "candidate_tp_at_5", "candidate_total_at_5",
        "candidate_tp_at_8", "candidate_total_at_8", "candidate_tp_at_10", "candidate_total_at_10"
    ]

    for f in check_fields:
        # Dev + Holdout == Overall
        assert o_cnt[f] == d_cnt[f] + h_cnt[f], f"Dev + Holdout != Overall for {f}"
        # Languages == Overall
        l_sum = sum(by_lang[lang]["counts_and_denominators"][f] for lang in by_lang)
        assert o_cnt[f] == l_sum, f"Language sum != Overall for {f}"


def test_compound_offence_disaggregation(fallback_report):
    """Verifies that compound offences distinguish micro section recall (7/14) from all-required completion (0/4)."""
    scen = fallback_report["scenario_special_metrics"]
    assert scen["compound_section_recall"] == 0.5000
    assert scen["compound_section_recall_ratio"] == "7/14"
    assert scen["compound_case_completion_rate"] == 0.0000
    assert scen["compound_case_completion_ratio"] == "0/4"


def test_provisional_ground_truth_cases_disclosure(fallback_report):
    """Verifies that the five disputed ground truth cases are explicitly disclosed as provisional."""
    meta = fallback_report["metadata"]
    provisional = meta.get("provisional_ground_truth_cases", [])
    expected = ["BNS-BM-17", "BNS-BM-28", "BNS-BM-30", "BNS-BM-31", "BNS-BM-45"]
    for cid in expected:
        assert cid in provisional, f"Disputed case {cid} must be listed as provisional"
