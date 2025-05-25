from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_sock import Sock
import os
import json

app = Flask(__name__)
sock = Sock(app)

UPLOAD_FOLDER = 'static'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 初始数据，添加了犯规和暂停及开始状态
data = {
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
    "teamAName": "苍南县星海学校",
    "teamBName": "苍南县星海学校",
    "teamALogo": "logo.webp",
    "teamBLogo": "logo.webp"
}

clients = set()

# 首页
@app.route('/')
def index():
    return render_template('index.html', data=data)

# 管理页面 - 你可以自己根据需要完善
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        data['teamAName'] = request.form.get('teamAName', data['teamAName'])
        data['teamBName'] = request.form.get('teamBName', data['teamBName'])

        teamAFile = request.files.get('teamALogo')
        if teamAFile and teamAFile.filename != '':
            teamAFile.save(os.path.join(UPLOAD_FOLDER, 'teamA_logo.webp'))
            data['teamALogo'] = 'teamA_logo.webp'

        teamBFile = request.files.get('teamBLogo')
        if teamBFile and teamBFile.filename != '':
            teamBFile.save(os.path.join(UPLOAD_FOLDER, 'teamB_logo.webp'))
            data['teamBLogo'] = 'teamB_logo.webp'

        broadcast_update()
        return redirect(url_for('admin'))
    return render_template('admin.html', data=data)

# 静态文件
@app.route('/static/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

# WebSocket
@sock.route('/ws')
def websocket(ws):
    clients.add(ws)
    try:
        # 首次连接发送当前数据
        ws.send(json.dumps(data))

        while True:
            msg = ws.receive()
            if not msg:
                break
            try:
                msg_data = json.loads(msg)
                updated = False

                # 处理清零请求
                if msg_data.get('reset'):
                    data['scoreA'] = 0
                    data['scoreB'] = 0
                    data['foulsA'] = 0
                    data['foulsB'] = 0
                    data['timeoutsA'] = 0
                    data['timeoutsB'] = 0
                    data['period'] = 1
                    data['time'] = "10:00"
                    data['isRunning'] = False
                    data['resetEnabled'] = False
                    updated = True

                # 处理开始/暂停按钮
                if 'isRunning' in msg_data:
                    data['isRunning'] = msg_data['isRunning']
                    # 开始时禁止清零，暂停时允许清零
                    data['resetEnabled'] = not data['isRunning']
                    updated = True

                # 其他数据更新
                for key in ['scoreA', 'scoreB', 'period', 'time', 'foulsA', 'foulsB', 'timeoutsA', 'timeoutsB']:
                    if key in msg_data:
                        data[key] = msg_data[key]
                        updated = True
                        
                if 'buzzer' in msg_data:
                    # 广播给所有人让他们播放蜂鸣
                    for client in clients.copy():
                        try:
                            client.send(json.dumps({"buzzer": True}))
                        except:
                            clients.discard(client)
                    continue

                if updated:
                    broadcast_update()

            except Exception as e:
                print("解析消息错误:", e)
    finally:
        clients.discard(ws)

def broadcast_update():
    for client in clients.copy():
        try:
            client.send(json.dumps(data))
        except:
            clients.discard(client)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
