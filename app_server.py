import cv2
import time
import threading
import json
import asyncio
import websockets
from pupil_apriltags import Detector
from flask import Flask, Response, render_template_string, request, jsonify

# === CONFIGURAÇÃO DO STREAM DO RASPBERRY ===
UDP_URL = "udp://0.0.0.0:5000?overrun_nonfatal=1&fifo_size=50000"
WIDTH = 1280
HEIGHT = 720

# === CONFIGURAÇÃO DO WEBSOCKET PARA O RASPBERRY ===
RASPBERRY_WS_URL = "ws://192.168.14.223:6789"  

app = Flask(__name__)

cap = cv2.VideoCapture(UDP_URL)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 
latest_frame = None
lock = threading.Lock()
actions_log = []

# APRILTAG: detector global
at_detector = Detector(
    families="tag36h11",
    nthreads=2,
    quad_decimate=2.0,
    quad_sigma=0.0,
    refine_edges=1,
    decode_sharpening=0.25,
    debug=0,
)

last_tag_send_time = 0.0 

# === WEBSOCKET: fila, loop e thread ===
ws_loop = None
ws_command_queue = None

async def ws_sender():
    """
    Mantém uma conexão WebSocket com o Raspberry e envia comandos
    colocados na fila ws_command_queue.
    """
    global ws_command_queue

    ws_command_queue = asyncio.Queue()

    while True:
        try:
            print("[WS] Conectando ao Raspberry em", RASPBERRY_WS_URL, flush=True)
            async with websockets.connect(RASPBERRY_WS_URL) as websocket:
                print("[WS] Conectado!", flush=True)
                while True:
                    cmd = await ws_command_queue.get()
                    try:
                        await websocket.send(json.dumps(cmd))
                        # resp = await websocket.recv()
                        # print("[WS] Resposta:", resp)
                    except Exception as e:
                        print("[WS] Erro ao enviar comando:", e, flush=True)
                        break  # sai pro while externo reconectar
        except Exception as e:
            print("[WS] Erro na conexão:", e, flush=True)

        print("[WS] Tentando reconectar em 2s...", flush=True)
        await asyncio.sleep(2)


def start_ws_thread():
    """
    Sobe uma thread com um event loop asyncio dedicado ao websocket.
    """
    global ws_loop

    def runner():
        global ws_loop
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        ws_loop.run_until_complete(ws_sender())

    t = threading.Thread(target=runner, daemon=True)
    t.start()


def send_ws_command(cmd: dict):
    """
    Interface thread-safe para colocar um comando na fila do websocket.
    Exemplo de cmd:
      {"type": "button", "action": "UP"}
      {"type": "apriltag", "id": 3, "center": [...], "corners": [...]}
    """
    global ws_loop, ws_command_queue
    if ws_loop is None or ws_command_queue is None:
        # ainda não inicializado / não conectado
        return

    def _put():
        ws_command_queue.put_nowait(cmd)

    # agendar dentro do loop asyncio
    ws_loop.call_soon_threadsafe(_put)


def capture_loop():
    global cap, latest_frame, last_tag_send_time
    frame_idx = 0
    while True:
        ...
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue

        frame = cv2.resize(frame, (WIDTH, HEIGHT))

        # 1) primeiro guarda para o MJPEG não atrasar
        with lock:
            latest_frame = frame

        # 2) depois faz visão computacional, sem travar a captura
        try:
            frame_idx += 1
            if frame_idx % 3 != 0:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            results = at_detector.detect(
                gray,
                estimate_tag_pose=False
            )

            if results:
                now = time.time()
                if now - last_tag_send_time > 0.5:
                    last_tag_send_time = now
                    for r in results:
                        cmd = {
                            "type": "apriltag",
                            "id": int(r.tag_id),
                            "center": [float(c) for c in r.center],
                            "corners": [[float(x) for x in pt] for pt in r.corners],
                            "family": getattr(r, "tag_family", "unknown"),
                        }
                        send_ws_command(cmd)
        except Exception as e:
            print("Erro na detecção de AprilTags:", e, flush=True)

        time.sleep(0.001)



def mjpeg_generator():
    """Gera um stream MJPEG a partir do último frame capturado."""
    while True:
        frame = None
        with lock:
            if latest_frame is not None:
                frame = latest_frame.copy()

        if frame is None:
            time.sleep(0.05)
            continue

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )
        time.sleep(0.01)


