#!/usr/bin/env python3

import click
import re
import os
import yaml
import math
import sys
import traceback
import tkinter as tk
from tkinter import filedialog as fd
from tkinter import ttk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from pypdf import Transformation, PdfReader, PdfWriter, PageObject
from io import BytesIO
from reportlab.pdfgen import canvas
from dataclasses import dataclass
from typing import Any, Union
from PIL import ImageColor

PDF_INDEX_DIR = os.path.join("data", "pdf_index")

PDFPTS_RATIO = 2.3
LIST_HEADER_RATIO = 0.1
LIST_HEADER_FONT_SIZE = 18
LIST_MARGIN_RATIO = 0.1
DATASHEET_ANNOT_EXTRA_MARGIN = 0.3

LIST_MODE_NOTHING = "nothing"
LIST_MODE_JUST_HEADER = "just_header"
LIST_MODE_FULL = "full"

DEFAULT_ANNOT_PARAMS = {
    "header_army_x": 0,
    "header_army_y": 477,
    "header_army_w": 157,
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
    "with_army_rule": True,
    "with_detachment_rule": True,
    "with_detachment_stratagems": True,
    "with_detachment_enhancements": True,
    "with_armoury": True,
    "with_unit_comp": False,
    "with_unit_annot": True,
    "list_mode": LIST_MODE_FULL,
    "with_armoury_padding": False
}

ARMY_SPEC_RE = (
    r"^(?P<list_header>(?P<list_name>[^\n]+?) \((?P<total_points>[0-9]+) points\)\n"
    r"(?P<raw_army_rule>[^\n]+?(?:\n[^\n]+?)?)\n"
    r"(?P<game_format>[^\n]+? \((?P<max_points>[0-9]+) points\))\n"
    r"(?P<detachment_rule>[^\n]+?))\n"
    r"\n\n"
    r"(?P<rest>(?:.*\n?)+\Z)"
)

