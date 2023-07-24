import click
import re
import os
import yaml
import pypdf
from pypdf.generic import AnnotationBuilder

from dataclasses import dataclass

@dataclass
class Unit:
    name: str
    id: str
    points: str
    wargear: str
    full_text: str

@dataclass
class Datasheet:
    id: str
    origin: str
    page_ranges: list[list[int]]
    pdf: pypdf.PdfReader

    def __str__(self):
        return f"pages {self.page_ranges} from '{self.origin}'"

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

PDF_INDEX_DIR = "data/pdf_index"
DEFAULT_FONT_FACE = "Arial"
DEFAULT_FONT_SIZE = 10
DEFAULT_X = 200
DEFAULT_Y = 264 # 282 for kratos
DEFAULT_H = 93 # 75 for kratos
DEFAULT_W = 339
DEFAULT_FG_COLOR = '000000'
DEFAULT_BG_COLOR = 'ffffff'
DEFAULT_BR_COLOR = '000000'

ARMY_X = 150
ARMY_Y = 477
ARMY_H = 61
ARMY_W = 207

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
@click.option("--annot-x", type=int, default=DEFAULT_X)
@click.option("--annot-y", type=int, default=DEFAULT_Y)
@click.option("--annot-w", type=int, default=DEFAULT_W)
@click.option("--annot-h", type=int, default=DEFAULT_H)
@click.option("--annot-fg-color", type=str, default=DEFAULT_FG_COLOR)
@click.option("--annot-bg-color", type=str, default=DEFAULT_BG_COLOR)
@click.option("--annot-br-color", type=str, default=DEFAULT_BR_COLOR)
def main(input_path, output_path, with_army_rule, with_detachment_rule, with_unit_comp, with_army_annot, with_unit_annot, annot_font_face, annot_font_size, annot_x, annot_y, annot_w, annot_h, annot_fg_color, annot_bg_color, annot_br_color):
    with open(input_path, "r", encoding="utf-8") as input_file:
        list_content = input_file.read()
    army_spec_match = re.search(ARMY_SPEC_RE, list_content)
    if army_spec_match is None:
        raise Exception("Army spec doesn't match the expected format.")
    army_spec_full_text = army_spec_match.group(0)
    list_name = army_spec_match.group("list_name")
    total_points = army_spec_match.group("total_points")
    raw_army_rule = army_spec_match.group("raw_army_rule")
    army_name_try = raw_army_rule.replace("\n", ": ")
    game_format = army_spec_match.group("game_format")
    max_points = army_spec_match.group("max_points")
    detachment_rule_name = army_spec_match.group("detachment_rule")
    print(f"Found army of '{army_name_try}' with {total_points}/{max_points}!")

    units = []
    for match in re.finditer(UNIT_RE, list_content):
        units.append(Unit(
            name=match.group("unit_name"),
            id=match.group("unit_name").strip().upper(),
            points=match.group("unit_points"),
            wargear=match.group("wargear"),
            full_text=match.group(0)
        ))
    for u in units:
        print(u)

    pdf_index_names = os.listdir(PDF_INDEX_DIR)
    if army_name_try + ".yaml" in pdf_index_names:
        army_name = army_name_try
        army_index_path = os.path.join(PDF_INDEX_DIR, army_name_try + ".yaml")
        retry = False
    elif ": " in army_name_try:
        new_try = army_name_try.split(": ")[0]
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
    if with_army_rule:
        print(f"Adding '{army_rule.id}' army rules to the output PDF...")
        for page_range in army_rule.page_ranges:
            output_pdf.append(fileobj=army_rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)
        if with_army_annot:
            annotation = AnnotationBuilder.free_text(
                army_spec_full_text,
                rect=(ARMY_X, ARMY_Y, ARMY_X + ARMY_W, ARMY_Y + ARMY_H),
                font=annot_font_face,
                bold=False,
                italic=False,
                font_size=annot_font_size,
                font_color=annot_fg_color,
                border_color=annot_br_color,
                background_color=annot_bg_color
            )
            output_pdf.add_annotation(page_number=0, annotation=annotation)
    if with_detachment_rule:
        print(f"Adding '{detachment_rule.id}' detachment rules to the output PDF...")
        for page_range in detachment_rule.page_ranges:
            output_pdf.append(fileobj=detachment_rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)
    for unit in units:
        try:
            datasheet = datasheets[unit.id]
        except:
            raise Exception(f"No datasheet found for '{unit.id}'. Loaded datasheets are {set(id for id in datasheets)}. Exiting")
        print(f"Adding '{datasheet.id}' datasheet to the output PDF...")
        if with_unit_comp:
            for page_range in datasheet.page_ranges:
                output_pdf.append(fileobj=datasheet.pdf, pages=(page_range[0]-1, page_range[1]))
            current_pages += page_range[1] - (page_range[0]-1)
        else:
            page_range_0 = datasheet.page_ranges[0][0]
            output_pdf.append(fileobj=datasheet.pdf, pages=(page_range_0-1, page_range_0))
            current_pages += 1
        if with_unit_annot:
            annotation = AnnotationBuilder.free_text(
                unit.full_text,
                rect=(annot_x, annot_y, annot_x + annot_w, annot_y + annot_h),
                font=annot_font_face,
                bold=False,
                italic=False,
                font_size=annot_font_size,
                font_color=annot_fg_color,
                border_color=annot_br_color,
                background_color=annot_bg_color
            )
            output_pdf.add_annotation(page_number=current_pages-1, annotation=annotation)
    print(f"Writing output PDF to {output_path}...")
    with open(output_path, "wb") as output_file:
        output_pdf.write(output_file)
    output_pdf.close()
    print("Done!")

def load_rec_index(army_rules, detachment_rules, datasheets, army_index_path):
    print(f"Loading '{army_index_path}'...")
    with open(army_index_path, "r", encoding="utf-8") as army_index_file:
        content = yaml.load(army_index_file)
        army_pdf = pypdf.PdfReader(content["associated_file"])
        if content["army_rules"] is not None:
            for army_rule_name, army_page_ranges in content["army_rules"].items():
                army_rules[army_rule_name] = Datasheet(army_rule_name, content["associated_file"], army_page_ranges, army_pdf)
        if content["detachment_rules"] is not None:
            for detachment_rule_name, detachment_page_ranges in content["detachment_rules"].items():
                detachment_rules[detachment_rule_name] = Datasheet(detachment_rule_name, content["associated_file"], detachment_page_ranges, army_pdf)
        for (id, page_ranges) in content["datasheets"].items():
            datasheets[id] = Datasheet(id, content["associated_file"], page_ranges, army_pdf)
        for include in content["includes"]:
            include_path = os.path.join(PDF_INDEX_DIR, include)
            load_rec_index(army_rules, detachment_rules, datasheets, include_path)

if __name__ == "__main__":
    main()
