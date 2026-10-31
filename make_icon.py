from PIL import Image

img = Image.open("ELNOC.png")
if img.mode != "RGBA":
    img = img.convert("RGBA")
print("source:", img.size, img.mode)

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# Handle non-square sources: fit onto a padded transparent square canvas
longest = max(img.size)
aside_start = 30  # tiny margin against edge-bleed in Explorer views
target = max(longest + 2 * aside_start, 256)
side = max(img.size) + 2 * aside_start

square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
x = (side - img.width) // 2
y = (side - img.height) // 2
square.paste(img, (x, y), img)

# trim target square if padding made it bigger than the max frame
if side > max(s for s, _ in sizes) * 4:
    pass
square.save("ELNOC.ico", format="ICO", sizes=sizes)
print("wrote ELNOC.ico  (canvas", side, "px)")
