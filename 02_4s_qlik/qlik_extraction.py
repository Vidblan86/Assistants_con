# importar la api key y el tenant
import json
import os
import pandas as pd
import requests
import websocket

# 1. Traemos las credenciales del archivo config.json y las cargamos en la variable config
CONFIG_PATH = os.path.join("..","config.json")

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# 2. Definimos las fuinciones 'on_message' y 'on_open' para pasar a Qlik por websoket

def on_message(ws, msg):
    global table_handle, all_rows, page_top, total_rows, column_names

    resp = json.loads(msg)
    msg_id = resp.get("id")
    print(f"DEBUG – ID recibido: {msg_id}")
    table_id = "BCSxDL" # Tabla especifica esto deberia ser una variable recibida de qlik

    # 1) OpenDoc → GetObject (table)
    if msg_id == 1:
        doc_handle = resp["result"]["qReturn"]["qHandle"]
        ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 2, "handle": doc_handle,
            "method": "GetObject", "params": {"qId": table_id}
        }))

    # 2) GetObject → save table_handle → GetLayout
    elif msg_id == 2:
        table_handle = resp["result"]["qReturn"]["qHandle"]
        ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 3, "handle": table_handle,
            "method": "GetLayout", "params": {}
        }))

    # 3) GetLayout → extract size & column names → first GetHyperCubeData
    elif msg_id == 3:
        layout = resp["result"]["qLayout"]["qHyperCube"]
        size = layout["qSize"]
        total_rows = size["qcy"]

        # Dynamic column names from dimensionInfo & measureInfo
        dim_info  = layout["qDimensionInfo"]
        meas_info = layout["qMeasureInfo"]
        dim_names  = [d["qFallbackTitle"] for d in dim_info]
        meas_names = [m["qFallbackTitle"] for m in meas_info]
        column_names = dim_names + meas_names

        pages = [{
            "qTop":  0,
            "qLeft": 0,
            "qHeight": min(page_size, total_rows),
            "qWidth": size["qcx"]
        }]
        payload = {
            "jsonrpc": "2.0",
            "id":       4,
            "handle":   table_handle,
            "method":   "GetHyperCubeData",
            "params":  ["/qHyperCubeDef", pages]
        }
        print(f"DEBUG – Enviando GetHyperCubeData: top=0, height={pages[0]['qHeight']}")
        ws.send(json.dumps(payload))

    # 4) GetHyperCubeData → accumulate pages & paginate or finish
    elif msg_id == 4:
        page = resp["result"]["qDataPages"][0]
        matrix = page["qMatrix"]
        all_rows.extend([[c.get("qText","") for c in row] for row in matrix])
        print(f"DEBUG – Recibida página top={page_top}, filas={len(matrix)}")

        if page_top + page_size < total_rows:
            page_top += page_size
            next_pages = [{
                "qTop":    page_top,
                "qLeft":   0,
                "qHeight": min(page_size, total_rows - page_top),
                "qWidth":  page["qArea"]["qWidth"]
            }]
            print(f"DEBUG – Enviando GetHyperCubeData: top={page_top}, height={next_pages[0]['qHeight']}")
            ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id":       4,
                "handle":   table_handle,
                "method":   "GetHyperCubeData",
                "params":  ["/qHyperCubeDef", next_pages]
            }))
        else:
            # All pages received → build DataFrame & save
            df = pd.DataFrame(all_rows, columns=column_names)
            #print("Vista previa del DataFrame:")
            #print(df.head())
            #df.to_csv("tabla_qlik.csv", index=False)
            #print(">> Archivo guardado: tabla_qlik.csv")
            ws.close()
    
def on_open(ws):
    ws.send(json.dumps({
        "jsonrpc":"2.0","id":1,"handle":-1,
        "method":"OpenDoc","params":{"qDocName":APP_ID}
    }))

# 3. Conexion a qlik.

TENANT = config["Qlik_connection"]["Qlik_tenant"]
API_KEY= config["Qlik_connection"]["Qlik_4s"]

base = f"https://{TENANT}/api/v1"
headers = {"Authorization": f"Bearer {API_KEY}"}

resp = requests.get(f"{base}/apps", headers=headers)
print("Status code:", resp.status_code)
# print("Response body:", resp.text)

# 4. Definimos variables globales y forzamos APP_ID del archivo config.json para no tocar otras aplicaciones.

table_handle = None
all_rows = []
page_top = 0
page_size = 1000
total_rows = None
column_names = None  # Will be set dynamically

APP_ID = config["Qlik_connection"]["AI_chatbot_test"]

# 4.1. creamos la url para pasar a travez de websocket

url = f"wss://{TENANT}/app/{APP_ID}"

# 5. Enviamos la solicitud a click

ws = websocket.WebSocketApp(
    url,
    on_message=on_message,
    on_open=on_open,
    header=[f"Authorization: Bearer {API_KEY}", "Sec-WebSocket-Protocol: qlik.api"]
)
ws.run_forever(sslopt={"cert_reqs": 0}) # Detiene el proceso

df = ws.run_forever(sslopt={"cert_reqs": 0})

# — Construir DataFrame tras cerrar WebSocket —
df = pd.DataFrame(all_rows, columns=column_names)
print("Vista previa del DF:")
print(df)