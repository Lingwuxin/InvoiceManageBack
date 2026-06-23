from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import re
import zipfile
import xml.etree.ElementTree as ET


WORD_NAMESPACE = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': WORD_NAMESPACE}
ET.register_namespace('w', WORD_NAMESPACE)


class LoopRowSpec:
    def __init__(self, list_name: str, variable_name: str, start_marker: str, end_markers: list[str]):
        self.list_name = list_name
        self.variable_name = variable_name
        self.start_marker = start_marker
        self.end_markers = end_markers


LOOP_ROW_SPECS = [
    LoopRowSpec(
        list_name='transport_items',
        variable_name='t',
        start_marker='{% for t in transport_items %}',
        end_markers=['{% endfor %}'],
    ),
    LoopRowSpec(
        list_name='accommodation_items',
        variable_name='a',
        start_marker='{% for a in accommodation_items %}',
        end_markers=['{% endfor %}', '{% end', 'for %}'],
    ),
    LoopRowSpec(
        list_name='expense_items',
        variable_name='e',
        start_marker='{% for e in expense_items %}',
        end_markers=['{% endfor %}'],
    ),
]


def render_reimbursement_docx(template_path: str, context: dict) -> bytes:
    with zipfile.ZipFile(template_path, 'r') as source_zip:
        package_entries = {name: source_zip.read(name) for name in source_zip.namelist()}

    if 'word/document.xml' not in package_entries:
        raise ValueError('word/document.xml not found in template package')

    for part_name, part_bytes in list(package_entries.items()):
        if not _should_process_word_xml_part(part_name, part_bytes):
            continue

        root = ET.fromstring(part_bytes)
        _expand_loop_rows(root, context)
        _replace_scalar_placeholders(root, context)
        _replace_legacy_literal_samples(root, context)
        package_entries[part_name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as target_zip:
        for name, data in package_entries.items():
            target_zip.writestr(name, data)
    return buffer.getvalue()


def _expand_loop_rows(root: ET.Element, context: dict) -> None:
    for spec in LOOP_ROW_SPECS:
        table, row = _find_table_row_with_marker(root, spec.start_marker)
        if table is None or row is None:
            continue

        child_index = list(table).index(row)
        table.remove(row)

        raw_items = context.get(spec.list_name) or []
        items = raw_items if raw_items else [{}]
        for offset, item in enumerate(items):
            cloned_row = deepcopy(row)
            _replace_loop_row_values(cloned_row, spec, item)
            table.insert(child_index + offset, cloned_row)


def _replace_scalar_placeholders(root: ET.Element, context: dict) -> None:
    scalar_replacements = {
        f'{{{{ {key} }}}}': _stringify(value)
        for key, value in context.items()
        if not isinstance(value, list)
    }
    for text_node in root.findall('.//w:t', NS):
        text = text_node.text or ''
        for placeholder, value in scalar_replacements.items():
            text = text.replace(placeholder, value)
        text_node.text = text


def _replace_loop_row_values(row: ET.Element, spec: LoopRowSpec, item: dict) -> None:
    placeholder_replacements = {
        spec.start_marker: '',
        **{marker: '' for marker in spec.end_markers},
    }
    for key, value in item.items():
        placeholder_replacements[f'{{{{ {spec.variable_name}.{key} }}}}'] = _stringify(value)

    unresolved_pattern = re.compile(rf'\{{\{{\s*{re.escape(spec.variable_name)}\.[^}}]+\s*\}}\}}')
    for text_node in row.findall('.//w:t', NS):
        text = text_node.text or ''
        for placeholder, value in placeholder_replacements.items():
            text = text.replace(placeholder, value)
        text = unresolved_pattern.sub('', text)
        text_node.text = text


def _replace_legacy_literal_samples(root: ET.Element, context: dict) -> None:
    traveler = _stringify(context.get('traveler'))
    project_code = _stringify(context.get('project_code'))

    for paragraph in root.findall('.//w:p', NS):
        text_nodes = paragraph.findall('.//w:t', NS)
        if not text_nodes:
            continue

        paragraph_text = ''.join(text_node.text or '' for text_node in text_nodes)
        updated_text = paragraph_text

        if traveler and '出差人：张三' in updated_text:
            updated_text = updated_text.replace('出差人：张三', f'出差人：{traveler}')
        if project_code and '项目编号：***************' in updated_text:
            updated_text = updated_text.replace('项目编号：***************', f'项目编号：{project_code}')

        if updated_text == paragraph_text:
            continue

        text_nodes[0].text = updated_text
        for text_node in text_nodes[1:]:
            text_node.text = ''


def _find_table_row_with_marker(root: ET.Element, marker: str) -> tuple[ET.Element | None, ET.Element | None]:
    for table in root.findall('.//w:tbl', NS):
        for row in table.findall('w:tr', NS):
            row_text = ''.join(text_node.text or '' for text_node in row.findall('.//w:t', NS))
            if marker in row_text:
                return table, row
    return None, None


def _should_process_word_xml_part(part_name: str, part_bytes: bytes) -> bool:
    if not part_name.startswith('word/') or not part_name.endswith('.xml'):
        return False
    if b'{{' in part_bytes or b'{%' in part_bytes:
        return True
    if part_name == 'word/document.xml':
        return True
    return False


def _stringify(value) -> str:
    if value in (None, ''):
        return ''
    return str(value)