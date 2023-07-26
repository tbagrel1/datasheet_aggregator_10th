import click
import re
import os
import yaml
import math
from pypdf import Transformation, PdfReader, PdfWriter, PageObject
from io import BytesIO
from reportlab.pdfgen import canvas
from dataclasses import dataclass
from typing import Any
from PIL import ImageColor

PDF_INDEX_DIR = os.path.join("data", "pdf_index")

PDFPTS_RATIO = 2.3
LIST_HEADER_RATIO = 0.1
LIST_HEADER_FONT_SIZE = 18
LIST_MARGIN_RATIO = 0.1
DATASHEET_ANNOT_EXTRA_MARGIN = 0.5
PADDING_HALF_PAGE = (os.path.join("data", "pdf", "Space Marines.pdf"), 219)

LIST_MODE_NOTHING = "nothing"
LIST_MODE_JUST_HEADER = "just_header"
LIST_MODE_FULL = "full"

DEFAULT_ANNOT_PARAMS = {
    "header_army_x": 157,
    "header_army_y": 477,
    "header_army_w": 200,
    "header_army_h": 61,
    "top_x": 157,
    "top_y": 445,
    "top_w": 200,
    "top_h": 93,
    "bottom_x": 157,
    "bottom_y": 175,
    "bottom_w": 200,
    "bottom_h": 93,
    "font_face": "Helvetica",
    "font_size": 12,
    "line_spacing": 1.2,
    "color_fg": '#202020',
    "color_bg": '#e3e3e3',
    "color_br": '#202020'
}
DEFAULT_FEATURES = {
    "with_army_rules": True,
    "with_detachment_rules": True,
    "with_extra_pages": True,
    "with_unit_comp": False,
    "with_unit_annot": True,
    "list_mode": LIST_MODE_FULL
}

ARMY_SPEC_RE = (
    r"^(?P<list_header>(?P<list_name>[^\n]+?) \((?P<total_points>[0-9]+) points\)\n"
    r"(?P<raw_army_rule>[^\n]+?(?:\n[^\n]+?)?)\n"
    r"(?P<game_format>[^\n]+? \((?P<max_points>[0-9]+) points\))\n"
    r"(?P<detachment_rule>[^\n]+?))\n"
    r"\n\n"
    r"(?P<rest>CHARACTER\n\n(?:.*?\n)+$)"
)

UNIT_RE = (
    r"(?P<unit_name>[^\n]+?) \((?P<unit_points>[0-9]+) points\)\n"
    r"(?P<wargear>(?:  [^\n]+?\n)+)"
    r"(?:\n|$)"
)

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
    pdf: PdfReader
    page_ranges: list[list[int]]

    def __str__(self):
        return f"pages {self.page_ranges} from '{self.origin}'"

    def __repr__(self):
        return self.__str__()

@dataclass
class Datasheet:
    id: str
    origin: str
    pdf: PdfReader
    page_nb: int
    extra_text: str = ""

    def __str__(self):
        return f"page {self.page_nb} from '{self.origin}'"

    def __repr__(self):
        return self.__str__()


def fuse_group_into(group: list[Unit], units: list[Unit]) -> None:
    if len(group) == 1:
        units.append(group[0])
        return
    total_points = sum(u.points for u in group)
    z = lambda l: ["  • " + l[0]] + ["    " + e for e in l[1:]]
    merged_full_text_lines = "\n".join(
        [f"{len(group)} u. of {group[0].name} ({total_points} points)\n"] +
        [l for u in group for l in z(u.full_text.split("\n")) if l]
    ).strip()
    units.append(
        Unit(
        name=group[0].name,
        id=group[0].id,
        points=total_points,
        full_text=merged_full_text_lines
    ))


