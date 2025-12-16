#!/usr/bin/env python3
import asyncio
import json
import websockets
import subprocess
import signal
import time
import pigpio
import RPi.GPIO as GPIO

HOST = "0.0.0.0"
PORT = 6789

# CONFIG DO STREAM DE VÍDEO
PC_IP = "192.168.14.38"
UDP_PORT = 5000

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30

video_proc = None

# CONFIG DOS MOTORES DC (pigpio)
PWM_PIN = 19
IN1 = 7
IN2 = 16

PWM_PIN2 = 13
IN3 = 25
IN4 = 8

FREQ = 1000
DUTY_80 = 800000
MOVE_TIME_S = 0.5

# CONFIG DO MOTOR DE PASSO
DIR_PIN = 22
STEP_PIN = 27
STEPS_PER_REV = 400
STEP_DELAY = 0.0025  # 2.5 ms

# Inicializa pigpio
pi = pigpio.pi()
if not pi.connected:
    raise SystemExit("Erro: rode 'sudo pigpiod' primeiro.")

pi.set_mode(PWM_PIN, pigpio.OUTPUT)
pi.set_mode(IN1, pigpio.OUTPUT)
pi.set_mode(IN2, pigpio.OUTPUT)
pi.set_mode(PWM_PIN2, pigpio.OUTPUT)
pi.set_mode(IN3, pigpio.OUTPUT)
pi.set_mode(IN4, pigpio.OUTPUT)

# Inicializa GPIO para o motor de passo
GPIO.setmode(GPIO.BCM)
GPIO.setup(DIR_PIN, GPIO.OUT)
GPIO.setup(STEP_PIN, GPIO.OUT)

# FUNÇÕES MOTOR DC
def motor_forward(duty=DUTY_80):
    pi.write(IN1, 1)
    pi.write(IN2, 0)
    pi.write(IN3, 1)
    pi.write(IN4, 0)
    pi.hardware_PWM(PWM_PIN, FREQ, duty)
    pi.hardware_PWM(PWM_PIN2, FREQ, duty)
    print("[MOTOR] Frente (DC)")

def motor_reverse(duty=DUTY_80):
    pi.write(IN1, 0)
    pi.write(IN2, 1)
    pi.write(IN3, 0)
    pi.write(IN4, 1)
    pi.hardware_PWM(PWM_PIN, FREQ, duty)
    pi.hardware_PWM(PWM_PIN2, FREQ, duty)
    print("[MOTOR] Ré (DC)")

def motor_cw(duty=DUTY_80):
    pi.write(IN1, 1)
    pi.write(IN2, 0)
    pi.write(IN3, 0)
    pi.write(IN4, 1)
    pi.hardware_PWM(PWM_PIN, FREQ, duty)
    pi.hardware_PWM(PWM_PIN2, FREQ, duty)
    print("[MOTOR] ROTATE CW (DC)")

def motor_ccw(duty=DUTY_80):
    pi.write(IN1, 0)
    pi.write(IN2, 1)
    pi.write(IN3, 1)
    pi.write(IN4, 0)
    pi.hardware_PWM(PWM_PIN, FREQ, duty)
    pi.hardware_PWM(PWM_PIN2, FREQ, duty)
    print("[MOTOR] ROTATE CCW (DC)")

def motor_stop():
    pi.hardware_PWM(PWM_PIN, 0, 0)
    pi.hardware_PWM(PWM_PIN2, 0, 0)
    pi.write(IN1, 0)
    pi.write(IN2, 0)
    pi.write(IN3, 0)
    pi.write(IN4, 0)
    print("[MOTOR] Parado (DC)")


# FUNÇÃO MOTOR DE PASSO (NOVO)
def girar_stepper(sentido_horario: bool):
    """Gira 1 volta completa do motor de passo."""
    GPIO.output(DIR_PIN, GPIO.HIGH if sentido_horario else GPIO.LOW)

    print(f"[STEPPER] Girando {'horário' if sentido_horario else 'anti-horário'}")

    for _ in range(STEPS_PER_REV):
        GPIO.output(STEP_PIN, GPIO.HIGH)
        time.sleep(STEP_DELAY)
        GPIO.output(STEP_PIN, GPIO.LOW)
        time.sleep(STEP_DELAY)

    print("[STEPPER] 1 volta completa concluída.")


