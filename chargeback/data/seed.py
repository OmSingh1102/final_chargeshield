import os
import csv as _csv
from collections import Counter, defaultdict

from chargeback.data.loader import ChargebackCaseLoader
from chargeback.engines.reason_code import ReasonCodeInterpreter


# ─── Sample Chargeback Cases ────────────────────────────────────
CASES = [
    {
        "case_id": "CB-2025-0001", "scenario": "Merchandise - Item Defective",
        "chargeback_category": "Merchandise - Defective Item", "reason_code": "13.3",
        "processor": "Adyen", "amount": 34.99, "win_probability": 52,
        "submission_date": "Jun 22, 2026", "submission_status": "Refunded", "outcome": "Refunded",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Mastercard", "card_last_four": "7401", "card_expiry": "04/2030",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "NAVY FEDERAL CREDIT UNION",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Not Authenticated",
        "transaction_date": "Jun 04, 2026, 12:57 PM PDT", "amount_authorized": 34.99, "amount_settled": 34.99,
        "dispute_psp_ref": "Z4SPH2Z93F2B3NF6", "payment_psp_ref": "03FG7DW8JVT187G3",
        "dispute_creation_date": "Jun 22, 2026, 21:06:49", "order_id": "TTS-ORD-20260604-LSH3T",
        "acquirer_ref": "24793306171002502006060", "acquirer_code": "AdyenVisa_US_WF400224",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "This account was closed due to fraud. It was reported as fraud and placed on the Exception File. The cardholder was advised of the information provided by the merchant and verified it is fraud. The cardholder has no knowledge of the transaction and/or merchant. Our cardholder did not authorize or benefit from this transaction. Per Visa regulations this dispute has not been remedied.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jun 22, 2026, 21:06:49"},
            {"event": "NotificationOfChargeback", "date": "Jun 22, 2026, 21:06:49"},
            {"event": "Chargeback", "date": "Jun 22, 2026, 23:15:02 - Adyen"},
            {"event": "InformationSupplied", "date": "Jun 30, 2026, 03:31:18"},
            {"event": "AcquirerPreArbitrationUploaded", "date": "Jun 30, 2026, 03:31:34"},
            {"event": "PreArbitrationLost", "date": "Jul 1, 2026, 06:03:45 - Adyen"}
        ]
    },
    {
        "case_id": "CB-2025-0002", "scenario": "Merchandise - Item Not Received",
        "chargeback_category": "Merchandise - Not Received", "reason_code": "13.1",
        "processor": "Adyen", "amount": 1225.0, "win_probability": 61,
        "submission_date": "Jul 2, 2026", "submission_status": "Auto-Submitted", "outcome": "Win",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "6658", "card_expiry": "09/2028",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CHASE BANK",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 18, 2026, 03:22 PM PDT", "amount_authorized": 1225.0, "amount_settled": 1225.0,
        "dispute_psp_ref": "WP-DSP-20260702-001", "payment_psp_ref": "WP-PAY-20260618-882",
        "dispute_creation_date": "Jul 2, 2026, 14:30:00", "order_id": "TTS-ORD-20260705-HVLZ0",
        "acquirer_ref": "24793306171002502007001", "acquirer_code": "WorldpayVisa_US_001",
        "auto_defended": True, "liability_shift": True, "issuer_comments": "",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 2, 2026, 14:30:00"},
            {"event": "AutoDefenseSubmitted", "date": "Jul 2, 2026, 14:35:00"},
            {"event": "DisputeWon", "date": "Jul 4, 2026, 10:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0003", "scenario": "Merchandise - Not as Described",
        "chargeback_category": "Merchandise - Not as Described", "reason_code": "13.3",
        "processor": "Braintree", "amount": 119.97, "win_probability": 49,
        "submission_date": "Jun 22, 2026", "submission_status": "Refunded", "outcome": "Refunded",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Mastercard", "card_last_four": "8849", "card_expiry": "12/2027",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CAPITAL ONE",
        "avs_response": "Postal code matches, address does not (P)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Not Authenticated",
        "transaction_date": "Jun 10, 2026, 09:15 AM PDT", "amount_authorized": 119.97, "amount_settled": 119.97,
        "dispute_psp_ref": "WP-DSP-20260622-003", "payment_psp_ref": "WP-PAY-20260610-554",
        "dispute_creation_date": "Jun 22, 2026, 18:00:00", "order_id": "TTS-ORD-20260701-B8C7X",
        "acquirer_ref": "24793306171002502006003", "acquirer_code": "WorldpayMC_US_002",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "Cardholder states the item received was significantly different from the product listing.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jun 22, 2026, 18:00:00"},
            {"event": "Refunded", "date": "Jun 23, 2026, 09:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0004", "scenario": "Fraud - Card Not Present (CNP)",
        "chargeback_category": "Fraud - CNP", "reason_code": "10.4",
        "processor": "Braintree", "amount": 55.98, "win_probability": 38,
        "submission_date": "Jun 28, 2026", "submission_status": "Submitted", "outcome": "Pending",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "2807", "card_expiry": "06/2029",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "WELLS FARGO",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Not Authenticated",
        "transaction_date": "Jun 12, 2026, 10:30 AM PDT", "amount_authorized": 55.98, "amount_settled": 55.98,
        "dispute_psp_ref": "ADY-DSP-20260628-004", "payment_psp_ref": "ADY-PAY-20260612-440",
        "dispute_creation_date": "Jun 28, 2026, 09:00:00", "order_id": "TTS-ORD-20260706-LOUFH",
        "acquirer_ref": "24793306171002502006004", "acquirer_code": "AdyenVisa_US_WF400224",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "Cardholder denies making this purchase. No 3DS authentication was performed.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jun 28, 2026, 09:00:00"},
            {"event": "DefenseSubmitted", "date": "Jun 30, 2026, 14:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0005", "scenario": "Fraud - Merchant Liability (No 3DS)",
        "chargeback_category": "Fraud - Merchant Liable", "reason_code": "10.4",
        "processor": "Stripe", "amount": 445.5, "win_probability": 33,
        "submission_date": "Jun 27, 2026", "submission_status": "Refunded", "outcome": "Refunded",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Mastercard", "card_last_four": "2960", "card_expiry": "08/2029",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "BANK OF AMERICA",
        "avs_response": "Street Address not provided (I). Postal Code matches (M).",
        "cvv_response": "Request bypassed (B).", "threed_secure": "Not Offered",
        "transaction_date": "Jun 15, 2026, 11:30 AM PDT", "amount_authorized": 445.5, "amount_settled": 445.5,
        "dispute_psp_ref": "ADY-DSP-20260627-005", "payment_psp_ref": "ADY-PAY-20260615-771",
        "dispute_creation_date": "Jun 27, 2026, 16:45:00", "order_id": "TTS-ORD-20260614-LAVZM",
        "acquirer_ref": "24793306171002502006005", "acquirer_code": "AdyenVisa_US_WF400224",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "Cardholder denies authorizing this transaction. No 3DS authentication was performed.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jun 27, 2026, 16:45:00"},
            {"event": "Refunded", "date": "Jun 28, 2026, 10:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0006", "scenario": "Fraud - No Authorization",
        "chargeback_category": "Fraud - No Auth", "reason_code": "11.3",
        "processor": "Stripe", "amount": 34.99, "win_probability": 22,
        "submission_date": "Jul 1, 2026", "submission_status": "Disputed", "outcome": "Lost",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "3848", "card_expiry": "02/2028",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CITI BANK",
        "avs_response": "Street Address not provided (I). Postal Code matches (M).",
        "cvv_response": "Request bypassed (B).", "threed_secure": "Not Offered",
        "transaction_date": "Jun 20, 2026, 02:15 PM PDT", "amount_authorized": 34.99, "amount_settled": 34.99,
        "dispute_psp_ref": "STR-DSP-20260701-006", "payment_psp_ref": "STR-PAY-20260620-990",
        "dispute_creation_date": "Jul 1, 2026, 11:00:00", "order_id": "TTS-ORD-20260604-QOTVO",
        "acquirer_ref": "24793306171002502007006", "acquirer_code": "StripeMC_US_001",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "No valid authorization obtained for this transaction.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 1, 2026, 11:00:00"},
            {"event": "DefenseSubmitted", "date": "Jul 3, 2026, 09:00:00"},
            {"event": "DisputeLost", "date": "Jul 5, 2026, 16:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0007", "scenario": "Refund - Credit Not Processed",
        "chargeback_category": "Refund - Credit Not Processed", "reason_code": "13.6",
        "processor": "Adyen", "amount": 49.98, "win_probability": 55,
        "submission_date": "Jun 30, 2026", "submission_status": "Submitted", "outcome": "Pending",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Mastercard", "card_last_four": "7870", "card_expiry": "11/2029",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "US BANK",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 14, 2026, 04:50 PM PDT", "amount_authorized": 49.98, "amount_settled": 49.98,
        "dispute_psp_ref": "BT-DSP-20260630-007", "payment_psp_ref": "BT-PAY-20260614-554",
        "dispute_creation_date": "Jun 30, 2026, 10:00:00", "order_id": "TTS-ORD-20260624-7G8B2",
        "acquirer_ref": "24793306171002502006007", "acquirer_code": "BraintreeVisa_US_001",
        "auto_defended": False, "liability_shift": True,
        "issuer_comments": "Cardholder states merchant promised a refund but it was never processed.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jun 30, 2026, 10:00:00"},
            {"event": "DefenseSubmitted", "date": "Jul 2, 2026, 11:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0008", "scenario": "Refund - Cancelled Merchandise",
        "chargeback_category": "Refund - Cancelled Merch", "reason_code": "13.7",
        "processor": "Stripe", "amount": 899.99, "win_probability": 68,
        "submission_date": "Jul 3, 2026", "submission_status": "Auto-Submitted", "outcome": "Win",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "5558", "card_expiry": "05/2030",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CHASE BANK",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 22, 2026, 08:00 AM PDT", "amount_authorized": 899.99, "amount_settled": 899.99,
        "dispute_psp_ref": "WP-DSP-20260703-008", "payment_psp_ref": "WP-PAY-20260622-330",
        "dispute_creation_date": "Jul 3, 2026, 09:30:00", "order_id": "TTS-ORD-20260609-NC21O",
        "acquirer_ref": "24793306171002502007008", "acquirer_code": "WorldpayVisa_US_002",
        "auto_defended": True, "liability_shift": True, "issuer_comments": "",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 3, 2026, 09:30:00"},
            {"event": "AutoDefenseSubmitted", "date": "Jul 3, 2026, 09:35:00"},
            {"event": "DisputeWon", "date": "Jul 5, 2026, 12:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0009", "scenario": "Processing - Incorrect Amount",
        "chargeback_category": "Processing - Incorrect Amount", "reason_code": "12.5",
        "processor": "Adyen", "amount": 13.99, "win_probability": 70,
        "submission_date": "Jul 4, 2026", "submission_status": "Auto-Submitted", "outcome": "Win",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "1984", "card_expiry": "06/2029",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "WELLS FARGO",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 25, 2026, 01:10 PM PDT", "amount_authorized": 13.99, "amount_settled": 13.99,
        "dispute_psp_ref": "STR-DSP-20260704-009", "payment_psp_ref": "STR-PAY-20260625-440",
        "dispute_creation_date": "Jul 4, 2026, 15:00:00", "order_id": "TTS-ORD-20260707-J2JCN",
        "acquirer_ref": "24793306171002502007009", "acquirer_code": "StripeVisa_US_002",
        "auto_defended": True, "liability_shift": True, "issuer_comments": "",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 4, 2026, 15:00:00"},
            {"event": "AutoDefenseSubmitted", "date": "Jul 4, 2026, 15:05:00"},
            {"event": "DisputeWon", "date": "Jul 6, 2026, 09:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0010", "scenario": "Subscription - Cancelled Recurring",
        "chargeback_category": "Subscription - Cancelled", "reason_code": "13.2",
        "processor": "Worldpay", "amount": 69.98, "win_probability": 72,
        "submission_date": "Jul 5, 2026", "submission_status": "Auto-Submitted", "outcome": "Win",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "1274", "card_expiry": "10/2028",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "DISCOVER BANK",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 28, 2026, 06:20 PM PDT", "amount_authorized": 69.98, "amount_settled": 69.98,
        "dispute_psp_ref": "BT-DSP-20260705-010", "payment_psp_ref": "BT-PAY-20260628-667",
        "dispute_creation_date": "Jul 5, 2026, 08:00:00", "order_id": "TTS-ORD-20260605-6XATO",
        "acquirer_ref": "24793306171002502007010", "acquirer_code": "BraintreeMC_US_001",
        "auto_defended": True, "liability_shift": True, "issuer_comments": "",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 5, 2026, 08:00:00"},
            {"event": "AutoDefenseSubmitted", "date": "Jul 5, 2026, 08:05:00"},
            {"event": "DisputeWon", "date": "Jul 7, 2026, 10:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0011", "scenario": "Processing - Duplicate Charge",
        "chargeback_category": "Processing - Duplicate", "reason_code": "12.6.1",
        "processor": "Worldpay", "amount": 39.98, "win_probability": 65,
        "submission_date": "Jul 4, 2026", "submission_status": "Auto-Submitted", "outcome": "Win",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Visa", "card_last_four": "5703", "card_expiry": "03/2029",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "NAVY FEDERAL CREDIT UNION",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
        "transaction_date": "Jun 24, 2026, 09:45 AM PDT", "amount_authorized": 39.98, "amount_settled": 39.98,
        "dispute_psp_ref": "ADY-DSP-20260704-011", "payment_psp_ref": "ADY-PAY-20260624-889",
        "dispute_creation_date": "Jul 4, 2026, 12:00:00", "order_id": "TTS-ORD-20260604-TC69Q",
        "acquirer_ref": "24793306171002502007011", "acquirer_code": "AdyenVisa_US_WF400224",
        "auto_defended": True, "liability_shift": True, "issuer_comments": "",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 4, 2026, 12:00:00"},
            {"event": "AutoDefenseSubmitted", "date": "Jul 4, 2026, 12:05:00"},
            {"event": "DisputeWon", "date": "Jul 6, 2026, 14:00:00"}
        ]
    },
    {
        "case_id": "CB-2025-0012", "scenario": "Processing - Paid by Other Means",
        "chargeback_category": "Processing - Paid Other Means", "reason_code": "12.6.2",
        "processor": "Adyen", "amount": 24.99, "win_probability": 45,
        "submission_date": "Jul 3, 2026", "submission_status": "Submitted", "outcome": "Pending",
        "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
        "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
        "payment_method": "Mastercard", "card_last_four": "8895", "card_expiry": "07/2028",
        "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CAPITAL ONE",
        "avs_response": "Both postal code and address match (Y)",
        "cvv_response": "Supplied, Matches (M)", "threed_secure": "Not Authenticated",
        "transaction_date": "Jun 19, 2026, 03:30 PM PDT", "amount_authorized": 24.99, "amount_settled": 24.99,
        "dispute_psp_ref": "STR-DSP-20260703-012", "payment_psp_ref": "STR-PAY-20260619-229",
        "dispute_creation_date": "Jul 3, 2026, 14:30:00", "order_id": "TTS-ORD-20260605-SYWP0",
        "acquirer_ref": "24793306171002502007012", "acquirer_code": "StripeVisa_US_003",
        "auto_defended": False, "liability_shift": False,
        "issuer_comments": "Cardholder states they paid using a different method.",
        "dispute_history": [
            {"event": "OpenDispute", "date": "Jul 3, 2026, 14:30:00"},
            {"event": "DefenseSubmitted", "date": "Jul 5, 2026, 10:00:00"}
        ]
    },
    {"case_id": "CB-2025-0030", "scenario": "Fraud - Card Not Present (CNP)", "chargeback_category": "Fraud - CNP",
     "reason_code": "10.4", "processor": "Stripe", "amount": 55.98, "win_probability": 15,
     "submission_date": "Jul 6, 2026", "submission_status": "Disputed", "outcome": "Lost",
     "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
     "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
     "payment_method": "Visa", "card_last_four": "2807", "card_expiry": "03/2027",
     "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "BARCLAYS",
     "avs_response": "Street address not provided (I). Postal Code matches (M).",
     "cvv_response": "Request bypassed (B).", "threed_secure": "Not Offered",
     "transaction_date": "Jun 30, 2026, 04:00 AM PDT", "amount_authorized": 55.98, "amount_settled": 55.98,
     "dispute_psp_ref": "STR-DSP-20260706-030", "payment_psp_ref": "STR-PAY-20260630-112",
     "dispute_creation_date": "Jul 6, 2026, 08:30:00", "order_id": "TTS-ORD-20260706-LOUFH",
     "acquirer_ref": "24793306171002502007030", "acquirer_code": "StripeMC_US_003",
     "auto_defended": False, "liability_shift": False,
     "issuer_comments": "Small amount test transaction. Card testing fraud suspected.",
     "dispute_history": [{"event": "OpenDispute", "date": "Jul 6, 2026, 08:30:00"}, {"event": "DisputeLost", "date": "Jul 7, 2026, 14:00:00"}]},
    {"case_id": "CB-2025-0031", "scenario": "Merchandise - Item Defective", "chargeback_category": "Merchandise - Defective Item",
     "reason_code": "13.3", "processor": "Stripe", "amount": 119.97, "win_probability": 52,
     "submission_date": "Jul 6, 2026", "submission_status": "Submitted", "outcome": "Pending",
     "merchant": "Acme Commerce Inc.", "merchant_account": "MID-ACME-0001",
     "descriptor_name": "Acme Online Store", "descriptor_url": "acme-store.example.com",
     "payment_method": "Mastercard", "card_last_four": "8849", "card_expiry": "11/2029",
     "cardholder": "***REDACTED***", "issuer_country": "United States", "issuer_name": "CHASE BANK",
     "avs_response": "Both postal code and address match (Y)",
     "cvv_response": "Supplied, Matches (M)", "threed_secure": "Authenticated",
     "transaction_date": "Jun 27, 2026, 03:20 PM PDT", "amount_authorized": 119.97, "amount_settled": 119.97,
     "dispute_psp_ref": "STR-DSP-20260706-031", "payment_psp_ref": "STR-PAY-20260627-775",
     "dispute_creation_date": "Jul 6, 2026, 11:00:00", "order_id": "TTS-ORD-20260701-B8C7X",
     "acquirer_ref": "24793306171002502007031", "acquirer_code": "StripeVisa_US_004",
     "auto_defended": False, "liability_shift": True,
     "issuer_comments": "Cardholder received a defective product. Photos provided to issuer.",
     "dispute_history": [{"event": "OpenDispute", "date": "Jul 6, 2026, 11:00:00"}, {"event": "DefenseSubmitted", "date": "Jul 7, 2026, 08:00:00"}]}
]


# ─── Ingestion Demo Engine (First-Party Merchant / Walmart Model) ─────────────

class IngestionDemo:
    """Simulates first-party merchant chargeback ingestion.
    Raw processor data is enriched from internal orders_db and products_db."""

    # ── Simulated Internal Databases ──

    ORDERS_DB = {
        "tx_10001": {"customer_id": "CUST-8831", "customer_lifetime_value": 2340.00, "order_history_count": 12,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.ups.com/1Z999AA10123456784",
                     "delivery_signature_present": True, "delivery_signed_at": "Jul 02, 2026 10:15 AM",
                     "customer_ip_address": "73.59.209.182", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A1", "order_date": "Jun 28, 2026"},
        "tx_10002": {"customer_id": "CUST-4420", "customer_lifetime_value": 890.00, "order_history_count": 5,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.fedex.com/794644790301",
                     "delivery_signature_present": True, "delivery_signed_at": "Jun 30, 2026 02:22 PM",
                     "customer_ip_address": "104.28.88.21", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A2", "order_date": "Jun 25, 2026"},
        "tx_10003": {"customer_id": "CUST-7712", "customer_lifetime_value": 340.00, "order_history_count": 3,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://tools.usps.com/9400111899223",
                     "delivery_signature_present": False, "delivery_signed_at": None,
                     "customer_ip_address": "192.168.45.12", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-B1", "order_date": "Jul 01, 2026"},
        "tx_10004": {"customer_id": "CUST-2290", "customer_lifetime_value": 5600.00, "order_history_count": 28,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.ups.com/1Z999AA10456789012",
                     "delivery_signature_present": True, "delivery_signed_at": "Jul 03, 2026 11:45 AM",
                     "customer_ip_address": "68.45.102.33", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A3", "order_date": "Jun 30, 2026"},
        "tx_10005": {"customer_id": "CUST-9901", "customer_lifetime_value": 120.50, "order_history_count": 1,
                     "shipping_status": "Not Shipped", "carrier_tracking_url": None,
                     "delivery_signature_present": False, "delivery_signed_at": None,
                     "customer_ip_address": "185.220.101.45", "avs_cvv_match_status": "Fail",
                     "product_id": "PROD-A4", "order_date": "Jun 27, 2026"},
        "tx_10006": {"customer_id": "CUST-3301", "customer_lifetime_value": 4200.00, "order_history_count": 34,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.ups.com/1Z999AA10789012345",
                     "delivery_signature_present": True, "delivery_signed_at": "Jun 29, 2026 09:30 AM",
                     "customer_ip_address": "72.14.204.18", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A5", "order_date": "Jun 24, 2026"},
        "tx_10007": {"customer_id": "CUST-5540", "customer_lifetime_value": 780.00, "order_history_count": 6,
                     "shipping_status": "In Transit", "carrier_tracking_url": "https://track.veho.com/d4l753a8f0d95fe86",
                     "delivery_signature_present": False, "delivery_signed_at": None,
                     "customer_ip_address": "98.210.45.77", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-B2", "order_date": "Jun 29, 2026"},
        "tx_10008": {"customer_id": "CUST-1122", "customer_lifetime_value": 34.50, "order_history_count": 1,
                     "shipping_status": "In Transit", "carrier_tracking_url": "https://tools.usps.com/9400111899445",
                     "delivery_signature_present": False, "delivery_signed_at": None,
                     "customer_ip_address": "185.220.102.88", "avs_cvv_match_status": "Fail",
                     "product_id": "PROD-B3", "order_date": "Jul 03, 2026"},
        "tx_10009": {"customer_id": "CUST-6670", "customer_lifetime_value": 3100.00, "order_history_count": 18,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.fedex.com/794644790455",
                     "delivery_signature_present": True, "delivery_signed_at": "Jul 01, 2026 03:10 PM",
                     "customer_ip_address": "66.87.120.55", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A6", "order_date": "Jun 26, 2026"},
        "tx_10010": {"customer_id": "CUST-8890", "customer_lifetime_value": 1450.00, "order_history_count": 9,
                     "shipping_status": "Delivered", "carrier_tracking_url": "https://track.ups.com/1Z999AA10345678901",
                     "delivery_signature_present": True, "delivery_signed_at": "Jul 05, 2026 01:50 PM",
                     "customer_ip_address": "74.125.68.100", "avs_cvv_match_status": "Pass",
                     "product_id": "PROD-A7", "order_date": "Jun 30, 2026"},
    }

    PRODUCTS_DB = {
        "PROD-A1": {"product_name": "Wireless Noise-Cancelling Headphones", "product_type": "Physical", "return_policy_days": 30},
        "PROD-A2": {"product_name": "Smart Watch Ultra Pro", "product_type": "Physical", "return_policy_days": 30},
        "PROD-A3": {"product_name": "LED Desk Lamp with USB Charger", "product_type": "Physical", "return_policy_days": 30},
        "PROD-A4": {"product_name": "65-inch 4K Smart TV", "product_type": "Physical", "return_policy_days": 15},
        "PROD-A5": {"product_name": "Espresso Machine Pro 3000", "product_type": "Physical", "return_policy_days": 30},
        "PROD-A6": {"product_name": "Electric Standing Desk Frame", "product_type": "Physical", "return_policy_days": 30},
        "PROD-A7": {"product_name": "Portable Bluetooth Speaker", "product_type": "Physical", "return_policy_days": 30},
        "PROD-B1": {"product_name": "Silicone Phone Case - Galaxy S24", "product_type": "Physical", "return_policy_days": 14},
        "PROD-B2": {"product_name": "Robot Vacuum Cleaner X500", "product_type": "Physical", "return_policy_days": 30},
        "PROD-B3": {"product_name": "15g Nail Glue Press-On Kit", "product_type": "Physical", "return_policy_days": 0},
    }

    # ── 10 raw processor cases (what Visa/MC network sends via Adyen/Stripe) ──

    PROCESSOR_CASES = [
        {"processor_case_id": "chg_10001", "chargeback_reason_code": "13.1", "reason_description": "Merchandise Not Received",
         "card_scheme": "Visa", "disputed_amount": 120.50, "currency": "USD", "transaction_id": "tx_10001"},
        {"processor_case_id": "chg_10002", "chargeback_reason_code": "13.1", "reason_description": "Merchandise Not Received",
         "card_scheme": "Mastercard", "disputed_amount": 245.00, "currency": "USD", "transaction_id": "tx_10002"},
        {"processor_case_id": "chg_10003", "chargeback_reason_code": "13.3", "reason_description": "Not as Described / Defective",
         "card_scheme": "Visa", "disputed_amount": 89.99, "currency": "USD", "transaction_id": "tx_10003"},
        {"processor_case_id": "chg_10004", "chargeback_reason_code": "10.4", "reason_description": "Fraud - Card Not Present",
         "card_scheme": "Visa", "disputed_amount": 156.30, "currency": "USD", "transaction_id": "tx_10004"},
        {"processor_case_id": "chg_10005", "chargeback_reason_code": "11.3", "reason_description": "No Authorization",
         "card_scheme": "Mastercard", "disputed_amount": 2150.00, "currency": "USD", "transaction_id": "tx_10005"},
        {"processor_case_id": "chg_10006", "chargeback_reason_code": "13.1", "reason_description": "Merchandise Not Received",
         "card_scheme": "Visa", "disputed_amount": 349.99, "currency": "USD", "transaction_id": "tx_10006"},
        {"processor_case_id": "chg_10007", "chargeback_reason_code": "13.6", "reason_description": "Credit Not Processed",
         "card_scheme": "Visa", "disputed_amount": 445.50, "currency": "USD", "transaction_id": "tx_10007"},
        {"processor_case_id": "chg_10008", "chargeback_reason_code": "10.4", "reason_description": "Fraud - Card Not Present",
         "card_scheme": "Mastercard", "disputed_amount": 34.50, "currency": "USD", "transaction_id": "tx_10008"},
        {"processor_case_id": "chg_10009", "chargeback_reason_code": "13.7", "reason_description": "Cancelled Merchandise/Services",
         "card_scheme": "Visa", "disputed_amount": 678.25, "currency": "USD", "transaction_id": "tx_10009"},
        {"processor_case_id": "chg_10010", "chargeback_reason_code": "12.5", "reason_description": "Incorrect Amount",
         "card_scheme": "Visa", "disputed_amount": 92.80, "currency": "USD", "transaction_id": "tx_10010"},
    ]

    @classmethod
    def triage(cls, processor_case, order, product):
        """Apply AI triage rules. Returns (queue, reason, score)."""
        rc = processor_case["chargeback_reason_code"]
        if rc == "13.1" and order["delivery_signature_present"]:
            return ("ai", f"Signed for at {order['delivery_signed_at']}", 92)
        if rc == "10.4" and order["avs_cvv_match_status"] == "Pass" and order["order_history_count"] >= 5:
            return ("ai", f"AVS/CVV Pass, repeat buyer ({order['order_history_count']} orders)", 85)
        if rc in ("13.7", "13.2") and order["delivery_signature_present"]:
            return ("ai", f"Delivered & signed, cancellation claim invalid", 88)
        if rc in ("12.5", "12.6.1") and order["avs_cvv_match_status"] == "Pass" and order["order_history_count"] >= 5:
            return ("ai", f"Transaction verified, repeat customer ({order['order_history_count']} orders)", 80)
        if rc == "13.3":
            return ("human", "Subjective claim - requires agent review of product description vs complaint", 40)
        if order["shipping_status"] in ("In Transit", "Not Shipped", "Pending"):
            return ("human", f"Shipping status: {order['shipping_status']} - no delivery proof available", 25)
        if rc in ("10.4", "11.3") and order["avs_cvv_match_status"] == "Fail":
            return ("human", f"AVS/CVV failed - weak authentication, high fraud risk", 15)
        if rc == "13.6":
            return ("human", "Credit/refund claim - agent must verify refund status in payment system", 45)
        return ("human", "Insufficient automated evidence for this case type", 35)

    @classmethod
    def get_demo_data(cls):
        cases = []
        for pc in cls.PROCESSOR_CASES:
            order = cls.ORDERS_DB[pc["transaction_id"]]
            product = cls.PRODUCTS_DB[order["product_id"]]
            queue, ai_reason, score = cls.triage(pc, order, product)
            cases.append({
                "processor": pc,
                "order": order,
                "product": product,
                "queue": queue,
                "ai_reason": ai_reason,
                "ai_score": score,
            })
        ai_count = sum(1 for c in cases if c["queue"] == "ai")
        human_count = sum(1 for c in cases if c["queue"] == "human")
        return {
            "cases": cases,
            "summary": {"total": len(cases), "ai": ai_count, "human": human_count},
        }

    # ── Helpers for full-pipeline mode ──

    @staticmethod
    def _map_fulfillment(status):
        mapping = {
            "Delivered": "Delivered",
            "Shipped": "In Transit",
            "Processing": "Not Shipped",
            "Cancelled": "Not Shipped",
            "Returned": "Delivered",
        }
        return mapping.get(status, "Not Shipped")

    @staticmethod
    def _make_tracking_url(order):
        tn = order.get("tracking_number", "")
        if not tn:
            return None
        carrier_urls = {
            "UPS": "https://track.ups.com/",
            "FedEx": "https://track.fedex.com/",
            "USPS": "https://tools.usps.com/",
            "Veho": "https://track.veho.com/",
            "DHL": "https://track.dhl.com/",
        }
        base = carrier_urls.get(order.get("shipping_carrier", ""), "https://track.unknown.com/")
        return base + tn

    @classmethod
    def get_full_demo_data(cls):
        """Load 1,000 orders + 12 chargebacks from CSV for full pipeline demo."""
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")

        # Load orders
        with open(os.path.join(static_dir, "orders_1000.csv"), "r", encoding="utf-8") as f:
            all_orders = list(_csv.DictReader(f))
        orders_by_id = {o["order_id"]: o for o in all_orders}

        # Per-customer aggregates
        cust_order_counts = Counter(o["customer_id"] for o in all_orders)
        cust_revenue = defaultdict(float)
        for o in all_orders:
            cust_revenue[o["customer_id"]] += float(o["order_amount"])

        # Load chargebacks
        with open(os.path.join(static_dir, "chargebacks_12.csv"), "r", encoding="utf-8") as f:
            chargebacks = list(_csv.DictReader(f))

        # Enrich and triage each chargeback
        cases = []
        for cb in chargebacks:
            raw = orders_by_id[cb["order_id"]]
            cid = raw["customer_id"]

            order = {
                "customer_id": cid,
                "customer_lifetime_value": round(cust_revenue[cid], 2),
                "order_history_count": cust_order_counts[cid],
                "shipping_status": cls._map_fulfillment(raw["fulfillment_status"]),
                "carrier_tracking_url": cls._make_tracking_url(raw),
                "delivery_signature_present": raw.get("delivery_signed") == "Yes",
                "delivery_signed_at": raw.get("delivery_date") if raw.get("delivery_signed") == "Yes" else None,
                "customer_ip_address": raw.get("customer_ip", ""),
                "avs_cvv_match_status": raw.get("avs_cvv_match", "Pass"),
                "product_id": raw["product_id"],
                "order_date": raw["order_date"],
            }
            product = {
                "product_name": raw["product_name"],
                "product_type": "Physical",
                "return_policy_days": int(raw.get("return_policy_days", 30)),
            }
            processor_case = {
                "processor_case_id": cb["dispute_ref"],
                "chargeback_reason_code": cb["reason_code"],
                "reason_description": cb["reason_description"],
                "card_scheme": cb["card_scheme"],
                "disputed_amount": float(cb["disputed_amount"]),
                "currency": "USD",
                "transaction_id": cb["order_id"],
            }
            queue, ai_reason, score = cls.triage(processor_case, order, product)
            cases.append({
                "processor": processor_case,
                "order": order,
                "product": product,
                "queue": queue,
                "ai_reason": ai_reason,
                "ai_score": score,
            })

        ai_count = sum(1 for c in cases if c["queue"] == "ai")
        human_count = sum(1 for c in cases if c["queue"] == "human")

        # Orders summary stats
        total_orders = len(all_orders)
        total_revenue = round(sum(float(o["order_amount"]) for o in all_orders), 2)

        status_breakdown = {}
        for o in all_orders:
            s = o["payment_status"]
            status_breakdown[s] = status_breakdown.get(s, 0) + 1

        fulfillment_breakdown = {}
        for o in all_orders:
            s = o["fulfillment_status"]
            fulfillment_breakdown[s] = fulfillment_breakdown.get(s, 0) + 1

        # Chargebacked order IDs + display orders (chargebacks first, then sample)
        chargeback_order_ids = {cb["order_id"] for cb in chargebacks}
        cb_orders = [o for o in all_orders if o["order_id"] in chargeback_order_ids]
        non_cb_orders = [o for o in all_orders if o["order_id"] not in chargeback_order_ids]
        display_orders = cb_orders + non_cb_orders[:38]  # 12 CB + 38 normal = 50 rows

        return {
            "cases": cases,
            "summary": {"total": len(cases), "ai": ai_count, "human": human_count},
            "orders_meta": {
                "total_orders": total_orders,
                "total_revenue": total_revenue,
                "chargeback_rate": f"{len(cases) / total_orders * 100:.2f}%",
                "status_breakdown": status_breakdown,
                "fulfillment_breakdown": fulfillment_breakdown,
                "display_orders": display_orders,
                "chargeback_order_ids": chargeback_order_ids,
            },
        }
