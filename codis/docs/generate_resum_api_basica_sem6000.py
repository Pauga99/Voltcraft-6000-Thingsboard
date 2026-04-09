from pathlib import Path


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 50

TITLE_SIZE = 18
HEADING_SIZE = 14
METHOD_NAME_SIZE = 12
BODY_SIZE = 11
CODE_SIZE = 10

TITLE_GAP = 12
HEADING_GAP = 8
METHOD_NAME_GAP = 6
BODY_GAP = 5
CODE_GAP = 4

LIBRARY_PATH = r"r:\Codis\github2\python3-voltcraft-sem6000"
OUTPUT_PATH = Path(__file__).with_name("resum_api_basica_sem6000.pdf")

STYLE_SPECS = {
    "title": {"font": "bold", "size": TITLE_SIZE, "gap": TITLE_GAP},
    "heading": {"font": "bold", "size": HEADING_SIZE, "gap": HEADING_GAP},
    "method_name": {"font": "bold", "size": METHOD_NAME_SIZE, "gap": METHOD_NAME_GAP},
    "body": {"font": "regular", "size": BODY_SIZE, "gap": BODY_GAP},
    "code": {"font": "regular", "size": CODE_SIZE, "gap": CODE_GAP},
    "blank": {"gap": BODY_GAP},
    "code_blank": {"gap": CODE_GAP},
}


def approximate_line_width(font_size):
    usable_width = PAGE_WIDTH - (2 * MARGIN)
    return max(30, int(usable_width / (font_size * 0.55)))


def approximate_text_width(text, font_size):
    return len(text) * font_size * 0.55


def escape_pdf_text(text):
    encoded = text.encode("cp1252", errors="replace")
    escaped = []

    for byte in encoded:
        if byte in (40, 41, 92):
            escaped.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03o}")

    return "".join(escaped)


def wrap_text(text, font_size, prefix=""):
    if not text:
        return [prefix.rstrip()]

    limit = approximate_line_width(font_size)
    if len(prefix) >= limit - 10:
        prefix = ""

    continuation = " " * len(prefix)
    words = text.split()
    lines = []
    current = prefix

    for word in words:
        candidate = word if current.strip() == "" else current + " " + word
        if len(candidate) <= limit:
            current = candidate
            continue

        if current.strip():
            lines.append(current)
            current = continuation + word
        else:
            while len(word) > limit:
                lines.append(word[:limit])
                word = word[limit:]
            current = continuation + word

    if current:
        lines.append(current)

    return lines


