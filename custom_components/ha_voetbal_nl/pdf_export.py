from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import struct
import zlib

# A4 landscape. Long cells wrap and grow vertically.
PAGE_W = 841.89
PAGE_H = 595.28
MARGIN = 28.0
BOTTOM = 34.0


def _pdf_text(value: object) -> str:
    """Return text safe for built-in WinAnsi PDF fonts."""
    text = "" if value is None else str(value)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _escape_pdf(value: object) -> str:
    text = _pdf_text(value)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _slug(value: str) -> str:
    value = _pdf_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "team"


def default_pdf_filename(team_name: str, season: str) -> str:
    return f"ha_voetbal_{_slug(team_name)}_{_slug(season)}.pdf"


def _fmt_num(value, digits=1):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png(data: bytes):
    """Decode common 8-bit PNGs to RGB for dependency-free PDF embedding."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    width = height = bit_depth = color_type = None
    palette = None
    transparency = None
    compressed = bytearray()
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", payload)
            if bit_depth != 8 or interlace != 0 or comp != 0 or filt != 0:
                return None
        elif kind == b"PLTE":
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload), 3)]
        elif kind == b"tRNS":
            transparency = bytes(payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if not width or not height or color_type is None:
        return None

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) < expected:
        return None

    rows = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        scan = bytearray(raw[offset:offset + stride])
        offset += stride
        bpp = channels
        for i in range(stride):
            left = scan[i - bpp] if i >= bpp else 0
            up = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                scan[i] = (scan[i] + left) & 0xFF
            elif filter_type == 2:
                scan[i] = (scan[i] + up) & 0xFF
            elif filter_type == 3:
                scan[i] = (scan[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                scan[i] = (scan[i] + _paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                return None
        rows.append(bytes(scan))
        previous = scan

    rgb = bytearray()
    for row in rows:
        for x in range(width):
            i = x * channels
            if color_type == 0:
                g = row[i]
                rgb.extend((g, g, g))
            elif color_type == 2:
                rgb.extend(row[i:i + 3])
            elif color_type == 3:
                idx = row[i]
                if not palette or idx >= len(palette):
                    rgb.extend((255, 255, 255))
                else:
                    r, g, b = palette[idx]
                    alpha = transparency[idx] if transparency and idx < len(transparency) else 255
                    rgb.extend((
                        (r * alpha + 255 * (255 - alpha)) // 255,
                        (g * alpha + 255 * (255 - alpha)) // 255,
                        (b * alpha + 255 * (255 - alpha)) // 255,
                    ))
            elif color_type == 4:
                g, alpha = row[i], row[i + 1]
                v = (g * alpha + 255 * (255 - alpha)) // 255
                rgb.extend((v, v, v))
            elif color_type == 6:
                r, g, b, alpha = row[i:i + 4]
                rgb.extend((
                    (r * alpha + 255 * (255 - alpha)) // 255,
                    (g * alpha + 255 * (255 - alpha)) // 255,
                    (b * alpha + 255 * (255 - alpha)) // 255,
                ))
    return {
        "width": width,
        "height": height,
        "colorspace": "/DeviceRGB",
        "bits": 8,
        "filter": "/FlateDecode",
        "data": zlib.compress(bytes(rgb), 9),
    }


def _jpeg_info(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xD8, 0xD9):
            continue
        if pos + 2 > len(data):
            break
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length >= 8:
                bits = data[pos + 2]
                height = struct.unpack(">H", data[pos + 3:pos + 5])[0]
                width = struct.unpack(">H", data[pos + 5:pos + 7])[0]
                components = data[pos + 7]
                return {
                    "width": width,
                    "height": height,
                    "colorspace": "/DeviceGray" if components == 1 else "/DeviceRGB",
                    "bits": bits,
                    "filter": "/DCTDecode",
                    "data": data,
                }
        pos += length
    return None


def _decode_image(data: bytes):
    if not data:
        return None
    return _decode_png(data) or _jpeg_info(data)


def _logo_cell(text: object, logo_url: str | None):
    return {"text": text or "", "image_key": logo_url}


class _SimplePdf:
    """Dependency-free A4 landscape PDF writer with images and wrapped tables."""

    def __init__(self, *, team: str, season: str, logo_bytes: dict[str, bytes] | None = None,
                 team_logo_url: str | None = None):
        self.team = _pdf_text(team)
        self.season = _pdf_text(season)
        self.generated = datetime.now().strftime("%d-%m-%Y %H:%M")
        self.pages: list[list[str]] = []
        self._ops: list[str] = []
        self.page_no = 0
        self.y = PAGE_H - MARGIN
        self.section_title = ""
        self.team_logo_url = team_logo_url
        self.images: dict[str, dict] = {}
        for key, raw in (logo_bytes or {}).items():
            decoded = _decode_image(raw)
            if decoded:
                self.images[key] = decoded
        self._image_names = {key: f"Im{idx}" for idx, key in enumerate(self.images, start=1)}
        self.new_page()

    @property
    def content_width(self):
        return PAGE_W - 2 * MARGIN

    def new_page(self, title: str | None = None):
        if self._ops:
            self._footer()
            self.pages.append(self._ops)
        self._ops = []
        self.page_no += 1
        if title is not None:
            self.section_title = title
        self.y = PAGE_H - MARGIN
        if self.section_title:
            self._header(self.section_title)

    def _header(self, title: str):
        logo_size = 55.0
        text_x = MARGIN
        if self.team_logo_url in self.images:
            self.image(self.team_logo_url, MARGIN, PAGE_H - 83, logo_size, logo_size)
            text_x = MARGIN + logo_size + 12
        self.text(text_x, PAGE_H - 38, self.team, 18, bold=True)
        self.text(text_x, PAGE_H - 58, title, 12.5, bold=True)
        self.text(text_x, PAGE_H - 75, f"Seizoen {self.season}", 8.5)
        self.text(PAGE_W - MARGIN, PAGE_H - 42, f"Gegenereerd: {self.generated}", 8,
                  align="right")
        self.y = PAGE_H - 96

    def _footer(self):
        self.text(MARGIN, 17, f"Pagina {self.page_no}", 7.5, ensure=False)
        self.text(PAGE_W - MARGIN, 17, f"{self.team} - Seizoen {self.season}", 7.5,
                  align="right", ensure=False)

    def _ensure(self, height: float):
        if self.y - height < BOTTOM:
            self.new_page()

    @staticmethod
    def _width(text: str, size: float, bold: bool = False) -> float:
        factor = 0.515 if bold else 0.49
        return len(text) * size * factor

    def text(self, x: float, y: float, text: object, size: float = 10, *, bold=False,
             align: str = "left", ensure: bool = False):
        if ensure:
            self._ensure(size + 4)
        font = "F2" if bold else "F1"
        value = _pdf_text(text)
        width = self._width(value, size, bold)
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        self._ops.append(
            f"BT /{font} {size:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_pdf(value)}) Tj ET"
        )

    def image(self, key: str | None, x: float, y: float, max_w: float, max_h: float):
        if not key or key not in self.images:
            return False
        image = self.images[key]
        iw, ih = image["width"], image["height"]
        scale = min(max_w / iw, max_h / ih)
        w, h = iw * scale, ih * scale
        dx = x + (max_w - w) / 2
        dy = y + (max_h - h) / 2
        name = self._image_names[key]
        self._ops.append(f"q {w:.2f} 0 0 {h:.2f} {dx:.2f} {dy:.2f} cm /{name} Do Q")
        return True

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.35,
             gray: float = 0.72):
        self._ops.append(
            f"q {gray:.2f} G {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q"
        )

    def rect(self, x: float, y: float, w: float, h: float, fill_gray: float | None = None,
             stroke_gray: float | None = None):
        if fill_gray is not None:
            self._ops.append(f"q {fill_gray:.3f} g {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f Q")
        if stroke_gray is not None:
            self._ops.append(f"q {stroke_gray:.2f} G 0.35 w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S Q")

    def _wrap(self, value: object, width: float, font_size: float, *, bold=False) -> list[str]:
        text = _pdf_text(value).strip()
        if not text:
            return [""]
        usable = max(8.0, width - 7.0)
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if self._width(test, font_size, bold) <= usable:
                current = test
                continue
            if current:
                lines.append(current)
                current = ""
            chunk = ""
            for ch in word:
                test_chunk = chunk + ch
                if chunk and self._width(test_chunk, font_size, bold) > usable:
                    lines.append(chunk)
                    chunk = ch
                else:
                    chunk = test_chunk
            current = chunk
        if current:
            lines.append(current)
        return lines or [""]

    @staticmethod
    def _cell(cell):
        if isinstance(cell, dict):
            return cell.get("text", ""), cell.get("image_key")
        return cell, None

    def summary_boxes(self, items: list[tuple[str, object]]):
        gap = 8
        box_w = (self.content_width - gap * (len(items) - 1)) / len(items)
        h = 44
        x = MARGIN
        for label, value in items:
            self.rect(x, self.y - h, box_w, h, fill_gray=0.95, stroke_gray=0.82)
            self.text(x + 8, self.y - 15, label, 7.5)
            self.text(x + 8, self.y - 34, value, 13, bold=True)
            x += box_w + gap
        self.y -= h + 14

    def table(self, headers: list[str], rows: list[list[object]], widths: list[float], *,
              font_size: float = 7.5, min_row_height: float = 19.0,
              header_size: float | None = None, alternating: bool = True,
              image_size: float = 19.0, keep_together_groups: list[int] | None = None):
        total = sum(widths)
        if total > self.content_width + 0.2:
            raise ValueError(f"Table is wider than page ({total:.1f}>{self.content_width:.1f})")
        header_size = header_size or font_size
        line_h = font_size + 2.1
        header_h = max(21.0, header_size + 11.0)

        def draw_header():
            if self.y - header_h < BOTTOM:
                self.new_page()
            top = self.y
            bottom = top - header_h
            self.rect(MARGIN, bottom, total, header_h, fill_gray=0.90, stroke_gray=0.75)
            x = MARGIN
            for header, width in zip(headers, widths):
                self.text(x + 4, bottom + 7, header, header_size, bold=True)
                x += width
                self.line(x, bottom, x, top, 0.3, 0.78)
            self.y = bottom

        def prepare_row(row):
            cell_data = []
            max_lines = 1
            has_image = False
            for cell, width in zip(row, widths):
                text, image_key = self._cell(cell)
                image_present = bool(image_key and image_key in self.images)
                text_width = width - (image_size + 6 if image_present else 0)
                wrapped = self._wrap(text, text_width, font_size)
                max_lines = max(max_lines, len(wrapped))
                has_image = has_image or image_present
                cell_data.append((wrapped, image_key if image_present else None, width))
            row_h = max(min_row_height, 7.0 + max_lines * line_h)
            if has_image:
                row_h = max(row_h, image_size + 7.0)
            return cell_data, row_h

        prepared = [prepare_row(row) for row in rows]
        group_starts = {}
        if keep_together_groups:
            start = 0
            for count in keep_together_groups:
                if count > 0:
                    group_starts[start] = count
                    start += count

        draw_header()
        for idx, row in enumerate(rows):
            # Keep logical blocks (for example one player plus all rides and
            # the total row) on a single page whenever the block itself fits.
            group_count = group_starts.get(idx)
            if group_count:
                group_h = sum(prepared[i][1] for i in range(idx, min(idx + group_count, len(prepared))))
                page_capacity = (PAGE_H - 96) - header_h - BOTTOM
                if group_h <= page_capacity and self.y - group_h < BOTTOM:
                    self.new_page()
                    draw_header()

            cell_data, row_h = prepared[idx]
            if self.y - row_h < BOTTOM:
                self.new_page()
                draw_header()

            top = self.y
            bottom = top - row_h
            if alternating and idx % 2 == 1:
                self.rect(MARGIN, bottom, total, row_h, fill_gray=0.965)
            self.rect(MARGIN, bottom, total, row_h, stroke_gray=0.82)

            x = MARGIN
            for lines, image_key, width in cell_data:
                text_x = x + 4
                if image_key:
                    self.image(image_key, x + 3, bottom + (row_h - image_size) / 2, image_size, image_size)
                    text_x += image_size + 5
                ty = top - font_size - 5
                for line_text in lines:
                    self.text(text_x, ty, line_text, font_size)
                    ty -= line_h
                x += width
                self.line(x, bottom, x, top, 0.3, 0.82)
            self.y = bottom

        self.y -= 10

    def finish(self) -> bytes:
        if self._ops:
            self._footer()
            self.pages.append(self._ops)
            self._ops = []

        objects: list[bytes] = []
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"")  # pages placeholder
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

        image_obj_numbers = {}
        for key in self.images:
            image_obj_numbers[key] = len(objects) + 1
            image = self.images[key]
            stream = image["data"]
            obj = (
                f"<< /Type /XObject /Subtype /Image /Width {image['width']} /Height {image['height']} "
                f"/ColorSpace {image['colorspace']} /BitsPerComponent {image['bits']} "
                f"/Filter {image['filter']} /Length {len(stream)} >>\nstream\n"
            ).encode("ascii") + stream + b"\nendstream"
            objects.append(obj)

        page_numbers = []
        for ops in self.pages:
            page_obj = len(objects) + 1
            content_obj = page_obj + 1
            page_numbers.append(page_obj)
            xobjects = " ".join(
                f"/{self._image_names[key]} {obj_no} 0 R"
                for key, obj_no in image_obj_numbers.items()
            )
            resource = f"/Font << /F1 3 0 R /F2 4 0 R >>"
            if xobjects:
                resource += f" /XObject << {xobjects} >>"
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
                    f"/Resources << {resource} >> /Contents {content_obj} 0 R >>"
                ).encode("ascii")
            )
            stream = ("\n".join(ops) + "\n").encode("cp1252", errors="replace")
            objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream")

        kids = " ".join(f"{n} 0 R" for n in page_numbers)
        objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode("ascii")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{number} 0 obj\n".encode("ascii"))
            out.extend(obj)
            out.extend(b"\nendobj\n")

        xref = len(out)
        out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
        out.extend(
            f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(out)


def build_season_pdf(export: dict, logo_bytes: dict[str, bytes] | None = None) -> bytes:
    """Build a landscape season PDF including club logos when available."""
    team = export.get("team_naam") or "Team"
    season = export.get("seizoen") or ""
    team_logo_url = export.get("team_logo_url")
    matches = list(export.get("wedstrijden", []))
    trainings = list(export.get("trainingskalender", []))
    people = list(export.get("rijschema_per_persoon", []))

    pdf = _SimplePdf(
        team=team,
        season=season,
        logo_bytes=logo_bytes,
        team_logo_url=team_logo_url,
    )

    # Page(s): complete match programme with home/away club logos.
    pdf.section_title = "Volledig wedstrijdprogramma"
    pdf._header(pdf.section_title)
    home_count = sum(1 for m in matches if m.get("thuiswedstrijd") is True)
    away_count = sum(1 for m in matches if m.get("thuiswedstrijd") is False)
    planned = sum(
        1 for m in matches
        if m.get("thuiswedstrijd") is False and (m.get("rijschema") or {}).get("status") == "geregeld"
    )
    flagging_enabled = bool(export.get("vlaggen_ingeschakeld", False))
    flagged = sum(1 for m in matches if m.get("vlagger_status") == "geregeld") if flagging_enabled else 0
    summary = [
        ("Wedstrijden", len(matches)),
        ("Thuis", home_count),
        ("Uit", away_count),
        ("Rijschema", f"{planned}/{away_count}"),
    ]
    if flagging_enabled:
        summary.append(("Vlaggers", f"{flagged}/{len(matches)}"))
    pdf.summary_boxes(summary)

    match_rows = []
    for m in matches:
        plan = m.get("rijschema", {}) or {}
        home_name = m.get("thuisteam") or (team if m.get("thuiswedstrijd") is True else m.get("tegenstander", ""))
        away_name = m.get("uitteam") or (m.get("tegenstander", "") if m.get("thuiswedstrijd") is True else team)
        row = [
            m.get("weeknummer") or str(m.get("week", "")).lstrip("W"),
            m.get("datum", ""),
            m.get("tijd", ""),
            _logo_cell(home_name, m.get("thuis_logo_url")),
            _logo_cell(away_name, m.get("uit_logo_url")),
            m.get("accommodatie", ""),
            f"{m.get('reistijd_minuten', 0) or 0} min",
            m.get("verzameltijd", "") or "-",
            plan.get("status", "-") if m.get("thuiswedstrijd") is False else "-",
        ]
        if flagging_enabled:
            row.append(
                f"{m.get('vlagger')} ({m.get('vlagger_status')})"
                if m.get("vlagger")
                else ("Niet geregeld" if m.get("vlaggen_verplicht") else "-")
            )
        match_rows.append(row)
    headers = ["Week", "Datum", "Tijd", "Thuisteam", "Uitteam", "Accommodatie", "Reistijd", "Verzamelen", "Rijschema"]
    widths = [35, 62, 40, 125, 125, 180, 58, 70, 70]
    if flagging_enabled:
        headers.append("Vlagger")
        widths = [32, 60, 38, 105, 105, 135, 55, 60, 55, 80]
    pdf.table(
        headers,
        match_rows,
        widths,
        font_size=6.6,
        min_row_height=25,
        image_size=20,
    )

    # Page: driving schedule by away match, with opponent logo.
    pdf.new_page("Rijschema per uitwedstrijd")
    away_rows = []
    for m in matches:
        if m.get("thuiswedstrijd") is not False:
            continue
        plan = m.get("rijschema", {}) or {}
        away_rows.append([
            m.get("weeknummer") or str(m.get("week", "")).lstrip("W"),
            m.get("datum", ""),
            _logo_cell(m.get("wedstrijd", "") or f"{m.get('tegenstander', '')} - {team}", m.get("tegenstander_logo_url")),
            f"{m.get('reistijd_minuten', '-')} min",
            f"{_fmt_num(m.get('afstand_retour_km'), 1)} km",
            ", ".join(plan.get("chauffeurs", [])),
        ])
    pdf.table(
        ["Week", "Datum", "Uitwedstrijd", "Reistijd", "Afstand retour", "Chauffeurs"],
        away_rows,
        [42, 72, 245, 68, 72, 287],
        font_size=7.4,
        min_row_height=25,
        image_size=20,
    )

    # Page: driving summary per person. Each assigned ride gets its own row.
    # This makes the schedule much easier to scan than a comma-separated list.
    pdf.new_page("Rijoverzicht per persoon")
    person_rows = []
    person_group_sizes = []
    for person in people:
        rides = person.get("ritten", [])
        player = person.get("speler", "")
        total_return = person.get("kilometers_retour")
        if total_return is None:
            total_return = sum(float(r.get("afstand_retour_km") or 0) for r in rides)

        for ride_index, ride in enumerate(rides):
            person_rows.append([
                player if ride_index == 0 else "",
                ride.get("week", ""),
                ride.get("datum", ""),
                _logo_cell(
                    ride.get("wedstrijd", ""),
                    ride.get("tegenstander_logo_url"),
                ),
                f"{_fmt_num(ride.get('afstand_retour_km'), 1)} km",
            ])

        # A separate total row keeps the number of rides and total kilometres
        # visible without wasting a column on every individual ride.
        person_rows.append([
            "", "", "",
            f"Totaal {person.get('aantal_ritten', len(rides))} ritten",
            f"{_fmt_num(total_return, 1)} km",
        ])
        person_group_sizes.append(len(rides) + 1)

    pdf.table(
        ["Speler", "Week", "Datum", "Wedstrijd", "Heen + terug km"],
        person_rows,
        [150, 55, 82, 385, 114],
        font_size=7.4,
        min_row_height=24,
        image_size=20,
        keep_together_groups=person_group_sizes,
    )

    # Flagging schedule: only included when flagging is enabled for this team.
    # This mirrors the driving section: complete match schedule followed by a
    # per-person overview of assigned assistant referees.
    if flagging_enabled:
        pdf.new_page("Vlaggers per wedstrijd")
        flag_rows = []
        for m in matches:
            flagger = m.get("vlagger", "") or "-"
            status = m.get("vlagger_status", "-") or "-"
            if status == "geregeld":
                status_text = "Geregeld"
            elif status in {"niet_geregeld", "conflict"}:
                status_text = "Niet geregeld"
            else:
                status_text = status
            flag_rows.append([
                m.get("weeknummer") or str(m.get("week", "")).lstrip("W"),
                m.get("datum", ""),
                m.get("tijd", ""),
                "Thuis" if m.get("thuiswedstrijd") is True else "Uit",
                _logo_cell(m.get("wedstrijd", ""), m.get("tegenstander_logo_url")),
                flagger,
                status_text,
            ])
        pdf.table(
            ["Week", "Datum", "Tijd", "Type", "Wedstrijd", "Vlagger", "Status"],
            flag_rows,
            [42, 72, 48, 48, 285, 170, 106],
            font_size=7.2,
            min_row_height=25,
            image_size=20,
        )

        pdf.new_page("Vlaggeroverzicht per persoon")
        flag_people = list(export.get("vlagger_per_persoon", []))
        flag_person_rows = []
        flag_group_sizes = []
        for person in flag_people:
            assignments = person.get("wedstrijden", [])
            name = person.get("speler", "")
            if assignments:
                for idx, assignment in enumerate(assignments):
                    flag_person_rows.append([
                        name if idx == 0 else "",
                        assignment.get("week", ""),
                        assignment.get("datum", ""),
                        assignment.get("tijd", ""),
                        _logo_cell(assignment.get("wedstrijd", ""), assignment.get("tegenstander_logo_url")),
                        "Thuis" if assignment.get("thuiswedstrijd") is True else "Uit",
                    ])
                flag_person_rows.append([
                    "", "", "", "",
                    f"Totaal {person.get('aantal_wedstrijden', len(assignments))} wedstrijden",
                    "Geregeld",
                ])
                flag_group_sizes.append(len(assignments) + 1)
            else:
                flag_person_rows.append([
                    name, "", "", "",
                    "Geen toegewezen wedstrijden",
                    "0 wedstrijden",
                ])
                flag_group_sizes.append(1)

        if flag_person_rows:
            pdf.table(
                ["Speler", "Week", "Datum", "Tijd", "Wedstrijd", "Status"],
                flag_person_rows,
                [140, 50, 75, 45, 385, 80],
                font_size=7.4,
                min_row_height=24,
                image_size=20,
                keep_together_groups=flag_group_sizes,
            )
        else:
            pdf.text(MARGIN, pdf.y - 10, "Er zijn nog geen vlaggers toegewezen.", 9)
            pdf.y -= 28

    # Training schedule with vacation/cancelled rows explicit.
    pdf.new_page(f"Trainingsschema {season}")
    training_rows = []
    for t in trainings:
        status = str(t.get("status") or "training")
        reason = t.get("reden") or "Training"
        if status == "vervallen":
            status_text = f"Geen training - {reason}"
            meeting = "-"
            training_time = "-"
        else:
            status_text = "Training" if reason == "Normale trainingsdag" else reason
            meeting = t.get("verzameltijd", t.get("aanwezig", "")) or "-"
            start = t.get("start", t.get("starttijd", "")) or ""
            end = t.get("einde", t.get("eindtijd", "")) or ""
            training_time = f"{start} - {end}".strip(" -") or "-"

        date_value = t.get("datum", "")
        week = t.get("weeknummer")
        if not week and date_value:
            try:
                week = datetime.strptime(date_value, "%d-%m-%Y").date().isocalendar().week
            except ValueError:
                week = ""

        training_rows.append([
            week or "", date_value, str(t.get("dag", "")).capitalize(), status_text,
            meeting, training_time, t.get("veld", "") or "-",
        ])
    pdf.table(
        ["Week", "Datum", "Dag", "Status", "Aanwezig", "Training", "Veld / ondergrond"],
        training_rows,
        [44, 76, 76, 220, 72, 112, 186],
        font_size=7.2,
        min_row_height=21,
    )

    return pdf.finish()


def write_season_pdf(export: dict, destination: Path, logo_bytes: dict[str, bytes] | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(build_season_pdf(export, logo_bytes=logo_bytes))
