"""Activity Path Poster — local web app. Run: uv run uvicorn app:app"""
import base64, json
from dataclasses import asdict, fields
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
import activity
import poster as core

app = FastAPI()
_ALLOWED = {f.name for f in fields(core.Params)}


@app.post("/generate")
async def generate(files: list[UploadFile], params: str = Form("{}"),
                   workout_date: str = Form(""), workout_time: str = Form("")):
    # The uploads are the customer's: read in place (f.file, never `await f.read()` — a
    # Health export can be GB), never written anywhere by us, and closed before we return.
    try:
        try:  # AttributeError: valid JSON that isn't an object, e.g. "5" or "[1]"
            kw = {k: v for k, v in json.loads(params).items() if k in _ALLOWED}
        except (ValueError, AttributeError) as e:
            raise HTTPException(400, str(e))
        # The shop sells three sizes and each is known to fit the plate with any caption
        # it can carry (poster.SIZES_MM). Anything else is a typo or a hand-rolled POST,
        # refused before a multi-GB export is read for nothing.
        if kw.get("size_mm", core.Params.size_mm) not in core.SIZES_MM:
            raise HTTPException(400, "Poster size must be one of "
                                     f"{', '.join(f'{s:g}' for s in core.SIZES_MM)}mm")
        try:
            legs = activity.read_activity([(f.filename or "", f.file) for f in files],
                                          workout_date, workout_time)
        except ValueError as e:   # names the file and what is wrong with it
            raise HTTPException(400, str(e))
        p0 = core.Params(**kw)
        try:
            p = core.resolve(p0)   # blank fields auto-scale; the preview needs the values
            # p0, not p: build_poster resolves anyway (idempotent), and an over-plate
            # refusal has to suggest a smaller size against the AUTO chin, which shrinks
            # with the poster. Handed the resolved p it would freeze the 250mm chin and
            # suggest 246.3mm — a size that is still over the plate once it rescales.
            frame, relief, path_files = core.build_poster(legs, p0)
            # finished OrcaSlicer projects (A1 0.4), every print setting embedded
            b64 = lambda bodies: base64.b64encode(core.write_3mf(bodies)).decode()
            out = {"frame": b64(frame), "relief": b64(relief),
                   "paths": {stem: b64(bodies) for stem, bodies in path_files}}
        except ValueError as e:   # an input check (size, chin, slot): the order, not the server
            # ponytail: any ValueError is a 400, a meshing bug raising one included; give
            # the input checks their own exception type if that ever misleads the operator
            raise HTTPException(400, str(e))
        except Exception as e:  # DEM/land-cover fetch or meshing failed
            raise HTTPException(502, f"Generation failed: {e}")
    finally:
        for f in files:
            await f.close()
    return {**out, "resolved": asdict(p), "legs": activity.legs_note(legs)}


@app.get("/dimensions")
def dimensions(size_mm: float = core.Params.size_mm, text: str = "", text2: str = ""):
    """Frame footprint for the live UI line under the size field. resolve + _grid
    only — no meshing, so it is instant. Nothing else in Params moves the footprint."""
    p0 = core.Params(size_mm=size_mm, text=text, text2=text2)
    p = core.resolve(p0)
    w, h = core.footprint_mm(p)
    return {"width": w, "height": h, "chin_mm": p.chin_mm,
            "fits": max(w, h) <= core.USABLE_MM, "max_size_mm": core.max_size_mm(p0)}


app.mount("/", StaticFiles(directory="static", html=True))
