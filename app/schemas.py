from pydantic import BaseModel

class QuickLogIn(BaseModel):
    link_id: int | None = None
    customer_name: str = ""
    link_name: str = ""
    circuit_id: str = ""
    device: str = ""
    symptom: str = ""
    status: str = "open"
    severity: str = "major"
    link_state: str = "down"
    typed_query: str = ""

class NoteIn(BaseModel):
    text: str = ""
    kind: str = "note"

class CloseIn(BaseModel):
    root_cause_category: str = ""
    root_cause_detail: str = ""
    fix: str = ""
    first_thing_to_check_next_time: str = ""

class StatusIn(BaseModel):
    status: str = "open"
    link_state: str = ""
    waiting_on: str = ""