def build_methods():
    return [
        {
            "anchor": "method_discover",
            "name": "SEM6000.discover(timeout=5, bluetooth_device='hci0')",
            "what": (
                "Escaneja l'entorn Bluetooth i retorna una llista de dispositius "
                "compatibles amb el servei del SEM6000."
            ),
            "params": [
                "timeout: segons d'espera per detectar dispositius.",
                "bluetooth_device: interface Bluetooth a utilitzar, habitualment hci0.",
            ],
            "returns": "Retorna una llista de diccionaris amb claus com name i address.",
            "example": [
                "devices = sem6000.SEM6000.discover()",
                "for device in devices:",
                "    print(device['name'], device['address'])",
            ],
            "notes": (
                "Pot requerir permisos elevats segons el sistema. Si no hi ha cap "
                "dispositiu visible, la llista pot ser buida."
            ),
        },
        {
            "anchor": "method_init",
            "name": "SEM6000(deviceAddr=None, pin=None, bluetooth_device='hci0', timeout=5, debug=False)",
            "what": (
                "Crea el client principal. Si passes deviceAddr, intenta connectar "
                "de seguida. Si tambe passes pin, intenta autoritzar-se."
            ),
            "params": [
                "deviceAddr: MAC del dispositiu, per exemple 00:11:22:33:44:55.",
                "pin: PIN de 4 digits, per exemple 0000.",
                "bluetooth_device: interface Bluetooth.",
                "timeout: temps maxim d'espera per resposta.",
                "debug: si es True, escriu informacio de depuracio a stderr.",
            ],
            "returns": "Retorna una instancia de la classe SEM6000.",
            "example": [
                "device = sem6000.SEM6000('00:11:22:33:44:55', pin='0000', debug=True)",
            ],
            "notes": "Si la connexio o l'autoritzacio fallen, es llancara una excepcio.",
        },
        {
            "anchor": "method_connect",
            "name": "connect(device_address)",
            "what": "Connecta el client actual a una MAC concreta.",
            "params": [
                "device_address: adreca MAC del dispositiu que vols obrir.",
            ],
            "returns": "Retorna el resultat intern de la reconnexio si tot va be.",
            "example": [
                "device = sem6000.SEM6000()",
                "device.connect('00:11:22:33:44:55')",
            ],
            "notes": "No autoritza per si sol. Despres cal cridar authorize(pin) si cal.",
        },
        {
            "anchor": "method_authorize",
            "name": "authorize(pin)",
            "what": "Envia el PIN al dispositiu connectat i valida l'acces.",
            "params": [
                "pin: codi de 4 digits del dispositiu.",
            ],
            "returns": "Retorna un AuthorizedNotification si l'autenticacio te exit.",
            "example": [
                "device.authorize('0000')",
            ],
            "notes": (
                "Si el PIN es incorrecte o el dispositiu no respon, es llanca una "
                "excepcio d'autenticacio."
            ),
        },
        {
            "anchor": "method_request_name",
            "name": "request_device_name()",
            "what": "Llegeix el nom configurat al dispositiu remot.",
            "params": [
                "Sense parametres.",
            ],
            "returns": (
                "Retorna un DeviceNameRequestedNotification amb la propietat device_name."
            ),
            "example": [
                "name_info = device.request_device_name()",
                "print(name_info.device_name)",
            ],
            "notes": "Serveix per identificar el dispositiu sense canviar-ne l'estat.",
        },
        {
            "anchor": "method_power_on",
            "name": "power_on()",
            "what": "Activa el rele i dona pas de corrent a la sortida de l'endoll.",
            "params": [
                "Sense parametres.",
            ],
            "returns": "Retorna un PowerSwitchedNotification si el canvi te exit.",
            "example": [
                "device.power_on()",
            ],
            "notes": "Llanca una excepcio si el dispositiu rebutja l'ordre.",
        },
        {
            "anchor": "method_power_off",
            "name": "power_off()",
            "what": "Desactiva el rele i talla el corrent a la sortida.",
            "params": [
                "Sense parametres.",
            ],
            "returns": "Retorna un PowerSwitchedNotification si el canvi te exit.",
            "example": [
                "device.power_off()",
            ],
            "notes": "Es l'equivalent de power_on(), pero per apagar l'endoll.",
        },
        {
            "anchor": "method_measurement",
            "name": "request_measurement()",
            "what": (
                "Demana els valors electrics actuals: consum, tensio, corrent, "
                "frequencia i consum total acumulat."
            ),
            "params": [
                "Sense parametres.",
            ],
            "returns": "Retorna un MeasurementRequestedNotification, no un diccionari.",
            "example": [
                "measurement = device.request_measurement()",
                "print(measurement.power_in_milliwatt)",
                "print(measurement.voltage_in_volt)",
            ],
            "notes": (
                "Les dades venen en atributs de l'objecte retornat, com "
                "power_in_milliwatt o total_consumption_in_kilowatt_hour."
            ),
        },
        {
            "anchor": "method_settings",
            "name": "request_settings()",
            "what": (
                "Consulta la configuracio activa del dispositiu: limit de potencia, "
                "preus i franja reduida."
            ),
            "params": [
                "Sense parametres.",
            ],
            "returns": "Retorna un SettingsRequestedNotification.",
            "example": [
                "settings = device.request_settings()",
                "print(settings.power_limit_in_watt)",
                "print(settings.normal_price_in_cent)",
            ],
            "notes": (
                "Igual que amb request_measurement(), el resultat es un objecte amb "
                "atributs, no una estructura JSON."
            ),
        },
        {
            "anchor": "method_disconnect",
            "name": "disconnect()",
            "what": "Tanca la connexio Bluetooth amb el dispositiu actual.",
            "params": [
                "Sense parametres.",
            ],
            "returns": "Retorna True si la desconnexio s'executa correctament.",
            "example": [
                "device.disconnect()",
            ],
            "notes": "Es recomanable cridar-lo al final per deixar la connexio neta.",
        },
    ]