#HANDLERS
async def handle_button(cmd: dict):
    subtype = cmd.get("subtype")

    if subtype == "move":
        direction = cmd.get("dir")
        print(f"[BUTTON] Comando de movimento recebido: {direction}")

        if isinstance(direction, str):
            d = direction.upper()
        else:
            d = ""

        if d == "UP":
            motor_forward(DUTY_80)
            await asyncio.sleep(MOVE_TIME_S)
            motor_stop()

        elif d == "DOWN":
            motor_reverse(DUTY_80)
            await asyncio.sleep(MOVE_TIME_S)
            motor_stop()

        elif d == "ROT_CW":
            motor_cw(DUTY_80)
            await asyncio.sleep(MOVE_TIME_S)
            motor_stop()

        elif d == "ROT_CCW":
            motor_ccw(DUTY_80)
            await asyncio.sleep(MOVE_TIME_S)
            motor_stop()


        elif d in ("STOP", "PARAR"):
            motor_stop()

        else:
            print("[MOTOR] Direção desconhecida:", direction)

    elif subtype == "fork":
        action = cmd.get("action")
        print(f"[BUTTON] Controle do garfo: {action}")

        if isinstance(action, str):
            a = action.upper()
        else:
            a = ""

        # CONTROLE DO MOTOR DE PASSO
        if a == "UP":
            girar_stepper(sentido_horario=True)   # sentido horário
        elif a == "DOWN":
            girar_stepper(sentido_horario=False)  # sentido anti-horário
        else:
            print("[STEPPER] Ação desconhecida:", action)

    else:
        print("[BUTTON] Subtipo desconhecido:", cmd)


async def handle_apriltag(cmd: dict):
    print("\n[APRILTAG]", cmd)


async def handle_message(message: str, websocket):
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        print("[WS] Mensagem inválida:", message)
        return

    if data.get("type") == "button":
        await handle_button(data)
    elif data.get("type") == "apriltag":
        await handle_apriltag(data)
    else:
        print("[WS] Tipo desconhecido:", data)


async def client_handler(websocket):
    print("[WS] Cliente conectado:", websocket.remote_address)
    try:
        async for message in websocket:
            await handle_message(message, websocket)
    except websockets.ConnectionClosed:
        print("[WS] Cliente desconectado:", websocket.remote_address)


# CONTROLE DO VÍDEO
def start_video_stream():
    global video_proc
    if video_proc is not None and video_proc.poll() is None:
        print("[VIDEO] Já rodando.")
        return

    udp_url = f"udp://{PC_IP}:{UDP_PORT}"
    cmd = [
        "rpicam-vid", "--inline",
        "--codec", "h264",
        "--width", str(VIDEO_WIDTH),
        "--height", str(VIDEO_HEIGHT),
        "--framerate", str(VIDEO_FPS),
        "-t", "0",
        "-o", udp_url,
    ]

    try:
        video_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
        )
        time.sleep(1)
        print("[VIDEO] Stream iniciado:", udp_url)
    except Exception as e:
        print("[VIDEO] ERRO:", e)


def stop_video_stream():
    global video_proc
    if video_proc and video_proc.poll() is None:
        video_proc.terminate()
        time.sleep(1)
    video_proc = None


# MAIN
async def main():
    print(f"[WS] Servidor ativo em ws://{HOST}:{PORT}")

    start_video_stream()

    async with websockets.serve(client_handler, HOST, PORT):
        try:
            await asyncio.Future()
        finally:
            stop_video_stream()
            motor_stop()
            GPIO.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Encerrado pelo usuário.")
    finally:
        stop_video_stream()
        motor_stop()
        GPIO.cleanup()
        pi.stop()
        print("[GERAL] Encerrado com segurança.")
