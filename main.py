import click
import re
import os
import yaml
import pypdf
import math
from pypdf import Transformation
from pypdf.generic import AnnotationBuilder, NameObject, TextStringObject
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.pdfgen.textobject import PDFTextObject
from reportlab.lib.pagesizes import A4
from PIL import ImageColor

from dataclasses import dataclass

@dataclass
class Unit:
    name: str
    id: str
    points: int
    full_text: str

@dataclass
class Rule:
    id: str
    origin: str
    page_ranges: list[list[int]]
    pdf: pypdf.PdfReader

    def __str__(self):
        return f"pages {self.page_ranges} from '{self.origin}'"

    def __repr__(self):
        return self.__str__()

@dataclass
class Datasheet:
    id: str
    origin: str
    page_nb: int
    pdf: pypdf.PdfReader
    extra_text: str = ""

    def __str__(self):
        return f"page {self.page_nb} from '{self.origin}'"

    def __repr__(self):
        return self.__str__()

ARMY_SPEC_RE = (
    r"^(?P<list_name>[^\n]+?) \((?P<total_points>[0-9]+) points\)\n"
    r"(?P<raw_army_rule>[^\n]+?(?:\n[^\n]+?)?)\n"
    r"(?P<game_format>[^\n]+? \((?P<max_points>[0-9]+) points\))\n"
    r"(?P<detachment_rule>[^\n]+?)\n"
)

UNIT_RE = (
    r"(?P<unit_name>[^\n]+?) \((?P<unit_points>[0-9]+) points\)\n"
    r"(?P<wargear>(?:  [^\n]+?\n)+)"
    r"\n"
)

PDF_INDEX_DIR = os.path.join("data", "pdf_index")
DEFAULT_FONT_FACE = "Helvetica"
DEFAULT_FONT_SIZE = 12
DEFAULT_XT = 157
DEFAULT_YT = 445
DEFAULT_HT = 93
DEFAULT_WT = 200
DEFAULT_XB = 157
DEFAULT_YB = 175
DEFAULT_HB = 93
DEFAULT_WB = 200
DEFAULT_FG_COLOR = '514e4f'
DEFAULT_BG_COLOR = 'e3e3e1'
DEFAULT_BR_COLOR = '514e4f'

ARMY_COMPACT_X = 157
ARMY_COMPACT_Y = 477
ARMY_COMPACT_H = 61
ARMY_COMPACT_W = 200

LEADING_RATIO = 1.2
PTS_RATIO = 2.3

MARGIN_RATIO = 0.1

def iround(x):
    return int(round(x))

def fuse_group_into(group, units):
    if len(group) == 1:
        units.append(group[0])
        return
    total_points = sum(u.points for u in group)
    merged_full_text_lines = "\n".join(
        [f"{len(group)} x {group[0].name} ({total_points} points)"] +
        ["  " + l for u in group for l in u.full_text.split("\n") if l] +
        [""]
    )
    units.append(
        Unit(
        name=group[0].name,
        id=group[0].id,
        points=total_points,
        full_text=merged_full_text_lines
    ))

def arrange_in_two(text, sep, lines_limit):
    groups = text.split(sep)
    l1 = []
    l2 = []
    l1_full = False
    l2_full = False
    c1 = 0
    c2 = 0
    for g in groups:
        if g.strip():
            pass
        if not l1_full:
            if not l1:
                l1.append(g)
                c1 += len(g).split("\n")
                continue
            new_nb = len((sep + g).split("\n"))
            if c1 + new_nb <= lines_limit:
                l1.append(sep + g)
                c1 += new_nb
            else:
                k = len((sep.lstrip("\n") + g).split("\n"))
                print(f"{c1}/{lines_limit} lines filled, putting the next {k}({new_nb}) on the next column")
                l1_full = True
                l2.append((sep.lstrip("\n") + g))
                c2 += k
        else:
            new_nb = len((sep + g).split("\n"))
            if not l2_full and c2 + new_nb > lines_limit:
                print(f"Warning: overflowing text: {g}...")
                l2_full = True
            l2.append(g)
            c2 += new_nb
    return sep.join(l1), sep.join(l2)

