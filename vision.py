
def tag_from_text(text):
    text = (text or "").lower()
    tags = set()

    if any(k in text for k in ("shirt","dress","jacket","clothes")):
        tags.add("clothing")
    if any(k in text for k in ("tool","drill","saw","wrench")):
        tags.add("tools")
    if any(k in text for k in ("tv","laptop","phone","electronics")):
        tags.add("electronics")
    if any(k in text for k in ("couch","table","chair","bed")):
        tags.add("furniture")

    if not tags:
        tags.add("misc")
    return list(tags)
