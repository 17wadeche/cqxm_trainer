import json
import os
from pathlib import Path
import re
import sys
TOKEN_NAME = 'MDT_GPT_API_TOKEN'
def _validate(value):
    if len(value) > 8192 or any(c in value for c in ('\r', '\n', '\x00')):
        raise ValueError('MDT_GPT_API_TOKEN must be a single line of at most 8192 characters.')
    return value.strip()
def read_token_file(path):
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return ''
    if len(raw) > 1024 * 1024:
        raise ValueError('The token configuration file is too large.')
    try:
        lines = raw.decode('utf-8-sig').splitlines()
    except UnicodeError:
        raise ValueError('The token configuration file must use UTF-8.') from None
    token = ''
    for line in lines:
        match = re.match(r'^\s*(?:export\s+)?MDT_GPT_API_TOKEN\s*=\s*(.*?)\s*$', line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith('"'):
            try:
                value, end = json.JSONDecoder().raw_decode(value)
            except ValueError:
                raise ValueError('Invalid quoted MDT_GPT_API_TOKEN in .env.') from None
            suffix = match.group(1)[end:].strip()
            if not isinstance(value, str) or (suffix and not suffix.startswith('#')):
                raise ValueError('Invalid quoted MDT_GPT_API_TOKEN in .env.')
        elif value.startswith("'"):
            end = value.find("'", 1)
            if end < 0 or (value[end+1:].strip() and not value[end+1:].strip().startswith('#')):
                raise ValueError('Invalid quoted MDT_GPT_API_TOKEN in .env.')
            value = value[1:end]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0]
            if value.startswith('#'):
                value = ''
        token = _validate(value)
    return token
def configured_token():
    injected = _validate(os.environ.get(TOKEN_NAME, ''))
    if injected:
        return injected
    directory = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
                 else Path(__file__).resolve().parent)
    return read_token_file(directory / '.env')
def write_token_file(path, token):
    token = _validate(token)
    if not token:
        raise ValueError('No MDT_GPT_API_TOKEN was found in the source .env file.')
    Path(path).write_text(TOKEN_NAME + '=' + json.dumps(token) + '\n', encoding='utf-8')