import json, os, websocket, time, threading

# — Cargar credenciales y APP_ID —
CONFIG_PATH = os.path.join("..", "config.json")
with open(CONFIG_PATH) as f:
    config = json.load(f)
TENANT  = config["Qlik_connection"]["Qlik_tenant"]
API_KEY = config["Qlik_connection"]["Qlik_4s"]
APP_ID  = config["Qlik_connection"]["AI_chatbot_test"]

# — Variables globales —
doc_handle   = None
timeout_secs = 10  # cierra WS si no hay respuesta en este tiempo

# — Callbacks WS —
def on_error(ws, error):
    print(f"{time.strftime('%H:%M:%S')} – ERROR: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"{time.strftime('%H:%M:%S')} – WebSocket cerrado: {close_status_code} / {close_msg}")

def stop_ws():
    print(f"{time.strftime('%H:%M:%S')} – TIMEOUT alcanzado, cerrando WS")
    ws.close()

def on_open(ws):
    print(f"{time.strftime('%H:%M:%S')} – Enviando OpenDoc")
    ws.send(json.dumps({
        "jsonrpc":"2.0","id":1,"handle":-1,
        "method":"OpenDoc","params":{"qDocName": APP_ID}
    }))

def on_message(ws, msg):
    t = time.strftime('%H:%M:%S')
    resp = json.loads(msg)
    msg_id = resp.get("id")
    print(f"{t} – Recibido msg_id={msg_id} → {json.dumps(resp, indent=2)}")

    if msg_id == 1:
        # lista hojas
        print(f"{time.strftime('%H:%M:%S')} – Enviando GetAppObjectList (sheet)")
        doc_handle = resp["result"]["qReturn"]["qHandle"]
        ws.send(json.dumps({
            "jsonrpc":"2.0","id":2,"handle":doc_handle,
            "method":"GetAppObjectList",
            "params":[{"qAppObjectListDef":{"qType":"sheet","qData":{}}}]
        }))

    elif msg_id == 2:
        print(f"{time.strftime('%H:%M:%S')} – Procesando respuesta de GetAppObjectList")
        items = resp.get("result", {}).get("qAppObjectList", {}).get("qItems", [])
        print(f"{time.strftime('%H:%M:%S')} – hojas encontradas: {len(items)}")
        # … aquí seguiría la lógica de iterar hojas …

# — Crear WS y timer —
url = f"wss://{TENANT}/app/{APP_ID}"
ws = websocket.WebSocketApp(
    url,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
    header=[
        f"Authorization: Bearer {API_KEY}",
        "Sec-WebSocket-Protocol: qlik.api"
    ]
)

# Arrancar timer y WS con ping para mantener vivo, timeout de ping a 5 s
timer = threading.Timer(timeout_secs, stop_ws)
timer.start()
ws.run_forever(sslopt={"cert_reqs": 0}, ping_interval=5, ping_timeout=2)
timer.cancel()
