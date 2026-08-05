"""Flight Path Poster — local web app. Run: uv run uvicorn app:app"""
import base64, json
from dataclasses import fields
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
import poster as core

app = FastAPI()
_ALLOWED = {f.name for f in fields(core.Params)}


@app.post("/generate")
async def generate(file: UploadFile, params: str = Form("{}")):
    kw = {k: v for k, v in json.loads(params).items() if k in _ALLOWED}
    try:
        track = core.parse_track(file.filename or "", await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        stl_poster, stl_strip = core.build_poster(track, core.Params(**kw))
    except Exception as e:  # DEM fetch or meshing failed
        raise HTTPException(502, f"Generation failed: {e}")
    return {"poster": base64.b64encode(stl_poster).decode(),
            "path": base64.b64encode(stl_strip).decode()}


app.mount("/", StaticFiles(directory="static", html=True))
