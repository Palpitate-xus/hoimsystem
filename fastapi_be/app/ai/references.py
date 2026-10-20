"""Stable server-owned reference keys shared by inspection and execution."""

SOURCE_REFERENCE_KEYS = frozenset(
    {
        "record_id",
        "structured_record_id",
        "prescription_id",
        "lab_result_id",
        "imaging_report_id",
        "surgery_application_id",
        "surgery_schedule_id",
        "perioperative_id",
        "home_id",
        "inpatient_charge_id",
        "outpatient_charge_id",
        "adverse_event_id",
    }
)
