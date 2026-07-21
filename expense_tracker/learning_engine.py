from __future__ import annotations

import sqlite3
import json
from decimal import Decimal
from datetime import datetime

def utc_now() -> str:
    return datetime.utcnow().isoformat().split(".")[0] + "Z"

class FeedbackManager:
    @staticmethod
    def add_feedback(
        conn: sqlite3.Connection,
        merchant_keys: list[str],
        predicted_label: str,
        actual_label: str,
        action: str,  # 'approved', 'rejected', 'ignored', 'created'
        evidence: dict | None = None
    ) -> None:
        """
        Store a user action as an immutable feedback event.
        merchant_keys: list of all normalized merchant names involved in the event.
        """
        keys_json = json.dumps(sorted(list(set(merchant_keys))))
        evidence_str = json.dumps(evidence or {})
        now = utc_now()
        conn.execute(
            """
            insert into relationship_feedback (
                merchant_keys_json, predicted_type,
                actual_type, action, evidence_json, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            (keys_json, predicted_label, actual_label, action, evidence_str, now)
        )
        conn.commit()


class LearningStatistics:
    @staticmethod
    def get_aggregate_stats(conn: sqlite3.Connection) -> list[dict]:
        """
        Compute dynamic accuracy statistics per predicted label.
        """
        rows = conn.execute(
            """
            select 
                predicted_type,
                sum(case when action = 'approved' then 1 else 0 end) as approvals,
                sum(case when action = 'rejected' then 1 else 0 end) as rejections,
                sum(case when action = 'ignored' then 1 else 0 end) as ignores,
                max(created_at) as last_seen
            from relationship_feedback
            group by predicted_type
            order by approvals desc
            """
        ).fetchall()
        
        stats = []
        for r in rows:
            approvals = r["approvals"] or 0
            rejections = r["rejections"] or 0
            ignores = r["ignores"] or 0
            total = approvals + rejections
            accuracy = float(approvals) / total if total > 0 else 1.0
            stats.append({
                "relationship_type": r["predicted_type"],
                "approvals": approvals,
                "rejections": rejections,
                "ignores": ignores,
                "accuracy": accuracy,
                "last_seen": r["last_seen"]
            })
        return stats


class ConfidenceEvaluator:
    @staticmethod
    def evaluate_confidence(
        conn: sqlite3.Connection,
        label: str,
        merchant_keys: list[str],
        base_confidence: float,
        evidence: dict
    ) -> tuple[float, list[str]]:
        """
        Adjust confidence using:
        1. Specific group of merchant keys feedback history
        2. Global accuracy performance for the predicted label
        3. Feature-level pattern correlation
        """
        # Fetch feedback history
        rows = conn.execute(
            """
            select action, predicted_type, actual_type, merchant_keys_json, evidence_json
            from relationship_feedback
            """
        ).fetchall()
        
        candidate_keys_set = set(merchant_keys)
        
        approvals = 0
        rejections = 0
        ignores = 0
        
        for r in rows:
            try:
                fb_keys = set(json.loads(r["merchant_keys_json"]))
            except Exception:
                continue
            
            # Match if candidate keys set matches feedback keys set
            if fb_keys == candidate_keys_set:
                act = r["action"]
                if act == "approved":
                    approvals += 1
                elif act == "rejected":
                    rejections += 1
                elif act == "ignored":
                    ignores += 1

        reasons = []
        confidence = base_confidence

        # A. Group-Level Key Learning
        if rejections > 0:
            reasons.append(f"Group match has {rejections} previous rejection(s). Suppressed suggestion.")
            return 0.0, reasons

        if approvals > 0:
            confidence = base_confidence + (1.0 - base_confidence) * (1.0 - 0.5 ** approvals)
            reasons.append(f"Similar suggestion approved {approvals} time(s) previously. Confidence boosted.")

        # B. Global-Level Label Learning
        global_stats = conn.execute(
            """
            select 
                sum(case when action = 'approved' then 1 else 0 end) as approvals,
                sum(case when action = 'rejected' then 1 else 0 end) as rejections
            from relationship_feedback
            where predicted_type = ?
            """,
            (label,)
        ).fetchone()
        
        if global_stats:
            g_app = global_stats["approvals"] or 0
            g_rej = global_stats["rejections"] or 0
            g_total = g_app + g_rej
            if g_total >= 5:
                g_accuracy = g_app / g_total
                confidence = confidence * (0.5 + 0.5 * g_accuracy)
                reasons.append(f"Global suggestion type accuracy is {int(g_accuracy * 100)}%. Adjusted score.")

        # C. Pattern-Level Learning (Features Correlation)
        signals = evidence.get("signals", {})
        same_amount = signals.get("same_amount", False)
        
        pattern_feedback = conn.execute(
            """
            select action
            from relationship_feedback
            where predicted_type = ? and json_extract(evidence_json, '$.signals.same_amount') = ?
            """,
            (label, 1 if same_amount else 0)
        ).fetchall()
        
        p_app = sum(1 for f in pattern_feedback if f["action"] == "approved")
        p_total = len(pattern_feedback)
        if p_total >= 5:
            p_accuracy = p_app / p_total
            confidence = 0.8 * confidence + 0.2 * p_accuracy
            reasons.append(f"Suggestions with similar amount signals show {int(p_accuracy * 100)}% approval rate.")

        final_conf = round(max(0.0, min(1.0, confidence)), 3)
        return final_conf, reasons
