from re import S
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
from fontTools.pens.basePen import BasePen
from xml.etree import ElementTree as ET
from svg.path import parse_path
import os
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen
from calculate_svg_baseline import calculate_baseline


def extract_codepoints(filename):
    tibetan_char = filename.split('_')[0]
    codepoints = [ord(char) for char in tibetan_char]
    return codepoints


class SVGPen(BasePen):
    def __init__(self, glyphSet=None):
        super().__init__(glyphSet)
        self.currentPoint = (0, 0)
        self.path = []

    def _moveTo(self, pt):
        if self.path and self.path[-1][0] != 'closePath':
            self.closePath()
        self.currentPoint = pt
        self.path.append(('moveTo', pt))

    def _lineTo(self, pt):
        self.currentPoint = pt
        self.path.append(('lineTo', pt))

    def _curveToOne(self, pt1, pt2, pt3):
        self.currentPoint = pt3
        self.path.append(('curveTo', (pt1, pt2, pt3)))

    def get_path(self):
        if self.path and self.path[-1][0] != 'closePath':
            self.closePath()
        return self.path

    def reset(self):
        self.currentPoint = (0, 0)
        self.path = []

    def closePath(self):
        self.path.append(('closePath',))

    def pathFromSVGPathData(self, path_data):
        path = parse_path(path_data)
        for segment in path:
            if segment.__class__.__name__ == 'Line':
                self._lineTo((segment.end.real, segment.end.imag))
            elif segment.__class__.__name__ == 'CubicBezier':
                self._curveToOne((segment.control1.real, segment.control1.imag),
                                 (segment.control2.real, segment.control2.imag),
                                 (segment.end.real, segment.end.imag))
            elif segment.__class__.__name__ == 'Move':
                self._moveTo((segment.end.real, segment.end.imag))
        if self.path and self.path[-1][0] != 'closePath':
            self.closePath()    

    def get_bbox(self):
        if not self.path:
            return None
        x_coords = []
        y_coords = []
        for pt in self.path:
            if pt[0] in ['moveTo', 'lineTo']:
                x_coords.append(pt[1][0])
                y_coords.append(pt[1][1])
            elif pt[0] == 'curveTo':
                for point in pt[1]:
                    x_coords.append(point[0])
                    y_coords.append(point[1])
        return min(x_coords), min(y_coords), max(x_coords), max(y_coords)




def parse_svg_to_glyph(svg_file_path,baseline_svg,desired_baseline):
    filename = os.path.splitext(os.path.basename(svg_file_path))[0]
    codepoints = extract_codepoints(filename)

    tree = ET.parse(svg_file_path)
    root = tree.getroot()
    glyph = TTGlyph()
    glyph.unicodes = codepoints or []
    pen = SVGPen(None)
    ttPen = TTGlyphPen()

    min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')

    for element in root.iter('{http://www.w3.org/2000/svg}path'):
        path_data = element.attrib.get('d', '')
        pen.pathFromSVGPathData(path_data)
        bbox = pen.get_bbox()
        pen.reset()

        if bbox:
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])

    vertical_translation = desired_baseline - baseline_svg

    for element in root.iter('{http://www.w3.org/2000/svg}path'):
        path_data = element.attrib.get('d', '')
        pen.pathFromSVGPathData(path_data)

        transform = (3.0, 0, 0, 3.0, 0, vertical_translation)
        transformPen = TransformPen(ttPen, transform)

        for command in pen.get_path():
            if command[0] == 'moveTo':
                transformPen.moveTo(command[1])
            elif command[0] == 'lineTo':
                transformPen.lineTo(command[1])
            elif command[0] == 'curveTo':
                transformPen.curveTo(*command[1])
            elif command[0] == 'closePath':
                transformPen.closePath()

        pen.reset()

    glyph = ttPen.glyph()

    print(f"File Name: {filename}")
    print(f"Unicodes: {codepoints}")

    return glyph, codepoints


def set_font_metadata(font, font_name, family_name):
    name_table = font['name']
    for name_record in name_table.names:
        if name_record.nameID == 1:
            name_record.string = family_name.encode('utf-16-be')
        elif name_record.nameID == 4:
            name_record.string = font_name.encode('utf-16-be')


def replace_glyphs_in_font(font, svg_dir_path, font_name, family_name):
    unicode_to_glyph = {}
    for filename in os.listdir(svg_dir_path):
        if filename.endswith('.svg'):
            svg_file_path = os.path.join(svg_dir_path, filename)
            baseline_svg = calculate_baseline(svg_file_path)
            desired_baseline = -2000
            glyph, unicode_values = parse_svg_to_glyph(svg_file_path,baseline_svg,desired_baseline)
            if len(unicode_values) == 1:
                unicode_to_glyph[unicode_values[0]] = glyph

    cmap = font.getBestCmap()

    glyph_to_unicode = {glyph: code for code, glyph in cmap.items()}

    glyph_count = 0
    for glyph_name in font['glyf'].keys():
        if glyph_name in glyph_to_unicode:
            unicode_value = glyph_to_unicode[glyph_name]
            if unicode_value in unicode_to_glyph:
                print(f"replacing glyph for unicode value: {unicode_value}")
                new_glyph = unicode_to_glyph[unicode_value]
                font['glyf'][glyph_name] = new_glyph
                original_advance_width, original_lsb = font['hmtx'][glyph_name]
                new_advance_width = int(original_advance_width)
                new_lsb = int(original_lsb)
                font['hmtx'][glyph_name] = (new_advance_width, new_lsb)
                glyph_count += 1

    set_font_metadata(font, font_name, family_name)

    return glyph_count


def main():
    svg_dir_path = '../../data/derge_font/svg'
    old_font_path = '../../data/base_font/MonlamTBslim.ttf'
    new_font_path = '../../data/derge_font/ttf/Derge(monlam).ttf'
    font = TTFont(old_font_path)
    font_name = "DergeMonlam"
    family_name = "DergeMonlam-Regular"
    glyph_count = replace_glyphs_in_font(font, svg_dir_path, font_name, family_name)

    font.save(new_font_path)
    print(f"Total glyphs replaced: {glyph_count}")


if __name__ == "__main__":
    main()