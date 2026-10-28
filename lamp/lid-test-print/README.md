# Glowing lid: test print

Your printed lithophane discs, a black tube that holds them on the 84 mm lamp, and a set of
spacer posts for the switch. Every file is a finished OrcaSlicer project for the A1 0.4:
open it, slice it, print it, flat on the Textured PEI plate as placed. Each file uses one
filament, so you don't need the AMS or a prime tower.

## Print these

| File | Filament | Layers | Time | Filament used |
|---|---|---|---|---|
| `lid_ring.3mf`: the tube, 98.7 mm across, 29.6 mm tall | black PLA | 0.2 mm | 1 h | 34 g |
| `lid_spacers.3mf`: eight posts, 3.6 to 6.4 mm tall | white PLA | 0.2 mm | 13 min | 3 g |

Times and weights are from Orca's own slice of these files. Keep your printed discs
`lid_A_contours.3mf` and `lid_B_city.3mf` as they are. The `_v2` discs are an alternative
layout you don't need.

## The tube

See `ring_section.png`.

- **It hides the lamp.** The tube stands on the table and covers the lamp's 20 mm of height.
- **No lip over the lamp.** Nothing rests on the lamp's top, so all of the top's light reaches
  the disc. Above the lamp, the tube opens as a funnel to the disc.
- **The disc floats 6 mm above the lamp** on a post standing on the button. The higher gap lets
  the light spread out to the caption.
- **The only contact** with the disc is a narrow step under its dark outer millimetre. It sits
  0.8 mm below the disc, so a press on the map clicks the button and stops there.

`lid_B_ring_compare.jpg` shows your disc B in the old ring and in the tube, lit only by the
lamp's top. The caption reads in the tube, with the outer half of the letters still dimmer
than the map, because it sits beyond the lamp's edge.

## Finding the right post

The height is engraved on each post.

1. Put the tube over the lamp and stand the 4.8 post on the button.
2. Lay the disc in the cup and press the middle of the map.
3. If it doesn't click, try the next taller post. If the disc sits high and wobbles, try the
   next shorter one.
4. The right post lets the disc rock very slightly at rest and click when pressed.
5. Fix that post to the button with a dot of glue or clear double-sided tape, so it can't tip.

The post and button sit under the map's centre and show as a soft darker spot when lit.

## Two things to check

- **Lamp height:** the tube assumes the lamp is 20 mm tall. The posts make up for about
  1 mm either way. For a bigger difference, rerun with `--lamp-h`.
- **Charging port or switch on the side:** the tube covers the lamp's whole side. Tell me
  where a port sits and I'll cut an opening.

## The test, in a dark room

- **Disc A, the ten segments:** they start at 12 o'clock with the thinnest, 0.6 mm and
  brightest, and run clockwise to 3.2 mm, the darkest. Note the last segment you can still
  tell from its neighbour.
- **Hot spot:** check whether the light shows as a bright centre or a ring under the map.
- **Readability:** check that the route, the contour lines and the lakes read from about a metre away.
- **Disc B:** check whether the streets and the caption read, and whether the two dots of the Ü
  stay separate.
- **Photos:** take one of each disc lit, with the phone held still and the room lights off.

## Regenerate

From any folder:

```bash
python3 ~/Desktop/lid-test-print/make_lid_test.py --ring-only
```

`--ring-only` remakes the tube, the posts, the drawing and the comparison, and leaves the discs
alone. Useful options:

- `--lamp-h`: the lamp's height, which the tube covers (default 20 mm).
- `--stop` and `--float`: the stop step's height above the lamp and how far the disc can be
  pressed (defaults 5.2 and 0.8 mm, so the disc floats 6 mm up).
- `--light-d` and `--disc-d`: the lamp and disc diameters (84.0 and 94.1).

## Folders

- `sliced/` holds Orca's sliced copies with the G-code inside.
- `map_cache/` keeps the map data, so a rerun doesn't wait on Overpass.
