import json

from langchain_core.messages import HumanMessage, SystemMessage

from .extract import PROMPT as PROMPT_V1
from .extract_v2 import PROMPT as PROMPT_V2
from ..contracts import select_contract
from ..payloads import extraction_payload, extraction_payload_v2


def build_messages(text, resource, batch, policy, allowed_nodes):
    contract = select_contract(policy)
    prompt = contract.prompt
    payload = (extraction_payload_v2 if contract.is_v2 else extraction_payload)(
        text, resource, batch, policy, allowed_nodes)
    return [SystemMessage(content=prompt), HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