def arrange_in_two(text: str, lines_limit: int, sep_p1: str, sep_p2: str) -> tuple[str, str]:
    groups = [[l for l in (sep_p2 + g).split("\n") if l] for g in text.split(sep_p1 + sep_p2) if g]
    l1 = []
    l2 = []
    l1_full = False
    l2_full = False
    c_sep_p1 = len(sep_p1[1:].split("\n")) - 1
    c1 = 0
    c2 = 0
    for g in groups:
        if not l1_full:
            if not l1:
                g[0] = g[0][len(sep_p2):]  # cut extra useless delimiter
                l1.extend(g)
                c1 += len(g)
            else:
                if c1 + c_sep_p1 + len(g) <= lines_limit:
                    g[0] = sep_p1[1:] + g[0]
                    l1.extend(g)
                    c1 += c_sep_p1 + len(g)
                else:
                    # print(f"{c1}/{lines_limit} lines filled, putting the next {len(g)}({c_sep_p1 + len(g)}) on the next column")
                    l1_full = True
                    l2.extend(g)
                    c2 += len(g)
        else:
            if not l2_full and c2 + c_sep_p1 + len(g) > lines_limit:
                m = "\n".join(g)
                print(f"Warning: overflowing text: {repr(m)}...")
                l2_full = True
            g[0] = sep_p1[1:] + g[0]
            l2.extend(g)
            c2 += c_sep_p1 + len(g)
    return "\n".join(l1), "\n".join(l2)


