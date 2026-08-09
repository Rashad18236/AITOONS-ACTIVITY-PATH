"""Flight Path Poster — local web app. Run: uv run uvicorn app:app"""
import base64, json
from dataclasses import asdict, fields
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
        p0 = core.Params(**kw)
        p = core.resolve(p0)   # blank fields auto-scale; the preview needs the values
        # p0, not p: build_poster resolves anyway (idempotent), and an over-plate
        # refusal has to suggest a smaller size against the AUTO chin, which shrinks
        # with the poster. Handed the resolved p it would freeze the 250mm chin and
        # suggest 246.3mm — a size that is still over the plate once it rescales.
        frame_bodies, bodies, path_stl = core.build_poster(track, p0)
        frame_3mf, relief_3mf = core.write_3mf(frame_bodies), core.write_3mf(bodies)
    except Exception as e:  # DEM/land-cover fetch or meshing failed
        raise HTTPException(502, f"Generation failed: {e}")
    b64 = lambda d: base64.b64encode(d).decode()
    return {"frame": b64(frame_3mf), "relief": b64(relief_3mf), "path": b64(path_stl),
            "resolved": asdict(p)}


app.mount("/", StaticFiles(directory="static", html=True))