@app.route("/video")
def video():
    return Response(
        mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


INDEX_HTML = """
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <title>Forklift Controller</title>
    <style>
      body {
        background: #0b2239;
        color: #ffffff;
        font-family: Arial, sans-serif;
        margin: 0;
        padding: 20px;
        box-sizing: border-box;
      }
      h1 {
        text-align: center;
        margin-bottom: 10px;
      }
      .container {
        max-width: 900px;
        margin: 0 auto;
      }
      .video-wrapper {
        text-align: center;
        margin-bottom: 20px;
      }
      .video-wrapper img {
        max-width: 100%;
        height: auto;
        border-radius: 8px;
        border: 2px solid #1e3a5f;
      }
      .controls {
        display: flex;
        gap: 20px;
        flex-wrap: wrap;
        justify-content: center;
        margin-bottom: 20px;
      }
      .dpad, .fork {
        background: #102b46;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.4);
      }
      .dpad-grid {
            display: grid;
            grid-template-columns: 60px 60px 60px 60px 60px;
            grid-template-rows: 60px 60px 60px;
            gap: 12px; /* aumenta o espaçamento */
      }
      button.ctrl-btn {
        width: 60px;
        height: 60px;
        border-radius: 6px;
        border: 2px solid #555;
        background: #333;
        color: #fff;
        font-size: 18px;
        font-weight: bold;
        cursor: pointer;
        box-shadow: 0 4px 0 #111;
        transition: all 0.1s ease;
      }
      button.ctrl-btn:active {
        box-shadow: 0 1px 0 #111;
        transform: translateY(3px);
      }
      .fork button {
        width: 160px;
        height: 50px;
        margin-bottom: 10px;
      }
      .log-box {
        background: #102b46;
        padding: 10px;
        border-radius: 8px;
        max-height: 200px;
        overflow-y: auto;
        font-size: 14px;
      }
      .log-item {
        margin-bottom: 4px;
      }
      .log-title {
        margin-bottom: 6px;
        font-weight: bold;
      }
      .clear-btn {
        width: auto;
        padding: 6px 12px;
        font-size: 14px;
        margin-top: 6px;
        border-radius: 6px;
        border: 2px solid #555;
        background: #444;
        color: #fff;
        cursor: pointer;
      }
      .clear-btn:active {
        box-shadow: 0 1px 0 #111;
        transform: translateY(3px);
      }
    </style>
  </head>
  <body>
    <div class="container">
      <h1>Forklift Controller Interface</h1>

      <div class="video-wrapper">
        <img src="/video" alt="Video stream">
      </div>

      <div class="controls">
        <div class="dpad">
          <div class="dpad-grid">
              <!-- Linha acima: espaço, ROT_CCW, UP, ROT_CW, espaço -->
              <div></div>
              <button class="ctrl-btn" onclick="sendAction('ROT_CCW')">⟲</button>
              <button class="ctrl-btn" onclick="sendAction('UP')">⬆️</button>
              <button class="ctrl-btn" onclick="sendAction('ROT_CW')">⟳</button>
              <div></div>

              <!-- Linha do meio -->
              <div></div>
              <button class="ctrl-btn" onclick="sendAction('LEFT')">⬅️</button>
              <div></div>
              <button class="ctrl-btn" onclick="sendAction('RIGHT')">➡️</button>
              <div></div>

              <!-- Linha de baixo -->
              <div></div>
              <div></div>
              <button class="ctrl-btn" onclick="sendAction('DOWN')">⬇️</button>
              <div></div>
              <div></div>
            </div>

        </div>

        <div class="fork">
          <button class="ctrl-btn" style="width:160px;height:50px;" onclick="sendAction('FORK_UP')">FORK UP</button><br>
          <button class="ctrl-btn" style="width:160px;height:50px;" onclick="sendAction('FORK_DOWN')">FORK DOWN</button>
        </div>
      </div>

      <div class="log-box">
        <div class="log-title">📝 Log de Ações (últimas 10)</div>
        <div id="log-list">
          {% if log %}
            {% for item in log %}
              <div class="log-item">{{ loop.index }}. {{ item }}</div>
            {% endfor %}
          {% else %}
            <div class="log-item">Nenhuma ação ainda.</div>
          {% endif %}
        </div>
        <button class="clear-btn" onclick="clearLog()">🗑️ Limpar Log</button>
      </div>
    </div>

    <script>
      async function sendAction(action) {
        try {
          const resp = await fetch("/action", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ action })
          });
          const data = await resp.json();
          if (data && data.log) {
            updateLog(data.log);
          }
        } catch (e) {
          console.error("Erro ao enviar ação:", e);
        }
      }

      async function clearLog() {
        try {
          const resp = await fetch("/clear_log", {
            method: "POST"
          });
          const data = await resp.json();
          if (data && data.log) {
            updateLog(data.log);
          }
        } catch (e) {
          console.error("Erro ao limpar log:", e);
        }
      }

      function updateLog(logArray) {
        const logDiv = document.getElementById("log-list");
        if (!logDiv) return;
        if (!logArray || logArray.length === 0) {
          logDiv.innerHTML = '<div class="log-item">Nenhuma ação ainda.</div>';
          return;
        }
        let html = "";
        logArray.forEach((item, index) => {
          html += '<div class="log-item">' + (index + 1) + '. ' + item + '</div>';
        });
        logDiv.innerHTML = html;
      }
    </script>
  </body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    # manda o log já em ordem reversa para aparecer mais recente em cima
    return render_template_string(INDEX_HTML, log=list(reversed(actions_log)))


@app.route("/action", methods=["POST"])
def action():
    """
    Quando o usuário clica nos botões, em vez de só dar print,
    mandamos um comando via WebSocket para o Raspberry.
    """
    global actions_log
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action:
        actions_log.append(action)
        actions_log = actions_log[-10:]

        # mapeia strings dos botões para comandos WebSocket
        if action in ["UP", "DOWN", "LEFT", "RIGHT"]:
            cmd = {"type": "button", "subtype": "move", "dir": action}
            send_ws_command(cmd)
        elif action == "FORK_UP":
            cmd = {"type": "button", "subtype": "fork", "action": "UP"}
            send_ws_command(cmd)
        elif action == "FORK_DOWN":
            cmd = {"type": "button", "subtype": "fork", "action": "DOWN"}
            send_ws_command(cmd)
        elif action == "ROT_CW":
            cmd = {"type": "button", "subtype": "rotate", "dir": "CW"}
            send_ws_command(cmd)
        elif action == "ROT_CCW":
            cmd = {"type": "button", "subtype": "rotate", "dir": "CCW"}
            send_ws_command(cmd)


    return jsonify({"ok": True, "log": list(reversed(actions_log))})


@app.route("/clear_log", methods=["POST"])
def clear_log():
    global actions_log
    actions_log = []
    return jsonify({"ok": True, "log": []})


if __name__ == "__main__":
    # inicia o websocket para comandos
    start_ws_thread()

    # inicia thread de captura de vídeo
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()

    # inicia o Flask
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