UNIT_RE = (
    r"(?P<unit_name>[^\n]+?) \((?P<unit_points>[0-9]+) points\)\n"
    r"(?P<wargear>(?:  [^\n]*?(?:\n|\Z))+)"
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
    page_range: list[int] | None

    def __str__(self):
        return f"pages {self.page_range} from '{self.origin}'"

    def __repr__(self):
        return self.__str__()

@dataclass
class Detachment:
    id: str
    origin: str
    rule: Rule
    stratagems: Rule
    enhancements: Rule

    def __str__(self):
        return f"{self.rule}\n{self.stratagems}\n{self.enhancements}"

    def __repr__(self):
        return self.__str__()

@dataclass
class Datasheet:
    id: str
    origin: str
    pdf: PdfReader
    page_range: list[int]
    extra_text: str = ""
    is_armoury: bool = False

    def __str__(self):
        return f"pages {self.page_range} from '{self.origin}'"

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
    u = Unit(
        name=group[0].name,
        id=group[0].id,
        points=total_points,
        full_text=merged_full_text_lines
    )
    units.append(u)


def arrange_in_two(text: str, lines_count_limit: int, sep: str, breakpoint_lookahead: str) -> tuple[str, str]:
    str_groups_with_lookahead_removed = [g for g in text.split(sep + breakpoint_lookahead) if g.strip()]
    str_groups_with_lookahead_added_back = [] if not str_groups_with_lookahead_removed else [str_groups_with_lookahead_removed[0]] + [breakpoint_lookahead + g for g in str_groups_with_lookahead_removed[1:]]
    lines_groups = [[l for l in g.split("\n") if l.strip()] for g in str_groups_with_lookahead_added_back]  # This removes empty lines inside a group
    nb_empty_lines_sep_equiv = len(sep.split("\n")) - 2

    lines_column1 = []
    lines_column2 = []
    is_full_column1 = False
    lines_count_column1 = 0
    lines_count_column2 = 0

    for lines_group in lines_groups:
        if not is_full_column1:
            if not lines_column1:
                # first element of column, so doesn't need to be prefixed by sep
                expected_size = len(lines_group)
                lines_column1.extend(lines_group)
                lines_count_column1 += expected_size
            else:
                # not the first element, so need to be prefixed by sep
                expected_size = len(lines_group) + nb_empty_lines_sep_equiv
                if lines_count_column1 + expected_size <= lines_count_limit:
                    # it will fit in column 1
                    lines_column1.extend([""] * nb_empty_lines_sep_equiv + lines_group)
                    lines_count_column1 += expected_size
                else:
                    # if won't fit in column 1, so mark column 1 as complete and go to column 2
                    # now it doesn't need to be prefixed by sep
                    expected_size = len(lines_group)
                    is_full_column1 = True
                    lines_column2.extend(lines_group)
                    lines_count_column2 += expected_size
        else:
            # it isn't the first element of column 2 (so it needs a sep), and we have to put it in column 2 regardless of its size
            expected_size = len(lines_group) + nb_empty_lines_sep_equiv
            lines_column2.extend([""] * nb_empty_lines_sep_equiv + lines_group)
            lines_count_column2 += expected_size

    if lines_count_column1 > lines_count_limit:
        # should not happen
        overflowing_text = "\n".join(lines_column1[lines_count_limit:])
        print(f"Warning: overflowing text in column 1: '''{overflowing_text}'''...")
    if lines_count_column2 > lines_count_limit:
        overflowing_text = "\n".join(lines_column2[lines_count_limit:])
        print(f"Warning: overflowing text in column 2: '''{overflowing_text}'''...")

    return "\n".join(lines_column1), "\n".join(lines_column2)


def add_annot(page: PageObject, text_content: str, pos_params: dict[str, float], annot_params: dict[str, Any], sep_can_be_discarded_pb: str, sep_must_be_kept: str, extra_margin: float = DATASHEET_ANNOT_EXTRA_MARGIN) -> None:
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
    l1, l2 = arrange_in_two(text_content, nb_lines_in_one_column, sep_can_be_discarded_pb, sep_must_be_kept)
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
        can.rect(canvas_width / 2, 0, 0, canvas_height)
        to2 = can.beginText(canvas_width / 2 + extra_margin * annot_params["font_size"], canvas_height - (1 + (max(0, extra_margin - 0.2))) * annot_params["font_size"])
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


def get_army_name(army_index_path: str) -> str:
    _, filename = os.path.split(army_index_path)
    base, _ = os.path.splitext(filename)
    return base


def parse_page_ref(raw: Union[int, list[int]], allow_none=False) -> list[int] | None:
    if isinstance(raw, int):
        return [raw, raw]
    elif isinstance(raw, list):
        return raw
    elif allow_none and raw is None:
        return None
    else:
        raise Exception("Invalid format for page reference")


def load_rec_index(army_index_path: str, army_rules: list[Rule], detachments: dict[str, Detachment], armoury_full_pages: list[Rule], armoury_half_pages: list[Datasheet], datasheets: dict[str, Datasheet], status_function, is_main: bool = True) -> None:
    status_function(f"Loading '{army_index_path}'...")
    with open(army_index_path, "r", encoding="utf-8") as army_index_file:
        content = yaml.load(army_index_file, yaml.Loader)
    army_pdf = PdfReader(content["associated_file"])
    if is_main and "army_rule" in content and content["army_rule"] is not None:
        army_rules.append(Rule(get_army_name(army_index_path), content["associated_file"], army_pdf, parse_page_ref(content["army_rule"])))
    if is_main and "detachments" in content and content["detachments"] is not None:
        for detachment in content["detachments"]:
            detachments[detachment["name"]] = Detachment(
                detachment["name"], content["associated_file"],
                Rule(detachment["name"] + " rule", content["associated_file"], army_pdf, parse_page_ref(detachment["rule"])),
                Rule(detachment["name"] + " stratagems", content["associated_file"], army_pdf, parse_page_ref(detachment["stratagems"])),
                Rule(detachment["name"] + " enhancements", content["associated_file"], army_pdf, parse_page_ref(detachment["enhancements"], allow_none=True))
            )
    if "armoury_full_pages" in content and content["armoury_full_pages"] is not None:
        armoury_full_pages.append(Rule("extra rule", content["associated_file"], army_pdf, parse_page_ref(content["armoury_full_pages"])))
    if "armoury_half_pages" in content and content["armoury_half_pages"] is not None:
        armoury_half_pages.append(Datasheet("armoury", content["associated_file"], army_pdf, parse_page_ref(content["armoury_half_pages"]), "", True))
    for (id, page_range) in content["datasheets"].items():
        datasheets[id] = Datasheet(id, content["associated_file"], army_pdf, parse_page_ref(page_range))
    if "includes" in content and content["includes"] is not None:
        for include in content["includes"]:
            include_path = os.path.join(PDF_INDEX_DIR, include)
            load_rec_index(include_path, army_rules, detachments, armoury_full_pages, armoury_half_pages, datasheets, status_function, is_main=True)
    if "includes_allies" in content and content["includes_allies"] is not None and is_main:
        for include in content["includes_allies"]:
            include_path = os.path.join(PDF_INDEX_DIR, include)
            load_rec_index(include_path, army_rules, detachments, armoury_full_pages, armoury_half_pages, datasheets, status_function, is_main=False)


def convert_color(hexstring: str) -> tuple[float, float, float]:
    return tuple(i/256.0 for i in ImageColor.getrgb(hexstring))


def parse_and_group_units(rest_of_the_list: str) -> list[Unit]:
    units = []
    group = []
    group_id = None
    for match in re.finditer(UNIT_RE, rest_of_the_list):
        # print(match)
        current = Unit(
            name=match.group("unit_name"),
            id=match.group("unit_name").strip().upper(),
            points=int(match.group("unit_points")),
            full_text=match.group(0).strip()
        )
        if current.id != group_id and group:
            fuse_group_into(group, units)
            group = []
        group.append(current)
        group_id = current.id
    if group:
        fuse_group_into(group, units)
    return units

def resolve_army_index_path_from_army_name(try_army_name: str) -> str:
    pdf_index_names = os.listdir(PDF_INDEX_DIR)
    if try_army_name + ".yaml" in pdf_index_names:
        army_index_path = os.path.join(PDF_INDEX_DIR, try_army_name + ".yaml")
        retry = False
    elif " -- " in try_army_name:
        new_try = try_army_name.split(" -- ")[0]
        print(f"Warning: I didn't find '{try_army_name}', trying '{new_try}'")
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
@click.option("--nogui-input-path", "-i", type=click.Path(exists=True, dir_okay=False, resolve_path=True), default=None)
@click.option("--output-path", "-o", type=click.Path(dir_okay=False), default=None)
@click.option("--with-army-rule/--without-army-rule", default=DEFAULT_FEATURES["with_army_rule"])
@click.option("--with-detachment-rule/--without-detachment-rule", default=DEFAULT_FEATURES["with_detachment_rule"])
@click.option("--with-detachment-stratagems/--without-detachment-stratagems", default=DEFAULT_FEATURES["with_detachment_stratagems"])
@click.option("--with-detachment-enhancements/--without-detachment-enhancements", default=DEFAULT_FEATURES["with_detachment_enhancements"])
@click.option("--with-armoury/--without-armoury", default=DEFAULT_FEATURES["with_armoury"])
@click.option("--with-unit-comp/--without-unit-comp", default=DEFAULT_FEATURES["with_unit_comp"])
@click.option("--with-unit-annot/--without-unit-annot", default=DEFAULT_FEATURES["with_unit_annot"])
@click.option("--list-mode", "-l", type=click.Choice([LIST_MODE_FULL, LIST_MODE_JUST_HEADER, LIST_MODE_NOTHING]), default=DEFAULT_FEATURES["list_mode"])
@click.option("--with-armoury-padding/--without-armoury-padding", default=DEFAULT_FEATURES["with_armoury_padding"])
@click.option("--annot-font-face", type=str, default=DEFAULT_ANNOT_PARAMS["font_face"])
@click.option("--annot-font-size", type=float, default=DEFAULT_ANNOT_PARAMS["font_size"])
@click.option("--annot-line-spacing", type=float, default=DEFAULT_ANNOT_PARAMS["line_spacing"])
@click.option("--annot-color-fg", type=str, default=DEFAULT_ANNOT_PARAMS["color_fg"])
@click.option("--annot-color-bg", type=str, default=DEFAULT_ANNOT_PARAMS["color_bg"])
@click.option("--annot-color-br", type=str, default=DEFAULT_ANNOT_PARAMS["color_br"])
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
def main(**params):
    if params["nogui_input_path"] is None:
        gui(
            {key: params[key] for key in DEFAULT_FEATURES},
            {key: params["annot_" + key] for key in DEFAULT_ANNOT_PARAMS}
        )
    else:
        try:

            with open(params["nogui_input_path"], "r", encoding="utf-8") as input_file:
                list_content = input_file.read()
            if params["output_path"] is None or not params["output_path"].strip():
                root, ext = os.path.splitext(params["nogui_input_path"])
                output_path = root + ".pdf"
            else:
                output_path = params["output_path"]
            convert_list_to_pdf(
                list_content,
                output_path,
                {key: params[key] for key in DEFAULT_FEATURES},
                {key: params["annot_" + key] for key in DEFAULT_ANNOT_PARAMS},
                print
            )
            sys.exit(0)
        except Exception as e:
            print(traceback.format_exc())
            sys.exit(1)

def derive_output_path(input_path: str | None) -> str:
    if input_path is None or not input_path:
        return ""
    else:
        return os.path.splitext(input_path)[0] + ".pdf"

def gui(features, annot_params):
    root = tk.Tk()
    root.title("Datasheet Aggregator")

    input_mode_choice_sv = tk.StringVar(); input_mode_choice_sv.set("file")
    input_path_sv = tk.StringVar()
    output_path_sv = tk.StringVar()
    status_sv = tk.StringVar()
    
    frame = ttk.Frame(root, padding=10)
    frame.grid()

    lbl_input = ttk.Label(frame, text="Input :")
    rb_input_mode_path = ttk.Radiobutton(frame, text="File", variable=input_mode_choice_sv, value="file")
    entry_input_path = ttk.Entry(frame, textvariable=input_path_sv, state=tk.DISABLED)
    btn_choose_input = ttk.Button(frame, text="Browse...")
    rb_input_mode_text = ttk.Radiobutton(frame, text="Text", variable=input_mode_choice_sv, value="text")
    textbox_input_text = ScrolledText(frame, wrap=tk.WORD, state=tk.DISABLED, bg=annot_params["color_bg"])
    lbl_output = ttk.Label(frame, text="Output file (PDF):")
    entry_output_path = ttk.Entry(frame, textvariable=output_path_sv)
    option_frame = ttk.Frame(frame)
    btn_generate = ttk.Button(frame, text="Generate")
    lbl_status = ttk.Label(frame, textvariable=status_sv)

    lbl_input.grid(row=0, column=0, columnspan=4, sticky="nsew")
    rb_input_mode_path.grid(row=1, column=0, sticky="nsew") ; entry_input_path.grid(row=1, column=1, columnspan=2, sticky="nsew") ; btn_choose_input.grid(row=1, column=3, sticky="nsew")
    rb_input_mode_text.grid(row=2, column=0, sticky="nsew") ; textbox_input_text.grid(row=2, column=1, columnspan=3, sticky="nsew")
    lbl_output.grid(row=3, column=0, columnspan=1, sticky="nsew") ; entry_output_path.grid(row=3, column=1, columnspan=3, sticky="nsew")
    option_frame.grid(row=4, column=0, columnspan=4, sticky="nsew")
    btn_generate.grid(row=5, column=1, columnspan=2, sticky="nsew")
    lbl_status.grid(row=6, column=0, columnspan=4, sticky="nsew")

    ###########################################################################
    # @click.option("--with-army-rule/--without-army-rule", default=DEFAULT_FEATURES["with_army_rule"])
    # @click.option("--with-detachment-rule/--without-detachment-rule", default=DEFAULT_FEATURES["with_detachment_rule"])
    # @click.option("--with-detachment-stratagems/--without-detachment-stratagems", default=DEFAULT_FEATURES["with_detachment_stratagems"])
    # @click.option("--with-detachment-enhancements/--without-detachment-enhancements", default=DEFAULT_FEATURES["with_detachment_enhancements"])
    # @click.option("--with-armoury/--without-armoury", default=DEFAULT_FEATURES["with_armoury"])
    # @click.option("--with-armoury-padding/--without-armoury-padding", default=DEFAULT_FEATURES["with_armoury_padding"])
    # @click.option("--with-unit-annot/--without-unit-annot", default=DEFAULT_FEATURES["with_unit_annot"])
    # @click.option("--with-unit-comp/--without-unit-comp", default=DEFAULT_FEATURES["with_unit_comp"])
    # @click.option("--list-mode", "-l", type=click.Choice([LIST_MODE_FULL, LIST_MODE_JUST_HEADER, LIST_MODE_NOTHING]), default=DEFAULT_FEATURES["list_mode"])
    # @click.option("--annot-font-size", type=float, default=DEFAULT_ANNOT_PARAMS["font_size"])
    # @click.option("--annot-line-spacing", type=float, default=DEFAULT_ANNOT_PARAMS["line_spacing"])
    # @click.option("--annot-font-face", type=str, default=DEFAULT_ANNOT_PARAMS["font_face"])
    # @click.option("--annot-color-fg", type=str, default=DEFAULT_ANNOT_PARAMS["color_fg"])
    # @click.option("--annot-color-bg", type=str, default=DEFAULT_ANNOT_PARAMS["color_bg"])
    # @click.option("--annot-color-br", type=str, default=DEFAULT_ANNOT_PARAMS["color_br"])
    to_bool = lambda x: True if x == 1 else False
    from_bool = lambda x: 1 if x else 0

    with_army_rule_iv = tk.IntVar(); with_army_rule_iv.set(from_bool(features["with_army_rule"]))
    with_detachment_rule_iv = tk.IntVar(); with_detachment_rule_iv.set(from_bool(features["with_detachment_rule"]))
    with_detachment_stratagems_iv = tk.IntVar(); with_detachment_stratagems_iv.set(from_bool(features["with_detachment_stratagems"]))
    with_detachment_enhancements_iv = tk.IntVar(); with_detachment_enhancements_iv.set(from_bool(features["with_detachment_enhancements"]))
    with_armoury_iv = tk.IntVar(); with_armoury_iv.set(from_bool(features["with_armoury"]))
    with_armoury_padding_iv = tk.IntVar(); with_armoury_padding_iv.set(from_bool(features["with_armoury_padding"]))
    with_unit_annot_iv = tk.IntVar(); with_unit_annot_iv.set(from_bool(features["with_unit_annot"]))
    with_unit_comp_iv = tk.IntVar(); with_unit_comp_iv.set(from_bool(features["with_unit_comp"]))
    list_mode_sv = tk.StringVar(); list_mode_sv.set(features["list_mode"])
    font_face_sv = tk.StringVar(); font_face_sv.set(str(annot_params["font_face"]))
    font_size_sv = tk.StringVar(); font_size_sv.set(str(annot_params["font_size"]))
    line_spacing_sv = tk.StringVar(); line_spacing_sv.set(str(annot_params["line_spacing"]))
    color_fg_sv = tk.StringVar(); color_fg_sv.set(annot_params["color_fg"])
    color_bg_sv = tk.StringVar(); color_bg_sv.set(annot_params["color_bg"])
    color_br_sv = tk.StringVar(); color_br_sv.set(annot_params["color_br"])

    cb_with_army_rule = ttk.Checkbutton(option_frame, text="Army rule", variable=with_army_rule_iv, onvalue=1, offvalue=0)
    cb_with_detachment_rule = ttk.Checkbutton(option_frame, text="Detachement rule", variable=with_detachment_rule_iv, onvalue=1, offvalue=0)
    cb_with_detachment_stratagems = ttk.Checkbutton(option_frame, text="Detachement stratagems", variable=with_detachment_stratagems_iv, onvalue=1, offvalue=0)
    cb_with_detachment_enhancements = ttk.Checkbutton(option_frame, text="Detachement enhancements", variable=with_detachment_enhancements_iv, onvalue=1, offvalue=0)
    cb_with_armoury = ttk.Checkbutton(option_frame, text="Armoury (if available)", variable=with_armoury_iv, onvalue=1, offvalue=0)
    cb_with_armoury_padding = ttk.Checkbutton(option_frame, text="Half page padding for armoury", variable=with_armoury_padding_iv, onvalue=1, offvalue=0)
    cb_with_unit_annot = ttk.Checkbutton(option_frame, text="Unit comp. & wargear annotations", variable=with_unit_annot_iv, onvalue=1, offvalue=0)
    cb_with_unit_comp = ttk.Checkbutton(option_frame, text="Verso card face with unit comp. and leaders", variable=with_unit_comp_iv, onvalue=1, offvalue=0)
    lbl_list_mode = ttk.Label(option_frame, text="List recap: ")
    rb_list_mode_full = ttk.Radiobutton(option_frame, text="full", variable=list_mode_sv, value=LIST_MODE_FULL)
    rb_list_mode_just_header = ttk.Radiobutton(option_frame, text="header with list spec", variable=list_mode_sv, value=LIST_MODE_JUST_HEADER)
    rb_list_mode_nothing = ttk.Radiobutton(option_frame, text="none", variable=list_mode_sv, value=LIST_MODE_NOTHING)

    lbl_font_face = ttk.Label(option_frame, text="Font face: "); entry_font_face = ttk.Entry(option_frame, textvariable=font_face_sv)
    lbl_font_size = ttk.Label(option_frame, text="Font size: "); entry_font_size = ttk.Entry(option_frame, textvariable=font_size_sv)
    lbl_line_spacing = ttk.Label(option_frame, text="Line spacing: "); entry_line_spacing = ttk.Entry(option_frame, textvariable=line_spacing_sv)
    lbl_color_fg = ttk.Label(option_frame, text="Foreground color: "); entry_color_fg = ttk.Entry(option_frame, textvariable=color_fg_sv)
    lbl_color_bg = ttk.Label(option_frame, text="Background color: "); entry_color_bg = ttk.Entry(option_frame, textvariable=color_bg_sv)
    lbl_color_br = ttk.Label(option_frame, text="Border color: "); entry_color_br = ttk.Entry(option_frame, textvariable=color_br_sv)

    cb_with_army_rule.grid(row=0, column=0, columnspan=2, sticky="nsew")
    cb_with_detachment_rule.grid(row=1, column=0, columnspan=2, sticky="nsew")
    cb_with_detachment_stratagems.grid(row=2, column=0, columnspan=2, sticky="nsew")
    cb_with_detachment_enhancements.grid(row=3, column=0, columnspan=2, sticky="nsew")

    cb_with_armoury.grid(row=0, column=2, columnspan=2, sticky="nsew")
    cb_with_armoury_padding.grid(row=1, column=2, columnspan=2, sticky="nsew")
    cb_with_unit_annot.grid(row=2, column=2, columnspan=2, sticky="nsew")
    cb_with_unit_comp.grid(row=3, column=2, columnspan=2, sticky="nsew")

    lbl_list_mode.grid(row=4, column=0, sticky="nsew")
    rb_list_mode_full.grid(row=4, column=1, sticky="nsew")
    rb_list_mode_just_header.grid(row=4, column=2, sticky="nsew")
    rb_list_mode_nothing.grid(row=4, column=3, sticky="nsew")

    lbl_color_fg.grid(row=5, column=0, columnspan=1, sticky="nsew"); entry_color_fg.grid(row=5, column=1, columnspan=1, sticky="nsew")
    lbl_color_bg.grid(row=6, column=0, columnspan=1, sticky="nsew"); entry_color_bg.grid(row=6, column=1, columnspan=1, sticky="nsew")
    lbl_color_br.grid(row=7, column=0, columnspan=1, sticky="nsew"); entry_color_br.grid(row=7, column=1, columnspan=1, sticky="nsew")

    lbl_font_face.grid(row=5, column=2, columnspan=1, sticky="nsew"); entry_font_face.grid(row=5, column=3, columnspan=1, sticky="nsew")
    lbl_font_size.grid(row=6, column=2, columnspan=1, sticky="nsew"); entry_font_size.grid(row=6, column=3, columnspan=1, sticky="nsew")
    lbl_line_spacing.grid(row=7, column=2, columnspan=1, sticky="nsew"); entry_line_spacing.grid(row=7, column=3, columnspan=1, sticky="nsew")

    active_widgets = [
        rb_input_mode_path, btn_choose_input, rb_input_mode_text, textbox_input_text, entry_output_path, btn_generate,
        cb_with_army_rule, cb_with_detachment_rule, cb_with_detachment_stratagems, cb_with_detachment_enhancements,
        cb_with_armoury, cb_with_armoury_padding, cb_with_unit_annot, cb_with_unit_comp,
        rb_list_mode_full, rb_list_mode_just_header, rb_list_mode_nothing,
        entry_font_face, entry_font_size, entry_line_spacing, entry_color_fg, entry_color_bg, entry_color_br
    ]

    def with_temp_enabled(widget, f):
        widget.configure(state=tk.NORMAL)
        f()
        widget.configure(state=tk.DISABLED)

    def input_choice_changed():
        if input_mode_choice_sv.get() == "file":
            textbox_input_text.configure(state=tk.DISABLED)
            textbox_input_text.configure(bg=annot_params["color_bg"])
            btn_choose_input.configure(state=tk.NORMAL)
            btn_choose_input.focus_set()
        else:
            textbox_input_text.configure(state=tk.NORMAL)
            textbox_input_text.configure(bg="#ffffff")
            textbox_input_text.focus_set()
            btn_choose_input.configure(state=tk.DISABLED)

    def select_input_file():
        filetypes = (
            ('text files', '*.txt'),
            ('All files', '*.*')
        )
        chosen_path = fd.askopenfilename(title="Select a list (plain text)", filetypes=filetypes)
        input_path_sv.set(chosen_path)
        output_path_sv.set(derive_output_path(chosen_path))

    def generate_output():
        status_sv.set("Processing...")
        for w in active_widgets:
            w.configure(state=tk.DISABLED)

        # @click.option("--with-army-rule/--without-army-rule", default=DEFAULT_FEATURES["with_army_rule"])
        # @click.option("--with-detachment-rule/--without-detachment-rule", default=DEFAULT_FEATURES["with_detachment_rule"])
        # @click.option("--with-detachment-stratagems/--without-detachment-stratagems", default=DEFAULT_FEATURES["with_detachment_stratagems"])
        # @click.option("--with-detachment-enhancements/--without-detachment-enhancements", default=DEFAULT_FEATURES["with_detachment_enhancements"])
        # @click.option("--with-armoury/--without-armoury", default=DEFAULT_FEATURES["with_armoury"])
        # @click.option("--with-armoury-padding/--without-armoury-padding", default=DEFAULT_FEATURES["with_armoury_padding"])
        # @click.option("--with-unit-annot/--without-unit-annot", default=DEFAULT_FEATURES["with_unit_annot"])
        # @click.option("--with-unit-comp/--without-unit-comp", default=DEFAULT_FEATURES["with_unit_comp"])
        # @click.option("--list-mode", "-l", type=click.Choice([LIST_MODE_FULL, LIST_MODE_JUST_HEADER, LIST_MODE_NOTHING]), default=DEFAULT_FEATURES["list_mode"])
        # @click.option("--annot-font-size", type=float, default=DEFAULT_ANNOT_PARAMS["font_size"])
        # @click.option("--annot-line-spacing", type=float, default=DEFAULT_ANNOT_PARAMS["line_spacing"])
        # @click.option("--annot-font-face", type=str, default=DEFAULT_ANNOT_PARAMS["font_face"])
        # @click.option("--annot-color-fg", type=str, default=DEFAULT_ANNOT_PARAMS["color_fg"])
        # @click.option("--annot-color-bg", type=str, default=DEFAULT_ANNOT_PARAMS["color_bg"])
        # @click.option("--annot-color-br", type=str, default=DEFAULT_ANNOT_PARAMS["color_br"])

        features["with_army_rule"] = to_bool(with_army_rule_iv.get())
        features["with_detachment_rule"] = to_bool(with_detachment_rule_iv.get())
        features["with_detachment_stratagems"] = to_bool(with_detachment_stratagems_iv.get())
        features["with_detachment_enhancements"] = to_bool(with_detachment_enhancements_iv.get())
        features["with_armoury"] = to_bool(with_armoury_iv.get())
        features["with_armoury_padding"] = to_bool(with_armoury_padding_iv.get())
        features["with_unit_annot"] = to_bool(with_unit_annot_iv.get())
        features["with_unit_comp"] = to_bool(with_unit_comp_iv.get())
        features["list_mode"] = list_mode_sv.get()
        annot_params["font_face"] = font_face_sv.get()
        annot_params["font_size"] = float(font_size_sv.get())
        annot_params["line_spacing"] = float(line_spacing_sv.get())
        annot_params["color_fg"] = color_fg_sv.get()
        annot_params["color_bg"] = color_bg_sv.get()
        annot_params["color_br"] = color_br_sv.get()

        try:
            if input_mode_choice_sv.get() == "file":
                with open(input_path_sv.get(), "r", encoding="utf-8") as input_file:
                    list_content = input_file.read()
                with_temp_enabled(textbox_input_text, lambda: textbox_input_text.delete('1.0', tk.END))
                with_temp_enabled(textbox_input_text, lambda: textbox_input_text.insert(tk.END, list_content))
            else:
                list_content = textbox_input_text.get('1.0', "end-1c")
            convert_list_to_pdf(
                list_content,
                output_path_sv.get(),
                features,
                annot_params,
                status_sv.set
            )
        except Exception as e:
            exception_repr = traceback.format_exc()
            status_sv.set("")
            messagebox.showerror("Error", exception_repr)
        for w in active_widgets:
            w.configure(state=tk.NORMAL)
        input_choice_changed()

    btn_generate.configure(command=generate_output)
    btn_choose_input.configure(command=select_input_file)
    rb_input_mode_path.configure(command=input_choice_changed)
    rb_input_mode_text.configure(command=input_choice_changed)

    root.mainloop()

def convert_list_to_pdf(list_content: str, output_path, features, annot_params, status_function):
    _annot_params = annot_params.copy()
    _annot_params["color_fg"] = convert_color(annot_params["color_fg"])
    _annot_params["color_bg"] = convert_color(annot_params["color_bg"])
    _annot_params["color_br"] = convert_color(annot_params["color_br"])
    annot_params = _annot_params

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
    status_function(f"Parsed army header of '{list_name}' ({try_army_name}) with {total_points}/{max_points} points!")

    final_list_units = parse_and_group_units(rest_of_the_list)
    main_army_index_path = resolve_army_index_path_from_army_name(try_army_name)

    army_rules: list[Rule] = []
    detachments: dict[str, Detachment] = {}
    armoury_full_pages: list[Rule] = []
    armoury_half_pages: list[Datasheet] = []
    datasheet_dict: dict[str, Datasheet] = {}
    load_rec_index(main_army_index_path, army_rules, detachments, armoury_full_pages, armoury_half_pages, datasheet_dict, status_function)

    # check that we only found 1 army rule
    if len(army_rules) > 1:
        raise Exception(f"Several army rules detected: {army_rules}, exiting.")
    army_rule = army_rules[0]
    if detachment_rule_name not in detachments:
        raise Exception(f"Requested detachment rule {detachment_rule_name} not found in {detachments}, exiting.")
    detachment = detachments[detachment_rule_name]
    status_function(f"Playing with army rule '{army_rule.id}' and detachment_rule '{detachment.id}'!")

    output_pdf = PdfWriter()
    current_pages = 0
    ref_box = army_rule.pdf.pages[0].mediabox

    # add first page with list recap if needed
    if features["list_mode"] == LIST_MODE_FULL:
        status_function("Adding a first page with the list recap...")
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

    # add army rule if needed
    if features["with_army_rule"]:
        page_range = army_rule.page_range
        status_function(f"Adding '{army_rule.id}' army rules (pages {page_range} from '{army_rule.origin}')...")
        output_pdf.append(fileobj=army_rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)

    # add detachment rule if needed
    if features["with_detachment_rule"]:
        page_range = detachment.rule.page_range
        status_function(f"Adding '{detachment.rule.id}' detachment rules (pages {page_range} from '{detachment.rule.origin}')...")
        output_pdf.append(fileobj=detachment.rule.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)
    # add detachment stratagems if needed
    if features["with_detachment_stratagems"]:
        page_range = detachment.stratagems.page_range
        status_function(f"Adding '{detachment.stratagems.id}' detachment stratagems (pages {page_range} from '{detachment.stratagems.origin}')...")
        output_pdf.append(fileobj=detachment.stratagems.pdf, pages=(page_range[0]-1, page_range[1]))
        current_pages += page_range[1] - (page_range[0]-1)
    # add detachment enhancements if needed
    if features["with_detachment_enhancements"]:
        page_range = detachment.enhancements.page_range
        if page_range is not None:
            status_function(f"Adding '{detachment.enhancements.id}' detachment enhancements (pages {page_range} from '{detachment.enhancements.origin}')...")
            output_pdf.append(fileobj=detachment.enhancements.pdf, pages=(page_range[0]-1, page_range[1]))
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
        if not features["with_unit_comp"]:
            # remove unit comp if the option hasn't been set
            datasheet.page_range = [datasheet.page_range[0], datasheet.page_range[0]]
        datasheets_to_print.append(datasheet)

    # add extra rule pages if needed
    if features["with_armoury"]:
        # now we add only the needed extra pages, starting with full ones:
        for extra_pages in armoury_full_pages:
            if extra_pages.origin not in used_origins:
                continue
            page_range = extra_pages.page_range
            status_function(f"Adding extra rule (pages {page_range[0]-page_range[1]} from '{extra_pages.origin}')...")
            output_pdf.append(fileobj=extra_pages.pdf, pages=(page_range[0]-1, page_range[1]))
            current_pages += page_range[1] - (page_range[0]-1)

        # now we add the half ones as pseudo-datasheets to be printed before the actual ones
        armoury_half_pages_to_include = [extra_pages for extra_pages in armoury_half_pages if extra_pages.origin in used_origins]
        datasheets_to_print = armoury_half_pages_to_include + datasheets_to_print

    # start bi-modal printing
    next_is_top = True
    prev_is_armoury = True
    for datasheet in datasheets_to_print:
        status_function(f"Adding '{datasheet.id}' ({datasheet})...")
        n = datasheet.page_range[1] - datasheet.page_range[0] + 1
        # force current datasheet to start on a new page if the current datasheet will be split over >=2 pages (and isn't armoury page)
        if n > 1 and not datasheet.is_armoury:
            next_is_top = True
        # force current datasheet to start on a new page if prev datasheet was the last armoury page
        if prev_is_armoury and not datasheet.is_armoury and features["with_armoury_padding"]:
            next_is_top = True

        for page_nb in range(datasheet.page_range[0], datasheet.page_range[1] + 1):
            if next_is_top:
                output_pdf.add_blank_page(ref_box.width, ref_box.height)
                current_pages += 1
                current_page = output_pdf.get_page(current_pages - 1)
                pdf_page = datasheet.pdf.pages[page_nb - 1]
                current_page.merge_transformed_page(pdf_page, Transformation().scale(ref_box.width / pdf_page.mediabox.width).translate(0, ref_box.height // 2), over=True, expand=False)
                if features["with_unit_annot"] and datasheet.extra_text:
                    add_annot(current_page, datasheet.extra_text, get_pos_params(annot_params, "top"), annot_params, "\n", "  • ")
                next_is_top = False
            else:
                pdf_page = datasheet.pdf.pages[page_nb - 1]
                current_page.merge_transformed_page(pdf_page, Transformation().scale(ref_box.width / pdf_page.mediabox.width).translate(0, 0), over=True, expand=False)
                if features["with_unit_annot"] and datasheet.extra_text and not features["with_unit_comp"]:
                    add_annot(current_page, datasheet.extra_text, get_pos_params(annot_params, "bottom"), annot_params, "\n", "  • ")
                next_is_top = True

        # force next datasheet to start on a new page if the current datasheet has been split on >=2 pages (and isn't armoury page)
        if n > 1 and not datasheet.is_armoury:
            next_is_top = True
        prev_is_armoury = datasheet.is_armoury

    if features["list_mode"] == LIST_MODE_JUST_HEADER:
        status_function("Adding a header with list info...")
        add_annot(output_pdf.get_page(0), list_header, get_pos_params(annot_params, "header_army"), annot_params, "\n", "")

    # Write PDF and we are done!
    status_function(f"Writing output PDF to '{output_path}'...")
    with open(output_path, "wb") as output_file:
        output_pdf.write(output_file)
    output_pdf.close()
    status_function("Done!")

if __name__ == "__main__":
    main()
