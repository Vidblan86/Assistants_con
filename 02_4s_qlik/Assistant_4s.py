import os
import json
import time
import io
import pandas as pd
import requests
import websocket
from openai import OpenAI

# --- 1. Leer config y crear cliente OpenAI ---
CONFIG_PATH = os.path.join("..","config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)
OPENAI_KEY = config["Qlik_connection"]["OPENAI"]
if not OPENAI_KEY:
    raise RuntimeError("No se encontró la API key en el config.json")
client = OpenAI(api_key=OPENAI_KEY)

# --- 2. Extraer tabla de Qlik a pandas.DataFrame ---
TENANT = config["Qlik_connection"]["Qlik_tenant"]
API_KEY = config["Qlik_connection"]["Qlik_4s"]
APP_ID = config["Qlik_connection"]["AI_chatbot_test"]
table_id = "BCSxDL"   # ajusta si cambias de tabla
page_size = 1000

# globals para callbacks
all_rows = []
column_names = []
total_rows = None
table_handle = None
page_top = 0

def on_message(ws, msg):
    global table_handle, all_rows, page_top, total_rows, column_names
    resp = json.loads(msg)
    mid = resp.get("id")

    if mid == 1:
        doc_handle = resp["result"]["qReturn"]["qHandle"]
        ws.send(json.dumps({
            "jsonrpc":"2.0","id":2,"handle":doc_handle,
            "method":"GetObject","params":{"qId": table_id}
        }))

    elif mid == 2:
        table_handle = resp["result"]["qReturn"]["qHandle"]
        ws.send(json.dumps({
            "jsonrpc":"2.0","id":3,"handle":table_handle,
            "method":"GetLayout","params":{}
        }))

    elif mid == 3:
        layout = resp["result"]["qLayout"]["qHyperCube"]
        total_rows = layout["qSize"]["qcy"]
        dim_names = [d["qFallbackTitle"] for d in layout["qDimensionInfo"]]
        meas_names = [m["qFallbackTitle"] for m in layout["qMeasureInfo"]]
        column_names = dim_names + meas_names

        pages = [{"qTop":0,"qLeft":0,"qHeight":min(page_size, total_rows),"qWidth":layout["qSize"]["qcx"]}]
        ws.send(json.dumps({
            "jsonrpc":"2.0","id":4,"handle":table_handle,
            "method":"GetHyperCubeData","params":["/qHyperCubeDef", pages]
        }))

    elif mid == 4:
        page = resp["result"]["qDataPages"][0]
        matrix = page["qMatrix"]
        all_rows.extend([[c.get("qText","") for c in row] for row in matrix])

        page_top += len(matrix)
        if page_top < total_rows:
            pages = [{"qTop":page_top,"qLeft":0,"qHeight":min(page_size, total_rows-page_top),"qWidth":page["qArea"]["qWidth"]}]
            ws.send(json.dumps({
                "jsonrpc":"2.0","id":4,"handle":table_handle,
                "method":"GetHyperCubeData","params":["/qHyperCubeDef", pages]
            }))
        else:
            ws.close()

def on_open(ws):
    ws.send(json.dumps({
        "jsonrpc":"2.0","id":1,"handle":-1,
        "method":"OpenDoc","params":{"qDocName": APP_ID}
    }))

# Conexión WebSocket
base = f"https://{TENANT}/api/v1"
resp = requests.get(f"{base}/apps", headers={"Authorization":f"Bearer {API_KEY}"})
if resp.status_code!=200:
    raise RuntimeError(f"Error al listar apps: {resp.status_code}")

url = f"wss://{TENANT}/app/{APP_ID}"
ws = websocket.WebSocketApp(
    url, on_message=on_message, on_open=on_open,
    header=[f"Authorization: Bearer {API_KEY}", "Sec-WebSocket-Protocol: qlik.api"]
)
ws.run_forever(sslopt={"cert_reqs": 0})

# --- 3. Transformar a DataFrame y luego a JSON in‐memory ---
df = pd.DataFrame(all_rows, columns=column_names)
records = df.to_dict(orient="records")
json_str = json.dumps(records, ensure_ascii=False)

# --- 4. Subir este JSON como archivo “assistants” en memoria ---
bio = io.BytesIO(json_str.encode("utf-8"))
bio.name = "datos_qlik.json"
uploaded = client.files.create(file=bio, purpose="assistants")
json_file_id = uploaded.id

# --- 5. Crear assistant y thread, adjuntar JSON en lugar de PDF ---
assistant = client.beta.assistants.create(
    model="gpt-4o-mini",
    name="AssistantConTablaQlik",
    instructions=(
    "Eres un analista de datos. Responde a la pregunta más reciente usando la tabla JSON proporcionada. "
    "Responde a la pregunta más reciente usando la tabla JSON. "
    "Si la consulta requiere cálculos numéricos, invoca la herramienta `code_interpreter`, "
    "muestra el código que usaste y el resultado."
    "No repitas la respuesta a menos que se te solicite alguna aclaracion."  
    ),
    tools=[{"type":"file_search"}, {"type":"code_interpreter"}],
)

# --- 6. Crear thread inicial y adjuntar JSON ---
thread = client.beta.threads.create()
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="He subido los datos de Qlik en formato JSON, listo para preguntas.",
    attachments=[{"file_id": json_file_id, "tools":[{"type":"file_search"}, {"type":"code_interpreter"}]}],
)

'''# --- 6. Loop de chat simple (nuevo thread por pregunta opcional) ---
def preguntar(client, assistant_id, pregunta):
    t = client.beta.threads.create()
    client.beta.threads.messages.create(
        thread_id=t.id, role="user",
        content=f"Nueva pregunta: {pregunta}",
        attachments=[{"file_id": json_file_id, "tools":[{"type":"file_search"}]}],
    )
    run = client.beta.threads.runs.create(thread_id=t.id, assistant_id=assistant_id)
    for _ in range(20):
        s = client.beta.threads.runs.retrieve(thread_id=t.id, run_id=run.id)
        if s.status=="completed": break
        time.sleep(1)
    msgs = client.beta.threads.messages.list(thread_id=t.id).data
    return next((m.content[0].text.value for m in reversed(msgs) if m.role=="assistant"), None)

while True:
    q = input("Tú: ").strip()
    if not q:
        print("Cerrando chat."); break
    resp = preguntar(client, assistant.id, q)
    print("Assistant:", resp or "[sin respuesta]")
'''

# --- 7. Chat reusando el mismo thread y seleccionando siempre la respuesta en índice 0 ---
def chat(client, assistant_id, thread_id, file_id):
    while True:
        pregunta = input("\nTú: ").strip()
        if not pregunta:
            print("Cerrando chat.")
            break

        # enviar mensaje con attachments
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=pregunta,
            attachments=[{"file_id": file_id, "tools":[{"type":"file_search"}, {"type":"code_interpreter"}]}],
        )
        # ejecutar assistant
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
        for _ in range(30):
            status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if status.status == "completed": break
            time.sleep(1)

        # extraer la primera respuesta de assistant (índice 0)
        msgs = client.beta.threads.messages.list(thread_id=thread_id).data
        if msgs and msgs[0].role == 'assistant' and msgs[0].content:
            resp = msgs[0].content[0].text.value
        else:
            resp = "[sin respuesta]"
        print("-----------\nAssistant:", resp)

# iniciar chat
chat(client, assistant.id, thread.id, json_file_id)
