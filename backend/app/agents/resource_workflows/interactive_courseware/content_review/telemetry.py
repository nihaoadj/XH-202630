"""Hash-chain entries are append-only, including reconciliation events."""
from app.models.courseware.content_review import CallTicketV1, json_hash


def append_ticket(ledger, values):
    raw = {"schema_version": "1.0", **values, "prev_record_hash": ledger[-1]["record_hash"] if ledger else "0"*64}
    # Include defaults in the canonical record hash.
    ticket = CallTicketV1.model_validate({**raw, "record_hash": "0"*64})
    raw = ticket.model_dump(mode="json", exclude={"record_hash"})
    return [*ledger, {**raw, "record_hash": json_hash(raw)}]


def latest_tickets(ledger):
    return list({t["ticket_id"]: t for t in ledger}.values())
