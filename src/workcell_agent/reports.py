import json
from pathlib import Path

from jinja2 import Environment, select_autoescape

TEMPLATE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>工站检查报告</title><style>
body{font:16px/1.7 sans-serif;max-width:1100px;margin:40px auto;padding:0 24px}
pre{white-space:pre-wrap;background:#f4f6f8;padding:24px;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #ddd;padding:10px;text-align:left}
td{overflow-wrap:anywhere}.notice{border-left:4px solid #dd8b16;padding:12px;background:#fff7e8}
</style><h1>工站检查报告</h1><p>检查范围、条件和未执行项目以以下记录为准。</p>
{% if report.get('coverage', {}).get('complete') == false or report.get('scene_changed_during_check') %}
<p class="notice">检查覆盖不完整或当前场景已经改变，请核对完整记录。</p>{% endif %}
{% if report.get('run') %}<p>运动状态：{{ report.run.state }}；仿真时间：{{ report.run.time_s }} s</p>{% endif %}
{% if 'findings' in report %}
<h2>检查记录：{{ report.findings|length }} 项</h2>
<table><thead><tr><th>对象 A</th><th>对象 B</th><th>分类</th><th>共同体积 m³ / 接触距离 m</th></tr></thead><tbody>
{% for item in report.findings[:500] %}<tr><td>{{ item.part_a }}</td><td>{{ item.part_b }}</td>
<td>{{ item.classification }}</td><td>{{ item.get('common_volume_m3', item.get('separation_m', '')) }}</td></tr>{% endfor %}
</tbody></table>{% if report.findings|length > 500 %}<p>表格显示前 500 项，完整数据见下方记录及 JSON。</p>{% endif %}
{% endif %}
<details><summary>查看完整检查数据</summary><pre>{{ content }}</pre></details></html>"""


def write_report(report: dict, directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    json_path = directory / "report.json"
    html_path = directory / "report.html"
    json_path.write_text(text, encoding="utf-8")
    environment = Environment(autoescape=select_autoescape(default_for_string=True))
    html_path.write_text(environment.from_string(TEMPLATE).render(content=text, report=report), encoding="utf-8")
    return {"json": json_path, "html": html_path}
