import json
from urllib.parse import parse_qs
from typing import Tuple, Optional

def parse_graphql_request(request_body: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a GraphQL request body and extract operation name, doc ID, and variables.
    Supports Facebook's URL-encoded format and standard JSON format.
    
    Returns:
        (operation_name, doc_id, variables)
    """
    operation_name = None
    doc_id = None
    variables = None
    
    if not request_body:
        return None, None, None

    try:
        # 1. Try Facebook's URL-encoded GraphQL format
        if "fb_api_req_friendly_name=" in request_body or "doc_id=" in request_body:
            parsed = parse_qs(request_body)
            operation_name = parsed.get("fb_api_req_friendly_name", [None])[0]
            doc_id = parsed.get("doc_id", [None])[0]
            vars_raw = parsed.get("variables", [None])[0]
            if vars_raw:
                try:
                    json.loads(vars_raw) # Validate JSON
                    variables = vars_raw
                except json.JSONDecodeError:
                    pass
            return operation_name, doc_id, variables

        # 2. Try standard JSON GraphQL format
        if request_body.strip().startswith("{"):
            payload = json.loads(request_body)
            if isinstance(payload, dict):
                operation_name = payload.get("operationName")
                variables_dict = payload.get("variables")
                if variables_dict:
                    variables = json.dumps(variables_dict, ensure_ascii=False)
                
            return operation_name, None, variables
            
    except Exception:
        pass
        
    return operation_name, doc_id, variables