def build_lines():
    methods = build_methods()
    lines = []

    def add_line(style, text, dest=None, link_dest=None):
        lines.append(
            {
                "style": style,
                "text": text,
                "dest": dest,
                "link_dest": link_dest,
            }
        )

    def add_blank(style="blank"):
        add_line(style, "")

    def add_title(text):
        add_line("title", text)
        add_blank()

    def add_heading(text):
        add_line("heading", text)

    def add_paragraph(text):
        for wrapped in wrap_text(text, BODY_SIZE):
            add_line("body", wrapped)
        add_blank()

    def add_bullet(text):
        for wrapped in wrap_text(text, BODY_SIZE, prefix="- "):
            add_line("body", wrapped)
        add_blank()

    def add_index_entry(text, link_dest):
        for wrapped in wrap_text(text, BODY_SIZE, prefix="- "):
            add_line("body", wrapped, link_dest=link_dest)

    def add_code(code_lines):
        for code_line in code_lines:
            if code_line == "":
                add_blank("code_blank")
                continue

            for wrapped in wrap_text(code_line, CODE_SIZE):
                add_line("code", wrapped)
        add_blank()

    add_title("Resum de l'API basica de sem6000")

    add_heading("1. Introduccio")
    add_paragraph(
        "La llibreria sem6000 permet descobrir, connectar i controlar endolls "
        "Voltcraft SEM6000 per Bluetooth, a mes de consultar dades de consum i "
        "configuracio."
    )
    add_paragraph(
        "En aquest projecte, la llibreria es troba a " + LIBRARY_PATH + ". Per fer "
        "servir discover() cal tenir Bluetooth actiu i permisos suficients."
    )

    add_heading("2. Patro d'importacio local")
    add_paragraph(
        "El patro recomanat es afegir el repositori local al sys.path abans "
        "d'importar el modul principal. Aixo evita haver d'instal.lar la "
        "llibreria globalment."
    )
    add_code(
        [
            "from pathlib import Path",
            "import sys",
            "",
            "PROJECT_ROOT = Path(__file__).resolve().parents[1]",
            "LIBRARY_ROOT = PROJECT_ROOT / \"github2\" / \"python3-voltcraft-sem6000\"",
            "if str(LIBRARY_ROOT) not in sys.path:",
            "    sys.path.insert(0, str(LIBRARY_ROOT))",
            "",
            "from sem6000 import sem6000",
        ]
    )

    add_heading("3. Index de funcions")
    add_paragraph("Fes clic en qualsevol entrada per anar directament a l'apartat de la funcio.")
    for method in methods:
        add_index_entry(method["name"], method["anchor"])
    add_blank()

    add_heading("4. Funcions principals")
    for method in methods:
        add_line("method_name", method["name"], dest=method["anchor"])
        add_bullet("Que fa: " + method["what"])
        add_bullet("Parametres:")
        for param in method["params"]:
            add_bullet("  " + param)
        add_bullet("Que retorna: " + method["returns"])
        add_bullet("Exemple minim:")
        add_code(method["example"])
        add_bullet("Errors o observacions importants: " + method["notes"])

    add_heading("5. Exemples d'us")
    add_paragraph("Exemple 1: descobrir dispositius disponibles.")
    add_code(
        [
            "devices = sem6000.SEM6000.discover()",
            "for device in devices:",
            "    print(f\"{device['name']}\\t{device['address']}\")",
        ]
    )

    add_paragraph("Exemple 2: connectar-se, autoritzar, llegir nom i una mesura.")
    add_code(
        [
            "device = sem6000.SEM6000()",
            "device.connect('00:11:22:33:44:55')",
            "device.authorize('0000')",
            "name_info = device.request_device_name()",
            "measurement = device.request_measurement()",
            "print(name_info.device_name)",
            "print(measurement.power_in_milliwatt)",
        ]
    )

    add_paragraph("Exemple 3: encendre, apagar i desconnectar.")
    add_code(
        [
            "device.power_on()",
            "device.power_off()",
            "device.disconnect()",
        ]
    )

    add_heading("6. Notes practiques i limitacions")
    add_bullet(
        "discover() necessita acces Bluetooth i pot requerir permisos elevats "
        "segons l'entorn."
    )
    add_bullet(
        "authorize() falla si el PIN no es correcte o si el dispositiu no respon."
    )
    add_bullet(
        "request_measurement() i request_settings() retornen objectes de "
        "notificacio, no diccionaris."
    )
    add_bullet(
        "Aquest patro d'us assumeix que el dispositiu trobat es compatible amb "
        "la llibreria SEM6000."
    )

    return lines


def layout_lines(lines):
    pages = [[]]
    destinations = {}
    y = PAGE_HEIGHT - MARGIN

    for line in lines:
        style = line["style"]
        spec = STYLE_SPECS[style]

        if style in ("blank", "code_blank"):
            y -= spec["gap"]
            if y < MARGIN:
                pages.append([])
                y = PAGE_HEIGHT - MARGIN
            continue

        font_size = spec["size"]
        if y - font_size < MARGIN:
            pages.append([])
            y = PAGE_HEIGHT - MARGIN

        entry = {
            "style": style,
            "text": line["text"],
            "font": spec["font"],
            "font_size": font_size,
            "x": MARGIN,
            "y": y,
            "link_dest": line["link_dest"],
        }
        pages[-1].append(entry)

        if line["dest"]:
            destinations[line["dest"]] = {
                "page_index": len(pages) - 1,
                "x": entry["x"],
                "top": min(PAGE_HEIGHT - MARGIN, entry["y"] + entry["font_size"]),
            }

        y -= font_size + spec["gap"]

    return pages, destinations