def add_annot(desired_width, desired_height, annot_font_size, annot_font_face, content, sep, page, ref_box, offset_x, offset_y, extra_margin = 0.0):
    leading = LEADING_RATIO * annot_font_size
    packet = BytesIO()
    # create a new PDF with Reportlab
    canvas_width, canvas_height = desired_width * PTS_RATIO, desired_height * PTS_RATIO
    can = canvas.Canvas(packet, pagesize=(canvas_width, canvas_height))
    can.setFillColorRGB(1, 1, 1)
    can.setStrokeColorRGB(1, 1, 1)
    can.rect(0, 0, canvas_width, canvas_height, fill=1)
    can.setFillColorRGB(0, 0, 0)
    #can.rect(0, 0, canvas_width, canvas_height)
    to = can.beginText(extra_margin * annot_font_size, canvas_height - (1 + (max(0, extra_margin - 0.2))) * annot_font_size)
    to.setFont(annot_font_face, annot_font_size, leading)
    nb_lines_in_one_column = int(math.floor(canvas_height / (leading * 0.87)))
    l1, l2 = arrange_in_two(content, sep, nb_lines_in_one_column)
    to.textLines(l1)
    can.drawText(to)
    if l2:
        can.rect(canvas_width / 2 - annot_font_size, 0, 0, canvas_height)
        to2 = can.beginText(canvas_width // 2 + annot_font_size, canvas_height - (1 + (max(0, extra_margin - 0.2))) * annot_font_size)
        to2.setFont(annot_font_face, annot_font_size)
        to2.setLeading(leading)
        to2.textLines(l2)
        can.drawText(to2)
    can.save()
    packet.seek(0)
    annotation = pypdf.PdfReader(packet).pages[0]
    page.merge_transformed_page(
            annotation, Transformation().scale(1.0 / PTS_RATIO).translate(offset_x, offset_y), over=True, expand=False
        )

@click.command()
@click.argument("INPUT_PATH", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.argument("OUTPUT_PATH", type=click.Path())
@click.option("--with-army-rule/--without-army-rule", default=True)
@click.option("--with-detachment-rule/--without-detachment-rule", default=True)
@click.option("--with-unit-comp/--without-unit-comp", default=True)
@click.option("--with-army-annot/--without-army-annot", default=True)
@click.option("--with-unit-annot/--without-army-annot", default=True)
@click.option("--annot-font-face", type=str, default=DEFAULT_FONT_FACE)
@click.option("--annot-font-size", type=int, default=DEFAULT_FONT_SIZE)
@click.option("--annot-xt", type=int, default=DEFAULT_XT)
@click.option("--annot-yt", type=int, default=DEFAULT_YT)
@click.option("--annot-wt", type=int, default=DEFAULT_WT)
@click.option("--annot-ht", type=int, default=DEFAULT_HT)
@click.option("--annot-xb", type=int, default=DEFAULT_XB)
@click.option("--annot-yb", type=int, default=DEFAULT_YB)
@click.option("--annot-wb", type=int, default=DEFAULT_WB)
@click.option("--annot-hb", type=int, default=DEFAULT_HB)
@click.option("--annot-fg-color", type=str, default=DEFAULT_FG_COLOR)
@click.option("--annot-bg-color", type=str, default=DEFAULT_BG_COLOR)
@click.option("--annot-br-color", type=str, default=DEFAULT_BR_COLOR)
@click.option("--booklet-mode/--compact-mode", default=False)
@click.option("--gui")
def _main(input_path, output_path, with_army_rule, with_detachment_rule, with_unit_comp, with_army_annot, with_unit_annot, annot_font_face, annot_font_size, annot_xt, annot_yt, annot_wt, annot_ht, annot_xb, annot_yb, annot_wb, annot_hb, annot_fg_color, annot_bg_color, annot_br_color, booklet_mode, gui):
    if gui:
        raise Exception("Not implement yet.")
    else:
        main(input_path, output_path, with_army_rule, with_detachment_rule, with_unit_comp, with_army_annot, with_unit_annot, annot_font_face, annot_font_size, annot_xt, annot_yt, annot_wt, annot_ht, annot_xb, annot_yb, annot_wb, annot_hb, annot_fg_color, annot_bg_color, annot_br_color, booklet_mode)

def main(input_path, output_path, with_army_rule, with_detachment_rule, with_unit_comp, with_army_annot, with_unit_annot, annot_font_face, annot_font_size, annot_xt, annot_yt, annot_wt, annot_ht, annot_xb, annot_yb, annot_wb, annot_hb, annot_fg_color, annot_bg_color, annot_br_color, booklet_mode):

    with open(input_path, "r", encoding="utf-8") as input_file:
        list_content = input_file.read()
    army_spec_match = re.search(ARMY_SPEC_RE, list_content)
    if army_spec_match is None:
        raise Exception("Army spec doesn't match the expected format.")
    army_spec_full_text = army_spec_match.group(0)
    list_name = army_spec_match.group("list_name")
    total_points = int(army_spec_match.group("total_points"))
    raw_army_rule = army_spec_match.group("raw_army_rule")
    army_name_try = raw_army_rule.replace("\n", " -- ")
    game_format = army_spec_match.group("game_format")
    max_points = int(army_spec_match.group("max_points"))
    detachment_rule_name = army_spec_match.group("detachment_rule")
    print(f"Found army of '{army_name_try}' with {total_points}/{max_points}!")

    units = []
    group = []
    group_id = None
    for match in re.finditer(UNIT_RE, list_content):
        current = Unit(
            name=match.group("unit_name"),
            id=match.group("unit_name").strip().upper(),
            points=int(match.group("unit_points")),
            full_text=match.group(0)
        )
        if current.id != group_id and group_id is not None:
            fuse_group_into(group, units)
            group = []
        group.append(current)
        group_id = current.id
    fuse_group_into(group, units)
    for u in units:
        print(u)

    pdf_index_names = os.listdir(PDF_INDEX_DIR)
    if army_name_try + ".yaml" in pdf_index_names:
        army_name = army_name_try
        army_index_path = os.path.join(PDF_INDEX_DIR, army_name_try + ".yaml")
        retry = False
    elif " -- " in army_name_try:
        new_try = army_name_try.split(" -- ")[0]
        print(f"I didn't find '{army_name_try}', trying '{new_try}'")
        army_name_try = new_try
        retry = True
    if retry:
        if army_name_try + ".yaml" in pdf_index_names:
            army_name = army_name_try
            army_index_path = os.path.join(PDF_INDEX_DIR, army_name_try + ".yaml")
        else:
            raise Exception(f"I didn't find '{army_name_try}', exiting.")

    army_rules = {}
    detachment_rules = {}
    datasheets = {}
    load_rec_index(army_rules, detachment_rules, datasheets, army_index_path)
    print(datasheets)
    if len(army_rules) > 1:
        raise Exception(f"Several army rules detected: {army_rules}, exiting.")
    army_rule = list(army_rules.items())[0][1]
    if detachment_rule_name not in detachment_rules:
        raise Exception(f"Requested detachement rule {detachment_rule_name} not found in {detachment_rules}, exiting.")
    detachment_rule = detachment_rules[detachment_rule_name]
    print(f"Playing with army rule '{army_rule.id}' and detachment_rule '{detachment_rule.id}'")

    output_pdf = pypdf.PdfWriter()
    current_pages = 0
    ref_box = army_rule.pdf.pages[0].mediabox
    if booklet_mode:
        output_pdf.add_blank_page(ref_box.width, ref_box.height)
        current_pages += 1
        
        desired_width = iround((1 - 2 * MARGIN_RATIO) * ref_box.width)
        desired_height = iround(ref_box.height - 2 * MARGIN_RATIO * ref_box.width)
        
        add_annot(desired_width, desired_height, annot_font_size, annot_font_face, list_content, "\n\n", output_pdf.get_page(current_pages-1), ref_box, iround(MARGIN_RATIO * ref_box.width), iround(ref_box.height - MARGIN_RATIO * ref_box.width - desired_height))

    if with_army_rule:
        print(f"Adding '{army_rule.id}' army rules to the output PDF...")
        for page_range in army_rule.page_ranges:
            output_pdf.append(fileobj=army_rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)
        if with_army_annot and not booklet_mode:
            add_annot(ARMY_COMPACT_W, ARMY_COMPACT_H, annot_font_size, annot_font_face, army_spec_full_text, "\n", output_pdf.get_page(0), ref_box, ARMY_COMPACT_X, ARMY_COMPACT_Y, extra_margin=0.3)
    if with_detachment_rule:
        print(f"Adding '{detachment_rule.id}' detachment rules to the output PDF...")
        for page_range in detachment_rule.page_ranges:
            output_pdf.append(fileobj=detachment_rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)

    datasheets_to_print = []
    for unit in units:
        try:
            datasheet = datasheets[unit.id]
        except:
            raise Exception(f"No datasheet found for '{unit.id}'. Loaded datasheets are {set(id for id in datasheets)}. Exiting")
        datasheet.extra_text = unit.full_text
        datasheets_to_print.append(datasheet)
        if with_unit_comp:
            datasheets_to_print.append(Datasheet(datasheet.id, datasheet.origin, datasheet.page_nb + 1, datasheet.pdf, datasheet.extra_text))

    next_is_top = True
    prev_datasheet_id = None
    for datasheet in datasheets_to_print:
        print(f"Adding '{datasheet.id}' ({datasheet}) to the output PDF...")
        if next_is_top:
            output_pdf.add_blank_page(ref_box.width, ref_box.height)
            current_pages += 1
            current_page = output_pdf.get_page(current_pages - 1)
            datasheet_page = datasheet.pdf.pages[datasheet.page_nb - 1]
            current_page.merge_transformed_page(
                datasheet_page, Transformation().scale(ref_box.width / datasheet_page.mediabox.width).translate(0, ref_box.height // 2), over=False, expand=False
            )
            if with_unit_annot:
                add_annot(annot_wt, annot_ht, annot_font_size, annot_font_face, datasheet.extra_text, "\n", output_pdf.get_page(current_pages-1), ref_box, annot_xt, annot_yt, extra_margin=0.3)
            prev_datasheet_id = datasheet.id
            next_is_top = False
        else:
            current_page = output_pdf.get_page(current_pages - 1)
            datasheet_page = datasheet.pdf.pages[datasheet.page_nb - 1]
            current_page.merge_transformed_page(
                datasheet_page, Transformation().scale(ref_box.width / datasheet_page.mediabox.width).translate(0, 0), over=True, expand=False
            )
            if with_unit_annot and datasheet.id != prev_datasheet_id:
                add_annot(annot_wb, annot_hb, annot_font_size, annot_font_face, datasheet.extra_text, "\n", output_pdf.get_page(current_pages-1), ref_box, annot_xb, annot_yb, extra_margin=0.3)
            prev_datasheet_id = datasheet.id
            next_is_top = True

    print(f"Writing output PDF to {output_path}...")
    with open(output_path, "wb") as output_file:
        output_pdf.write(output_file)
    output_pdf.close()
    print("Done!")

def load_rec_index(army_rules, detachment_rules, datasheets, army_index_path):
    print(f"Loading '{army_index_path}'...")
    with open(army_index_path, "r", encoding="utf-8") as army_index_file:
        content = yaml.load(army_index_file, yaml.Loader)
        army_pdf = pypdf.PdfReader(content["associated_file"])
        if content["army_rules"] is not None:
            for army_rule_name, army_page_ranges in content["army_rules"].items():
                army_rules[army_rule_name] = Rule(army_rule_name, content["associated_file"], army_page_ranges, army_pdf)
        if content["detachment_rules"] is not None:
            for detachment_rule_name, detachment_page_ranges in content["detachment_rules"].items():
                detachment_rules[detachment_rule_name] = Rule(detachment_rule_name, content["associated_file"], detachment_page_ranges, army_pdf)
        for (id, page_nb) in content["datasheets"].items():
            datasheets[id] = Datasheet(id, content["associated_file"], page_nb, army_pdf)
        for include in content["includes"]:
            include_path = os.path.join(PDF_INDEX_DIR, include)
            load_rec_index(army_rules, detachment_rules, datasheets, include_path)

if __name__ == "__main__":
    _main()
