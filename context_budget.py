import json
from math import ceil
from config import CONTEXT_TOKENS, CONTEXT_HEADROOM, MAX_INPUT_TOKENS
def estimate_tokens(value):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'))
    ascii_bytes=sum(ord(c)<128 for c in text)
    return ceil(ascii_bytes/2)+(len(text.encode('utf-8'))-ascii_bytes)+1024
def input_estimate(payload,scale=1):
    return ceil(estimate_tokens({k:v for k,v in payload.items() if k not in {'max_tokens','max_output_tokens','stream','store'}})*max(1,scale))
def fits_context(tokens,output_tokens):
    return tokens<=MAX_INPUT_TOKENS and tokens+output_tokens+CONTEXT_HEADROOM<=CONTEXT_TOKENS