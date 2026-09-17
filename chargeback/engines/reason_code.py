"""Reason-code knowledge base, keyed by dispute family.

The keys are Visa-format because Visa's numbering is the only one that reads as
a hierarchy, not because Visa is privileged: each entry's `network_codes` names
what the *same dispute* is called on each network, and `NETWORK_CODE_INDEX`
below inverts that so a Mastercard or Amex or Discover case resolves to its own
family. Keep `network_codes` correct and resolution follows — there is no second
table to drift out of step with it.

`network_codes` values are bare codes. They used to be free text of three
different shapes ("4837 - No Cardholder Authorization" beside "4860" beside
"DP/4534 - Duplicate Processing"), which read badly in the badges that render
them as "Network: code" and made them useless to invert.
"""

REASON_CODES = {
    "10.3": {
        # The sheet files card-present fraud under 10.3; without this entry
        # those cases resolve nothing and fall back to a bare code.
        "title": "Other Fraud, Card-Present Environment",
        "network_codes": {
            "Visa": "10.3",
            "Mastercard": "4870",
            "Amex": "F31",
            "Discover": "UA01"
        },
        "definition": "This chargeback reason code is used when a cardholder disputes a transaction made in a card-present environment, claiming the card was not present at the point of sale or that the transaction was not authorized by them.",
        "scenarios": ["True Fraud", "Counterfeit Card", "Friendly Fraud (Chargeback Fraud)"],
        "merchant_challenge": "Prove the genuine card was present and the cardholder participated in the transaction — chip read, PIN entry or signature at the terminal.",
        "defense_goals": [
            "The card was read at the terminal and the transaction was authorized",
            "The cardholder was present and participated in the purchase",
            "The chargeback is invalid due to friendly fraud",
            "A refund was already issued for the disputed amount"
        ],
        "supporting_docs_general": [
            {"category": "Proof of Card Presence", "evidences": ["Terminal receipt showing chip read or PIN entry", "Signed sales receipt", "EMV transaction log"]},
            {"category": "Proof of Delivery and Service", "evidences": ["Collection or pickup confirmation", "Proof of usage"]},
            {"category": "Transaction and Account History", "evidences": ["Purchase history", "Prior undisputed transactions on the same card"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "10.4": {
        "title": "Other Fraud, Card-Absent Environment",
        "network_codes": {
            "Visa": "10.4",
            "Mastercard": "4837",
            "Amex": "F29",
            "Discover": "UA02"
        },
        "definition": "This chargeback reason code is used when a cardholder disputes a transaction conducted in a card-not-present (CNP) environment, claiming they did not authorize or participate in the transaction.",
        "scenarios": ["True Fraud", "Friendly Fraud (Chargeback Fraud)"],
        "merchant_challenge": "Prove the transaction was legitimate and the cardholder made the purchase or is responsible for it. Particularly difficult in card-absent environments.",
        "defense_goals": [
            "The transaction was genuinely authorized by the cardholder",
            "The cardholder received the goods or services",
            "The chargeback is invalid due to friendly fraud",
            "A refund was already issued for the disputed amount"
        ],
        "supporting_docs_general": [
            {"category": "Proof of Cardholder Authentication", "evidences": ["AVS match and CVV2 match", "Visa Secure / 3-D Secure authentication"]},
            {"category": "Proof of Delivery and Service", "evidences": ["Shipping and delivery confirmation", "Proof of usage", "Travel and entertainment (T&E)"]},
            {"category": "Transaction and Account History", "evidences": ["Matching IP addresses", "Consistent account details", "Purchase history", "Account log-in details"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Transaction History", "Service Usage", "Proof of consent signed documents"]}
        ],
        "supporting_docs_platform": [
            {"category": "Proof of Cardholder Authentication", "evidences": ["Visa Secure / 3-D Secure authentication"]},
            {"category": "Proof of Delivery and Service", "evidences": ["Shipping and delivery confirmation", "Proof of usage"]},
            {"category": "Transaction and Account History", "evidences": ["Matching IP addresses and Geo Location", "Consistent account details", "Account History, Binding History and Purchase history", "Account log-in details", "Undisputed transactions"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Subscription"]}
        ],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "11.3": {
        "title": "No Authorization",
        "network_codes": {
            # Was Mastercard "NA" and Discover "UA06". NA is Discover's code,
            # not Mastercard's, and UA06 is a chip-and-PIN *fraud* code, not an
            # authorization one.
            "Visa": "11.3",
            "Mastercard": "4808",
            "Amex": "A02",
            "Discover": "NA"
        },
        "definition": "This chargeback reason code is filed when a transaction is processed without a valid authorization. Obtaining authorization from the card issuer is a fundamental step in the payment process.",
        "scenarios": ["True Fraud", "Friendly Fraud (Chargeback Fraud)", "Merchant Error"],
        "merchant_challenge": "Prove that the card issuer's claim of 'no authorization' is false. Show that a valid authorization was indeed obtained.",
        "defense_goals": [
            "The transaction was genuinely authorized by the cardholder",
            "The cardholder received the goods or services",
            "A refund was already issued for the disputed amount",
            "Written communication where cardholder explicitly states they no longer wish to dispute"
        ],
        "supporting_docs_general": [
            {"category": "Proof of Valid Authorization", "evidences": ["AVS match and CVV match", "Proof of Auth - Success & Failure", "Visa Secure / 3-D Secure authentication"]},
            {"category": "Proof of Delivery and Service", "evidences": ["Shipping and delivery confirmation", "Proof of usage", "Travel and entertainment (T&E)"]},
            {"category": "Transaction and Account History", "evidences": ["Matching IP addresses", "Consistent account details", "Purchase history", "Account log-in details"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Transaction History", "Service Usage", "Proof of consent signed documents"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "12.5": {
        "title": "Incorrect Amount",
        "network_codes": {
            # Amex and Discover were straightforwardly swapped: AW is
            # Discover's altered-amount code and P05 is Amex's.
            "Visa": "12.5",
            "Mastercard": "4831",
            "Amex": "P05",
            "Discover": "AW"
        },
        "definition": "The cardholder claims the amount charged is different from the amount they expected or agreed to pay. The discrepancy can be a clerical error, calculation mistake, or unauthorized change.",
        "scenarios": ["Merchant Error", "Data Entry Error", "Calculation Error", "Unauthorized Adjustments", "Friendly Fraud"],
        "merchant_challenge": "Provide compelling evidence that proves the amount charged was correct and the cardholder consented to it.",
        "defense_goals": [
            "The transaction matches the agreed amount",
            "The cardholder received the goods or services",
            "A refund was already issued for the disputed amount",
            "The burden of proof is on the merchant"
        ],
        "supporting_docs_general": [
            {"category": "Transaction and Account History", "evidences": ["Consistent account details", "Purchase history", "Account log-in details", "Signed Sales Receipt", "Proof of Refund"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Transaction History", "Service Usage", "Proof of consent signed documents"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "12.6.1": {
        "title": "Duplicate Processing",
        "network_codes": {
            # DP is Discover's duplicate code and 4834 is Mastercard's; the two
            # were on each other's rows.
            "Visa": "12.6.1",
            "Mastercard": "4834",
            "Amex": "P08",
            "Discover": "DP"
        },
        "definition": "The cardholder claims they were charged more than once for the same transaction due to a merchant system error or manual error submitting the transaction multiple times.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove the two charges were not duplicates but for two separate, distinct transactions with valid and separate purchases.",
        "defense_goals": [
            "The transaction matches the agreed amount",
            "The cardholder received the goods or services",
            "A refund was already issued for the disputed amount",
            "The burden of proof is on the merchant"
        ],
        "supporting_docs_general": [
            {"category": "Transaction and Account History", "evidences": ["Consistent account details", "Purchase history", "Account log-in details", "Signed Sales Receipt", "Proof of Refund"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Transaction History", "Service Usage", "Proof of consent signed documents"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "12.6.2": {
        "title": "Paid by Other Means",
        "network_codes": {
            # Discover's value was a Mastercard number, then briefly P07 —
            # which is Amex's late-submission code. Discover publishes PM.
            "Visa": "12.6.2",
            "Mastercard": "4834",
            "Amex": "C14",
            "Discover": "PM"
        },
        "definition": "The cardholder claims they paid for goods/services using an alternative payment method (cash, check, another card, store credit) and were charged on their card in error.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove the credit card was the only form of payment used for the transaction.",
        "defense_goals": [
            "The transaction matches the agreed amount",
            "The cardholder received the goods or services",
            "A refund was already issued for the disputed amount",
            "The burden of proof is on the merchant"
        ],
        "supporting_docs_general": [
            {"category": "Transaction and Account History", "evidences": ["Consistent account details", "Purchase history", "Account log-in details", "Signed Sales Receipt", "Proof of Refund"]},
            {"category": "Merchant-Cardholder Communications", "evidences": ["Copies of all correspondence (emails, chat logs, phone records)"]},
            {"category": "For Recurring Transactions", "evidences": ["Transaction History", "Service Usage", "Proof of consent signed documents"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "13.1": {
        "title": "Merchandise/Service Not Received",
        "network_codes": {
            # 4853 is Mastercard's umbrella cardholder-dispute code; 4855 is the
            # specific goods-not-provided one, which is what the sheet uses.
            # Discover was blank and is RG.
            "Visa": "13.1",
            "Mastercard": "4855",
            "Amex": "C08",
            "Discover": "RG"
        },
        "definition": "The cardholder is disputing a transaction by claiming they never received the merchandise or services they purchased.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Provide compelling evidence of delivery including tracking, signed receipts, photos, transaction records, customer communication, and for services, proof of rendering.",
        "defense_goals": [
            "Proof of Delivery: shipping carrier tracking, signature confirmation, AVS-matched delivery address",
            "Proof of Service: redeemed coupons, confirmation emails, login records",
            "Communication with the Cardholder showing acknowledgment",
            "Proof of a Refund if already issued",
            "Evidence of undisputed purchases from the same device/card"
        ],
        "supporting_docs_general": [
            {"category": "Tracking and Delivery", "evidences": ["Tracking numbers showing delivery date, time, correct address", "Signature confirmation for high-value items", "Customer address matches transaction address"]},
            {"category": "Service Confirmation", "evidences": ["Signed work orders / service reports / contracts", "Usage logs or records (login history, activity)", "Event ticket scanning or redemption records"]},
            {"category": "Correspondence", "evidences": ["Emails, chat logs, communications acknowledging receipt or delays"]},
            {"category": "Transaction Details", "evidences": ["Original receipt with date, amount, item/service description"]},
            {"category": "Terms and Conditions", "evidences": ["Proof customer agreed to terms of service or return policy"]}
        ],
        "supporting_docs_platform": [
            {"category": "Tracking and Delivery", "evidences": ["Marketplace shipping tracking with carrier confirmation", "Delivery photos from carrier"]},
            {"category": "Account Evidence", "evidences": ["Account activity showing order was placed by account holder", "IP address and geolocation matching", "Undisputed transactions from same account"]},
            {"category": "Communications", "evidences": ["In-app messages or customer service chat logs"]}
        ],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "13.2": {
        "title": "Cancelled Recurring Transaction",
        "network_codes": {
            # 4841 is Mastercard's cancelled-recurring code; 4853 was the
            # umbrella again. Discover was blank and is AP.
            "Visa": "13.2",
            "Mastercard": "4841",
            "Amex": "C28",
            "Discover": "AP"
        },
        "definition": "The cardholder disputes a recurring transaction, claiming the merchant processed the payment after they had already requested to cancel the service, subscription, or recurring billing agreement.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove the subscription was active, the cancellation policy was followed, and/or the service was used after the charge.",
        "defense_goals": [
            "Proof of Active Subscription showing it was active at time of charge",
            "Cancellation Policy showing the charge aligns with its terms",
            "Proof of Service Usage after the charge",
            "Proof of a Refund if one was processed"
        ],
        "supporting_docs_general": [
            {"category": "Subscription Evidence", "evidences": ["Original recurring billing agreement", "Cancellation policy with required notice period", "Customer account logs proving cancellation after billing date"]},
            {"category": "Usage Proof", "evidences": ["Proof of continued service use after the charge", "Login records, activity logs"]},
            {"category": "Refund Evidence", "evidences": ["Payment processor records of refund (date, amount, ID)", "Customer communication confirming refund"]},
            {"category": "Transaction Documentation", "evidences": ["Transaction receipt/invoice", "Terms and conditions"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "13.3": {
        "title": "Not as Described or Defective Merchandise/Services",
        "network_codes": {
            # The worst of them: C31 is an Amex code and was filed under
            # Mastercard, RM is a Discover code and was filed under Amex, and
            # Discover — whose code it actually is — was left blank.
            "Visa": "13.3",
            "Mastercard": "4853",
            "Amex": "C31",
            "Discover": "RM"
        },
        "definition": "The cardholder claims goods/services received did not match the description, were damaged or defective, or were of lower quality than expected.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove quality and disprove defect claims. These are subjective chargebacks requiring extensive evidence beyond delivery proof.",
        "defense_goals": [
            "Prove product quality with pre-shipping documentation",
            "Show accurate product description matched what was delivered",
            "Provide evidence of friendly fraud (continued use after claimed issue)",
            "Show refund/replacement was already offered"
        ],
        "supporting_docs_general": [
            {"category": "Product Description Proof", "evidences": ["Screenshots of product page", "Original sales invoice", "Terms and conditions the cardholder agreed to"]},
            {"category": "Delivery/Service Proof", "evidences": ["Shipping carrier tracking information", "Usage logs, timestamps, signed contracts"]},
            {"category": "Customer Communication", "evidences": ["All emails, chat transcripts showing cardholder accepted item", "Records showing cardholder didn't follow return policy", "Attempted resolution correspondence"]},
            {"category": "Refund/Replacement Evidence", "evidences": ["Payment processor documentation of refund", "New tracking details for replacement item"]},
            {"category": "Friendly Fraud Evidence", "evidences": ["Past undisputed transactions from same cardholder", "Usage logs showing continued use after claimed issue"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "13.6": {
        "title": "Credit Not Processed",
        "network_codes": {
            "Visa": "13.6",
            "Mastercard": "4860",
            "Amex": "C02",
            "Discover": "RN2"
        },
        "definition": "The cardholder claims the merchant promised them a refund or credit but failed to process it.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove the refund was already issued, or that the customer is not eligible for a refund per the return/cancellation policy.",
        "defense_goals": [
            "Proof of Credit already issued (date, amount, transaction ID)",
            "Customer Communication confirming the credit was processed",
            "Return/Cancellation Policy showing conditions for refund",
            "Proof of Policy Acknowledgment at time of purchase"
        ],
        "supporting_docs_general": [
            {"category": "Proof of Credit", "evidences": ["Payment processor record showing refund date, amount, transaction ID", "Customer communication confirming credit was processed", "Timestamp showing credit processed before chargeback date"]},
            {"category": "Policy Documentation", "evidences": ["Return/Cancellation policy with refund conditions", "Proof customer agreed to policy at purchase (checkout page screenshot)"]},
            {"category": "Communication Records", "evidences": ["Correspondence explaining why customer was not eligible for refund"]},
            {"category": "Void Documentation", "evidences": ["POS/payment processor documentation of voided transaction", "Transaction logs from original transaction to void"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    },
    "13.7": {
        "title": "Cancelled Merchandise/Services",
        "network_codes": {
            # Mastercard's cancelled-merchandise code is 4860, not the 4853
            # umbrella. Discover was blank and is RG.
            "Visa": "13.7",
            "Mastercard": "4860",
            "Amex": "C05",
            "Discover": "RG"
        },
        "definition": "The cardholder claims to have returned merchandise or canceled a service, but the merchant has not issued the promised credit or refund.",
        "scenarios": ["Merchant Error", "Friendly Fraud"],
        "merchant_challenge": "Prove that the customer is not entitled to a refund, or that a refund was already issued.",
        "defense_goals": [
            "Payment processor documentation showing refund was successful",
            "Customer communication confirming refund",
            "Cancellation/return policy outlining refund conditions",
            "Proof customer was aware of and agreed to policy"
        ],
        "supporting_docs_general": [
            {"category": "Return/Cancellation Policy", "evidences": ["Copy of mutually agreed-upon return/cancellation policy"]},
            {"category": "Proof of Refund", "evidences": ["Payment processor documentation with date, amount, transaction ID"]},
            {"category": "Shipping/Tracking", "evidences": ["Tracking showing no return delivery received", "Record showing no return shipment was initiated"]},
            {"category": "Communication with Cardholder", "evidences": ["Explanation of policy", "Attempts to resolve issue directly", "Cardholder acknowledgment of policy non-compliance"]},
            {"category": "Proof of Use", "evidences": ["Logs showing continued use after claimed cancellation"]},
            {"category": "Resolution Confirmation", "evidences": ["Signed letter or email from cardholder confirming dispute withdrawal"]}
        ],
        "supporting_docs_platform": [],
        "portals": ["Merchant processor portal", "CRM", "Payment Gateway", "Shipment portals"]
    }
}

# ─── The published catalog ────────────────────────────────────────────────────
#
# Every reason code each network publishes, as (category, description). This is
# what the UI shows beside a bare number — "4837" means nothing to anyone who
# does not work chargebacks daily, and it appeared bare in twenty places.
#
# It is also the authority for REASON_CODES above. `_build_network_index` checks
# every (network, code) pair in every family against this table and raises at
# import if one is not published by that network. That check exists because a
# real error got through without it: family 12.6.2 carried Discover "P07", and
# P07 is an Amex code — Discover's "paid by other means" is PM.
#
# Networks are keyed lowercase; the sheet spells them VISA / Mastercard / Amex /
# Discover, and `card_type.title()` only normalises the all-caps one.
NETWORK_REASON_CODES = {
    "visa": {
        "10.1": ("Fraud", "EMV Liability Shift Counterfeit Fraud"),
        "10.2": ("Fraud", "EMV Liability Shift Non-Counterfeit Fraud"),
        "10.3": ("Fraud", "Other Fraud - Card Present Environment"),
        "10.4": ("Fraud", "Other Fraud - Card Absent Environment"),
        "10.5": ("Fraud", "Visa Fraud Monitoring Program"),
        "11.1": ("Authorization", "Card Recovery Bulletin or Exception File"),
        "11.2": ("Authorization", "Declined Authorization"),
        "11.3": ("Authorization", "No Authorization"),
        "12.1": ("Processing Error", "Late Presentment"),
        "12.2": ("Processing Error", "Incorrect Transaction Code"),
        "12.3": ("Processing Error", "Incorrect Currency"),
        "12.4": ("Processing Error", "Incorrect Transaction Account Number"),
        "12.5": ("Processing Error", "Incorrect Transaction Amount"),
        # Visa publishes 12.6 as one code; the app splits it the way the
        # dispute is actually worked, so all three spellings resolve.
        "12.6": ("Processing Error", "Duplicate Processing or Paid by Other Means"),
        "12.6.1": ("Processing Error", "Duplicate Processing"),
        "12.6.2": ("Processing Error", "Paid by Other Means"),
        "12.7": ("Processing Error", "Invalid Data"),
        "13.1": ("Consumer Dispute", "Services Not Provided or Merchandise Not Received"),
        "13.2": ("Consumer Dispute", "Cancelled Recurring Transaction"),
        "13.3": ("Consumer Dispute", "Not as Described or Defective Merchandise/Services"),
        "13.4": ("Consumer Dispute", "Counterfeit Merchandise"),
        "13.5": ("Consumer Dispute", "Misrepresentation of the purchased good and/or service"),
        "13.6": ("Consumer Dispute", "Credit Not Processed"),
        "13.7": ("Consumer Dispute", "Cancelled Merchandise/Services"),
        "13.8": ("Consumer Dispute", "Original Credit Transaction Not Accepted"),
        "13.9": ("Consumer Dispute", "Non-Receipt of Cash or Load Transaction Value at ATM"),
        "RETRIEVAL": ("Query", "Retrieval Request"),
    },
    "mastercard": {
        "4837": ("Fraud", "No Cardholder Authorization"),
        "4840": ("Fraud", "Fraudulent Processing of Transactions"),
        "4849": ("Fraud", "Questionable Merchant Activity"),
        "4863": ("Fraud", "Cardholder Does Not Recognize - Potential Fraud"),
        "4870": ("Fraud", "Chip Liability Shift"),
        "4871": ("Fraud", "Chip/PIN Liability Shift"),
        "4807": ("Authorization", "Warning Bulletin File"),
        "4808": ("Authorization", "Authorization-Related Chargeback"),
        "4812": ("Authorization", "Account Number Not On File"),
        "4834": ("Processing Error", "Point-of-Interaction Error"),
        "4831": ("Processing Error", "Transaction Amount Differs"),
        "4842": ("Processing Error", "Late Presentment"),
        "4846": ("Processing Error", "Correct Transaction Currency Code Not Provided"),
        "4850": ("Processing Error", "Installment Billing Dispute"),
        "4999": ("Processing Error", "Domestic Chargeback Dispute (Europe Region Only)"),
        "4853": ("Consumer Dispute", "Cardholder Dispute"),
        "4841": ("Consumer Dispute", "Canceled Recurring or Digital Goods Transactions"),
        "4854": ("Consumer Dispute", "Cardholder Dispute - Not Elsewhere Classified (U.S. Region Only)"),
        "4855": ("Consumer Dispute", "Goods or Services Not Provided"),
        "4859": ("Consumer Dispute", "Addendum, No-show, or ATM Dispute"),
        "4860": ("Consumer Dispute", "Credit Not Processed"),
        "RETRIEVAL": ("Query", "Retrieval Request"),
    },
    "discover": {
        "UA01": ("Fraud", "Fraud - Card Present Transaction"),
        "UA02": ("Fraud", "Fraud - Card Not Present Transaction"),
        "UA05": ("Fraud", "Fraud - Chip Counterfeit Transaction"),
        "UA06": ("Fraud", "Fraud - Chip and PIN Transaction"),
        "UA10": ("Fraud", "Request Transaction Receipt (swiped card transactions)"),
        "UA11": ("Fraud", "Cardholder Claims Fraud (swiped transaction, no signature)"),
        "NA": ("Authorization", "No Authorization"),
        "DA": ("Authorization", "Declined Authorization"),
        "AT": ("Authorization", "Authorization Non-Compliance"),
        "EX": ("Authorization", "Expired Card"),
        "IN": ("Processing Error", "Invalid Card Number"),
        "LP": ("Processing Error", "Late Presentment"),
        "5": ("Consumer Dispute", "Good Faith Investigation"),
        "AA": ("Consumer Dispute", "Does Not Recognize"),
        "AP": ("Consumer Dispute", "Recurring Payments"),
        "AW": ("Consumer Dispute", "Altered Amount"),
        "CD": ("Consumer Dispute", "Credit/Debit Posted Incorrectly"),
        "DP": ("Consumer Dispute", "Duplicate Processing"),
        "IC": ("Consumer Dispute", "Illegible Sales Data"),
        "NF": ("Consumer Dispute", "Non-Receipt of Cash from ATM"),
        "PM": ("Consumer Dispute", "Paid by Other Means"),
        "RG": ("Consumer Dispute", "Non-Receipt of Goods, Services, or Cash"),
        "RM": ("Consumer Dispute", "Cardholder Disputes Quality of Goods or Services"),
        "RN2": ("Consumer Dispute", "Credit Not Processed"),
        "DC": ("Consumer Dispute", "Dispute Compliance"),
        "NC": ("Not Classified", "Not Classified"),
        "RETRIEVAL": ("Query", "Retrieval Request"),
    },
    "amex": {
        "A01": ("Authorization", "Charge Amount Exceeds Authorization Amount"),
        "A02": ("Authorization", "No Valid Authorization"),
        "A08": ("Authorization", "Authorization Approval Expired"),
        "C02": ("Consumer Dispute", "Credit Not Processed"),
        "C04": ("Consumer Dispute", "Goods/Services Returned or Refused"),
        "C05": ("Consumer Dispute", "Goods/Services Canceled"),
        "C08": ("Consumer Dispute", "Goods/Services Not Received or Only Partially Received"),
        "C14": ("Consumer Dispute", "Paid by Other Means"),
        "C18": ("Consumer Dispute", '"No Show" or CARDeposit Canceled'),
        "C28": ("Consumer Dispute", "Canceled Recurring Billing"),
        "C31": ("Consumer Dispute", "Goods/Services Not As Described"),
        "C32": ("Consumer Dispute", "Goods/Services Damaged or Defective"),
        "F10": ("Fraud", "Missing Imprint"),
        "F14": ("Fraud", "Missing Signature"),
        "F24": ("Fraud", "No Card Member Authorization"),
        "F29": ("Fraud", "Card Not Present"),
        "F30": ("Fraud", "EMV Counterfeit"),
        "F31": ("Fraud", "EMV Lost/Stolen/Non-Received"),
        "FR2": ("Fraud", "Fraud Full Recourse Program"),
        "FR4": ("Fraud", "Immediate Chargeback Program"),
        "FR6": ("Fraud", "Partial Immediate Chargeback Program"),
        "M01": ("Inquiry", "Chargeback Authorization"),
        "M10": ("Inquiry", "Vehicle Rental - Capital Damages"),
        "M49": ("Inquiry", "Vehicle Rental - Theft or Loss of Use"),
        "P01": ("Processing Error", "Unassigned Card Number"),
        "P03": ("Processing Error", "Credit Processed as Charge"),
        "P04": ("Processing Error", "Charge Processed as Credit"),
        "P05": ("Processing Error", "Incorrect Charge Amount"),
        "98": ("Processing Error", "Pre-compliance Chargeback"),
        "P07": ("Processing Error", "Late Submission"),
        "P08": ("Processing Error", "Duplicate Charge"),
        "P22": ("Processing Error", "Non-Matching Card Number"),
        "P23": ("Processing Error", "Currency Discrepancy"),
        "R03": ("Inquiry", "Insufficient Reply"),
        "R13": ("Inquiry", "No Reply"),
        "RETRIEVAL": ("Query", "Retrieval Request"),
    },
}


# ─── Network code → dispute family ────────────────────────────────────────────
#
# Built from `network_codes` above rather than hand-written, so correcting a
# badge corrects resolution in the same edit and the two cannot disagree.
#
# Codes a family does not own outright but that belong to it. Amex splits the
# cancelled-merchandise family across two codes, and the sheet uses C04.
SECONDARY_CODES = {
    ("Amex", "C04"): "13.7",
    # "Credit Processed as Charge" has no exact Visa twin. 12.5 is the closest
    # honest home — it is the amount-dispute family, and its evidence packet
    # (amount audit trail, settlement references, proof of refund) is the right
    # one to build. The case still displays its own P03 and its own ReasonMsg.
    ("Amex", "P03"): "12.5",
}

# Where one code legitimately belongs to more than one family, the family that
# owns it for a bare (network-less) lookup. Stated rather than left to dict
# ordering, so a reordering of REASON_CODES cannot silently repoint a code.
PRIMARY_FAMILY = {
    "4834": "12.6.1",   # also 12.6.2 (paid by other means)
    "4860": "13.6",     # also 13.7 (cancelled merchandise)
    "RG": "13.1",       # also 13.7
}


def _build_network_index():
    """(network, code) → family id, plus a bare code → family id fallback.

    Also checks every curated pair against NETWORK_REASON_CODES. Without that
    check, filing a code under a network that does not publish it is invisible:
    12.6.2 carried Discover "P07" for a while, and P07 is Amex's late-submission
    code — Discover's "paid by other means" is PM. Nothing caught it until the
    published catalog was there to check against.
    """
    by_pair, by_code, seen = {}, {}, {}
    for family, entry in REASON_CODES.items():
        for network, code in (entry.get("network_codes") or {}).items():
            code = (code or "").strip()
            if not code:
                continue
            published = NETWORK_REASON_CODES.get(network.lower(), {})
            if code.upper() not in {k.upper() for k in published}:
                raise AssertionError(
                    "family %s files %r under %s, which does not publish it — "
                    "check NETWORK_REASON_CODES" % (family, code, network))
            by_pair.setdefault((network.lower(), code.upper()), family)
            seen.setdefault(code.upper(), set()).add(family)
    for (network, code), family in SECONDARY_CODES.items():
        by_pair[(network.lower(), code.upper())] = family
        seen.setdefault(code.upper(), set()).add(family)
    for code, families in seen.items():
        if len(families) == 1:
            by_code[code] = next(iter(families))
        elif code in PRIMARY_FAMILY:
            by_code[code] = PRIMARY_FAMILY[code]
        else:
            raise AssertionError(
                "reason code %r maps to %s — add it to PRIMARY_FAMILY"
                % (code, sorted(families)))
    return by_pair, by_code


NETWORK_CODE_INDEX, BARE_CODE_INDEX = _build_network_index()

# The internal bucket each family belongs to. Derived from the family rather
# than string-matched against the sheet's category label, so rewording a label
# upstream cannot silently reroute a case to the generic evidence bundle. The
# app's buckets predate the sheet's four-category vocabulary and are the keys
# AgentDesk.EVIDENCE_BUNDLES and the /add-case category map are written against.
FAMILY_BUCKETS = {
    "10.3": "fraud",
    "10.4": "fraud",
    "11.3": "authorization",
    "12.5": "processing",
    "12.6.1": "processing",
    "12.6.2": "processing",
    "13.1": "merchandise",
    "13.2": "merchandise",
    "13.3": "merchandise",
    "13.6": "processing",
    "13.7": "merchandise",
}


# ─── Scenario to Reason Code Mapping ──────────────────────────────────────────
SCENARIO_CATEGORIES = {
    "Fraud - Card Not Present (CNP)": {"reason_code": "10.4", "chargeback_category": "Fraud - CNP"},
    "Fraud - No Authorization": {"reason_code": "11.3", "chargeback_category": "Fraud - No Auth"},
    "Fraud - Merchant Liability (No 3DS)": {"reason_code": "10.4", "chargeback_category": "Fraud - Merchant Liable"},
    "Merchandise - Item Not Received": {"reason_code": "13.1", "chargeback_category": "Merchandise - Not Received"},
    "Merchandise - Item Defective": {"reason_code": "13.3", "chargeback_category": "Merchandise - Defective Item"},
    "Merchandise - Not as Described": {"reason_code": "13.3", "chargeback_category": "Merchandise - Not as Described"},
    "Processing - Duplicate Charge": {"reason_code": "12.6.1", "chargeback_category": "Processing - Duplicate"},
    "Processing - Incorrect Amount": {"reason_code": "12.5", "chargeback_category": "Processing - Incorrect Amount"},
    "Processing - Paid by Other Means": {"reason_code": "12.6.2", "chargeback_category": "Processing - Paid Other Means"},
    "Subscription - Cancelled Recurring": {"reason_code": "13.2", "chargeback_category": "Subscription - Cancelled"},
    "Refund - Credit Not Processed": {"reason_code": "13.6", "chargeback_category": "Refund - Credit Not Processed"},
    "Refund - Cancelled Merchandise": {"reason_code": "13.7", "chargeback_category": "Refund - Cancelled Merch"},
}


class ReasonCodeInterpreter:
    """Maps chargeback reason codes to defense strategies,
    network codes, and scenario categories."""

    @classmethod
    def resolve(cls, reason_code, network=""):
        """Map any network's code to its dispute family.

        Returns (family_id, entry). Both are empty/`{}` when the code belongs to
        no family — callers must not assume a hit. The network is consulted
        first because a bare code can be ambiguous across networks; without one
        we fall back to the unambiguous bare index.
        """
        code = (reason_code or "").strip()
        if not code:
            return "", {}
        if code in REASON_CODES:
            return code, REASON_CODES[code]
        key = code.upper()
        family = NETWORK_CODE_INDEX.get(((network or "").strip().lower(), key))
        if not family:
            family = BARE_CODE_INDEX.get(key, "")
        return (family, REASON_CODES[family]) if family else ("", {})

    @classmethod
    def describe(cls, reason_code, network=""):
        """The network's own description for a code, for display beside it.

        Precedence mirrors `resolve`: the network's published entry, then an
        unambiguous match on any network, then the dispute family's title.
        Returns "" rather than guessing when the code is unknown — callers
        render the bare code in that case rather than a dangling separator.
        """
        code = (reason_code or "").strip()
        if not code:
            return ""
        key = code.upper()
        published = NETWORK_REASON_CODES.get((network or "").strip().lower())
        if published:
            for name, (_cat, desc) in published.items():
                if name.upper() == key:
                    return desc
        # No network given, or the code is not that network's. Accept a match
        # only where exactly one network publishes it, so an ambiguous code
        # never gets another network's meaning attached to it.
        hits = {desc for table in NETWORK_REASON_CODES.values()
                for name, (_cat, desc) in table.items() if name.upper() == key}
        if len(hits) == 1:
            return next(iter(hits))
        return (cls.resolve(code, network)[1] or {}).get("title", "")

    @classmethod
    def category_of(cls, reason_code, network=""):
        """The network's own category for a code: Fraud, Consumer Dispute, …"""
        key = (reason_code or "").strip().upper()
        published = NETWORK_REASON_CODES.get((network or "").strip().lower(), {})
        for name, (cat, _desc) in published.items():
            if name.upper() == key:
                return cat
        return ""

    @classmethod
    def bucket(cls, reason_code, network=""):
        """Internal evidence bucket for a code: fraud/authorization/…"""
        family, _ = cls.resolve(reason_code, network)
        return FAMILY_BUCKETS.get(family, "")

    @classmethod
    def interpret(cls, reason_code, network=""):
        """Look up a reason code and return its full defense strategy."""
        return cls.resolve(reason_code, network)[1]

    @classmethod
    def get_scenario_info(cls, scenario_name):
        """Map a scenario name to its reason code and category."""
        return SCENARIO_CATEGORIES.get(scenario_name, {})

    @classmethod
    def get_all_codes(cls):
        """Return the full reason code knowledge base."""
        return REASON_CODES


class ReasonCodeRulebook:
    """Rule set defining mandatory evidence by reason code."""

    RULES = {
        "10.4": [
            "Gateway receipt with auth code, AVS, CVV, 3DS, transaction ID",
            "CRM order confirmation and customer contact trace",
            "IP address and prior undisputed transaction evidence",
            "Terms and conditions acceptance snapshot",
        ],
        "11.3": [
            "Gateway authorization logs and transaction copy",
            "AVS/CVV/3DS verification evidence",
            "CRM order confirmation and communication proof",
            "Policy documents and checkout consent record",
        ],
        "12.5": [
            "Transaction amount audit trail",
            "Gateway capture/settlement references",
            "Customer communication and invoice details",
            "Policy disclosure and checkout snapshot",
        ],
        "12.6.1": [
            "Duplicate transaction comparison report",
            "Gateway auth/capture timestamps",
            "CRM communications clarifying purchase intent",
            "Refund or correction policy evidence",
        ],
        "12.6.2": [
            "Alternative payment verification records",
            "Gateway transaction copy and authorization proof",
            "CRM order and communication records",
            "Terms and refund policy artifacts",
        ],
        "13.1": [
            "Proof of delivery with tracking outcome",
            "CRM order confirmation and dispatch timeline",
            "Gateway receipt and IP/device evidence",
            "Terms and return policy documents",
        ],
        "13.2": [
            "Subscription lifecycle and cancellation logs",
            "Gateway recurring billing authorization proof",
            "Customer communication records",
            "Cancellation policy documentation",
        ],
        "13.3": [
            "Product description and fulfillment evidence",
            "CRM correspondence for dispute handling",
            "Gateway transaction and auth snapshot",
            "Return policy and checkout terms",
        ],
        "13.6": [
            "Refund/credit processing evidence",
            "CRM communication confirming credit status",
            "Gateway refund/void timeline",
            "Refund policy with customer acknowledgment",
        ],
        "13.7": [
            "Return cancellation eligibility records",
            "POD or non-return tracking evidence",
            "Gateway refund activity and transaction copy",
            "Terms and refund policy repository docs",
        ],
    }

    DEFAULT_RULE = [
        "Gateway transaction evidence and auth details",
        "CRM order confirmation data",
        "Fulfillment/POD tracking details",
        "Policy and terms repository documents",
    ]

    NETWORKS = ["Visa", "Mastercard", "Discover", "Diners Club", "Amex"]

    @classmethod
    def required_evidence(cls, reason_code):
        return cls.RULES.get(reason_code, cls.DEFAULT_RULE)

    @classmethod
    def network_reason_matrix(cls, reason_code):
        reason = REASON_CODES.get(reason_code, {})
        codes = reason.get("network_codes", {})
        discover_code = codes.get("Discover", "") or "Refer Discover bulletin"
        return {
            "Visa": codes.get("Visa", "Refer Visa core rules"),
            "Mastercard": codes.get("Mastercard", "Refer Mastercard chargeback guide"),
            "Discover": discover_code,
            "Diners Club": codes.get("Diners Club", discover_code),
            "Amex": codes.get("Amex", "Refer American Express reason guide"),
        }