def build_page_stream(page_lines):
    commands = []

    for entry in page_lines:
        font_ref = "/F2" if entry["font"] == "bold" else "/F1"
        escaped = escape_pdf_text(entry["text"])
        commands.append(
            f"BT {font_ref} {entry['font_size']} Tf 1 0 0 1 {entry['x']} {entry['y']:.2f} Tm ({escaped}) Tj ET"
        )

    return ("\n".join(commands) + "\n").encode("ascii")


def build_annotations(pages, destinations):
    annotations = []

    for page_entries in pages:
        page_annotations = []

        for entry in page_entries:
            if not entry["link_dest"]:
                continue

            target = destinations[entry["link_dest"]]
            width = approximate_text_width(entry["text"], entry["font_size"])
            page_annotations.append(
                {
                    "rect": (
                        entry["x"],
                        max(0, entry["y"] - 2),
                        min(PAGE_WIDTH - MARGIN, entry["x"] + width),
                        min(PAGE_HEIGHT, entry["y"] + entry["font_size"]),
                    ),
                    "target": target,
                }
            )

        annotations.append(page_annotations)

    return annotations


def write_pdf(page_streams, annotations_by_page):
    page_count = len(page_streams)
    regular_font_id = 1
    bold_font_id = 2
    content_start = 3
    content_ids = list(range(content_start, content_start + page_count))
    page_start = content_start + page_count
    page_ids = list(range(page_start, page_start + page_count))

    next_id = page_start + page_count
    annotation_ids_by_page = []
    for page_annotations in annotations_by_page:
        ids = []
        for _ in page_annotations:
            ids.append(next_id)
            next_id += 1
        annotation_ids_by_page.append(ids)

    pages_tree_id = next_id
    catalog_id = pages_tree_id + 1
    max_id = catalog_id
    objects = [b""] * (max_id + 1)

    objects[regular_font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    objects[bold_font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )

    for object_id, stream in zip(content_ids, page_streams):
        objects[object_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )

    for page_index, page_id in enumerate(page_ids):
        annots = annotation_ids_by_page[page_index]
        annots_part = ""
        if annots:
            refs = " ".join(f"{annot_id} 0 R" for annot_id in annots)
            annots_part = f" /Annots [{refs}]"

        objects[page_id] = (
            f"<< /Type /Page /Parent {pages_tree_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {regular_font_id} 0 R /F2 {bold_font_id} 0 R >> >> "
            f"/Contents {content_ids[page_index]} 0 R{annots_part} >>"
        ).encode("ascii")

    for page_index, page_annotations in enumerate(annotations_by_page):
        for annot_id, annotation in zip(annotation_ids_by_page[page_index], page_annotations):
            left, bottom, right, top = annotation["rect"]
            target_page_id = page_ids[annotation["target"]["page_index"]]
            dest_x = annotation["target"]["x"]
            dest_top = annotation["target"]["top"]
            objects[annot_id] = (
                f"<< /Type /Annot /Subtype /Link /Border [0 0 0] "
                f"/Rect [{left:.2f} {bottom:.2f} {right:.2f} {top:.2f}] "
                f"/A << /S /GoTo /D [{target_page_id} 0 R /XYZ {dest_x:.2f} {dest_top:.2f} null] >> >>"
            ).encode("ascii")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_tree_id] = (
        f"<< /Type /Pages /Count {page_count} /Kids [{kids}] >>"
    ).encode("ascii")
    objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_tree_id} 0 R >>".encode("ascii")

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray(header)
    offsets = [0] * (max_id + 1)

    for object_id in range(1, max_id + 1):
        offsets[object_id] = len(body)
        body.extend(f"{object_id} 0 obj\n".encode("ascii"))
        body.extend(objects[object_id])
        body.extend(b"\nendobj\n")

    xref_offset = len(body)
    body.extend(f"xref\n0 {max_id + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")

    for object_id in range(1, max_id + 1):
        body.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))

    body.extend(
        (
            f"trailer\n<< /Size {max_id + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )

    OUTPUT_PATH.write_bytes(body)


def main():
    lines = build_lines()
    pages, destinations = layout_lines(lines)
    page_streams = [build_page_stream(page) for page in pages]
    annotations_by_page = build_annotations(pages, destinations)
    write_pdf(page_streams, annotations_by_page)
    print(f"PDF generat a: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
