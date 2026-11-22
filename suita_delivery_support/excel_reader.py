"""Read normal Excel .xlsx workbooks using the Python standard library.

This avoids reliance on an external browser CDN and does not depend on filenames
being valid Japanese text.  Uploaded bytes remain in memory and are not saved.
"""
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PKG = '{http://schemas.openxmlformats.org/package/2006/relationships}'
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
MAX_SHEETS = 20
MAX_ROWS_PER_SHEET = 10000
MAX_COLUMNS = 160


class ExcelReadError(ValueError):
    pass


def _check_zip_members(z):
    members = z.infolist()
    if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
        raise ExcelReadError('Excelファイルの展開後サイズが大きすぎます。')
    # Validate each member before parsing. All target paths are inside the zip.
    return set(z.namelist())


def _shared_strings(z, names):
    if 'xl/sharedStrings.xml' not in names:
        return []
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    return [''.join(node.text or '' for node in si.iter(MAIN+'t'))
            for si in root.findall(MAIN+'si')]


def _column_index(reference):
    match = re.match(r'^([A-Za-z]+)', reference or '')
    if not match:
        return None
    col = 0
    for ch in match.group(1).upper():
        col = col * 26 + ord(ch) - ord('A') + 1
    return col - 1


def _parse_cell(cell, strings):
    kind = cell.attrib.get('t')
    if kind == 'inlineStr':
        return ''.join(x.text or '' for x in cell.iter(MAIN+'t'))
    value = cell.find(MAIN+'v')
    if value is None or value.text is None:
        # Formula-only or blank cells are not numeric values.
        return ''
    txt = value.text
    if kind == 's':
        idx = int(txt)
        return strings[idx] if 0 <= idx < len(strings) else ''
    if kind in ('str', 'e', 'd'):
        return txt
    if kind == 'b':
        return txt == '1'
    try:
        num = float(txt)
        return int(num) if num.is_integer() else num
    except (ValueError, OverflowError):
        return txt


def _sheet_rows(z, target, strings):
    root = ET.fromstring(z.read(target))
    result = []
    for row in root.iter(MAIN + 'row'):
        if len(result) >= MAX_ROWS_PER_SHEET:
            raise ExcelReadError('1シートの行数が上限を超えています。')
        content = {}
        for cell in row.findall(MAIN + 'c'):
            col = _column_index(cell.attrib.get('r'))
            if col is None or col >= MAX_COLUMNS:
                continue
            content[col] = _parse_cell(cell, strings)
        if content:
            line = [''] * (max(content) + 1)
            for col, val in content.items():
                line[col] = val
        else:
            line = []
        result.append(line)
    return result


def read_xlsx_sheets(blob):
    if not blob:
        raise ExcelReadError('Excelファイルを選択してください。')
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ExcelReadError('20MB以内のExcelファイルを選択してください。')
    try:
        with zipfile.ZipFile(io.BytesIO(blob), 'r') as z:
            names = _check_zip_members(z)
            if 'xl/workbook.xml' not in names or 'xl/_rels/workbook.xml.rels' not in names:
                raise ExcelReadError('有効な.xlsx形式ではありません。')
            strings = _shared_strings(z, names)
            wb = ET.fromstring(z.read('xl/workbook.xml'))
            rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            targets = {node.attrib.get('Id'): node.attrib.get('Target', '') for node in rels}
            sheet_list = wb.find(MAIN+'sheets')
            if sheet_list is None:
                raise ExcelReadError('ワークシートが見つかりません。')
            result = []
            for sheet in list(sheet_list)[:MAX_SHEETS]:
                target_name = targets.get(sheet.attrib.get(REL+'id'), '')
                if not target_name:
                    continue
                path = target_name.lstrip('/') if target_name.startswith('/') else posixpath.normpath('xl/'+target_name)
                if not path.startswith('xl/') or path not in names:
                    continue
                try:
                    rows = _sheet_rows(z, path, strings)
                except ET.ParseError as error:
                    raise ExcelReadError('ExcelシートのXMLが破損しています。') from error
                result.append({'name': sheet.attrib.get('name','Sheet'), 'rows':rows})
            if not result:
                raise ExcelReadError('読み込めるシートがありません。')
            return result
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, OSError) as error:
        if isinstance(error, ExcelReadError):
            raise
        raise ExcelReadError('Excelファイルを解析できませんでした。.xlsx形式で保存し直してください。') from error
