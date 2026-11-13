"""Write the Lab 10 recorded data as a PDF: typed tables, then the original data sheet photos.

Usage: python3 data_pdf.py OUTPUT_DIR
"""
import sys, os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = '/usr/share/fonts/truetype/dejavu'
pdfmetrics.registerFont(TTFont('DV', os.path.join(FONT_DIR, 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DV-B', os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')))

INK, MUTED, RULE, ACCENT = (colors.HexColor(c) for c in ('#1a1a1a', '#555555', '#c8c8c8', '#1F4E79'))
title = ParagraphStyle('t', fontName='DV-B', fontSize=16, leading=20, textColor=INK)
sub = ParagraphStyle('s', fontName='DV', fontSize=10, leading=13, textColor=MUTED)
h2 = ParagraphStyle('h2', fontName='DV-B', fontSize=11.5, leading=14, textColor=ACCENT, spaceBefore=12, spaceAfter=5)
cell = ParagraphStyle('c', fontName='DV', fontSize=9.5, leading=12, textColor=INK)
head = ParagraphStyle('h', parent=cell, fontName='DV-B')


def table(rows, widths):
    t = Table([[Paragraph(str(v), head if i == 0 else cell) for v in r] for i, r in enumerate(rows)],
              colWidths=[w * inch for w in widths])
    t.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 0.9, INK), ('LINEBELOW', (0, 1), (-1, -1), 0.4, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    return t


story = [
    Paragraph('Lab 10 – External Flow over a Cylinder: Recorded Data', title),
    Paragraph('Grant Bellon', sub),
    Paragraph('Environmental Conditions', h2),
    table([['Quantity', 'Value', 'Uncertainty'],
           ['Barometric pressure, P<sub>atm</sub>', '999.7 mbar', '± 0.1 mbar'],
           ['Room temperature, T<sub>atm</sub>', '27.1 °C', '± 1 °C']], [3.0, 1.75, 1.75]),
    Paragraph('Water Density Sample', h2),
    table([['Quantity', 'Value', 'Uncertainty'],
           ['Water volume, Vol<sub>water</sub>', '24 mL', '± 0.5 mL'],
           ['Water mass, m<sub>water</sub>', '24.2 g', '± 0.05 g']], [3.0, 1.75, 1.75]),
    Paragraph('Geometry', h2),
    table([['Quantity', 'Value', 'Uncertainty'],
           ['Cylinder diameter, D', '24.9 mm', '± 0.1 mm'],
           ['Cylinder length, L<sub>cylinder</sub>', '5 7/8 in', '± 1/32 in'],
           ['Water channel width, w<sub>channel</sub>', '6 1/4 in', '± 1/32 in'],
           ['Wetted height, h<sub>wetted</sub>', '5 1/8 in', '± 1/32 in'],
           ['Bearing to eyebolt, L<sub>1</sub>', '2 1/16 in', 'not recorded'],
           ['Bearing to cylinder center, L<sub>2</sub>', '6 1/4 in', '± 1/32 in']], [3.0, 1.75, 1.75]),
    Paragraph('Drag Force Runs', h2),
    table([['Motor controller setpoint', 'Flowrate, Q', 'U<sub>Q</sub>', 'Tension, T', 'U<sub>T</sub>'],
           ['10', '52.7 GPM', '± 0.5 GPM', '0.146 N', '± 0.01 N'],
           ['20', '106.2 GPM', '± 0.5 GPM', '1.02 N', '± 0.01 N'],
           ['30', '162.8 GPM', '± 2 GPM', '2.86 N', '± 0.1 N'],
           ['40', '208.2 GPM', '± 3 GPM', '3.68 N', '± 0.1 N'],
           ['50', '223.5 GPM', '± 5 GPM', '3.98 N', '± 0.1 N'],
           ['60', '247.8 GPM', '± 7 GPM', '4.73 N', '± 0.2 N']], [1.9, 1.2, 1.1, 1.1, 1.0]),
    Paragraph('Flow pattern sketches for each setpoint are on the original data sheets that follow.', sub),
]

for i in range(1, 5):
    story += [PageBreak(), Paragraph(f'Original Data Sheet, Page {i}', h2),
              Image(os.path.join(HERE, 'data_sheets', f'sheet{i}.jpg'), width=6.3 * inch, height=8.4 * inch)]

SimpleDocTemplate(os.path.join(OUT, 'Lab_10_-_Recorded_Data.pdf'), pagesize=letter,
                  leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.7 * inch, bottomMargin=0.6 * inch,
                  title='Lab 10 Recorded Data', author='Grant Bellon').build(story)
