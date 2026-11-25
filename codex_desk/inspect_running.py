"""Read loaded thread status through an existing native Unix control WebSocket."""
import argparse
import json


def inspect_running(socket):
    from websockets.sync.client import unix_connect
    # Native control sockets speak WebSocket, not newline JSON. The CLI's
    # `app-server proxy` is only a raw-byte bridge; it does not add this handshake.
    with unix_connect(socket, uri='ws://localhost/', open_timeout=10) as connection:
        number=0
        def request(method,params):
            nonlocal number
            number+=1
            connection.send(json.dumps({'id':number,'method':method,'params':params}))
            while True:
                response=json.loads(connection.recv(timeout=10))
                if response.get('id')==number:
                    if 'error' in response:
                        raise RuntimeError(response['error'].get('message',str(response['error'])))
                    return response['result']
        request('initialize',{'clientInfo':{'name':'codex_desk_inspector','version':'0.1.0'}})
        connection.send('{"method":"initialized","params":{}}')
        identifiers=request('thread/loaded/list',{})['data']
        rows=[]
        for identifier in identifiers:
            thread=request('thread/read',{'threadId':identifier,'includeTurns':False})['thread']
            rows.append({k:thread.get(k) for k in ('id','status','modelProvider','cwd')})
        return {'loadedThreads':rows}


def main():
    parser=argparse.ArgumentParser(description='Read the existing Codex backend without starting, resuming, interrupting or editing threads')
    parser.add_argument('--sock',required=True,help='Existing native Unix control socket')
    args=parser.parse_args()
    try:
        print(json.dumps(inspect_running(args.sock),indent=2))
    except ImportError:
        parser.exit(1,'Install the optional control dependency: python3 -m pip install ".[control]"\n')
    except (RuntimeError,OSError,TimeoutError) as error:
        parser.exit(1,'Control inspection failed: '+str(error)+'\n')

if __name__=='__main__':main()
