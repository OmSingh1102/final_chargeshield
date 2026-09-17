class QAReviewEngine:
    """Quality assurance and compliance audit engine."""

    @classmethod
    def compute(cls, cases, ml_stats, evidence_results, reason_code_db):
        classified = ml_stats["classified_cases"]
        auto_cases = [c for c in classified if c["ml"]["routing"] == "auto_represent"]
        hitl_cases = [c for c in classified if c["ml"]["routing"] == "hitl_review"]

        # Auto-decision audit
        auto_audit = []
        issues_found = 0
        for c in auto_cases:
            ev = evidence_results.get(c["case_id"], {})
            completeness = ev.get("overall_completeness_pct", 0)
            correct = c["outcome"] in ["Win", "Pending"]
            issue = None
            if not correct:
                issue = "Auto-decision resulted in loss/refund"
                issues_found += 1
            elif completeness < 80:
                issue = f"Evidence completeness below threshold ({completeness}%)"
                issues_found += 1
            auto_audit.append({
                "case_id": c["case_id"],
                "confidence": c["ml"]["confidence"],
                "outcome": c["outcome"],
                "completeness": completeness,
                "correct": correct,
                "issue": issue,
                "reason_code": c["reason_code"],
                # The audit row carried a bare code and nothing to explain it.
                # The network is what lets the template name the code.
                "network": c.get("payment_method", ""),
                "amount": c["amount"],
            })

        # Agent quality (synthetic per analyst from DashboardAnalytics.ANALYSTS)
        analysts = [
            {"name": "Priya Sharma", "cases_reviewed": 5, "wins": 4, "losses": 1, "win_rate": 80,
             "avg_time_min": 18, "quality_score": 94, "issues": 0, "status": "Online"},
            {"name": "Marcus Chen", "cases_reviewed": 4, "wins": 2, "losses": 2, "win_rate": 50,
             "avg_time_min": 25, "quality_score": 78, "issues": 2, "status": "Online"},
            {"name": "Sarah Johnson", "cases_reviewed": 3, "wins": 2, "losses": 1, "win_rate": 67,
             "avg_time_min": 32, "quality_score": 85, "issues": 1, "status": "Away"},
        ]

        # Flagged cases
        flagged = []
        for c in classified:
            ev = evidence_results.get(c["case_id"], {})
            completeness = ev.get("overall_completeness_pct", 0)
            flags = []
            if c["ml"]["confidence"] < 45 and c["ml"]["routing"] == "auto_represent":
                flags.append("Low confidence auto-decision")
            if c["outcome"] in ["Lost", "Refunded"] and c["ml"]["confidence"] >= 60:
                flags.append("High-confidence case lost - review defense strategy")
            if completeness < 50 and c["outcome"] == "Pending":
                flags.append(f"Pending case with weak evidence ({completeness}%)")
            if not c.get("liability_shift") and c["reason_code"] in ["10.4", "11.3"]:
                flags.append("Fraud case without liability shift")
            if flags:
                flagged.append({
                    "case_id": c["case_id"],
                    "flags": flags,
                    "severity": "high" if any("lost" in f.lower() or "low confidence" in f.lower() for f in flags) else "medium",
                    "confidence": c["ml"]["confidence"],
                    "outcome": c["outcome"],
                    "amount": c["amount"],
                })

        # Compliance checklist per case
        compliance = []
        for c in classified:
            ev = evidence_results.get(c["case_id"], {})
            rc = reason_code_db.get(c["reason_code"], {})
            # "Deadline within SLA" used to sit here hardcoded to True — a
            # check that could not fail, quietly inflating every score by a
            # fifth. Removed rather than implemented: nothing tracks when a
            # case was worked, so there is no deadline to check against.
            checks = {
                "Evidence collected": ev.get("overall_completeness_pct", 0) > 0,
                "Reason code matched": c["reason_code"] in reason_code_db,
                "AVS/CVV verified": "match" in c.get("avs_response", "").lower() or "(Y)" in c.get("avs_response", ""),
                "Defense docs prepared": c["submission_status"] in ["Auto-Submitted", "Submitted"],
            }
            passed = sum(1 for v in checks.values() if v)
            compliance.append({
                "case_id": c["case_id"],
                "checks": checks,
                "passed": passed,
                "total": len(checks),
                "score": round(passed / len(checks) * 100),
            })

        total_audited = len(auto_audit) + len(analysts)
        avg_compliance = round(sum(c["score"] for c in compliance) / len(compliance)) if compliance else 0

        return {
            "stats": {
                "cases_audited": total_audited,
                "auto_reviewed": len(auto_audit),
                "issues_found": issues_found + sum(a["issues"] for a in analysts),
                "compliance_score": avg_compliance,
            },
            "auto_audit": auto_audit,
            "analysts": analysts,
            "flagged": flagged,
            "compliance": compliance,
        }
