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
    try:  # AttributeError: valid JSON that isn't an object, e.g. "5" or "[1]"
        kw = {k: v for k, v in json.loads(params).items() if k in _ALLOWED}
        track = core.parse_track(file.filename or "", await file.read())
    except (ValueError, AttributeError) as e:
        raise HTTPException(400, str(e))
    try:
        frame_bodies, bodies, path_stl = core.build_poster(track, core.Params(**kw))
        frame_3mf, relief_3mf = core.write_3mf(frame_bodies), core.write_3mf(bodies)
    except Exception as e:  # DEM/land-cover fetch or meshing failed
        raise HTTPException(502, f"Generation failed: {e}")
    b64 = lambda d: base64.b64encode(d).decode()
    return {"frame": b64(frame_3mf), "relief": b64(relief_3mf), "path": b64(path_stl)}


app.mount("/", StaticFiles(directory="static", html=True))
