import json
from config import DEFAULT_MODEL
def wire_response(value):
    output=[]
    reason=value.get('stop_reason','end_turn')
    for c in value.get('content',[]):
        if c['type']=='text':
            output.append({'type':'message','role':'assistant','status':'completed','content':[
                {'type':'refusal','refusal':c['text']} if reason=='refusal' else {'type':'output_text','text':c['text']}]})
        elif c['type']=='tool_use':
            output.append({'type':'function_call','status':'completed','call_id':c['id'], 'name':c['name'],'arguments':json.dumps(c['input'])})
    result={'output':output,'status':'completed','model':value.get('model',DEFAULT_MODEL),
            'usage':value.get('usage',{'input_tokens':100,'output_tokens':50})}
    if reason=='max_tokens':result.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
    elif reason not in {'end_turn','tool_use','refusal'}:result['status']=reason
    return result
def response(text='{"status":"ok"}', **kwargs):
    return wire_response({'content':[{'type':'text','text':text}],**kwargs})
def decode_payload(payload):
    system=payload['input'][0]['content']
    messages=[]
    for i in payload['input'][1:]:
        kind=i.get('type')
        if kind=='function_call':
            messages.append({'role':'assistant','content':[{'type':'tool_use','id':i['call_id'],'name':i['name'],'input':json.loads(i['arguments'])}]})
        elif kind=='function_call_output':
            messages.append({'role':'user','content':[{'type':'tool_result','tool_use_id':i['call_id'],'content':i['output']}]})
        elif kind=='reasoning':continue
        elif kind=='message':
            messages.append({'role':i['role'],'content':[{'type':'text','text':c['text']} for c in i['content']]})
        else:messages.append(i)
    return system,messages
def invoke_mock(mock,payload):
    system,messages=decode_payload(payload)
    return wire_response(mock.message(system,messages,tools=payload.get('tools'),schema=payload.get('text'),max_tokens=payload['max_output_tokens']))