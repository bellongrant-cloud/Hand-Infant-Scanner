"""Write the drive-wheel torque calculation as a PDF.

Usage: python3 torque_pdf.py OUTPUT_DIR
"""
import sys, os, math
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

FONT_DIR = '/usr/share/fonts/truetype/dejavu'
pdfmetrics.registerFont(TTFont('DV', os.path.join(FONT_DIR, 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DV-B', os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('DV', normal='DV', bold='DV-B')

# ------------------------------------------------------------------ inputs (same as torque.py)
R = 0.048          # m
C_f = 0.02
W = 1470.0         # N
m = 150.0          # kg
a = 0.447          # m/s^2
theta_ramp = 4.76  # deg
theta = 5.0        # deg
SF = 1.5

th = math.radians(theta)
F_R = W * C_f * math.cos(th)
F_B = W * math.sin(th)
F_A = m * a
F_tot = F_R + F_B + F_A
T = R * F_tot
T_design = SF * T

# ------------------------------------------------------------------ styles
INK = colors.HexColor('#1a1a1a')
MUTED = colors.HexColor('#555555')
RULE = colors.HexColor('#c8c8c8')
ACCENT = colors.HexColor('#1F4E79')
title = ParagraphStyle('t', fontName='DV-B', fontSize=17, leading=21, textColor=INK, spaceAfter=2)
sub = ParagraphStyle('s', fontName='DV', fontSize=10, leading=13, textColor=MUTED)
h2 = ParagraphStyle('h2', fontName='DV-B', fontSize=12, leading=15, textColor=ACCENT, spaceBefore=10, spaceAfter=4)
body = ParagraphStyle('b', fontName='DV', fontSize=10, leading=14, textColor=INK)
label = ParagraphStyle('l', parent=body, textColor=MUTED, fontSize=9.5)
eq = ParagraphStyle('e', parent=body, fontSize=11, leading=15)
res = ParagraphStyle('r', parent=eq, fontName='DV-B', alignment=2)


def n(x, d=2):
    return f'{x:,.{d}f}'


story = [
    Paragraph('Drive Wheel Torque Calculation', title),
    Paragraph('Grant Bellon', sub),
    Spacer(1, 10),
    Paragraph('The torque the drive motor must supply at the wheel is the wheel radius times the total force '
              'needed to overcome rolling resistance, climb the incline, and accelerate the load. A safety '
              'factor is then applied to get the design torque.', body),
    Paragraph('Given Data', h2),
]

given = [
    ['Wheel radius', 'R', '48 mm = 0.048 m'],
    ['Rolling resistance coefficient (rubber on concrete)', 'C<sub>f</sub>', '0.02'],
    ['Total weight of the loaded vehicle', 'W', '1470 N'],
    ['Mass of the loaded vehicle', 'm', '150 kg'],
    ['Acceleration', 'a', '0.447 m/s<super>2</super>'],
    ['Incline angle (1:12 ramp)', 'θ<sub>ramp</sub>', '4.76°'],
    ['Design incline angle (rounded up)', 'θ', '5°'],
    ['Safety factor', 'SF', '1.5'],
]
gt = Table([[Paragraph(d, body), Paragraph(s, eq), Paragraph(v, eq)] for d, s, v in given],
           colWidths=[3.6 * inch, 0.9 * inch, 2.0 * inch])
gt.setStyle(TableStyle([
    ('LINEBELOW', (0, 0), (-1, -1), 0.5, RULE),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
]))
story.append(gt)


def step(name, formula, subst, result, boxed=False):
    rows = [[Paragraph(name, label), ''],
            [Paragraph(formula + ' = ' + subst, eq), Paragraph(result, res)]]
    t = Table(rows, colWidths=[5.1 * inch, 1.4 * inch])
    style = [('SPAN', (0, 0), (-1, 0)), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
             ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
             ('LINEBELOW', (0, 1), (-1, 1), 0.5, RULE), ('BOTTOMPADDING', (0, 1), (-1, 1), 7)]
    if boxed:
        style += [('BOX', (1, 1), (1, 1), 1.2, ACCENT)]
    t.setStyle(TableStyle(style))
    story.extend([t, Spacer(1, 3)])


story.append(Paragraph('Forces at the Wheel', h2))
step('Rolling resistance', 'F<sub>R</sub> = W·C<sub>f</sub>·cos θ',
     f'(1470 N)(0.02) cos(5°)', f'{n(F_R)} N')
step('Grade (incline) force', 'F<sub>B</sub> = W·sin θ',
     f'(1470 N) sin(5°)', f'{n(F_B)} N')
step('Acceleration force', 'F<sub>A</sub> = m·a',
     f'(150 kg)(0.447 m/s<super>2</super>)', f'{n(F_A)} N')
step('Total force', 'F<sub>total</sub> = F<sub>R</sub> + F<sub>B</sub> + F<sub>A</sub>',
     f'{n(F_R)} N + {n(F_B)} N + {n(F_A)} N', f'{n(F_tot)} N')

story.append(Paragraph('Torque', h2))
step('Required wheel torque', 'T = R·F<sub>total</sub>',
     f'(0.048 m)({n(F_tot)} N)', f'{n(T)} N·m')
step('Design torque with the safety factor applied', 'T<sub>design</sub> = SF·T',
     f'(1.5)({n(T)} N·m)', f'{n(T_design)} N·m', boxed=True)

story += [Spacer(1, 10), Paragraph(
    'Note: the incline is a 1:12 ramp (4.76°), rounded up to 5° for a conservative design. Using 4.76° '
    f'instead would give T<sub>design</sub> ≈ '
    f'{n(SF * R * (W * C_f * math.cos(math.radians(theta_ramp)) + W * math.sin(math.radians(theta_ramp)) + F_A), 1)} N·m.',
    label)]

doc = SimpleDocTemplate(os.path.join(OUT, 'Torque_Calculation.pdf'), pagesize=letter,
                        leftMargin=1 * inch, rightMargin=1 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                        title='Drive Wheel Torque Calculation', author='Grant Bellon')
doc.build(story)
print('T', round(T, 3), 'T_design', round(T_design, 3))
