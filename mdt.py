from copy import deepcopy
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from uuid import uuid4
from config import ENVIRONMENT, ENDPOINT, DEFAULT_AUTH, DEFAULT_MODEL
from context_budget import input_estimate, fits_context
class ProviderError(Exception):
    def __init__(self, message, *, status=None, field=None, unsupported_format=False,
                 unsupported_tools=False, stop_reason=None, output_limit=None):
        super().__init__(message)
        self.status, self.field = status, field
        self.unsupported_format, self.unsupported_tools = unsupported_format, unsupported_tools
        self.stop_reason, self.output_limit = stop_reason, output_limit
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials to a redirected destination.
def error_description(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return ''
    found = []
    def visit(item, depth=0):
        if depth > 4:
            return
        if isinstance(item, str):
            found.append(item[:2000])
        elif isinstance(item, dict):
            for key in ['message', 'msg', 'error', 'detail', 'details', 'errors', 'param']:
                if key in item:
                    visit(item[key], depth+1)
            loc = item.get('loc')
            if isinstance(loc, list):
                found.append('.'.join(str(part) for part in loc[:10] if isinstance(part, (str,int))))
        elif isinstance(item, list):
            for part in item[:8]:
                visit(part, depth+1)
    visit(value)
    return ' '.join(found)[:8000]
def classify_error(description):
    text = description.lower()
    unsupported = any(v in text for v in ['not supported', 'does not support', 'unsupported', 'unknown parameter',
        'unrecognized', 'not allowed', 'unexpected keyword', 'extra inputs are not permitted', 'extra fields not permitted'])
    format_field = any(v in text for v in ['text.format', 'text[', 'structured output', 'json_schema', "'text'", '"text"'])
    invalid_schema = any(v in text for v in ['invalid schema', 'schema is invalid', 'malformed schema'])
    if format_field:
        return 'text.format', unsupported and not invalid_schema
    for field in ['max_output_tokens', 'tool_choice', 'tools', 'include', 'store', 'input']:
        if re.search(r'\b'+field+r'\b', text):
            return field, unsupported and not invalid_schema
    if 'model' in text:
        return 'model', False
    return None, False
def safe_diagnostic(description, token):
    value = description.replace(token, '[credential removed]') if token else description
    value = re.sub(r'(?i)bearer\s+[^\s,;"\]}]+', 'Bearer [credential removed]', value)
    value = re.sub(r'(?i)((?:x-api-key|api[_ -]?key|token|authorization)["\s]*[:=]["\s]*)[^\s,;"\]}]+',
                   r'\1[credential removed]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[credential removed]', value)
    value = re.sub(r'https?://[^\s<>"\]]+', '[URL omitted]', value)
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', value)
    return ' '.join(value.split())[:420]
def network_error(exc):
    reason = getattr(exc, 'reason', exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        detail = 'TLS certificate verification failed. Ask IT to check the approved certificate configuration.'
    elif isinstance(reason, socket.gaierror):
        detail = 'The server name could not be resolved. Ask IT to check DNS and Zscaler routing.'
    elif isinstance(reason, (socket.timeout, TimeoutError)):
        detail = 'The connection timed out. Check the service and your Medtronic connection.'
    elif isinstance(reason, (ssl.SSLError, ConnectionResetError, ConnectionAbortedError)):
        detail = 'The secure connection was interrupted. Ask IT to check Zscaler and proxy access.'
    else:
        detail = 'A network connection could not be established. Ask IT to check Zscaler and proxy access.'
    return ProviderError('Could not reach MDT-GPT Production (api.gpt.medtronic.com:443). '+detail)
def response_input(messages, portable=False):
    result = []
    for message in messages:
        role, content = message['role'], message['content']
        if isinstance(content, str):
            result.append({'role':role, 'content':content})
            continue
        if portable:
            visible = [c for c in content if c.get('type') != 'responses_output']
            result.append({'role':role, 'content':json.dumps(visible, ensure_ascii=False)})
            continue
        envelope = next((c for c in content if c.get('type')=='responses_output'), None)
        if envelope is not None:
            result.extend(deepcopy(envelope['items']))
            continue
        for block in content:
            kind = block.get('type')
            if kind == 'text':
                result.append({'role':role, 'content':block['text']})
            elif kind == 'tool_result':
                result.append({'type':'function_call_output', 'call_id':block['tool_use_id'], 'output':block['content']})
            elif kind == 'tool_use':
                result.append({'type':'function_call','call_id':block['id'],'name':block['name'],
                               'arguments':json.dumps(block['input'],ensure_ascii=False)})
            else:
                raise ProviderError('Unsupported internal conversation item. No request was sent.')
    return result
class MDTClient:
    def __init__(self, token, model=DEFAULT_MODEL, auth_style=DEFAULT_AUTH, transport=None, *, environment=ENVIRONMENT):
        if not isinstance(token,str) or not token.strip() or '\n' in token or '\r' in token:
            raise ProviderError('Enter your MDT-GPT Production API token as one line.')
        if model != DEFAULT_MODEL:
            raise ProviderError('This build uses the exact model ID '+DEFAULT_MODEL+'. No other model is selected.')
        if auth_style != DEFAULT_AUTH:
            raise ProviderError('The Production OpenAI Responses connection uses Authorization: Bearer.')
        if environment != ENVIRONMENT:
            raise ProviderError('This build only connects to MDT-GPT Production.')
        self.token, self.model, self.auth_style = token.strip(), model, DEFAULT_AUTH
        self.environment, self.endpoint, self.transport = ENVIRONMENT, ENDPOINT, transport
        self.usage = {'input_tokens':0,'output_tokens':0}
        self.structured_mode, self.tool_mode = 'auto', 'native'
        self.estimate_scale, self.context_usage = 1.0, []
        self.reported_models = set()
    def headers(self):
        return {'Content-Type':'application/json','Authorization':'Bearer '+self.token}
    def _payload(self, system, messages, tools, schema, max_tokens, compatibility=False):
        if not isinstance(system,str):
            raise ProviderError('System instructions must be text.')
        portable = self.tool_mode == 'validated_json'
        if schema and compatibility:
            system += '\nReturn only a JSON object matching this schema. No Markdown fences or prose. The application validates the result before accepting it.\n'+json.dumps(schema,ensure_ascii=False)
        if tools and portable and not schema:
            system += ('\nRETRIEVAL PROTOCOL: Return only JSON with exactly two keys: "tool_calls" (an array of '
                       'objects with "name" and "arguments") and "text" (a string). Request up to 8 allowed '
                       'read-only tools per turn. Arguments must match the tool schema. When ready use '
                       '{"tool_calls":[],"text":"READY"}. Never invent tool results. The app executes the '
                       'requests and sends back tool_result items. Allowed tools:\n'+json.dumps(tools,ensure_ascii=False))
        payload = {'model':self.model,'input':[{'role':'system','content':system},*response_input(messages,portable)],
                   'max_output_tokens':max_tokens,'store':False}
        if tools and not portable and not schema:
            payload['tools'] = [{'type':'function','name':t['name'],'description':t.get('description',''),
                                 'parameters':output_schema(t['input_schema']),'strict':True} for t in tools]
            payload['tool_choice'] = 'auto'
            payload['include'] = ['reasoning.encrypted_content']
        if schema and not compatibility:
            payload['text'] = {'format':{'type':'json_schema','name':'gch_review','strict':True,'schema':output_schema(schema)}}
        return payload
    def _http_error(self, exc, diagnostic):
        try:
            description = error_description(exc.read(65536))
        except OSError:
            description = ''
        field, unsupported = classify_error(description)
        messages = {
            401:'MDT-GPT rejected the token. Enter a valid Production token in Check my work.',
            403:'Access to MDT-GPT Production was denied. Ask IT or the MDT-GPT owner to check access to this endpoint and model.',
            402:'MDT-GPT reports insufficient quota or billing access.',
            404:'The Production Responses route or '+DEFAULT_MODEL+' model was not found. Ask the MDT-GPT owner to confirm access.',
            429:'MDT-GPT rate limit reached. Wait and start a new review.'}
        if exc.code in {400,422}:
            message = ('MDT-GPT rejected the configured model '+self.model+'. Confirm it is enabled in Production → OpenAI → Models.'
                       if field=='model' else 'MDT-GPT rejected '+(field+' ' if field else 'the request ')+f'(HTTP {exc.code}).')
        else:
            message = messages.get(exc.code,f'MDT-GPT returned HTTP {exc.code}. Check its service status and try again.')
        if diagnostic and description:
            message += ' Gateway detail: '+safe_diagnostic(description,self.token)
        request_id = (exc.headers or {}).get('request-id') or (exc.headers or {}).get('x-request-id') or ''
        if re.fullmatch(r'[A-Za-z0-9._-]{1,100}',request_id) and request_id != self.token:
            message += ' Request ID: '+request_id+'.'
        context_error = exc.code in {400,413,422} and any(t in description.lower() for t in
            ['prompt is too long','prompt too long','maximum context','context window','input token limit','input is too long','context_length_exceeded'])
        if context_error:
            message = 'MDT-GPT needs a smaller input packet for this review.'
        return ProviderError(message,status=exc.code,field=field,
            stop_reason='input_context_budget' if context_error else None,
            unsupported_format=exc.code in {400,422} and field=='text.format' and unsupported,
            unsupported_tools=exc.code in {400,422} and field in {'tools','tool_choice','include'} and unsupported)
    def _normalize(self, response, payload):
        if not isinstance(response,dict) or not isinstance(response.get('output'),list):
            raise ProviderError('MDT-GPT did not return an OpenAI Responses result.')
        usage = response.get('usage') or {}
        usage = usage if isinstance(usage,dict) else {}
        counts = {k:usage.get(k,usage.get(alias,0)) for k,alias in
                  [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')]}
        counts = {k:v if type(v)==int and v>=0 else 0 for k,v in counts.items()}
        for key,value in counts.items():self.usage[key] += value
        if counts['input_tokens']:
            self.estimate_scale = max(self.estimate_scale,counts['input_tokens']/max(1,input_estimate(payload))*1.15)
        self.context_usage[-1]['reported_input'] = counts['input_tokens']
        reported_model = response.get('model')
        if reported_model is not None:
            if (not isinstance(reported_model,str) or
                    not re.fullmatch(r'[A-Za-z0-9._:/-]{1,160}',reported_model) or
                    self.token in reported_model):
                raise ProviderError('MDT-GPT returned invalid model metadata. No report was accepted.')
            self.reported_models.add(reported_model)
        self.context_usage[-1].update(requested_model=self.model, reported_model=reported_model)
        status = response.get('status')
        incomplete = response.get('incomplete_details') or {}
        reason = incomplete.get('reason') if isinstance(incomplete,dict) else None
        if status=='incomplete' or reason:
            if reason=='max_output_tokens':
                raise ProviderError(f'The model response was incomplete because it reached the output allowance (stop_reason=max_tokens; limit={payload["max_output_tokens"]}). Partial findings were not accepted.',stop_reason='max_tokens',output_limit=payload['max_output_tokens'])
            if reason=='content_filter':
                raise ProviderError('The model declined this request (stop_reason=refusal). No report was accepted.',stop_reason='refusal')
            raise ProviderError('MDT-GPT returned an incomplete response. No report was accepted.',stop_reason='unrecognized')
        if response.get('error') or status not in {None,'completed'}:
            raise ProviderError('MDT-GPT did not complete this response. No report was accepted.',stop_reason='unrecognized')
        content, ids = [], set()
        for item in response['output']:
            if not isinstance(item,dict) or item.get('status') not in {None,'completed'}:
                raise ProviderError('MDT-GPT returned an incomplete output item.',stop_reason='unrecognized')
            kind = item.get('type')
            if kind=='message':
                if item.get('role','assistant') != 'assistant' or not isinstance(item.get('content'),list):
                    raise ProviderError('MDT-GPT returned an invalid output message.')
                for block in item['content']:
                    if not isinstance(block,dict):raise ProviderError('MDT-GPT returned an invalid text block.')
                    if block.get('type')=='refusal':
                        raise ProviderError('The model declined this request (stop_reason=refusal). No report was accepted.',stop_reason='refusal')
                    if block.get('type')!='output_text' or not isinstance(block.get('text'),str):
                        raise ProviderError('MDT-GPT returned an unsupported output block.')
                    content.append({'type':'text','text':block['text']})
            elif kind=='function_call':
                call_id, name = item.get('call_id'), item.get('name')
                if not isinstance(call_id,str) or not call_id or call_id in ids or not isinstance(name,str):
                    raise ProviderError('MDT-GPT returned invalid or duplicate tool calls.')
                try:args=json.loads(item['arguments'])
                except (KeyError,ValueError,TypeError):raise ProviderError('MDT-GPT returned invalid tool arguments.') from None
                if not isinstance(args,dict):raise ProviderError('MDT-GPT tool arguments must be an object.')
                allowed={t['name'] for t in payload.get('tools',[])}
                if name not in allowed or payload.get('tool_choice')=='none':
                    raise ProviderError('MDT-GPT requested a tool outside the current review phase.')
                ids.add(call_id)
                content.append({'type':'tool_use','id':call_id,'name':name,'input':args})
            elif kind!='reasoning':
                raise ProviderError('MDT-GPT returned an unsupported output item.')
        if not content:
            raise ProviderError('MDT-GPT returned no usable text or retrieval calls. No report was accepted.')
        if len(ids)>8:raise ProviderError('The model requested too many tool calls in one turn.',stop_reason='too_many_tool_calls')
        content.append({'type':'responses_output','items':deepcopy(response['output'])})
        return {'content':content,'model':reported_model or self.model,'requested_model':self.model,
                'reported_model':reported_model,'stop_reason':'tool_use' if ids else 'end_turn','usage':counts}
    def _send(self, payload, diagnostic=False):
        encoded=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        if len(encoded)>4*1024*1024:
            raise ProviderError('This request exceeds the transport size limit. Split the source sections.')
        input_tokens=input_estimate(payload,self.estimate_scale)
        if not fits_context(input_tokens,payload['max_output_tokens']):
            raise ProviderError('This request needs a smaller evidence packet to fit the configured context budget.',stop_reason='local_context_budget')
        try:
            if self.transport:
                response=self.transport(payload)
            else:
                request=urllib.request.Request(self.endpoint,encoded,self.headers(),method='POST')
                with urllib.request.build_opener(NoRedirect()).open(request,timeout=60 if diagnostic else 120) as res:
                    raw=res.read(4*1024*1024+1)
                    if len(raw)>4*1024*1024:raise ProviderError('MDT-GPT response exceeded the size limit.')
                    response=json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc,diagnostic) from None
        except (urllib.error.URLError,socket.timeout,TimeoutError,ssl.SSLError,ConnectionError) as exc:
            raise network_error(exc) from None
        except (json.JSONDecodeError,UnicodeDecodeError):
            raise ProviderError('MDT-GPT returned an unreadable response.') from None
        self.context_usage.append({'input_budget':input_tokens,'method':'estimated','reported_input':0,
                                   'output_limit':payload['max_output_tokens']})
        return self._normalize(response,payload)
    def message(self, system, messages, tools=None, schema=None, max_tokens=6000, diagnostic=False):
        for _ in range(3):  # At most one explicit format fallback and one tool fallback.
            compatibility=self.structured_mode=='validated_json'
            payload=self._payload(system,messages,tools,schema,max_tokens,compatibility)
            try:
                response=self._send(payload,diagnostic)
            except ProviderError as exc:
                if schema and not compatibility and exc.unsupported_format:
                    self.structured_mode='validated_json';continue
                if tools and self.tool_mode=='native' and exc.unsupported_tools:
                    self.tool_mode='validated_json';continue
                raise
            if schema and self.structured_mode=='auto':self.structured_mode='native'
            if tools and not schema and self.tool_mode=='validated_json':
                try:
                    value=json.loads(response_text(response))
                    if not isinstance(value,dict) or set(value)!={'tool_calls','text'} or not isinstance(value['text'],str):raise ValueError()
                    calls=value['tool_calls']
                    if not isinstance(calls,list):raise ValueError()
                    if len(calls)>8:raise ProviderError('The model requested too many tool calls in one turn.',stop_reason='too_many_tool_calls')
                    allowed={t['name'] for t in tools}
                    content=[]
                    for call in calls:
                        if not isinstance(call,dict) or set(call)!={'name','arguments'} or call['name'] not in allowed or not isinstance(call['arguments'],dict):raise ValueError()
                        content.append({'type':'tool_use','id':'call_'+uuid4().hex,'name':call['name'],'input':call['arguments']})
                    content.append({'type':'text','text':value['text']})
                    response['content']=content;response['stop_reason']='tool_use' if calls else 'end_turn'
                except (ValueError,TypeError,KeyError):
                    raise ProviderError('The model returned an invalid retrieval plan. No report was accepted.') from None
            return response
        raise ProviderError('The gateway compatibility checks did not finish. No report was accepted.')
def probe_connection(client, discover=False):
    system='Connection test. No complaint documents are involved.'
    try:
        basic=client.message(system,[{'role':'user','content':'Reply with OK.'}],max_tokens=4096,diagnostic=True)
    except ProviderError as exc:
        raise ProviderError('Basic Production token/model connection test failed. '+str(exc),status=exc.status,field=exc.field) from None
    if not response_text(basic).strip():
        raise ProviderError('The basic connection succeeded but the model returned no text. No documents were sent.')
    schema={'type':'object','properties':{'status':{'type':'string','enum':['ok']}},'required':['status'],'additionalProperties':False}
    try:
        answer=client.message(system,[{'role':'user','content':'Return JSON with status equal to ok.'}],schema=schema,max_tokens=4096,diagnostic=True)
    except ProviderError as exc:
        raise ProviderError('The token and model worked for a basic text request, but the JSON-format check failed. '+str(exc),status=exc.status,field=exc.field) from None
    try:valid=json.loads(response_text(answer))=={'status':'ok'}
    except (ValueError,TypeError):valid=False
    if not valid:raise ProviderError('The token and model connected, but the JSON response failed local validation. No complaint documents were sent.')
    return {'structured_mode':getattr(client,'structured_mode','native'),'model':client.model}
def output_schema(schema):
    if isinstance(schema,dict):
        result={k:output_schema(v) for k,v in schema.items() if k not in
                {'title','minLength','maxLength','minItems','maxItems','minimum','maximum','default'}}
        notes=[f'{key}={schema[key]}' for key in ['minLength','maxLength','minItems','maxItems','minimum','maximum'] if key in schema]
        if notes:result['description']=(result.get('description','')+' Local validation requires: '+', '.join(notes)+'.').strip()
        if result.get('type')=='object' and 'properties' in result:
            result['additionalProperties']=False
            result['required']=list(result['properties'])
        return result
    if isinstance(schema,list):return [output_schema(v) for v in schema]
    return schema
def response_text(response):
    return '\n'.join(c.get('text','') for c in response['content'] if isinstance(c,dict) and c.get('type')=='text')
