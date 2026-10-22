"""Vendor the A1 0.4 / 0.24 Draft / Bambu PLA Basic system profiles as orca_a1_pla.json.

    uv run python orca_profile.py      # after an OrcaSlicer update, then commit the json

Orca fills a loaded project config from compiled defaults and then applies it as
"(modified)" edits over the preset print_settings_id names, so a partial
project_settings.config would blank machine_start_gcode and every other key it
omits. write_3mf therefore embeds the whole flattened chain, as Orca writes it."""
import json

BBL = "/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL"
DROP = {"type", "name", "inherits", "from", "setting_id", "instantiation", "description",
        "compatible_printers", "compatible_printers_condition", "compatible_prints",
        "compatible_prints_condition", "filament_id", "filament_settings_id",
        "print_settings_id", "printer_settings_id"}


def flatten(kind, name):
    """One system profile with its inherits chain folded in, child keys winning."""
    with open(f"{BBL}/{kind}/{name}.json") as f:
        d = json.load(f)
    out = flatten(kind, d["inherits"]) if "inherits" in d else {}
    out.update(d)
    return {k: v for k, v in out.items() if k not in DROP}


if __name__ == "__main__":
    with open("orca_a1_pla.json", "w") as f:
        json.dump({"machine": flatten("machine", "Bambu Lab A1 0.4 nozzle"),
                   "process": flatten("process", "0.24mm Draft @BBL A1"),
                   "filament": flatten("filament", "Bambu PLA Basic @BBL A1")}, f, indent=1)
