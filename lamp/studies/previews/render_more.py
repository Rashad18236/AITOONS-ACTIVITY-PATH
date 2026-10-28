"""Round 2 palettes: rooms, industrial design, nature, running culture. Renders the
three test scenes for every new theme (reuses render_previews' machinery)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_previews as R
import activity, poster

ST, TR, RL, BL = "streets", "trails", "rail", "buildings"
T2 = {
 # rooms
 "scandi_oak":   dict(label="Scandinavian — oak and linen",        frame="#C9A97A", text="#2B2B2B", land="#EFE9DD", water="#9DB8C8", band="#D8D1C3", detail="#8C8577", path="#2F3A45", groups={ST, TR}),
 "japandi":      dict(label="Japandi — clay and charcoal",         frame="#3A3A38", text="#EAE3D6", land="#D9C9B3", water="#7A9AA6", band="#B9B0A2", detail="#5B5651", path="#B5543A", groups={ST, TR}),
 "bauhaus":      dict(label="Bauhaus — primaries on white",        frame="#111111", text="#FFFFFF", land="#F2F0EB", water="#1F4FBF", band=None,      detail="#111111", path="#E63312", groups={ST, BL}, legs=("#FFFFFF", "#E63312", "#F2C300")),
 "concrete":     dict(label="Brutalist — raw concrete",            frame="#6E6E6A", text="#F4F4F2", land="#B8B6B0", water="#52606D", band="#D5D3CD", detail="#3C3C3A", path="#FF4F1F", groups={ST, BL}),
 "gallery":      dict(label="Gallery white — sculpture relief",    frame="#F7F7F5", text="#1A1A1A", land="#FFFFFF", water="#E6E6E3", band=None,      detail=None,      path="#1A1A1A", groups=set()),
 # industrial design
 "rams":         dict(label="Greige and signal orange",            frame="#D7D2C8", text="#222222", land="#E8E4DC", water="#8FA3AD", band="#C8C3B9", detail="#4A4845", path="#F26419", groups={ST, RL}),
 "steel_brass":  dict(label="Blackened steel and brass",           frame="#1C1C1C", text="#C9A961", land="#3B3D40", water="#23303A", band="#6B6E72", detail="#8A8D91", path="#C9A961", groups={ST}),
 "verdigris":    dict(label="Copper and verdigris",                frame="#2E2A26", text="#E6D2B8", land="#4F8A7B", water="#2C5F6E", band="#9FB9AE", detail="#B87333", path="#E07A3F", groups={TR, ST}),
 "workshop":     dict(label="Workshop — plywood and safety yellow", frame="#D9B77E", text="#1E1E1E", land="#E7DCC3", water="#6E8FA6", band="#C9BFA7", detail="#2B2B2B", path="#FFC400", groups={ST, RL, BL}),
 # nature
 "sandstone":    dict(label="Desert sandstone",                    frame="#5A3E2B", text="#F5E9D6", land="#E2B98A", water="#4F8FB0", band="#A96F4B", detail="#7A5236", path="#1F3A5F", groups={TR, ST}),
 "ocean":        dict(label="Ocean and coral",                     frame="#0B2A3A", text="#F3F6F7", land="#1E5F74", water="#58C1D3", band="#E4E9EC", detail="#0B2A3A", path="#FF6F61", groups={ST}),
 "larch":        dict(label="Autumn larch",                        frame="#2E2419", text="#F3E5C8", land="#6B6F3F", water="#4A7C9B", band="#D9A441", detail="#3C2F23", path="#C73E1D", groups={TR}),
 "glacier":      dict(label="Glacier ice",                         frame="#DDE7EE", text="#0E2A3F", land="#CFE0EA", water="#4A8FB8", band="#F6FBFD", detail="#7E96A6", path="#FF3B30", groups={TR, ST}),
 "moss_slate":   dict(label="Moss and slate",                      frame="#2F3A34", text="#DDE6D9", land="#5C7A5A", water="#3F6B86", band="#7E8686", detail="#B9C0B4", path="#F2E394", groups={TR, ST}),
 "blue_hour":    dict(label="Blue hour — sodium lights",           frame="#141A2E", text="#F7D5A8", land="#2B3A5C", water="#0F1E3A", band="#8B9BC4", detail="#52648C", path="#F7A541", groups={ST}),
 "volcanic":     dict(label="Volcanic — basalt and ember",         frame="#0D0D0D", text="#FFB37A", land="#262323", water="#3A4A55", band="#5E5957", detail="#8A7F79", path="#FF4D00", groups={TR, ST}),
 # running culture
 "track":        dict(label="Running track — oxide red",           frame="#1A1A1A", text="#FFFFFF", land="#B33A2E", water="#2C6FAA", band=None,      detail="#F2E7D5", path="#FFFFFF", groups={ST, BL}, legs=("#FFFFFF", "#F2E7D5", "#FFD60A")),
 "neon_kit":     dict(label="Race kit — volt on black",            frame="#0A0A0A", text="#CCFF00", land="#171717", water="#1C2B3A", band=None,      detail="#3A3A3A", path="#CCFF00", groups={ST}, legs=("#FF2D95", "#CCFF00", "#00E0FF")),
 "retro_70s":    dict(label="Retro seventies stripes",             frame="#F4E3C1", text="#2B2118", land="#E9D8B4", water="#4C86A8", band="#C9A86A", detail="#A6553D", path="#C8102E", groups={ST, TR}, legs=("#C8102E", "#F28C28", "#2E6B5E")),
 "night_run":    dict(label="Night run — reflective silver",       frame="#0F1115", text="#E8E8E8", land="#1B1F26", water="#0B2540", band=None,      detail="#C0C0C0", path="#FFD60A", groups={ST}),
 "medal":        dict(label="Finisher medal — bronze on navy",     frame="#0F2238", text="#CD7F32", land="#16304D", water="#0A1A2E", band="#345E85", detail="#5C7FA3", path="#CD7F32", groups={ST}),
 "chalk":        dict(label="Chalk and charcoal",                  frame="#2B2B2B", text="#F2F2F0", land="#F2F2F0", water="#BFC7CC", band="#DADAD6", detail="#2B2B2B", path="#2B2B2B", groups={ST, TR}, legs=("#2B2B2B", "#6B6B6B", "#A6A6A6")),
}
R.T.update(T2)

def main():
    scenes = {
        "zermatt": (activity.read_activity([("z.gpx", open(os.path.expanduser("~/Desktop/zermatt-trail-run/Zermatt_Trail_Run.gpx"), "rb"))]),
                    ("ZERMATT TRAIL RUN", "14.2 KM · +1735 M · 15.08.2026")),
        "zurich_tri": (activity.read_activity([("t.fit", open(os.path.expanduser("~/Desktop/activity-poster-demo/zurich-triathlon.fit"), "rb"))]),
                       ("ZÜRICH TRIATHLON 2026", "3.8 · 180 · 42.2")),
        "zurich_city": (R.city_loop(), ("ZÜRICH CITY 5K", "ALTSTADT · 05.04.2026")),
    }
    for key, (legs, cap) in scenes.items():
        b, walls = R.scene_bounds(legs)
        mpm = R.m_per_mm(b)
        elev = poster.fetch_elevation(b, R.PX)
        els = R.fetch(b)
        print(key, f"{mpm:.1f} m/mm")
        for theme, t in T2.items():
            M = R.masks(els, b, t["groups"], mpm)
            R.compose(theme, elev, M, walls, b, caption=cap).save(f"{R.OUT}/{key}__{theme}.png", optimize=True)
        print("  rendered", len(T2))
    print("done")

if __name__ == "__main__":
    main()
