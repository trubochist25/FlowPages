import os
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "docx"
ASSET_DIR = ROOT / "output" / "docx_assets"
OUT_PATH = Path(
    os.environ.get(
        "BOOKSTORE_PZ_OUT",
        OUT_DIR / "Пояснительная записка.docx",
    )
)

TITLE = "Разработка поисково-рекомендательной системы для CMS с использованием локальных ML-моделей (на примере интернет магазина книг)"
GOAL = "Разработать и интегрировать в интернет-магазин книг поисково-рекомендательную систему на основе локальной ML-модели, способную интерпретировать запросы на естественном языке, учитывать сочетания характеристик книг и формировать релевантную поисковую выдачу и рекомендации."
HYPOTHESIS = "Применение локальной ML-модели для семантического сопоставления пользовательских запросов с описаниями и характеристиками книг повысит релевантность результатов по неявным и многокритериальным запросам по сравнению со стандартным лексическим поиском CMS."


def font_path(bold=False):
    candidates = [
        Path("C:/Windows/Fonts/timesbd.ttf" if bold else "C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def pil_font(size, bold=False):
    path = font_path(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def rounded_box(draw, xy, text, fill="#EEF3F7", outline="#5B7185", width=3, font=None):
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=width)
    x1, y1, x2, y2 = xy
    lines = []
    for part in text.split("\n"):
        lines.extend(wrap(part, width=27) or [""])
    bbox = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=8, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((x1+x2-tw)/2, (y1+y2-th)/2), "\n".join(lines), fill="#111111", font=font, spacing=8, align="center")


def arrow(draw, start, end, color="#475B6B"):
    draw.line([start, end], fill=color, width=6)
    x, y = end
    draw.polygon([(x, y), (x-17, y-10), (x-17, y+10)], fill=color)


def make_architecture(path):
    im = Image.new("RGB", (1500, 760), "white")
    d = ImageDraw.Draw(im)
    f = pil_font(30, True)
    boxes = [
        (40, 240, 300, 480, "Пользователь\nи форма поиска"),
        (360, 240, 650, 480, "CMS\nконтроллер поиска"),
        (710, 90, 1050, 320, "Локальный ML-сервис\n127.0.0.1:8765"),
        (710, 440, 1050, 670, "База данных CMS\nцены и остатки"),
        (1110, 240, 1460, 480, "Ранжированная выдача\nи рекомендации"),
    ]
    for x1,y1,x2,y2,t in boxes:
        rounded_box(d, (x1,y1,x2,y2), t, font=f)
    arrow(d, (300,360), (360,360)); arrow(d, (650,310), (710,210)); arrow(d, (650,410), (710,550))
    arrow(d, (1050,210), (1110,310)); arrow(d, (1050,550), (1110,410))
    d.text((522, 55), "Локальная архитектура системы", font=pil_font(42, True), fill="#111111")
    im.save(path)


def make_search_pipeline(path):
    im = Image.new("RGB", (1500, 760), "white")
    d = ImageDraw.Draw(im)
    f = pil_font(26, True)
    labels = ["Запрос", "Исправление\nи сущности", "Мягкие\nпредпочтения", "Строгие\nфильтры", "E5-вектор\n384", "Гибридное\nранжирование", "Топ результатов"]
    xs = [25, 230, 445, 660, 875, 1090, 1305]
    for i, (x, label) in enumerate(zip(xs, labels)):
        rounded_box(d, (x, 260, x+170, 480), label, fill="#F4F6F8" if i % 2 == 0 else "#EAF2F8", font=f)
        if i < len(labels)-1:
            arrow(d, (x+170,370), (xs[i+1],370))
    d.text((470, 70), "Последовательность обработки поискового запроса", font=pil_font(40, True), fill="#111111")
    im.save(path)


def make_recommend_pipeline(path):
    im = Image.new("RGB", (1500, 800), "white")
    d = ImageDraw.Draw(im)
    f = pil_font(27, True)
    rounded_box(d, (60, 250, 310, 520), "Просмотры\nИзбранное\nКорзина\nПокупки", fill="#F4F6F8", font=f)
    rounded_box(d, (410, 250, 720, 520), "Обезличенные сигналы\nproduct_id, тип, давность", fill="#EAF2F8", font=f)
    rounded_box(d, (820, 250, 1120, 520), "Профиль интересов\nиз векторов книг", fill="#F4F6F8", font=f)
    rounded_box(d, (1220, 120, 1450, 340), "Рекомендуем вам", fill="#EAF2F8", font=f)
    rounded_box(d, (1220, 460, 1450, 680), "Попробуйте другое", fill="#EAF2F8", font=f)
    arrow(d, (310,385), (410,385)); arrow(d, (720,385), (820,385)); arrow(d, (1120,340), (1220,230)); arrow(d, (1120,430), (1220,570))
    d.text((520, 55), "Формирование персональных рекомендаций", font=pil_font(40, True), fill="#111111")
    im.save(path)


def make_experiment_chart(path):
    im = Image.new("RGB", (1400, 820), "white")
    d = ImageDraw.Draw(im)
    title_f, label_f, value_f = pil_font(40, True), pil_font(30), pil_font(34, True)
    d.text((325, 45), "Доля запросов с подходящей книгой в топ-5", font=title_f, fill="#111111")
    left, top, bottom, maxw = 260, 190, 670, 980
    for pct in range(0, 101, 20):
        x = left + int(maxw * pct / 100)
        d.line((x, top, x, bottom), fill="#D7DDE2", width=2)
        d.text((x-18, bottom+18), str(pct), font=pil_font(24), fill="#333333")
    rows = [("CMS", 10.0, "#9AA6B2"), ("ML-система", 92.5, "#2F6F9F")]
    for i,(name,val,color) in enumerate(rows):
        y = 270 + i*210
        d.text((20,y+25), name, font=label_f, fill="#111111")
        d.rounded_rectangle((left,y,left+int(maxw*val/100),y+90), radius=12, fill=color)
        d.text((left+int(maxw*val/100)+18,y+25), f"{val:.1f}%".replace('.',','), font=value_f, fill="#111111")
    d.text((left+maxw-250, 725), "40 запросов средней сложности", font=pil_font(25), fill="#444444")
    im.save(path)


def make_rank_chart(path):
    im = Image.new("RGB", (1400, 820), "white")
    d = ImageDraw.Draw(im)
    d.text((305, 45), "Позиция первого подходящего результата", font=pil_font(40, True), fill="#111111")
    vals = [24,5,3,3,2,3]
    labels = ["1", "2", "3", "4", "5", "нет в топ-5"]
    x0, y0, h = 150, 675, 440
    d.line((x0,y0,1280,y0),fill="#333333",width=3)
    for i,(label,val) in enumerate(zip(labels,vals)):
        x=220+i*175; barh=int(h*val/24)
        d.rounded_rectangle((x,y0-barh,x+95,y0),radius=10,fill="#2F6F9F" if i<5 else "#9AA6B2")
        d.text((x+31,y0-barh-45),str(val),font=pil_font(30,True),fill="#111111")
        tw=d.textbbox((0,0),label,font=pil_font(25))[2]
        d.text((x+(95-tw)/2,y0+18),label,font=pil_font(25),fill="#111111")
    d.text((840, 745), "Локальная ML-система, 40 запросов", font=pil_font(25), fill="#444444")
    im.save(path)


def set_run_font(run, size=14, bold=None, italic=None):
    run.font.name = "Times New Roman"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Times New Roman")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Times New Roman")
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Times New Roman")
    run.font.size = Pt(size)
    if bold is not None: run.bold = bold
    if italic is not None: run.italic = italic
    run.font.color.rgb = RGBColor(0,0,0)


