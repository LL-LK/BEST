"""离线打印指定尝试的实际调用、用户答案或失败message，供当前助手直接复核。"""
import argparse
import json
from common_e6 import HERE, read

def dump(batch, lane, task, repeats):
    for repeat in repeats:
        directory = batch/'lanes'/lane/task/f'repeat-{repeat}'
        for path in sorted(directory.glob('attempt-*-result.json')):
            run = read(path)
            events = [json.loads(s) for s in (directory/run['trace']).read_text().splitlines()]
            calls = [e['payload'] for e in events if e['type']=='tool_call']
            print('\nREVIEW',lane,task,repeat,path.name)
            print('COMPLETE',run['completed'],'ERROR',run.get('error'))
            print('NATIVE_CALLS',[{'tool':c['tool'],'args':c['args']} for c in calls])
            print('TOOL_STATUS',[{'ok':e['status']['ok'],'code':e['status'].get('error_code'),
                                 'total':e['data'].get('total_count',e['data'].get('total')),
                                 'rows':len(e['data'].get('rows',[]))} for e in run['envelopes']])
            if run.get('answer_text'):
                print('ANSWER',run['answer_text'],'CARD',run.get('card'),'CLARIFICATION',run.get('clarification'))
            else:
                for event in events:
                    if event['type']!='model_response':
                        continue
                    response=event['payload']['raw']
                    print('RESPONSE_STATUS',response.get('status'),'USAGE',response.get('usage'))
                    for output in response.get('output',[]):
                        if output.get('type')=='message':
                            print('RAW_MESSAGE',output.get('content'))
                        elif output.get('type')=='function_call':
                            print('RAW_FUNCTION_CALL',output.get('name'),output.get('arguments'))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--lane',required=True)
    parser.add_argument('--task',required=True)
    parser.add_argument('--repeats',nargs='+',type=int,default=[1,2,3,4,5])
    args=parser.parse_args()
    dump(HERE/'batches'/read(HERE/'current.json')['batch'],args.lane,args.task,args.repeats)
