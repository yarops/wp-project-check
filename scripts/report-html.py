#!/usr/bin/env python3
"""Преобразует Markdown-отчёт wp-project-review в автономный HTML.

Использование: python3 report-html.py <отчёт.md> [-o <файл.html>]
(в Windows — также `python` или `py -3`).

Требуется Python >= 3.8, только стандартная библиотека. HTML пишется рядом с отчётом (то же имя,
расширение .html) и генерируется из Markdown целиком: правки вносятся в .md,
HTML пересобирается. Разбирается подмножество Markdown, которое задаёт
references/reporting.md: заголовки, списки, таблицы, блоки кода, `код`,
**жирный**, ссылки.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"\b((?:SEC|REL|TOOL|REC|CTX|E)-\d+)\b")
ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
SEVERITIES = ["Critical", "High", "Medium", "Low"]


# --- inline -----------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(text, quote=True)


def safe_url(url: str) -> str | None:
    if re.match(r"^(https?://|#|\.{0,2}/|[\w.-]+(/|$))", url) and not re.match(
        r"^\s*(javascript|data|vbscript):", url, re.I
    ):
        return url
    return None


def link_ids(fragment: str, ids: set[str]) -> str:
    """Связывает ID находок, точек входа и рекомендаций вне тегов и ссылок."""
    out = []
    for part in re.split(r"(<a\b.*?</a>|<[^>]+>)", fragment, flags=re.S):
        if part.startswith("<"):
            out.append(part)
        else:
            out.append(
                ID_RE.sub(
                    lambda m: f'<a class="ref" href="#{m.group(1)}">{m.group(1)}</a>'
                    if m.group(1) in ids
                    else m.group(1),
                    part,
                )
            )
    return "".join(out)


def inline_text(text: str, ids: set[str]) -> str:
    t = esc(text)

    def link(m: re.Match) -> str:
        url = safe_url(html.unescape(m.group(2)))
        if url is None:
            return m.group(0)
        return f'<a href="{esc(url)}">{m.group(1)}</a>'

    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return link_ids(t, ids)


def inline(text: str, ids: set[str]) -> str:
    out, pos = [], 0
    for m in re.finditer(r"(`+)(.+?)(?<!`)\1(?!`)", text):
        out.append(inline_text(text[pos : m.start()], ids))
        out.append(f"<code>{esc(m.group(2).strip())}</code>")
        pos = m.end()
    out.append(inline_text(text[pos:], ids))
    return "".join(out)


def plain(text: str) -> str:
    """Текст заголовка без разметки — для оглавления и атрибутов."""
    return re.sub(r"[`*]", "", text).strip()


# --- blocks -----------------------------------------------------------------

def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, in_code, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


class Block:
    def __init__(self, kind: str, html_: str = "", level: int = 0, text: str = ""):
        self.kind, self.html, self.level, self.text = kind, html_, level, text


def parse_blocks(lines: list[str], ids: set[str]) -> list[Block]:
    blocks: list[Block] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        m = FENCE_RE.match(line)
        if m:
            fence, lang = m.group(2), m.group(3)
            body = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence[:3]):
                body.append(lines[i])
                i += 1
            i += 1
            cls = f' class="lang-{esc(lang)}"' if lang else ""
            blocks.append(Block("code", f"<pre><code{cls}>{esc(chr(10).join(body))}</code></pre>"))
            continue

        m = HEADING_RE.match(line)
        if m and indent_of(line) < 4:
            blocks.append(Block("heading", level=len(m.group(1)), text=m.group(2)))
            i += 1
            continue

        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            blocks.append(Block("html", "<hr>"))
            i += 1
            continue

        if line.lstrip().startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            head = split_row(line)
            rows = []
            i += 2
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            blocks.append(Block("html", render_table(head, rows, ids)))
            continue

        if ITEM_RE.match(line):
            start = i
            base = indent_of(line)
            i += 1
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and (indent_of(lines[j]) > base or (
                        ITEM_RE.match(lines[j]) and indent_of(lines[j]) == base
                    )):
                        i = j
                        continue
                    break
                if indent_of(cur) <= base and not ITEM_RE.match(cur):
                    if HEADING_RE.match(cur) or cur.lstrip().startswith("|") or FENCE_RE.match(cur):
                        break
                    # ленивое продолжение строки пункта
                if indent_of(cur) < base:
                    break
                i += 1
            blocks.append(Block("html", render_list(lines[start:i], ids)))
            continue

        if line.lstrip().startswith(">"):
            body = []
            while i < n and lines[i].lstrip().startswith(">"):
                body.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = "".join(b.html for b in parse_blocks(body, ids) if b.kind != "heading")
            blocks.append(Block("html", f"<blockquote>{inner}</blockquote>"))
            continue

        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not (
            HEADING_RE.match(lines[i]) or FENCE_RE.match(lines[i]) or ITEM_RE.match(lines[i])
            or (lines[i].lstrip().startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]))
        ):
            para.append(lines[i].strip())
            i += 1
        blocks.append(Block("para", f"<p>{inline(' '.join(para), ids)}</p>"))
    return blocks


def render_table(head: list[str], rows: list[list[str]], ids: set[str]) -> str:
    th = "".join(f"<th>{inline(c, ids)}</th>" for c in head)
    body = []
    for r in rows:
        r = (r + [""] * len(head))[: max(len(head), len(r))]
        first = r[0].strip("` ") if r else ""
        rid = f' id="{esc(first)}"' if re.fullmatch(r"E-\d+", first) else ""
        body.append(f"<tr{rid}>" + "".join(f"<td>{inline(c, ids)}</td>" for c in r) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def render_list(lines: list[str], ids: set[str]) -> str:
    base = indent_of(lines[0])
    items: list[tuple[str, list[str]]] = []
    ordered = bool(re.match(r"\d", ITEM_RE.match(lines[0]).group(2)))
    start_num = int(re.match(r"\d+", ITEM_RE.match(lines[0]).group(2)).group()) if ordered else 1
    offset = 2
    for line in lines:
        m = ITEM_RE.match(line)
        if m and indent_of(line) == base:
            offset = len(m.group(1)) + len(m.group(2)) + 1
            items.append((m.group(3), []))
        elif items:
            strip = min(indent_of(line), offset) if line.strip() else 0
            items[-1][1].append(line[strip:])
    out = []
    for first, rest in items:
        body = [first] + rest
        blocks = parse_blocks(body, ids)
        attrs = ""
        mid = re.match(r"^((?:E|REC)-\d+)\s*·", first) or re.match(r"^\*\*((?:REC|E)-\d+)\.?\*\*", first)
        if mid:
            attrs = f' id="{mid.group(1)}"'
        if len(blocks) == 1 and blocks[0].kind == "para":
            content = blocks[0].html[3:-4]
        else:
            parts = []
            for k, b in enumerate(blocks):
                if b.kind == "para" and k == 0:
                    parts.append(b.html[3:-4])
                elif b.kind == "heading":
                    parts.append(f"<p><strong>{inline(b.text, ids)}</strong></p>")
                else:
                    parts.append(b.html)
            content = "".join(parts)
        out.append(f"<li{attrs}>{content}</li>")
    tag = "ol" if ordered else "ul"
    start = f' start="{start_num}"' if ordered and start_num != 1 else ""
    return f"<{tag}{start}>{''.join(out)}</{tag}>"


# --- document structure -----------------------------------------------------

def collect_ids(md: str) -> set[str]:
    ids = set(re.findall(r"^#{3,5}\s+((?:SEC|REL|TOOL|CTX)-\d+)\b", md, re.M))
    ids |= set(re.findall(r"^\s*[-*]\s+((?:E|REC)-\d+)\s*·", md, re.M))
    ids |= set(re.findall(r"^\s*[-*]\s+\*\*((?:REC|E)-\d+)\.?\*\*", md, re.M))
    ids |= set(re.findall(r"^\|\s*`?(E-\d+)`?\s*\|", md, re.M))
    return ids


def finding_meta(blocks: list[Block]) -> tuple[dict, list[Block]]:
    """Достаёт строку «Область / тип / важность» из первого списка карточки."""
    meta = {"area": "", "type": "defect", "sev": "none", "label": ""}
    for b in blocks:
        if b.kind != "html" or not b.html.startswith("<ul>"):
            continue
        m = re.search(r"<li><strong>Область / тип / важность:</strong>\s*(.*?)</li>", b.html, re.S)
        if not m:
            break
        raw = re.sub(r"<[^>]+>", "", m.group(1))
        raw = html.unescape(raw).strip()
        parts = [p.strip() for p in raw.split("·")]
        meta["area"] = parts[0].lower() if parts else ""
        low = raw.lower()
        if "гипотез" in low:
            meta["type"] = "hypothesis"
        elif "недостат" in low or "контекст" in low:
            meta["type"] = "context"
        for s in SEVERITIES:
            if re.search(rf"\b{s}\b", raw):
                meta["sev"] = s.lower()
                break
        meta["label"] = parts[1] if len(parts) > 1 else ""
        meta["prelim"] = "предварительно" in low
        b.html = b.html.replace(m.group(0), "", 1)
        break
    return meta, blocks


TYPE_LABEL = {"defect": "дефект", "hypothesis": "гипотеза", "context": "недостаток контекста"}


def build(md: str) -> str:
    ids = collect_ids(md)
    blocks = parse_blocks(md.splitlines(), ids)

    title = "Отчёт wp-project-review"
    if blocks and blocks[0].kind == "heading" and blocks[0].level == 1:
        title = plain(blocks[0].text)
        blocks = blocks[1:]

    # Разбивка на разделы h2.
    sections: list[tuple[Block | None, list[Block]]] = [(None, [])]
    for b in blocks:
        if b.kind == "heading" and b.level == 2:
            sections.append((b, []))
        else:
            sections[-1][1].append(b)

    toc, body, findings = [], [], []
    for si, (head, content) in enumerate(sections):
        if head is None and not content:
            continue
        sid = f"s{si}"
        htext = plain(head.text) if head else ""
        is_findings = "Находки" in htext
        is_coverage = "Покрытие" in htext
        sub_toc = []
        parts = []
        if is_findings:
            parts.append(FILTER_BAR)
        k = 0
        while k < len(content):
            b = content[k]
            if b.kind == "heading" and b.level == 3:
                sub_id = f"{sid}-{k}"
                group = []
                k += 1
                while k < len(content) and not (content[k].kind == "heading" and content[k].level <= 3):
                    group.append(content[k])
                    k += 1
                sub_toc.append((sub_id, plain(b.text)))
                inner = render_group(group, ids, findings) if is_findings else render_plain(group, ids)
                if is_coverage:
                    parts.append(
                        f'<details class="cov" id="{sub_id}"><summary><h3>{inline(b.text, ids)}</h3></summary>'
                        f'<div class="cov-body">{inner}</div></details>'
                    )
                else:
                    cls = ' class="fgroup"' if is_findings else ""
                    parts.append(f'<div{cls} id="{sub_id}"><h3>{inline(b.text, ids)}</h3>{inner}</div>')
                continue
            if b.kind == "heading" and b.level >= 4 and is_findings:
                group = []
                while k < len(content) and not (content[k].kind == "heading" and content[k].level <= 3):
                    group.append(content[k])
                    k += 1
                parts.append(render_group(group, ids, findings))
                continue
            parts.append(render_plain([b], ids))
            k += 1
        if is_findings:
            parts.append('<p class="empty" hidden>Под выбранные фильтры находок нет.</p>')
        if head:
            toc.append((sid, htext, sub_toc))
            body.append(f'<section id="{sid}"><h2>{inline(head.text, ids)}</h2>{"".join(parts)}</section>')
        else:
            body.append(f'<section>{"".join(parts)}</section>')

    toc_html = "".join(
        f'<li><a href="#{sid}">{esc(t)}</a>'
        + (
            "<ul>" + "".join(f'<li><a href="#{a}">{esc(b)}</a></li>' for a, b in subs) + "</ul>"
            if subs
            else ""
        )
        + "</li>"
        for sid, t, subs in toc
    )
    return PAGE.format(
        title=esc(title),
        summary=render_summary(findings),
        toc=toc_html,
        body="".join(body),
        css=CSS,
        js=JS,
    )


def render_plain(group: list[Block], ids: set[str]) -> str:
    out = []
    for b in group:
        if b.kind == "heading":
            lvl = min(max(b.level, 3), 6)
            out.append(f"<h{lvl}>{inline(b.text, ids)}</h{lvl}>")
        else:
            out.append(b.html)
    return "".join(out)


def render_group(group: list[Block], ids: set[str], findings: list[dict]) -> str:
    """Карточки находок: каждый h4 и всё до следующего h4."""
    out, k = [], 0
    while k < len(group):
        b = group[k]
        if b.kind == "heading" and b.level >= 4:
            body = []
            k += 1
            while k < len(group) and not (group[k].kind == "heading" and group[k].level <= b.level):
                body.append(group[k])
                k += 1
            m = re.match(r"^((?:SEC|REL|TOOL|CTX)-\d+)\.?\s*(.*)$", b.text)
            fid, ftitle = (m.group(1), m.group(2)) if m else ("", b.text)
            meta, body = finding_meta(body)
            meta["id"] = fid
            findings.append(meta)
            sev = meta["sev"]
            badges = []
            if sev != "none":
                badges.append(
                    f'<span class="badge sev-{sev}">{"≈ " if meta.get("prelim") else ""}{sev.capitalize()}</span>'
                )
            badges.append(f'<span class="badge type">{TYPE_LABEL[meta["type"]]}</span>')
            if meta["area"]:
                badges.append(f'<span class="badge area">{esc(meta["area"])}</span>')
            idattr = f' id="{fid}"' if fid else ""
            out.append(
                f'<article class="finding sev-{sev}"{idattr} data-sev="{sev}" data-area="{esc(meta["area"])}" '
                f'data-type="{meta["type"]}"><header><span class="fid">{esc(fid)}</span>'
                f'<h4>{inline(ftitle, ids)}</h4><div class="badges">{"".join(badges)}</div></header>'
                f'<div class="fbody">{render_plain(body, ids)}</div></article>'
            )
            continue
        out.append(render_plain([b], ids))
        k += 1
    return "".join(out)


def render_summary(findings: list[dict]) -> str:
    if not findings:
        return ""
    defects = [f for f in findings if f["type"] == "defect"]
    hyps = [f for f in findings if f["type"] == "hypothesis"]
    ctx = [f for f in findings if f["type"] == "context"]
    tiles = []
    for s in SEVERITIES:
        c = sum(1 for f in defects if f["sev"] == s.lower())
        tiles.append(
            f'<div class="tile sev-{s.lower()}{" zero" if not c else ""}"><b>{c}</b><span>{s}</span></div>'
        )
    tiles.append(f'<div class="tile neutral{" zero" if not hyps else ""}"><b>{len(hyps)}</b><span>гипотезы</span></div>')
    if ctx:
        tiles.append(f'<div class="tile neutral"><b>{len(ctx)}</b><span>контекст</span></div>')
    areas = {}
    for f in findings:
        if f["area"]:
            areas[f["area"]] = areas.get(f["area"], 0) + 1
    area_txt = " · ".join(f"{esc(a)} {c}" for a, c in sorted(areas.items()))
    return (
        f'<div class="summary"><div class="tiles">{"".join(tiles)}</div>'
        f'<p class="areas">Подтверждённые дефекты по важности; всего находок {len(findings)}'
        f'{": " + area_txt if area_txt else ""}</p></div>'
    )


FILTER_BAR = """<div class="filters" role="group" aria-label="Фильтры находок">
<div class="fgroup-btns" data-key="sev"><span>Важность</span>
<button data-v="critical">Critical</button><button data-v="high">High</button><button data-v="medium">Medium</button><button data-v="low">Low</button></div>
<div class="fgroup-btns" data-key="type"><span>Тип</span>
<button data-v="defect">дефект</button><button data-v="hypothesis">гипотеза</button><button data-v="context">контекст</button></div>
<div class="fgroup-btns" data-key="area"><span>Область</span>
<button data-v="security">security</button><button data-v="reliability">reliability</button><button data-v="tooling">tooling</button></div>
<button class="reset" type="button">Сбросить</button>
</div>"""

CSS = r"""
:root{--bg:#f7f7f5;--surface:#fff;--text:#1d1f23;--muted:#5d636d;--border:#e1e2e0;--code-bg:#f0f0ed;
--accent:#2d5bd7;--critical:#8f1d2c;--high:#c2362b;--medium:#b06a00;--low:#3b6fb6;--neutral:#6b7280;
--critical-bg:#f8e6e9;--high-bg:#fbe9e7;--medium-bg:#fbf0de;--low-bg:#e7eef9;--neutral-bg:#eeeff1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171a;--surface:#1d2024;--text:#e6e7e9;
--muted:#a0a6b0;--border:#30343a;--code-bg:#262a30;--accent:#7ea2ff;--critical:#ff8a9a;--high:#ff8f80;
--medium:#f0b45a;--low:#8ab4ff;--neutral:#a0a6b0;--critical-bg:#3a1d23;--high-bg:#3a221f;--medium-bg:#352a17;
--low-bg:#1c2a40;--neutral-bg:#2a2d32}}
:root[data-theme="dark"]{--bg:#15171a;--surface:#1d2024;--text:#e6e7e9;--muted:#a0a6b0;--border:#30343a;
--code-bg:#262a30;--accent:#7ea2ff;--critical:#ff8a9a;--high:#ff8f80;--medium:#f0b45a;--low:#8ab4ff;
--neutral:#a0a6b0;--critical-bg:#3a1d23;--high-bg:#3a221f;--medium-bg:#352a17;--low-bg:#1c2a40;--neutral-bg:#2a2d32}
*{box-sizing:border-box}
html{scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
code{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code-bg);padding:0 3px;border-radius:3px;overflow-wrap:anywhere}
pre{background:var(--code-bg);padding:12px 14px;border-radius:8px;overflow-x:auto;margin:12px 0}
pre code{background:none;padding:0;white-space:pre;overflow-wrap:normal}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 24px;border-bottom:1px solid var(--border);background:var(--surface)}
.top h1{font-size:20px;margin:0;line-height:1.3}
.top .tools{display:flex;gap:8px;flex-shrink:0}
button{font:inherit;font-size:13px;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer}
button:hover{border-color:var(--muted)}
button[aria-pressed="true"]{background:var(--text);color:var(--surface);border-color:var(--text)}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:32px;max-width:1280px;margin:0 auto;padding:24px}
nav.toc{position:sticky;top:16px;align-self:start;max-height:calc(100vh - 32px);overflow:auto;font-size:13px}
nav.toc ul{list-style:none;margin:0;padding:0}nav.toc ul ul{padding-left:12px;margin:2px 0 6px}
nav.toc li{margin:3px 0}nav.toc a{color:var(--muted)}nav.toc a:hover{color:var(--text)}
nav.toc summary{display:none}
main{min-width:0;max-width:980px}
section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px 24px 16px;margin-bottom:20px}
h2{font-size:18px;margin:16px 0 8px}h3{font-size:16px;margin:20px 0 8px}h4{font-size:15px;margin:0}
ul,ol{padding-left:22px;margin:8px 0}li{margin:3px 0}
.table-wrap{overflow-x:auto;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid var(--border);padding:6px 10px;text-align:left;vertical-align:top}
th{background:var(--code-bg);font-weight:600}
tr:target,li:target{background:var(--medium-bg)}
.summary{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin-bottom:20px}
.tiles{display:flex;flex-wrap:wrap;gap:10px}
.tile{min-width:92px;padding:10px 14px;border-radius:8px;background:var(--neutral-bg);display:flex;flex-direction:column}
.tile b{font-size:24px;line-height:1.1}.tile span{font-size:12px;color:var(--muted)}
.tile.zero{opacity:.45}
.areas{margin:10px 0 0;color:var(--muted);font-size:13px}
.sev-critical{--sev:var(--critical);--sev-bg:var(--critical-bg)}.sev-high{--sev:var(--high);--sev-bg:var(--high-bg)}
.sev-medium{--sev:var(--medium);--sev-bg:var(--medium-bg)}.sev-low{--sev:var(--low);--sev-bg:var(--low-bg)}
.sev-none{--sev:var(--neutral);--sev-bg:var(--neutral-bg)}
.tile[class*="sev-"]{background:var(--sev-bg)}.tile[class*="sev-"] b{color:var(--sev)}
.filters{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding:10px 0 4px;position:sticky;top:0;background:var(--surface);z-index:2}
.fgroup-btns{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.fgroup-btns span{font-size:12px;color:var(--muted);margin-right:4px}
.finding{border:1px solid var(--border);border-left:4px solid var(--sev);border-radius:8px;margin:12px 0;background:var(--surface)}
.finding:target{box-shadow:0 0 0 2px var(--accent)}
.finding header{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;padding:12px 16px;cursor:pointer}
.finding .fid{font:600 13px ui-monospace,Menlo,monospace;color:var(--sev)}
.finding h4{flex:1 1 300px}
.badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--neutral-bg);color:var(--muted);white-space:nowrap}
.badge[class*="sev-"]{background:var(--sev-bg);color:var(--sev);font-weight:600}
.fbody{padding:0 16px 10px;border-top:1px solid var(--border)}
.finding.collapsed .fbody{display:none}
.fbody ul{padding-left:18px}
details.cov{border-top:1px solid var(--border)}
details.cov>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px}
details.cov>summary::before{content:"▸";color:var(--muted);transition:transform .15s}
details.cov[open]>summary::before{transform:rotate(90deg)}
details.cov>summary::-webkit-details-marker{display:none}
details.cov>summary h3{margin:12px 0}
.empty{color:var(--muted)}
@media (max-width:860px){
.layout{grid-template-columns:1fr;padding:16px;gap:12px}
nav.toc{position:static;max-height:none;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px 14px}
nav.toc summary{display:block;cursor:pointer;font-weight:600}
section{padding:4px 16px 12px}.top{padding:14px 16px;flex-wrap:wrap}
.filters{position:static}
}
@media print{nav.toc,.top .tools,.filters{display:none}.layout{display:block;padding:0}
section,.summary{border:none;padding:0}.finding{break-inside:avoid}.finding.collapsed .fbody{display:block}}
"""

JS = r"""
(function(){
var root=document.documentElement;
function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
if(matchMedia('(max-width:860px)').matches){var td=document.querySelector('nav.toc details');if(td)td.open=false}
var t=store('wpr-theme');if(t)root.setAttribute('data-theme',t);
document.getElementById('theme').addEventListener('click',function(){
var dark=root.getAttribute('data-theme')?root.getAttribute('data-theme')==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
var n=dark?'light':'dark';root.setAttribute('data-theme',n);store('wpr-theme',n)});
var covs=[].slice.call(document.querySelectorAll('details.cov'));
var cards=[].slice.call(document.querySelectorAll('.finding'));
document.getElementById('toggle').addEventListener('click',function(){
var open=covs.some(function(d){return !d.open})||cards.some(function(c){return c.classList.contains('collapsed')});
covs.forEach(function(d){d.open=open});cards.forEach(function(c){c.classList.toggle('collapsed',!open)});
this.textContent=open?'Свернуть всё':'Развернуть всё'});
cards.forEach(function(c){c.querySelector('header').addEventListener('click',function(e){
if(e.target.closest('a'))return;c.classList.toggle('collapsed')})});
var state={sev:[],type:[],area:[]};
var bar=document.querySelector('.filters');
function apply(){
var any=0;cards.forEach(function(c){var ok=Object.keys(state).every(function(k){
return !state[k].length||state[k].indexOf(c.dataset[k])>=0});c.hidden=!ok;if(ok)any++});
document.querySelectorAll('.fgroup').forEach(function(g){var cs=g.querySelectorAll('.finding');
if(cs.length)g.hidden=![].some.call(cs,function(c){return !c.hidden})});
var e=document.querySelector('.empty');if(e)e.hidden=any>0}
if(bar){
bar.querySelectorAll('.fgroup-btns').forEach(function(g){var key=g.dataset.key;
g.querySelectorAll('button').forEach(function(b){
var has=cards.some(function(c){return c.dataset[key]===b.dataset.v});if(!has){b.hidden=true;return}
b.setAttribute('aria-pressed','false');
b.addEventListener('click',function(){var v=b.dataset.v,i=state[key].indexOf(v);
if(i<0)state[key].push(v);else state[key].splice(i,1);
b.setAttribute('aria-pressed',i<0?'true':'false');apply()})})});
bar.querySelector('.reset').addEventListener('click',reset)}
function reset(){Object.keys(state).forEach(function(k){state[k]=[]});
if(bar)bar.querySelectorAll('[aria-pressed]').forEach(function(b){b.setAttribute('aria-pressed','false')});apply()}
function reveal(){var id=decodeURIComponent(location.hash.slice(1));if(!id)return;
var el=document.getElementById(id);if(!el)return;
var card=el.closest('.finding');if(card){if(card.hidden)reset();card.classList.remove('collapsed')}
var d=el.closest('details');while(d){d.open=true;d=d.parentElement&&d.parentElement.closest('details')}
el.scrollIntoView()}
addEventListener('hashchange',reveal);if(location.hash)setTimeout(reveal,0);
addEventListener('beforeprint',function(){covs.forEach(function(d){d.open=true})});
})();
"""

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="wp-project-review report-html.py">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="top"><h1>{title}</h1><div class="tools">
<button id="toggle" type="button">Развернуть всё</button><button id="theme" type="button" >Тема</button>
</div></div>
<div class="layout">
<nav class="toc" aria-label="Оглавление"><details open><summary>Оглавление</summary><ul>{toc}</ul></details></nav>
<main>{summary}{body}</main>
</div>
<script>{js}</script>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    # Вывод в pipe идёт в кодировке локали (в Windows — ANSI): символ пути вне
    # неё не должен ронять процесс после успешной записи HTML.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Markdown-отчёт wp-project-review → HTML")
    ap.add_argument("report", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    src: Path = args.report
    if not src.is_file():
        print(f"report-html: файл не найден: {src}", file=sys.stderr)
        return 1
    out = args.output or src.with_suffix(".html")
    out.write_text(build(src.read_text(encoding="utf-8-sig")), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
