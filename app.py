from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_sock import Sock
import os
import json
from urllib.parse import unquote
from threading import Thread
import time

app = Flask(__name__)
sock = Sock(app)

UPLOAD_FOLDER = 'static'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

games = {}  # 多场比赛的数据结构
clients = {}  # 每场比赛对应的 WebSocket 客户端集合
timer_threads = {}


def default_game_data():
    return {
        "scoreA": 0,
        "scoreB": 0,
        "foulsA": 0,
        "foulsB": 0,
        "timeoutsA": 0,
        "timeoutsB": 0,
        "period": 1,
        "time": "10:00",
        "isRunning": False,
        "resetEnabled": True,
        "teamAName": "Team A",
        "teamBName": "Team B",
        "teamALogo": "logo.webp",
        "teamBLogo": "logo.webp"
    }

def get_game(game_id):
    if game_id not in games:
        games[game_id] = default_game_data()
    return games[game_id]

def broadcast_update(game_id):
    for client in clients.get(game_id, set()).copy():
        try:
            client.send(json.dumps(games[game_id]))
        except:
            clients[game_id].discard(client)

def start_timer_loop(game_id):
    try:
        while True:
            # 实时检查暂停状态
            if not games[game_id]["isRunning"]:
                break

            time.sleep(1)

            m, s = map(int, games[game_id]["time"].split(":"))

            if m == 0 and s == 0:
                # 触发蜂鸣器
                for client in clients.get(game_id, set()).copy():
                    try:
                        client.send(json.dumps({"buzzer": True}))
                    except:
                        clients[game_id].discard(client)

                games[game_id]["period"] += 1
                games[game_id]["time"] = "10:00" if games[game_id]["period"] <= 4 else "05:00"
                games[game_id]["isRunning"] = False
                broadcast_update(game_id)
                break

            if s == 0:
                m -= 1
                s = 59
            else:
                s -= 1

            games[game_id]["time"] = f"{m:02d}:{s:02d}"
            broadcast_update(game_id)

    finally:
        timer_threads.pop(game_id, None)  # 移除线程记录



def handle_client_message(game_id, data):
    if data.get("isRunning") == True:
        games[game_id]["isRunning"] = True
        Thread(target=start_timer_loop, args=(game_id,), daemon=True).start()
    elif data.get("isRunning") == False:
        games[game_id]["isRunning"] = False
    # 其他如 score、reset、period 处理
    broadcast_update(game_id, games[game_id])

@app.route('/')
def index():
    game_id = request.args.get('game_id', 'default')
    data = get_game(game_id)
    data['period'] = int(data.get('period', 1))
    return render_template('index.html', data=data, game_id=game_id)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    game_id = request.args.get('game_id', 'default')
    data = get_game(game_id)

    if request.method == 'POST':
        data['teamAName'] = request.form.get('teamAName', data['teamAName'])
        data['teamBName'] = request.form.get('teamBName', data['teamBName'])

        teamAFile = request.files.get('teamALogo')
        if teamAFile and teamAFile.filename != '':
            filename = f'{game_id}_teamA_logo.webp'
            teamAFile.save(os.path.join(UPLOAD_FOLDER, filename))
            data['teamALogo'] = filename

        teamBFile = request.files.get('teamBLogo')
        if teamBFile and teamBFile.filename != '':
            filename = f'{game_id}_teamB_logo.webp'
            teamBFile.save(os.path.join(UPLOAD_FOLDER, filename))
            data['teamBLogo'] = filename

        broadcast_update(game_id)
        return redirect(url_for('admin', game_id=game_id))

    return render_template('admin.html', data=data, game_id=game_id)

@app.route('/games')
def games_page():
    # 解码后去重
    decoded_ids = {}
    for game_id in games.keys():
        readable = unquote(game_id)
        # 保留第一个出现的编码版本，后续跳转仍用原始编码形式
        if readable not in decoded_ids:
            decoded_ids[readable] = game_id
    return render_template('games.html', game_map=decoded_ids)

@app.route('/delete_game/<path:game_id>', methods=['POST'])
def delete_game(game_id):
    # 直接删除原始编码形式的 game_id
    games.pop(game_id, None)
    clients.pop(game_id, None)
    return redirect(url_for('games_page'))



@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

@sock.route('/ws')
def websocket(ws):
    query = ws.environ.get('QUERY_STRING', '')
    game_id = dict(q.split('=') for q in query.split('&') if '=' in q).get('game_id', 'default')
    data = get_game(game_id)

    if game_id not in clients:
        clients[game_id] = set()
    clients[game_id].add(ws)

    try:
        ws.send(json.dumps(data))
        while True:
            msg = ws.receive()
            if not msg:
                break
            try:
                msg_data = json.loads(msg)
                if not isinstance(msg_data, dict):
                    return

                # RESET 优先处理并直接 broadcast
                if msg_data.get('reset'):
                    data['isRunning'] = False
                    data['resetEnabled'] = True
                    for field in ['scoreA', 'scoreB', 'foulsA', 'foulsB', 'timeoutsA', 'timeoutsB', 'period', 'time']:
                        data[field] = default_game_data()[field]
                    broadcast_update(game_id)
                    continue  # 不进入后续逻辑

                # 开始 / 停止处理
                if 'isRunning' in msg_data:
                    if msg_data['isRunning']:
                        data['isRunning'] = True
                        data['resetEnabled'] = False

                        # 只在没有线程在跑时才启动
                        if game_id not in timer_threads:
                            t = Thread(target=start_timer_loop, args=(game_id,), daemon=True)
                            timer_threads[game_id] = t
                            t.start()
                    else:
                        data['isRunning'] = False
                        data['resetEnabled'] = True

                    updated = True

                for key in ['scoreA', 'scoreB', 'period', 'time', 'foulsA', 'foulsB', 'timeoutsA', 'timeoutsB']:
                    if key in msg_data:
                        data[key] = msg_data[key]
                        updated = True

                if 'buzzer' in msg_data:
                    for client in clients[game_id].copy():
                        try:
                            client.send(json.dumps({"buzzer": True}))
                        except:
                            clients[game_id].discard(client)
                    continue

                if updated:
                    broadcast_update(game_id)

            except Exception as e:
                print("WebSocket error:", e)
    finally:
        clients[game_id].discard(ws)

@app.template_filter('url_unquote')
def url_unquote_filter(s):
    return unquote(s)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
