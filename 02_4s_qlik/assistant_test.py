import os
import json
import time
from openai import OpenAI

# --- carga config y cliente ---
CONFIG_PATH = os.path.join("..", "..", "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)
openAI_api_key = config["Qlik_connection"]["OPENAI"]
if not openAI_api_key:
    raise RuntimeError("No se encontró la API key en el config.json")
client = OpenAI(api_key=openAI_api_key)

# --- subir el PDF ---
pdf_path = os.path.join("..", "..", "Minuta Contrato Obra 001-2024 GERCOTEK INGENIERIA S.A.S. Alcaldia Martires (1).pdf")
with open(pdf_path, "rb") as f:
    uploaded = client.files.create(file=f, purpose="assistants")
file_id = uploaded.id

# --- crear el assistant ---
assistant = client.beta.assistants.create(
    model="gpt-4o-mini",
    name="AssistantConPDF",
    instructions=(
        "Responde únicamente a la pregunta más reciente usando el PDF como contexto. "
        "No repitas respuestas anteriores a menos que se te pida explícitamente aclararlas."
    ),
    tools=[{"type": "file_search"}],
)

# --- crear thread y adjuntar el PDF una vez ---
thread = client.beta.threads.create()
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="He subido el contrato en PDF, estoy listo para hacer preguntas sobre él.",
    attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}],
)

# --- funciones ---
def preguntar_en_nuevo_thread(client, assistant_id, pregunta):
    # crear thread limpio
    thread = client.beta.threads.create()

    # adjuntar el PDF con la pregunta y forzar foco en esa única pregunta
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=f"Nueva pregunta (ignora todo lo anterior): {pregunta}",
        attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}],
    )

    # ejecutar
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant_id)

    # esperar
    for _ in range(20):
        status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if status.status == "completed":
            break
        time.sleep(1)

    # leer respuesta
    messages = client.beta.threads.messages.list(thread_id=thread.id).data
    for msg in reversed(messages):
        if msg.role == "assistant":
            try:
                return msg.content[0].text.value
            except:
                return "[respuesta con estructura inesperada]"
    return None


def chat_con_assistant_simple(client, assistant_id, thread_id):
    while True:
        pregunta_usuario = input("Tú: ").strip()
        if not pregunta_usuario:
            print("Cerrando chat.")
            break

        respuesta = preguntar_en_nuevo_thread(client, assistant_id, pregunta_usuario)
        print("\nAssistant:", respuesta + "\n" or "[sin respuesta]")

# --- iniciar interacción ---
chat_con_assistant_simple(client, assistant.id, thread.id)
