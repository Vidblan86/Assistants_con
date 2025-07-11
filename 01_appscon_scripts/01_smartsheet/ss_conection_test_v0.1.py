# ss_conection_test_v0.1.py

import os
# 🔧 evita el error de OpenMP
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import smartsheet
import pandas as pd
import torch
import json

#from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

CONFIG_PATH = os.path.join("..","..","..","config.json")

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

def cargar_dataframe(sheet_id: str):
    token = config["SS_Assistants"]["Smartsheet"]
    if not token:
        raise RuntimeError("Define SMARTSHEET_TOKEN en el entorno")
    client = smartsheet.Smartsheet(token)
    sheet = client.Sheets.get_sheet(sheet_id)
    cols = [c.title for c in sheet.columns]
    data = []
    for row in sheet.rows:
        row_data = {col: cell.value for col, cell in zip(cols, row.cells)}
        data.append(row_data)
    return pd.DataFrame(data)


def cargar_modelo():
    # Cambia aquí a flan-t5-base si luego lo deseas
    tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-large")
    model = AutoModelForSeq2SeqLM.from_pretrained(
    "google/flan-t5-large",
    torch_dtype=torch.float16,
    device_map="auto"
    )
    return tokenizer, model

def answer_question(df, tokenizer, model, pregunta):
    # Contexto reducido: solo column "Concepto"
    serie = df["Concepto"].dropna().astype(str).head(50)
    context = "\n".join(serie)
    prompt = (
        "Estos son valores de la columna 'Concepto':\n"
        f"{context}\n\n"
        f"Pregunta: {pregunta}\n"
        "Respuesta (en español):"
    )
    print("\n=== Prompt ===\n", prompt)

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = {k: v.to(device) for k, v in inputs.items()}
    outputs = model.generate(
    **inputs,
    max_new_tokens=100,       # límite de tokens generados
    num_beams=5,              # beam search para mejor calidad
    temperature=0.7,          # controla aleatoriedad
    no_repeat_ngram_size=2    # evita repeticiones
    )   
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

if __name__ == "__main__":
    SHEET_ID = "GhQRHWJvqh9P33wf87FRW75cRf3WFpPv3cGC3vq1"
    df = cargar_dataframe(SHEET_ID)
    df = df.tail(50)
    tok, mdl = cargar_modelo()

    while True:
        q = input("\nPregunta ('salir' para terminar): ")
        if q.strip().lower() in ("salir", "exit"):
            break
        respuesta = answer_question(df, tok, mdl, q)
        print("\nRespuesta:", respuesta)