def set_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=90, bottom=90, end=90):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = tcPr.first_child_found_in("w:tcMar")
    if tcMar is None:
        tcMar = OxmlElement("w:tcMar")
        tcPr.append(tcMar)
    for m, v in (("top",top),("start",start),("bottom",bottom),("end",end)):
        node = tcMar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}"); tcMar.append(node)
        node.set(qn("w:w"), str(v)); node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="B7B7B7", size="6"):
    tblPr = table._tbl.tblPr
    borders = tblPr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders"); tblPr.append(borders)
    for edge in ("top","left","bottom","right","insideH","insideV"):
        el = OxmlElement(f"w:{edge}"); el.set(qn("w:val"),"single"); el.set(qn("w:sz"),size); el.set(qn("w:color"),color); borders.append(el)


def page_field(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = " PAGE "
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t"); text.text = "2"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin,instr,separate,text,end]); set_run_font(run, 12)


def add_body(doc, text, bold_lead=None):
    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    if bold_lead and text.startswith(bold_lead):
        r = p.add_run(bold_lead); set_run_font(r,14,True)
        r = p.add_run(text[len(bold_lead):]); set_run_font(r,14)
    else:
        r = p.add_run(text); set_run_font(r,14)
    return p


def add_list(doc, items, numbered=False):
    for i,item in enumerate(items,1):
        p=doc.add_paragraph()
        p.paragraph_format.left_indent=Cm(1.25); p.paragraph_format.first_line_indent=Cm(-0.63)
        p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing_rule=WD_LINE_SPACING.SINGLE
        prefix=f"{i}. " if numbered else "– "
        r=p.add_run(prefix+item); set_run_font(r,14)


def add_main_heading(doc, text):
    p=doc.add_paragraph(style="Heading 1"); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run(text); set_run_font(r,16,True)
    return p


def add_subheading(doc, text):
    p=doc.add_paragraph(style="Heading 2"); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run(text); set_run_font(r,14,True)
    return p


def add_caption(doc, text):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(6)
    r=p.add_run(text); set_run_font(r,14)


def add_table_title(doc, text):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.first_line_indent=Cm(0); p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(0)
    r=p.add_run(text); set_run_font(r,14)


def add_figure(doc, path, caption, width=15.6):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(0)
    p.add_run().add_picture(str(path), width=Cm(width))
    add_caption(doc, caption)


def add_table(doc, headers, rows, widths=None, font_size=11):
    table=doc.add_table(rows=1, cols=len(headers)); table.alignment=WD_TABLE_ALIGNMENT.CENTER; table.autofit=False
    set_table_borders(table)
    if widths:
        for j, width in enumerate(widths):
            table.columns[j].width = Cm(width)
    for j,h in enumerate(headers):
        cell=table.rows[0].cells[j]; set_cell_shading(cell,"D9EAF7"); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER; set_cell_margins(cell)
        p=cell.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing_rule=WD_LINE_SPACING.SINGLE
        r=p.add_run(h); set_run_font(r,font_size,True)
        if widths: cell.width=Cm(widths[j])
    for i,row in enumerate(rows):
        cells=table.add_row().cells
        for j,val in enumerate(row):
            if i%2: set_cell_shading(cells[j],"F5F8FA")
            cells[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER; set_cell_margins(cells[j])
            p=cells[j].paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.LEFT if j==0 else WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing_rule=WD_LINE_SPACING.SINGLE
            r=p.add_run(str(val)); set_run_font(r,font_size)
            if widths: cells[j].width=Cm(widths[j])
    return table


def page_break(doc):
    doc.add_page_break()


def setup_styles(doc):
    sec=doc.sections[0]
    sec.page_width=Cm(21); sec.page_height=Cm(29.7); sec.top_margin=Cm(2); sec.bottom_margin=Cm(2); sec.left_margin=Cm(3); sec.right_margin=Cm(1)
    sec.header_distance=Cm(1); sec.footer_distance=Cm(1)
    sec.different_first_page_header_footer=True
    normal=doc.styles["Normal"]
    normal.font.name="Times New Roman"; normal.font.size=Pt(14); normal.font.color.rgb=RGBColor(0,0,0)
    normal._element.rPr.rFonts.set(qn("w:ascii"),"Times New Roman"); normal._element.rPr.rFonts.set(qn("w:hAnsi"),"Times New Roman"); normal._element.rPr.rFonts.set(qn("w:eastAsia"),"Times New Roman")
    normal.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY; normal.paragraph_format.first_line_indent=Cm(1.25); normal.paragraph_format.space_before=Pt(0); normal.paragraph_format.space_after=Pt(0); normal.paragraph_format.line_spacing_rule=WD_LINE_SPACING.SINGLE
    for name,size,after in (("Heading 1",16,18),("Heading 2",14,12)):
        st=doc.styles[name]; st.font.name="Times New Roman"; st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor(0,0,0)
        st._element.rPr.rFonts.set(qn("w:ascii"),"Times New Roman"); st._element.rPr.rFonts.set(qn("w:hAnsi"),"Times New Roman"); st._element.rPr.rFonts.set(qn("w:eastAsia"),"Times New Roman")
        st.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.CENTER; st.paragraph_format.first_line_indent=Cm(0); st.paragraph_format.space_before=Pt(0); st.paragraph_format.space_after=Pt(after); st.paragraph_format.keep_with_next=True
    page_field(sec.footer.paragraphs[0])
    first_footer=sec.first_page_footer
    first_footer.is_linked_to_previous=False
    first_p=first_footer.paragraphs[0]
    first_p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    first_p.paragraph_format.first_line_indent=Cm(0)
    first_p.paragraph_format.space_before=Pt(0)
    first_p.paragraph_format.space_after=Pt(0)
    first_run=first_p.add_run("Минск 2026")
    set_run_font(first_run,14)
    settings=doc.settings._element
    hyphenation=OxmlElement("w:autoHyphenation"); hyphenation.set(qn("w:val"),"false"); settings.append(hyphenation)
    update=OxmlElement("w:updateFields"); update.set(qn("w:val"),"true"); settings.append(update)


def title_page(doc):
    def centered(text, size=14, bold=False, before=0, after=0):
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent=Cm(0); p.paragraph_format.space_before=Pt(before); p.paragraph_format.space_after=Pt(after)
        r=p.add_run(text); set_run_font(r,size,bold); return p
    centered("МИНИСТЕРСТВО ОБРАЗОВАНИЯ РЕСПУБЛИКИ\nБЕЛАРУСЬ",14,True)
    centered("Учреждение образования\n«Национальный детский технопарк»",14,True,before=38)
    centered("Образовательное направление «Информационные и компьютерные\nтехнологии»\n«Цифровой ритейл»",14,True,before=45)
    centered("Исследовательский проект",14,True,before=45)
    centered(TITLE.upper(),16,True,before=26)
    table=doc.add_table(rows=1,cols=2); table.alignment=WD_TABLE_ALIGNMENT.CENTER; table.autofit=False
    table.columns[0].width=Cm(8.7); table.columns[1].width=Cm(8.3)
    c=table.cell(0,1); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.TOP
    p=c.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.LEFT; p.paragraph_format.first_line_indent=Cm(0); p.paragraph_format.space_before=Pt(52)
    for text,bold in [("Выполнил:\n",False),("ФИО учащегося,\nучащийся образовательного учреждения\n\n",False),("Руководители проекта:\n",False),("ФИО руководителя проекта, должность",False)]:
        r=p.add_run(text); set_run_font(r,14,bold)


def toc_page(doc):
    add_main_heading(doc,"СОДЕРЖАНИЕ")
    p=doc.add_paragraph(); p.paragraph_format.first_line_indent=Cm(0); p.paragraph_format.tab_stops.add_tab_stop(Cm(16.2), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    begin=OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"),"begin")
    instr=OxmlElement("w:instrText"); instr.set(qn("xml:space"),"preserve"); instr.text=' TOC \\o "1-2" \\h \\z \\u '
    sep=OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"),"separate")
    r=p.add_run(); r._r.extend([begin,instr,sep]); set_run_font(r,14)
    entries=[
        ("ВВЕДЕНИЕ",3),("1 ТЕОРЕТИЧЕСКИЕ ОСНОВЫ ПОИСКА И РЕКОМЕНДАЦИЙ",5),("1.1 Поиск товаров в цифровом ритейле",5),("1.2 Лексический и семантический поиск",6),("1.3 Локальные модели текстовых представлений",7),("1.4 Рекомендательные системы и выбор CMS",8),
        ("2 ПРОГРАММНАЯ РЕАЛИЗАЦИЯ",9),("2.1 Архитектура разработанной системы",9),("2.2 Подготовка каталога и поисковых профилей",10),("2.3 Локальная модель и векторный индекс",11),("2.4 Анализ запроса и гибридное ранжирование",12),("2.5 Персональные рекомендации",13),("2.6 Интеграция с CMS и интерфейс",14),("2.7 Надёжность, приватность и сопровождение",15),
        ("3 ЭКСПЕРИМЕНТАЛЬНАЯ ПРОВЕРКА",16),("3.1 Методика эксперимента",16),("3.2 Результаты основного эксперимента",17),("3.3 Анализ ошибок и ограничения",18),("ЗАКЛЮЧЕНИЕ",19),("СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ",20)]
    for idx,(name,page) in enumerate(entries):
        if idx: r.add_break()
        text=("    " if name[0].isdigit() and "." in name[:4] else "")+name+"\t"+str(page)
        r.add_text(text)
    end=OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"),"end"); r._r.append(end)


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True); ASSET_DIR.mkdir(parents=True, exist_ok=True)
    figures={
        "arch":ASSET_DIR/"architecture.png", "search":ASSET_DIR/"search_pipeline.png", "rec":ASSET_DIR/"recommend_pipeline.png", "exp":ASSET_DIR/"experiment.png", "rank":ASSET_DIR/"rank.png"
    }
    make_architecture(figures["arch"]); make_search_pipeline(figures["search"]); make_recommend_pipeline(figures["rec"]); make_experiment_chart(figures["exp"]); make_rank_chart(figures["rank"])
    doc=Document(); setup_styles(doc); title_page(doc)
    page_break(doc); toc_page(doc)

    # Page 3
    page_break(doc); add_main_heading(doc,"ВВЕДЕНИЕ")
    add_body(doc,"Поиск в интернет-магазине обычно строится на совпадении слов запроса с названием, описанием или тегами товара. Такой механизм подходит, когда покупатель знает точное название книги или автора. При запросах вида «уютная история о семье», «быстрый детектив до 350 страниц» или «мрачная фантастика о власти» отдельные слова могут отсутствовать в видимом описании, хотя книга соответствует смыслу запроса. В результате формально исправный поиск возвращает пустую или малополезную выдачу.")
    add_body(doc,"Актуальность проекта связана с необходимостью понимать короткие естественно-языковые запросы и сочетать смысловой поиск с точными ограничениями каталога. Для небольшого интернет-магазина важно, чтобы обработка выполнялась без передачи каталога и поведения покупателей внешним сервисам. Поэтому в проекте применяется локальная модель текстовых представлений, а интеграция выполнена на уровне системы управления содержимым интернет-магазина.")
    add_body(doc,"Новизна работы состоит в совместном применении локального семантического сопоставления, лексических сигналов, структурированных характеристик книг и персонального профиля интересов в действующей CMS. Свободный текст трактуется как мягкое предпочтение, а явно выбранные фильтры — как строгие условия. Такой подход сохраняет управляемость обычного каталога и расширяет его возможностями машинного обучения.")
    add_body(doc,"Практическая значимость заключается в создании работающего прототипа, который принимает запрос на русском языке, возвращает товары из реального каталога, формирует персональные и похожие рекомендации, а при недоступности ML-сервиса автоматически переключается на стандартный поиск CMS.")

    # Page 4
    page_break(doc); add_subheading(doc,"Основные характеристики исследования")
    add_body(doc,"Название проекта: "+TITLE)
    add_body(doc,"Цель: "+GOAL)
    add_body(doc,"Объект: процесс поиска и подбора книг в интернет-магазине.")
    add_body(doc,"Предмет: методы семантического поиска и формирования рекомендаций с использованием локальных ML-моделей.")
    add_body(doc,"Гипотеза: "+HYPOTHESIS)
    add_body(doc,"Для достижения цели были поставлены следующие задачи:")
    add_list(doc,[
        "изучить ограничения стандартного лексического поиска CMS и способы семантического сопоставления текстов;",
        "спроектировать локальную архитектуру обмена данными между CMS и ML-сервисом;",
        "подготовить каталог и поисковые профили книг с проверяемыми характеристиками;",
        "реализовать анализ запросов, строгие фильтры и гибридное ранжирование;",
        "реализовать персональные рекомендации и подбор похожих книг;",
        "интегрировать разработанные функции в интерфейс интернет-магазина и предусмотреть аварийный режим;",
        "провести сравнительный эксперимент со стандартным поиском CMS и проверить программные компоненты автоматическими тестами."
    ])
    add_body(doc,"Личный вклад автора включает проектирование архитектуры, подготовку данных каталога, интеграцию локальной модели, разработку поискового и рекомендательного модулей, изменение интерфейса CMS, создание сценариев проверки и анализ результатов эксперимента.")

    # Page 5
    page_break(doc); add_main_heading(doc,"1 ТЕОРЕТИЧЕСКИЕ ОСНОВЫ ПОИСКА И РЕКОМЕНДАЦИЙ")
    add_subheading(doc,"1.1 Поиск товаров в цифровом ритейле")
    add_body(doc,"Система управления содержимым интернет-магазина хранит карточки товаров, категории, цены, остатки, заказы и данные покупателей. OpenCart является открытой платформой электронной коммерции и предоставляет средства управления каталогом, расширениями, продажами и отчётами [1]. Это позволяет использовать готовый торговый контур и сосредоточить разработку на поиске и рекомендациях.")
    add_body(doc,"Поисковый сценарий начинается с потребности пользователя. Навигационный запрос содержит название, автора или серию. Категорийный запрос описывает жанр. Описательный запрос выражает настроение, тему, темп чтения, допустимый объём или сочетание нескольких признаков. Чем меньше запрос похож на текст карточки товара, тем ниже вероятность точного лексического совпадения.")
    add_body(doc,"Для книжного каталога существенны две группы условий. Первая группа задаёт обязательные ограничения: цена, автор, жанр, число страниц, год, возрастная категория, настроение и темп. Вторая группа описывает желательную смысловую близость. Если пользователь выбирает возраст 12+ в интерфейсе, книги другой категории не должны попадать в результат. Если слово «короткий» встречается только в строке запроса, разумно понизить позиции длинных книг, но не всегда полностью исключать их.")
    add_body(doc,"Поэтому поисковая система должна одновременно обеспечивать полноту, точность и предсказуемость. В данном проекте стандартные функции CMS сохранены, а интеллектуальная обработка вынесена в отдельный локальный сервис. CMS остаётся источником актуальных цен и остатков, а ML-компонент определяет порядок идентификаторов товаров.")

    # Page 6
    page_break(doc); add_subheading(doc,"1.2 Лексический и семантический поиск")
    add_body(doc,"Лексический поиск сопоставляет символы и слова. Его преимущества — простота, скорость и понятное поведение при точном названии. В резервном алгоритме данного проекта слова запроса проверяются по названию или тегам, дополнительно поддерживаются точные поля модели, артикула и ISBN. Недостаток проявляется при синонимах, изменённых формулировках и описании потребности вместо названия товара.")
    add_body(doc,"Семантический поиск сравнивает смысл запроса и документа по их векторным представлениям. Документация Sentence Transformers отмечает, что такой поиск способен учитывать синонимы, сокращения и некоторые опечатки, а для небольших корпусов может выполняться прямым сравнением векторов [2]. Для интернет-магазина запрос обычно короче поискового профиля книги, поэтому задача относится к асимметричному информационному поиску.")
    add_body(doc,"Вектор, или embedding, представляет текст набором чисел фиксированной размерности. Близость двух векторов оценивается косинусной мерой: чем меньше угол между ними, тем ближе тексты по смыслу. Однако одна семантическая оценка недостаточна. Точное совпадение названия должно иметь больший приоритет, редкая сюжетная деталь не должна теряться внутри общего смысла, а коммерческая сортировка не должна смешиваться с релевантностью.")
    add_body(doc,"В проекте применено гибридное ранжирование. Оно объединяет семантическую близость, совпадения названия и автора, редкие слова поискового профиля, структурированные характеристики, популярность и рейтинг. Строгие фильтры применяются до ранжирования. Таким образом, смысловая модель расширяет стандартный поиск, но не заменяет проверяемые условия каталога.")
    add_table_title(doc,"Таблица 1.1 — Сравнение подходов к поиску")
    add_table(doc,["Подход","Сильная сторона","Ограничение"],[
        ["Лекс.","Точные названия и авторы","Зависимость от совпадения слов"],
        ["Семант.","Неявные формулировки","Возможны близкие, но неверные ответы"],
        ["Гибрид","Сочетание точности и смысла","Требуется настройка весов"]
    ],[3.0,6.3,6.3],10.5)

    # Page 7
    page_break(doc); add_subheading(doc,"1.3 Локальные модели текстовых представлений")
    add_body(doc,"Семейство E5 предназначено для построения универсальных текстовых векторов и обучается контрастивным способом на парах текстов [3]. Многоязычная версия поддерживает запросы и документы на разных языках; её технический отчёт описывает модели размеров small, base и large и компромисс между качеством и вычислительными затратами [4]. Для проекта выбрана компактная версия multilingual-e5-small, дообученная на целевых примерах книжного поиска.")
    add_body(doc,"Локальный запуск даёт три практических преимущества. Во-первых, каталог не передаётся внешнему API во время поиска. Во-вторых, система продолжает работать в изолированной сети. В-третьих, стоимость отдельного запроса не зависит от тарифа облачного поставщика. Цена этих преимуществ — необходимость хранить модель и индекс, контролировать их версии и обеспечивать достаточную производительность компьютера.")
    add_body(doc,"Размерность вектора выбранной модели равна 384. Каталог содержит 1000 книг, поэтому поиск выполняется полным матричным сравнением 1000 × 384. Для такого объёма отдельная векторная база данных не требуется: все векторы загружаются из локального индексного файла и сравниваются в памяти.")
    add_body(doc,"Поисковый профиль книги ограничен 512 токенами. В него включаются название, автор, жанры, темы, настроение, темп, возраст, объём, год, целевая аудитория и подтверждённые детали. Профиль не заменяет пользовательскую аннотацию. Он служит техническим представлением товара и строится только из сведений каталога, что уменьшает риск появления неподтверждённых сюжетных утверждений.")
    add_body(doc,"Индекс снабжён manifest-файлом. При запуске сервис проверяет имя модели, размерность, контрольную сумму каталога и порядок идентификаторов. Изменение каталога требует явного перестроения индекса; устаревшая комбинация модели и данных не принимается.")

    # Page 8
    page_break(doc); add_subheading(doc,"1.4 Рекомендательные системы и выбор CMS")
    add_body(doc,"Рекомендательная система решает другую задачу, чем поиск. Поиск начинается с явного запроса, а рекомендации формируются по доступным сигналам поведения: просмотрам, избранному, корзине и покупкам. В content-based подходе профиль интересов строится из признаков уже выбранных товаров, после чего система ищет похожие позиции.")
    add_body(doc,"Преимущество такого подхода для учебного проекта состоит в том, что ему не требуется большая матрица взаимодействий множества покупателей. Рекомендации появляются даже при небольшом числе пользователей. Ограничение — риск однообразной выдачи. Если профиль сформирован по одному автору или жанру, ближайшие векторы могут повторять один и тот же тип книг. Для снижения повторов применяется MMR-подобный отбор, который учитывает релевантность кандидата и его отличие от уже выбранных результатов.")
    add_body(doc,"OpenCart выбран как основа, поскольку платформа уже реализует каталог, карточку товара, корзину, оформление заказа, учёт пользователей и расширение контроллеров [1]. ML-сервис построен на FastAPI — Python-фреймворке для API с типизированными схемами и автоматически формируемой документацией [5]. Между компонентами передаются только необходимые поля.")
    add_body(doc,"Итоговая система разделяет обязанности: CMS отвечает за торговые данные и интерфейс, Python-сервис — за анализ текста, векторы и ранжирование. Это уменьшает связность компонентов. При остановке ML-сервиса магазин сохраняет базовую возможность поиска, а карточки товаров продолжают загружаться из основной базы данных.")
    add_body(doc,"Теоретический анализ показал, что для поставленной цели нужен не отдельный чат-бот и не полная замена поиска CMS, а локальный гибридный слой. Он должен понимать короткие описательные запросы, уважать строгие фильтры и возвращать только существующие товары.")

    # Page 9
    page_break(doc); add_main_heading(doc,"2 ПРОГРАММНАЯ РЕАЛИЗАЦИЯ")
    add_subheading(doc,"2.1 Архитектура разработанной системы")
    add_body(doc,"Разработанная система состоит из интерфейса интернет-магазина, контроллеров CMS, локального Python-сервиса, каталога поисковых профилей, векторного индекса и базы данных магазина. Браузер не обращается к Python-порту напрямую. Запрос принимает CMS, проверяет параметры и отправляет JSON на адрес 127.0.0.1:8765.")
    add_figure(doc,figures["arch"],"Рисунок 2.1 — Архитектура поисково-рекомендательной системы",15.8)
    add_body(doc,"ML-сервис возвращает упорядоченные идентификаторы товаров и технические объяснения. Затем CMS загружает актуальные названия, изображения, цены, остатки и ссылки из MySQL. Благодаря этому индекс не становится вторым источником коммерческих данных. Изменение цены не требует перестроения векторов.")
    add_body(doc,"API включает маршруты поиска, рекомендаций, подсказок, анализа запроса, списка фильтров и проверки состояния. Такая граница позволяет тестировать ML-ядро отдельно от шаблонов CMS и сохраняет возможность заменить модель без переработки торговой части.")

    # Page 10
    page_break(doc); add_subheading(doc,"2.2 Подготовка каталога и поисковых профилей")
    add_body(doc,"Исходный каталог содержит 1000 книг. Для каждой записи подготовлены название, автор, жанры, темы, настроение, темп, возрастная категория, число страниц, год, цена, рейтинг, аннотация, теги и служебный текст для поиска. Товарные записи связаны с CMS по product_id.")
    add_body(doc,"Подготовка данных разделена на сбор, нормализацию, классификацию характеристик, проверку и импорт. Текст приводится к единому регистру, очищается от технических символов, а списочные значения сохраняются в согласованном формате. Отдельный поисковый профиль объединяет поля, которые должны влиять на смысловую близость.")
    add_body(doc,"Сюжетные детали включаются только при наличии подтверждения в исходных метаданных. Ранее использовавшийся шаблонный генератор поискового текста исключён из рабочего процесса, поскольку он не проверял содержательные утверждения. Текущий конвейер формирует параллельный черновик, проверяет каждую запись и только после приёмки обновляет основной каталог.")
    add_table_title(doc,"Таблица 2.1 — Состав данных каталога")
    add_table(doc,["Данные","Примеры","Использование"],[
        ["ID","название, автор, серия","точное и нечёткое сопоставление"],
        ["Смысл","жанр, тема, настроение","семантика и мягкие признаки"],
        ["Фильтры","страницы, год, возраст","строгие фильтры"],
        ["Продажи","цена, остаток, рейтинг","фильтрация и сортировка"],
        ["Связь","product_id, searchText","связь CMS и индекса"]
    ],[3.5,5.4,6.7],10.5)
    add_body(doc,"После изменения поисковых профилей индекс перестраивается отдельной командой. Контрольная сумма каталога защищает сервис от запуска с несовместимой версией данных.")

    # Page 11
    page_break(doc); add_subheading(doc,"2.3 Локальная модель и векторный индекс")
    add_body(doc,"В рабочей конфигурации используется модель multilingual-e5-small-finetuned-lr1e-5-epoch3. Она хранится локально и запускается в офлайн-режиме. Сервис не обращается к внешним API при поиске и рекомендациях. Для разработки предусмотрен только один рабочий ключ модели — small; неподдерживаемое значение вызывает ошибку конфигурации.")
    add_body(doc,"При построении индекса каждый поисковый профиль преобразуется в вектор размерности 384. Дополнительно подготовлены представления отдельных полей для многовекторного переранжирования. Это помогает различать общий смысл аннотации и более конкретные сигналы названия, автора или характеристик.")
    add_body(doc,"При запуске индекс загружается в память. Для одного запроса модель вычисляет вектор текста, после чего выполняется сравнение с матрицей каталога. Полный перебор оправдан малым размером набора: 1000 векторов не требуют отдельной распределённой инфраструктуры. Такой выбор упрощает установку и делает результат детерминированным при одинаковых входных данных.")
    add_body(doc,"Для точных названий и авторов действует отдельный распознаватель сущностей. Он поддерживает варианты раскладки, транслитерацию и алиасы каталога. Слова найденного названия удаляются перед извлечением жанра и настроения: например, часть названия не должна ошибочно становиться пользовательским фильтром.")
    add_body(doc,"Поисковая конфигурация версионируется вместе с индексом. В проекте сохранён аварийный профиль предыдущей реализации, но основной запуск использует выбранную по закрытому сравнению дообученную модель. Это позволяет выполнить откат без изменения контроллера CMS.")

    # Page 12
    page_break(doc); add_subheading(doc,"2.4 Анализ запроса и гибридное ранжирование")
    add_body(doc,"Обработка запроса выполняется последовательно. Сначала проверяются раскладка и транслитерация, затем распознаются название и автор. Из оставшегося текста извлекаются мягкие предпочтения по жанру, теме, настроению, темпу, объёму и году. Параметры формы передаются отдельно и применяются как строгие фильтры.")
    add_figure(doc,figures["search"],"Рисунок 2.2 — Последовательность обработки поискового запроса",15.8)
    add_body(doc,"Для описательного запроса основную долю оценки даёт E5-вектор, а лексические совпадения сохраняют редкие конкретные детали. Если найдено уверенное название или автор, приоритет переключается на сущность. Популярность и рейтинг имеют небольшой вес и используются для устойчивого порядка близких результатов, но не должны вытеснять смысл запроса.")
    add_body(doc,"Мягкое ограничение не удаляет кандидата полностью. Слово «короткий» создаёт предпочтение книгам примерно до 250 страниц, но немного более длинная книга может остаться в выдаче. Строгий фильтр pages_max, напротив, исключает все записи, превышающие указанное число страниц. Такое различие делает свободный текст терпимым к неточности, а элементы интерфейса — предсказуемыми.")

    # Page 13
    page_break(doc); add_subheading(doc,"2.5 Персональные рекомендации")
    add_body(doc,"Рекомендации строятся по подтверждённым просмотрам, избранному, корзине и покупкам. Просмотр засчитывается после пяти секунд видимого времени в карточке. Для профиля учитывается до 30 последних уникальных просмотренных книг за 90 дней. Сила сигнала возрастает в порядке: просмотр, избранное, корзина, покупка.")
    add_figure(doc,figures["rec"],"Рисунок 2.3 — Поток персональных рекомендаций",15.8)
    add_body(doc,"PHP передаёт только product_id, тип действия, давность и вес. Векторы выбранных книг объединяются во взвешенный профиль интересов. Стратегия balanced формирует основную полку «Рекомендуем вам». Стратегия explore сохраняет связь с профилем, но усиливает жанровую новизну и разнообразие. В карточке товара отдельная стратегия similar использует текущую книгу как смысловой якорь и исключает её из результата.")
    add_body(doc,"При пустой истории применяется холодный старт на основе популярности и рейтинга с небольшой детерминированной случайной примесью. Случайное зерно фиксируется в сессии, поэтому состав полки не меняется при каждом обновлении страницы. MMR-подобный отбор снижает повторение авторов, серий и почти одинаковых книг.")

    # Page 14
    page_break(doc); add_subheading(doc,"2.6 Интеграция с CMS и интерфейс")
    add_body(doc,"Страница поиска объединяет текстовый запрос, фильтры, сортировку и пагинацию. Пользователь вводит фразу, выбирает необходимые ограничения и нажимает кнопку «Найти». Отдельной кнопки применения фильтров нет: запрос и фильтры отправляются одновременно, что исключает два разных состояния одной формы.")
    add_body(doc,"Интерфейс поддерживает ограничения по цене, автору, жанру, числу страниц, году, возрасту, настроению и темпу. Доступны сортировки по релевантности, возрастанию и убыванию цены, внешнему рейтингу и рейтингу одобренных отзывов магазина. Сначала формируется релевантный пул, после чего применяется выбранная коммерческая сортировка.")
    add_body(doc,"Подсказки названий, авторов, жанров и характерных фраз запрашиваются отдельным маршрутом. Контроллер ограничивает длину строки и число подсказок. После получения идентификаторов CMS форматирует карточки обычным способом, поэтому корзина, скидки, налоги, изображения и наличие продолжают работать штатно.")
    add_table_title(doc,"Таблица 2.2 — Основные маршруты локального API")
    add_table(doc,["Маршрут","Назначение"],[
        ["POST /search","поиск и строгие фильтры"],["POST /recommend","персональные рекомендации"],["GET /suggest","подсказки"],["GET /analyze","разбор запроса"],["GET /facets","значения фильтров"],["GET /health","состояние модели и индекса"]
    ],[5.0,10.6],11)
    add_body(doc,"Для диагностики API предоставляет интерактивное описание схем. FastAPI формирует такую документацию автоматически на основе объявленных маршрутов и типов данных [5].")

    # Page 15
    page_break(doc); add_subheading(doc,"2.7 Надёжность, приватность и сопровождение")
    add_body(doc,"Надёжность обеспечивается разделением торгового и интеллектуального контуров. Если локальный сервис не отвечает или возвращает ошибку, контроллер автоматически запускает стандартный поиск CMS и показывает уведомление. Расширенные фильтры в этом режиме не применяются, поэтому интерфейс честно сообщает об ограниченном результате. В карточке товара резервом служат штатные связанные товары.")
    add_body(doc,"Приватность рекомендаций обеспечивается минимизацией передаваемых данных. Python-сервис не получает идентификатор покупателя или сессии и не хранит пользовательскую историю. Для гостя просмотры находятся в стандартной сессии CMS. Для авторизованного пользователя агрегированная история успешных просмотров хранится в таблице основной базы магазина.")
    add_body(doc,"Проверка состояния сообщает имя модели, число книг, размерность индекса и активность дополнительных компонентов. Это позволяет до демонстрации убедиться, что запущена именно выбранная конфигурация. Manifest предотвращает незаметное использование индекса от другой версии каталога.")
    add_body(doc,"Проект содержит автоматические тесты ядра поиска, рекомендаций, контрактов API и пользовательских сценариев. Для запуска применяется стандартный модуль unittest, который поддерживает объединение тестов в наборы и автоматическое выполнение [6]. При контрольном запуске 17 сентября 2026 года выполнено 98 тестов, все завершились успешно.")
    add_body(doc,"Сопровождение включает обновление каталога, проверку поисковых профилей, перестроение индекса и повторный регрессионный прогон. Такой процесс отделяет изменение данных от изменения алгоритма и помогает обнаружить ухудшение до публикации новой версии.")

    # Page 16
    page_break(doc); add_main_heading(doc,"3 ЭКСПЕРИМЕНТАЛЬНАЯ ПРОВЕРКА")
    add_subheading(doc,"3.1 Методика эксперимента")
    add_body(doc,"Для проверки гипотезы сравнивались стандартный лексический поиск CMS и активная локальная ML-система. Обе системы возвращали не более пяти результатов. Оценивались два заранее выбранных показателя: позиция первой подходящей книги и доля запросов, для которых хотя бы одна подходящая книга найдена среди первых пяти результатов.")
    add_body(doc,"Основная выборка включает 40 коротких запросов длиной от двух до пяти слов. По десять запросов относятся к четырём группам: настроение и тема; жанр и настроение; жанр и тема; жанр и дополнительная характеристика — объём, темп или возраст. Запросы не содержат длинных пересказов сюжета и соответствуют обычному сценарию выбора книги.")
    add_body(doc,"Для каждого запроса до запуска поиска были определены все книги, одновременно удовлетворяющие указанным характеристикам каталога. Поэтому правильных ответов могло быть несколько. Такой способ оценки не требует угадывать единственное название и соответствует задаче подбора товаров.")
    add_body(doc,"Стандартный поиск воспроизведён по действующему резервному алгоритму и тому же источнику импортированного каталога. ML-система использовала модель multilingual-e5-small-finetuned-lr1e-5-epoch3, индекс 1000 × 384, распознаватель названий и многовекторное переранжирование. Выборка и результаты сохранены в отдельных JSON-файлах с контрольными суммами SHA-256.")
    add_body(doc,"Ограничением методики является то, что запросы и оценки релевантности подготовлены одним оценщиком и не являются независимой пользовательской экспертизой. Эксперимент измеряет качество выдачи, но не продажи, конверсию, длительность сессии или удовлетворённость покупателей.")

    # Page 17
    page_break(doc); add_subheading(doc,"3.2 Результаты основного эксперимента")
    add_figure(doc,figures["exp"],"Рисунок 3.1 — Доля успешных запросов в основном эксперименте",15.5)
    add_table_title(doc,"Таблица 3.1 — Общие результаты основного эксперимента")
    add_table(doc,["Система","Найдено в топ-5","Hit@5","Средняя позиция"],[
        ["Стандартный поиск CMS","4 из 40","10,0%","1,00"],
        ["Локальная ML-система","37 из 40","92,5%","1,76"]
    ],[5.2,4.0,2.8,3.6],10)
    add_body(doc,"Локальная система нашла хотя бы одну подходящую книгу в первой пятёрке для 37 из 40 запросов. Стандартный поиск справился с 4 запросами. Разница составила 82,5 процентного пункта. В 24 случаях подходящая книга занимала первую позицию, медианная позиция также равна единице.")
    add_body(doc,"По группам ML-система получила 90% для сочетаний настроения и темы, 90% для жанра и настроения, 100% для жанра и темы и 90% для жанра с дополнительной характеристикой. Стандартный поиск получил соответственно 0%, 20%, 10% и 10%.")
    add_body(doc,"Три неуспешных запроса — «мрачная история о власти», «лёгкая романтическая книга» и «длинное медленное фэнтези». Эти случаи показывают, что сочетание субъективного настроения и нескольких характеристик всё ещё может уступить близким по смыслу кандидатам.")

    # Page 18
    page_break(doc); add_subheading(doc,"3.3 Анализ ошибок и ограничения")
    add_figure(doc,figures["rank"],"Рисунок 3.2 — Распределение позиции первого подходящего результата",15.5)
    add_body(doc,"Распределение позиций показывает, что в 24 из 40 запросов первая же книга соответствовала заданным характеристикам. Ещё для пяти запросов подходящая книга находилась на второй позиции, для трёх — на третьей, для трёх — на четвёртой и для двух — на пятой. Таким образом, большая часть успешных результатов находилась в начале выдачи, а не только формально присутствовала в пределах топ-5.")
    add_body(doc,"Три ошибки получены на запросах «мрачная история о власти», «лёгкая романтическая книга» и «длинное медленное фэнтези». Во всех случаях запрос сочетал несколько признаков, один из которых имел субъективный характер. Семантически близкие кандидаты получили высокий общий балл, но заранее отмеченная по характеристикам каталога книга не вошла в первую пятёрку. Для улучшения таких случаев можно увеличить число обучающих примеров с сочетаниями настроения, темы и темпа и точнее настроить вклад структурированных признаков.")
    add_body(doc,"Основное ограничение эксперимента связано с размером выборки и способом оценки. Запросы и перечни подходящих книг подготовлены одним оценщиком, поэтому результат следует трактовать как проверку разработанного прототипа на зафиксированном наборе, а не как универсальную точность для всех покупателей. Эксперимент также не измеряет продажи, конверсию, длительность сессии и субъективную удовлетворённость.")
    add_body(doc,"Гипотеза подтверждена в пределах основной выборки: семантическое сопоставление повысило Hit@5 с 10,0% до 92,5%. Для дальнейшей проверки необходимы независимая разметка несколькими людьми, накопление реальных обезличенных запросов и оценка поведения системы после внедрения.")

    # Page 19
    page_break(doc); add_main_heading(doc,"ЗАКЛЮЧЕНИЕ")
    add_body(doc,"В ходе проекта разработана и интегрирована в интернет-магазин книг локальная поисково-рекомендательная система. Она принимает запросы на естественном языке, учитывает сочетания характеристик, применяет строгие фильтры, формирует персональные рекомендации и подбор похожих книг. CMS сохраняет ответственность за цены, остатки и карточки товаров, а локальный Python-сервис выполняет анализ текста и ранжирование.")
    add_body(doc,"Поставленная цель достигнута. Изучены ограничения стандартного поиска, спроектирована архитектура, подготовлен каталог из 1000 книг, построен индекс размерности 384, реализованы гибридный поиск, подсказки, фильтры, персональные стратегии и аварийный режим. Интерфейс применяет запрос и выбранные фильтры при нажатии одной кнопки «Найти».")
    add_body(doc,"Эксперимент показал, что на 40 коротких запросах средней сложности локальная ML-система нашла подходящую книгу в первой пятёрке в 92,5% случаев, а стандартный поиск CMS — в 10,0%. Средняя позиция первого подходящего результата среди успешных запросов ML-системы составила 1,76, медианная — 1. Разница Hit@5 равна 82,5 процентного пункта. Все 98 автоматических тестов завершились успешно.")
    add_body(doc,"Полученные данные подтверждают гипотезу в пределах основной выборки. Результат нельзя трактовать как универсальную точность для любых возможных формулировок: эксперимент охватывает короткие запросы средней сложности по жанру, теме, настроению, темпу, возрасту и объёму. Зафиксированные ошибки использованы для определения направлений дальнейшей настройки ранжирования.")
    add_body(doc,"Практическая значимость состоит в том, что решение работает локально, не передаёт историю покупателей в ML-сервис и сохраняет стандартный поиск при отказе интеллектуального компонента. Архитектура подходит для переноса на другой товарный каталог при подготовке его характеристик и поисковых профилей.")
    add_body(doc,"Каждая поставленная задача завершилась проверяемым результатом: определены границы двух подходов, разделены CMS и ML-сервис, подготовлены каталог и индекс, реализованы маршруты поиска и рекомендаций, а эксперимент дал числовое сравнение с исходным алгоритмом. При этом точные параметры пользователя остаются обязательными, товарные данные берутся из CMS, а вывод модели ограничен существующим каталогом.")
    add_body(doc,"Дальнейшее развитие включает сбор обезличенных реальных запросов, независимую оценку релевантности, расширение обучающей выборки, улучшение обработки отрицаний и длинных описаний, а также онлайн-проверку влияния на конверсию и время взаимодействия с каталогом.")

    # Page 20
    page_break(doc); add_main_heading(doc,"СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ")
    sources=[
        "OpenCart Documentation [Электронный ресурс]. — Режим доступа: https://docs.opencart.com/. — Дата доступа: 17.09.2026.",
        "Semantic Search // Sentence Transformers Documentation [Электронный ресурс]. — Режим доступа: https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html. — Дата доступа: 17.09.2026.",
        "Wang L. et al. Text Embeddings by Weakly-Supervised Contrastive Pre-training [Электронный ресурс]. — Режим доступа: https://arxiv.org/abs/2212.03533. — Дата доступа: 17.09.2026.",
        "Wang L. et al. Multilingual E5 Text Embeddings: A Technical Report [Электронный ресурс]. — Режим доступа: https://arxiv.org/abs/2402.05672. — Дата доступа: 17.09.2026.",
        "FastAPI Documentation [Электронный ресурс]. — Режим доступа: https://fastapi.tiangolo.com/. — Дата доступа: 17.09.2026.",
        "unittest — Unit testing framework // Python Documentation [Электронный ресурс]. — Режим доступа: https://docs.python.org/3/library/unittest.html. — Дата доступа: 17.09.2026.",
        "Исходный каталог и поисковые профили разработанного проекта: 1000 записей [Электронный ресурс]. — Локальный файл data/book_catalog/catalog.json. — Дата обращения: 17.09.2026.",
        "Архитектура локального поискового ядра разработанного проекта [Электронный ресурс]. — Локальный файл ml_search/ARCHITECTURE.md. — Дата обращения: 17.09.2026.",
        "Эксперимент по оценке поисковой релевантности разработанного проекта [Электронный ресурс]. — Локальный файл docs/defense-search-experiment.md. — Дата обращения: 17.09.2026."
    ]
    for i,s in enumerate(sources,1): add_body(doc,f"{i}. {s}")
    add_body(doc,"Основная выборка эксперимента: SHA-256 f89536ea9e6473553b42bfe5704683a8cb4a7fc493385ee2af11fb1f8c896531. Результаты основного эксперимента: SHA-256 1029ff596404d728f9a5ea40629d513bbcb425a84f7a63837d3a841f1ee25682.")

    # Document properties and final package settings
    doc.core_properties.title=TITLE
    doc.core_properties.subject="Пояснительная записка к исследовательскому проекту"
    doc.core_properties.author="Автор проекта"
    doc.core_properties.keywords="семантический поиск, рекомендации, локальная ML-модель, CMS, книги"
    doc.save(OUT_PATH)
    print(OUT_PATH)


if __name__ == "__main__":
    build()