def add_annot(page: PageObject, text_content: str, pos_params: dict[str, float], annot_params: dict[str, Any], sep_p1: str, sep_p2: str, extra_margin: float = DATASHEET_ANNOT_EXTRA_MARGIN) -> None:
    line_height = annot_params["line_spacing"] * annot_params["font_size"]
    packet = BytesIO()
    # create a new PDF with Reportlab
    canvas_width, canvas_height = pos_params["w"] * PDFPTS_RATIO, pos_params["h"] * PDFPTS_RATIO
    can = canvas.Canvas(packet, pagesize=(canvas_width, canvas_height))
    can.setFillColorRGB(*annot_params["color_bg"])
    can.setStrokeColorRGB(*annot_params["color_br"])
    can.rect(0, 0, canvas_width, canvas_height, fill=1)
    can.setFillColorRGB(*annot_params["color_fg"])
    to = can.beginText(extra_margin * annot_params["font_size"], canvas_height - (1 + (max(0, extra_margin - 0.2))) * annot_params["font_size"])
    to.setFont(annot_params["font_face"], annot_params["font_size"], line_height)
    nb_lines_in_one_column = int(math.floor(canvas_height / line_height))
    l1, l2 = arrange_in_two(text_content, nb_lines_in_one_column, sep_p1, sep_p2)
    for line in l1.split("\n"):
        line = line.rstrip()
        if line and line[-1] == ")":
            to.setFont(annot_params["font_face"] + "-Bold", annot_params["font_size"], line_height)
            to.textLine(line)
            to.setFont(annot_params["font_face"], annot_params["font_size"], line_height)
        else:
            to.textLine(line)
    # to.textLines(l1, trim=0)
    can.drawText(to)
    if l2:
        can.rect(canvas_width / 2 - annot_params["font_size"], 0, 0, canvas_height)
        to2 = can.beginText(canvas_width // 2 + annot_params["font_size"], canvas_height - (1 + (max(0, extra_margin - 0.2))) * annot_params["font_size"])
        to2.setFont(annot_params["font_face"], annot_params["font_size"])
        to2.setLeading(line_height)
        for line in l2.split("\n"):
            line = line.rstrip()
            if line and line[-1] == ")":
                to2.setFont(annot_params["font_face"] + "-Bold", annot_params["font_size"], line_height)
                to2.textLine(line)
                to2.setFont(annot_params["font_face"], annot_params["font_size"], line_height)
            else:
                to2.textLine(line)
        # to2.textLines(l2, trim=0)
        can.drawText(to2)
    can.save()
    packet.seek(0)
    annotation = PdfReader(packet).pages[0]
    page.merge_transformed_page(
            annotation, Transformation().scale(1.0 / PDFPTS_RATIO).translate(pos_params["x"], pos_params["y"]), over=True, expand=False
        )

def load_rec_index(army_index_path: str, army_rules: dict[str, Rule], detachment_rules: dict[str, Rule], full_extra_pages: list[Rule], half_extra_pages: list[Datasheet], datasheets: dict[str, Datasheet]) -> None:
    print(f"Loading '{army_index_path}'...")
    with open(army_index_path, "r", encoding="utf-8") as army_index_file:
        content = yaml.load(army_index_file, yaml.Loader)
    army_pdf = PdfReader(content["associated_file"])
    if "army_rules" in content and content["army_rules"] is not None:
        for army_rule_name, army_page_ranges in content["army_rules"].items():
            army_rules[army_rule_name] = Rule(army_rule_name, content["associated_file"], army_pdf, army_page_ranges)
    if "detachment_rules" in content and content["detachment_rules"] is not None:
        for detachment_rule_name, detachment_page_ranges in content["detachment_rules"].items():
            detachment_rules[detachment_rule_name] = Rule(detachment_rule_name, content["associated_file"], army_pdf, detachment_page_ranges)
    if "full_extra_pages" in content and content["full_extra_pages"] is not None:
        full_extra_pages.append(Rule("extra rule", content["associated_file"], army_pdf, content["full_extra_pages"]))
    if "half_extra_pages" in content and content["half_extra_pages"] is not None:
        for page_nb in content["half_extra_pages"]:
            half_extra_pages.append(Datasheet("extra rule", content["associated_file"], army_pdf, page_nb))
    for (id, page_nb) in content["datasheets"].items():
        datasheets[id] = Datasheet(id, content["associated_file"], army_pdf, page_nb)
    if content["includes"]:
        for include in content["includes"]:
            include_path = os.path.join(PDF_INDEX_DIR, include)
            load_rec_index(include_path, army_rules, detachment_rules, full_extra_pages, half_extra_pages, datasheets)


def convert_color(hexstring: str) -> tuple[float, float, float]:
    return tuple(i/256.0 for i in ImageColor.getrgb(hexstring))


def parse_and_group_units(rest_of_the_list: str) -> list[Unit]:
    units = []
    group = []
    group_id = None
    for match in re.finditer(UNIT_RE, rest_of_the_list):
        current = Unit(
            name=match.group("unit_name"),
            id=match.group("unit_name").strip().upper(),
            points=int(match.group("unit_points")),
            full_text=match.group(0).strip()
        )
        if current.id != group_id and group_id is not None:
            fuse_group_into(group, units)
            group = []
        group.append(current)
        group_id = current.id
    fuse_group_into(group, units)
    return units

def resolve_army_index_path_from_army_name(try_army_name: str) -> str:
    pdf_index_names = os.listdir(PDF_INDEX_DIR)
    if try_army_name + ".yaml" in pdf_index_names:
        army_index_path = os.path.join(PDF_INDEX_DIR, try_army_name + ".yaml")
        retry = False
    elif " -- " in try_army_name:
        new_try = try_army_name.split(" -- ")[0]
        print(f"I didn't find '{try_army_name}', trying '{new_try}'")
        try_army_name = new_try
        retry = True
    else:
        raise Exception(f"I didn't find '{try_army_name}', exiting.")
    if retry:
        if try_army_name + ".yaml" in pdf_index_names:
            army_index_path = os.path.join(PDF_INDEX_DIR, try_army_name + ".yaml")
        else:
            raise Exception(f"I didn't find '{try_army_name}', exiting.")
    return army_index_path

def get_pos_params(annot_params: dict[str, Any], region: str) -> dict[str, float]:
    return {c: annot_params[region + "_" + c] for c in "xywh"}


@click.command()
@click.argument("INPUT_PATH", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.argument("OUTPUT_PATH", type=click.Path())
@click.option("--with-army-rules/--without-army-rules", default=DEFAULT_FEATURES["with_army_rules"])
@click.option("--with-detachment-rules/--without-detachment-rules", default=DEFAULT_FEATURES["with_detachment_rules"])
@click.option("--with-extra-pages/--without-with-extra-pages", default=DEFAULT_FEATURES["with_extra_pages"])
@click.option("--with-unit-comp/--without-unit-comp", default=DEFAULT_FEATURES["with_unit_comp"])
@click.option("--with-unit-annot/--without-unit-annot", default=DEFAULT_FEATURES["with_unit_annot"])
@click.option("--list-mode", type=click.Choice([LIST_MODE_FULL, LIST_MODE_JUST_HEADER, LIST_MODE_NOTHING]), default=DEFAULT_FEATURES["list_mode"])
@click.option("--annot-header-army-x", type=float, default=DEFAULT_ANNOT_PARAMS["header_army_x"])
@click.option("--annot-header-army-y", type=float, default=DEFAULT_ANNOT_PARAMS["header_army_y"])
@click.option("--annot-header-army-w", type=float, default=DEFAULT_ANNOT_PARAMS["header_army_w"])
@click.option("--annot-header-army-h", type=float, default=DEFAULT_ANNOT_PARAMS["header_army_h"])
@click.option("--annot-top-x", type=float, default=DEFAULT_ANNOT_PARAMS["top_x"])
@click.option("--annot-top-y", type=float, default=DEFAULT_ANNOT_PARAMS["top_y"])
@click.option("--annot-top-w", type=float, default=DEFAULT_ANNOT_PARAMS["top_w"])
@click.option("--annot-top-h", type=float, default=DEFAULT_ANNOT_PARAMS["top_h"])
@click.option("--annot-bottom-x", type=float, default=DEFAULT_ANNOT_PARAMS["bottom_x"])
@click.option("--annot-bottom-y", type=float, default=DEFAULT_ANNOT_PARAMS["bottom_y"])
@click.option("--annot-bottom-w", type=float, default=DEFAULT_ANNOT_PARAMS["bottom_w"])
@click.option("--annot-bottom-h", type=float, default=DEFAULT_ANNOT_PARAMS["bottom_h"])
@click.option("--annot-font-face", type=str, default=DEFAULT_ANNOT_PARAMS["font_face"])
@click.option("--annot-font-size", type=float, default=DEFAULT_ANNOT_PARAMS["font_size"])
@click.option("--annot-line-spacing", type=float, default=DEFAULT_ANNOT_PARAMS["line_spacing"])
@click.option("--annot-color-fg", type=str, default=DEFAULT_ANNOT_PARAMS["color_fg"])
@click.option("--annot-color-bg", type=str, default=DEFAULT_ANNOT_PARAMS["color_bg"])
@click.option("--annot-color-br", type=str, default=DEFAULT_ANNOT_PARAMS["color_br"])
@click.option("--gui/--no-gui", default=False)
def _main(**params):
    if params["gui"]:
        raise Exception("Not implement yet.")
    else:
        main(
            params["input_path"],
            params["output_path"],
            {key: params[key] for key in DEFAULT_FEATURES},
            {key: params["annot_" + key] for key in DEFAULT_ANNOT_PARAMS}
        )

def main(input_path, output_path, features, annot_params):
    annot_params["color_fg"] = convert_color(annot_params["color_fg"])
    annot_params["color_bg"] = convert_color(annot_params["color_bg"])
    annot_params["color_br"] = convert_color(annot_params["color_br"])

    with open(input_path, "r", encoding="utf-8") as input_file:
        list_content = input_file.read()

    list_match = re.search(ARMY_SPEC_RE, list_content)
    if list_match is None:
        raise Exception("Army list doesn't match the expected format.")
    
    list_header = list_match.group("list_header")
    list_name = list_match.group("list_name")
    total_points = int(list_match.group("total_points"))
    raw_army_name = list_match.group("raw_army_rule")
    game_format = list_match.group("game_format")
    max_points = int(list_match.group("max_points"))
    detachment_rule_name = list_match.group("detachment_rule")
    
    rest_of_the_list = list_match.group("rest")

    try_army_name = raw_army_name.replace("\n", " -- ")
    print(f"Parsed army header of '{list_name}' ({try_army_name}) with {total_points}/{max_points} points!")

    final_list_units = parse_and_group_units(rest_of_the_list)
    main_army_index_path = resolve_army_index_path_from_army_name(try_army_name)

    army_rules: dict[str, Rule] = {}
    detachment_rules: dict[str, Rule] = {}
    datasheet_dict: dict[str, Datasheet] = {}
    full_extra_pages: list[Rule] = []
    half_extra_pages: list[Datasheet] = []
    load_rec_index(main_army_index_path, army_rules, detachment_rules, full_extra_pages, half_extra_pages, datasheet_dict)

    # TODO: fix that for allied IK and RK
    # check that we only found 1 army rule
    if len(army_rules) > 1:
        raise Exception(f"Several army rules detected: {army_rules}, exiting.")
    army_rule = list(army_rules.items())[0][1]
    if detachment_rule_name not in detachment_rules:
        raise Exception(f"Requested detachement rule {detachment_rule_name} not found in {detachment_rules}, exiting.")
    detachment_rule = detachment_rules[detachment_rule_name]
    print(f"Playing with army rule '{army_rule.id}' and detachment_rule '{detachment_rule.id}'!")

    output_pdf = PdfWriter()
    current_pages = 0
    ref_box = army_rule.pdf.pages[0].mediabox

    # add first page with list recap if needed
    if features["list_mode"] == LIST_MODE_FULL:
        print("Adding a first page with the list recap...")
        output_pdf.add_blank_page(ref_box.width, ref_box.height)
        current_pages += 1
        
        # add list header
        h = (LIST_HEADER_RATIO * ref_box.height)
        pos_params = {
            "x": (LIST_MARGIN_RATIO * ref_box.width),
            "y": (ref_box.height - LIST_MARGIN_RATIO * ref_box.width - h),
            "w": ((1 - 2 * LIST_MARGIN_RATIO) * ref_box.width),
            "h": h
        }
        list_header_annot_params = annot_params.copy()
        list_header_annot_params["font_size"] = LIST_HEADER_FONT_SIZE
        add_annot(output_pdf.get_page(current_pages-1), list_header, pos_params, list_header_annot_params, "\n", "")

        # add rest of the list
        h = ((1 - LIST_HEADER_RATIO) * ref_box.height - 2 * LIST_MARGIN_RATIO * ref_box.width)
        pos_params = {
            "x": (LIST_MARGIN_RATIO * ref_box.width),
            "y": ((1 - LIST_HEADER_RATIO) * ref_box.height - LIST_MARGIN_RATIO * ref_box.width - h),
            "w": ((1 - 2 * LIST_MARGIN_RATIO) * ref_box.width),
            "h": h
        }
        add_annot(output_pdf.get_page(current_pages-1),rest_of_the_list, pos_params, annot_params, "\n\n", "")

    # add army rules if needed
    if features["with_army_rules"]:
        for page_range in army_rule.page_ranges:
            print(f"Adding '{army_rule.id}' army rules (pages {page_range[0]-page_range[1]} from '{army_rule.origin}')...")
            output_pdf.append(fileobj=army_rule.pdf, pages=(page_range[0]-1, page_range[1]))
            current_pages += page_range[1] - (page_range[0]-1)
        
        if features["list_mode"] == LIST_MODE_JUST_HEADER:
            add_annot(output_pdf.get_page(0), list_header, get_pos_params(annot_params, "header_army"), annot_params, "\n", "")

    # add detachment rules if needed
    if features["with_detachment_rules"]:
        for page_range in detachment_rule.page_ranges:
            print(f"Adding '{detachment_rule.id}' detachment rules (pages {page_range[0]-page_range[1]} from '{detachment_rule.origin}')...")
            output_pdf.append(fileobj=detachment_rule.pdf, pages=(page_range[0]-1, page_range[1]))
            current_pages += page_range[1] - (page_range[0]-1)

    datasheets_to_print: list[Datasheet] = []
    # we want to only include extra pages of indexes from which at least one unit is drawn
    # so first we trace which indexes are actually "used"
    used_origins = set()
    for unit in final_list_units:
        try:
            datasheet = datasheet_dict[unit.id]
        except:
            raise Exception(f"No datasheet found for '{unit.id}'. Loaded datasheets are {set(id for id in datasheet_dict)}. Exiting")
        used_origins.add(datasheet.origin)
        datasheet.extra_text = unit.full_text
        datasheets_to_print.append(datasheet)
        if features["with_unit_comp"]:
            # add the unit composition sheet as a pseudo-datasheet
            datasheets_to_print.append(Datasheet(datasheet.id, datasheet.origin, datasheet.pdf, datasheet.page_nb + 1, datasheet.extra_text))

    # add extra rule pages if needed
    if features["with_extra_pages"]:
        # now we add only the needed extra pages, starting with full ones:
        for extra_pages in full_extra_pages:
            if extra_pages.origin not in used_origins:
                continue
            for page_range in extra_pages.page_ranges:
                print(f"Adding extra rule (pages {page_range[0]-page_range[1]} from '{extra_pages.origin}')...")
                output_pdf.append(fileobj=extra_pages.pdf, pages=(page_range[0]-1, page_range[1]))
                current_pages += page_range[1] - (page_range[0]-1)

        # now we add the half ones as pseudo-datasheets to be printed before the actual ones
        half_extra_pages_to_include = [extra_page for extra_page in half_extra_pages if extra_page.origin in used_origins]
        if len(half_extra_pages_to_include) % 2 == 1:
            # pad to start datasheets on a new page
            half_extra_pages_to_include.append(Datasheet("padding", PADDING_HALF_PAGE[0], PdfReader(PADDING_HALF_PAGE[0]), PADDING_HALF_PAGE[1]))
        datasheets_to_print = half_extra_pages_to_include + datasheets_to_print

    # start bi-modal printing
    next_is_top = True
    for datasheet in datasheets_to_print:
        print(f"Adding '{datasheet.id}' ({datasheet})...")
        if next_is_top:
            output_pdf.add_blank_page(ref_box.width, ref_box.height)
            current_pages += 1
            current_page = output_pdf.get_page(current_pages - 1)
            pdf_page = datasheet.pdf.pages[datasheet.page_nb - 1]
            current_page.merge_transformed_page(pdf_page, Transformation().scale(ref_box.width / pdf_page.mediabox.width).translate(0, ref_box.height // 2), over=True, expand=False)
            if features["with_unit_annot"] and datasheet.extra_text:
                add_annot(current_page, datasheet.extra_text, get_pos_params(annot_params, "top"), annot_params, "\n", "  • ")
            next_is_top = False
        else:
            pdf_page = datasheet.pdf.pages[datasheet.page_nb - 1]
            current_page.merge_transformed_page(pdf_page, Transformation().scale(ref_box.width / pdf_page.mediabox.width).translate(0, 0), over=True, expand=False)
            if features["with_unit_annot"] and datasheet.extra_text and not features["with_unit_comp"]:
                add_annot(current_page, datasheet.extra_text, get_pos_params(annot_params, "bottom"), annot_params, "\n", "  • ")
            next_is_top = True

    # Write PDF and we are done!
    print(f"Writing output PDF to '{output_path}'...")
    with open(output_path, "wb") as output_file:
        output_pdf.write(output_file)
    output_pdf.close()
    print("Done!")

if __name__ == "__main__":
    _main()
