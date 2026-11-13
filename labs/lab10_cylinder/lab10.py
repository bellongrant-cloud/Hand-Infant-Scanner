"""Build the Lab 10 (External Flow over a Cylinder) SMath worksheet and its Excel plot workbook.

Usage: python3 lab10.py OUTPUT_DIR
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import subprocess, tempfile, shutil
import numpy as np
from smgen import Sheet

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
S = Sheet()


def vec(vals, unit):
    return f"mat({','.join(str(v) for v in vals)},{len(vals)},1)" + (('*' + unit) if unit else '')


def vcall(fn, n):
    return f"mat({','.join(f'{fn}({i})' for i in range(1, n + 1))},{n},1)"


# ------------------------------------------------------------------ data from the data sheets
setpoint = [10, 20, 30, 40, 50, 60]
N = len(setpoint)
Q = [52.7, 106.2, 162.8, 208.2, 223.5, 247.8]      # GPM
U_Q = [0.5, 0.5, 2, 3, 5, 7]                       # GPM
T = [0.146, 1.02, 2.86, 3.68, 3.98, 4.73]          # N
U_T = [0.01, 0.01, 0.1, 0.1, 0.1, 0.2]             # N
# Smooth cylinder drag coefficient read from Figure 15-34, Cengel et al.
Re_lit = [10, 50, 100, 500, 1000, 5000, 10000, 20000, 30000]
CD_lit = [2.6, 1.9, 1.5, 1.0, 0.87, 1.0, 1.28, 1.2, 1.1]

# ------------------------------------------------------------------ header
for t in ('Grant Bellon', 'Lab [10]', 'External Flow over a Cylinder'):
    S.text(t, bold=True, h=26, gap=12)
S.space(10)
S.text('Introduction', bold=True, h=26)
S.text('Water was run past a cylinder in a recirculating water channel at six motor controller setpoints. '
       'The drag force was found from a tension gauge on the pivoting cylinder assembly, and hydrogen bubbles '
       'showed the flow pattern. The drag coefficient was calculated at each Reynolds number and compared with '
       'literature data. Uncertainties were propagated with the Kline-McClintock method.')
S.space(8)

# ------------------------------------------------------------------ given data
S.text('Given Data', bold=True, h=26)
S.text('Environmental conditions')
S.row([('def', "P.atm := 99.97*'kPa", 140, 29), ('def', "U.P_atm := 0.01*'kPa", 140, 29),
       ('def', 'T.atm_degC := 27.1', 130, 29), ('def', 'U.T_atm_degC := 1', 130, 29)])
S.text('Water density sample')
S.row([('def', "Vol.water := 24*'cm^3", 150, 40), ('def', "U.Vol_water := 0.5*'cm^3", 160, 40),
       ('def', "m.water := 24.2*'g", 140, 29), ('def', "U.m_water := 0.05*'g", 150, 29)])
S.text('Cylinder and water channel geometry. The L1 uncertainty was blank on the data sheet, so the L2 value is used.')
S.row([('def', "D := 24.9*'mm", 130, 29), ('def', "U.D := 0.1*'mm", 130, 29),
       ('def', "L.cylinder := (5+7/8)*'in", 190, 40), ('def', "U.L_cylinder := 1/32*'in", 180, 40)])
S.row([('def', "w.channel := (6+1/4)*'in", 190, 40), ('def', "U.w_channel := 1/32*'in", 180, 40),
       ('def', "h.wetted := (5+1/8)*'in", 180, 40), ('def', "U.h_wetted := 1/32*'in", 170, 40)])
S.row([('def', "L.1 := (2+1/16)*'in", 170, 40), ('def', "U.L_1 := 1/32*'in", 150, 40),
       ('def', "L.2 := (6+1/4)*'in", 170, 40), ('def', "U.L_2 := 1/32*'in", 150, 40)])
S.text('Flowrate and tension at motor controller setpoints 10, 20, 30, 40, 50, and 60')
S.row([('def', "GPM := 3.785411784*10^(-3)*'m^3/(60*'s)", 300, 50)])
S.row([('def', f"Q := {vec(Q, 'GPM')}", 220, 150), ('def', f"U.Q := {vec(U_Q, 'GPM')}", 220, 150),
       ('def', f"T := {vec(T, chr(39) + 'N')}", 200, 150), ('def', f"U.T := {vec(U_T, chr(39) + 'N')}", 200, 150)])
S.text('Water viscosity from Table A-15 at 25 °C and 30 °C, interpolated linearly to T_atm')
S.row([('def', "μ.25C := 0.891*10^(-3)*'kg/('m*'s)", 240, 45), ('def', "μ.30C := 0.798*10^(-3)*'kg/('m*'s)", 240, 45)])
S.row([('defq', 'μ.water := μ.25C+(T.atm_degC-25)/(30-25)*(μ.30C-μ.25C)', 560, 55, "'kg/('m*'s)")])
S.text('Viscosity uncertainty from the temperature uncertainty and the table slope')
S.row([('defq', 'U.μ_water := (μ.25C-μ.30C)/(30-25)*U.T_atm_degC', 460, 55, "'kg/('m*'s)")])

# ------------------------------------------------------------------ density
S.space(10)
S.text('Water Density', bold=True, h=26)
S.row([('defq', 'ρ.water := m.water/Vol.water', 330, 55, "'kg/'m^3")])
S.row([('defq', 'U.ρ_water := sqrt((U.m_water/Vol.water)^2+(m.water*U.Vol_water/Vol.water^2)^2)', 560, 75, "'kg/'m^3")])

# ------------------------------------------------------------------ velocity and Reynolds number
S.space(10)
S.text('Water Velocity and Reynolds Number', bold=True, h=26)
S.row([('defq', 'A.channel := w.channel*h.wetted', 300, 35, "'m^2")])
S.row([('fn', 'V.k(k) := el(Q,k)/A.channel', 260, 55)])
S.row([('defq', 'V := ' + vcall('V.k', N), 380, 150, "'m/'s")])
S.text('Kline-McClintock uncertainty of the velocity')
S.row([('fn', 'U.V_k(k) := V.k(k)*sqrt((el(U.Q,k)/el(Q,k))^2+(U.w_channel/w.channel)^2+(U.h_wetted/h.wetted)^2)', 760, 60)])
S.row([('defq', 'U.V := ' + vcall('U.V_k', N), 380, 150, "'m/'s")])
S.row([('fn', 'Re.D_k(k) := ρ.water*V.k(k)*D/μ.water', 320, 55)])
S.row([('defq', 'Re.D := ' + vcall('Re.D_k', N), 380, 150)])
S.text('Kline-McClintock uncertainty of the Reynolds number')
S.row([('fn', 'U.Re_D_k(k) := Re.D_k(k)*sqrt((U.ρ_water/ρ.water)^2+(U.V_k(k)/V.k(k))^2+(U.D/D)^2+(U.μ_water/μ.water)^2)', 860, 60)])
S.row([('defq', 'U.Re_D := ' + vcall('U.Re_D_k', N), 380, 150)])

# ------------------------------------------------------------------ drag
S.space(10)
S.text('Drag Force and Drag Coefficient', bold=True, h=26)
S.text('Moment balance about pivot A: ΣM_A = T·L1 - F_D·L2 = 0, so F_D = T·L1/L2')
S.row([('fn', 'F.D_k(k) := el(T,k)*L.1/L.2', 260, 55)])
S.row([('defq', 'F.D := ' + vcall('F.D_k', N), 380, 150, "'N")])
S.row([('fn', 'U.F_D_k(k) := F.D_k(k)*sqrt((el(U.T,k)/el(T,k))^2+(U.L_1/L.1)^2+(U.L_2/L.2)^2)', 700, 60)])
S.row([('defq', 'U.F_D := ' + vcall('U.F_D_k', N), 380, 150, "'N")])
S.text('Frontal area of the cylinder and its uncertainty')
S.row([('defq', 'A := L.cylinder*D', 220, 35, "'m^2")])
S.row([('defq', 'U.A := sqrt((D*U.L_cylinder)^2+(L.cylinder*U.D)^2)', 440, 45, "'m^2")])
S.text('Drag coefficient and its Kline-McClintock uncertainty')
S.row([('fn', 'C.D_k(k) := F.D_k(k)/(1/2*ρ.water*V.k(k)^2*A)', 400, 60)])
S.row([('defq', 'C.D := ' + vcall('C.D_k', N), 380, 150)])
S.row([('fn', 'U.C_D_k(k) := C.D_k(k)*sqrt((U.F_D_k(k)/F.D_k(k))^2+(U.ρ_water/ρ.water)^2+(2*U.V_k(k)/V.k(k))^2+(U.A/A)^2)', 900, 60)])
S.row([('defq', 'U.C_D := ' + vcall('U.C_D_k', N), 380, 150)])

S.space(10)
S.text('Drag Coefficient from Literature', bold=True, h=26)
S.text('Smooth cylinder values read from Figure 15-34 of Cengel et al.')
S.row([('def', f"Re.D_lit := {vec(Re_lit, '')}", 200, 210), ('def', f"C.D_lit := {vec(CD_lit, '')}", 180, 210)])

S.space(10)
S.text('Flow Pattern Observations', bold=True, h=26)
S.text('Separation angle from the sketches: about 90° from the front stagnation point at every setpoint, close to '
       'the 80° expected for a laminar boundary layer. The wake grew wider and more turbulent as the setpoint increased.')

# ------------------------------------------------------------------ excel workbook and chart images
E = S.env.vars
Re, U_Re, CD, U_CD = E['Re.D'], E['U.Re_D'], E['C.D'], E['U.C_D']

from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.chart.error_bar import ErrorBars
from openpyxl.chart.data_source import NumDataSource, NumRef
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties

DATA = 'Data'
MEAS = (3, 2 + N)
LIT = (MEAS[1] + 4, MEAS[1] + 3 + len(Re_lit))


def fill_data(ws):
    def table(title, row0, hdr, rows):
        ws.cell(row0 - 2, 1, title)
        for j, h in enumerate(hdr):
            ws.cell(row0 - 1, j + 1, h)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                ws.cell(row0 + i, j + 1, round(float(v), 5))
    table('Measured', MEAS[0], ['Re_D', 'C_D', 'U C_D', 'U Re_D'],
          [[Re[k], CD[k], U_CD[k], U_Re[k]] for k in range(N)])
    table('Literature, Figure 15-34', LIT[0], ['Re_D,lit', 'C_D,lit'],
          [[Re_lit[k], CD_lit[k]] for k in range(len(Re_lit))])


def make_chart(ws):
    ch = ScatterChart(); ch.title = 'Cylinder Drag Coefficient vs. Reynolds Number'
    ch.style = 2; ch.scatterStyle = 'lineMarker'
    ch.x_axis.title, ch.y_axis.title = 'Reynolds Number, Re_D', 'Drag Coefficient, C_D'
    ch.x_axis.scaling.logBase = 10
    ch.x_axis.scaling.min, ch.x_axis.scaling.max = 1, 100000
    ch.y_axis.scaling.min, ch.y_axis.scaling.max, ch.y_axis.majorUnit = 0, 3, 0.5
    ch.x_axis.delete = False; ch.y_axis.delete = False
    ch.legend.position = 'b'
    ch.height, ch.width = 11, 18
    spec = [('Measured Drag Coefficient', MEAS, '1F77B4', 'circle', 3),
            ('Drag Coefficient from Literature', LIT, 'FF7F0E', 'square', None)]
    for name, (r0, r1), color, sym, uc in spec:
        s = Series(Reference(ws, min_col=2, min_row=r0, max_row=r1),
                   Reference(ws, min_col=1, min_row=r0, max_row=r1), title=name)
        s.marker.symbol = sym; s.marker.size = 7
        s.marker.graphicalProperties = GraphicalProperties(solidFill=color)
        s.marker.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.solidFill = color
        s.graphicalProperties.line.width = 19050
        s.smooth = False
        if uc:
            L = chr(64 + uc)
            ref = NumRef(f=f"'{DATA}'!${L}${r0}:${L}${r1}")
            s.errBars = ErrorBars(errDir='y', errBarType='both', errValType='cust', noEndCap=False,
                                  plus=NumDataSource(numRef=ref), minus=NumDataSource(numRef=ref),
                                  spPr=GraphicalProperties(ln=LineProperties(solidFill=color, w=12700)))
        ch.series.append(s)
    return ch


wb = Workbook(); ws = wb.active; ws.title = DATA; fill_data(ws)
wb.create_sheet('Chart').add_chart(make_chart(ws), 'A1')
wb.save(os.path.join(OUT, 'Lab_10_-_Cylinder_Drag_Plot.xlsx'))

import pymupdf
from PIL import Image, ImageChops
tmp = tempfile.mkdtemp()
wb = Workbook(); ws = wb.active; ws.title = DATA; fill_data(ws)
sh = wb.create_sheet('chart', 0); sh.add_chart(make_chart(ws), 'A1')
sh.page_setup.orientation = 'landscape'
sh.page_margins.left = sh.page_margins.right = sh.page_margins.top = sh.page_margins.bottom = 0.3
wb.active = 0
wb.save(os.path.join(tmp, 'charts.xlsx'))
subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', tmp,
                os.path.join(tmp, 'charts.xlsx')], check=True, capture_output=True)
png = os.path.join(OUT, 'Lab_10_-_Cylinder_Drag_Plot.png')
pymupdf.open(os.path.join(tmp, 'charts.pdf'))[0].get_pixmap(dpi=110).save(png)
im = Image.open(png).convert('RGB')
bbox = ImageChops.difference(im, Image.new('RGB', im.size, 'white')).getbbox()
im = im.crop((max(bbox[0] - 12, 0), max(bbox[1] - 12, 0), bbox[2] + 12, bbox[3] + 12))
im.thumbnail((720, 720)); im.save(png)
shutil.rmtree(tmp)

S.space(10)
S.text('Plot', bold=True, h=26)
S.text('Chart generated in MS Excel, Lab_10_-_Cylinder_Drag_Plot.xlsx. Error bars show ± uncertainty.')
S.picture(png, im.size[0], im.size[1])

# ------------------------------------------------------------------ Q&A
qa = [
    'Flow pattern with increasing Reynolds number: at setpoint 10 the flow stayed close to the cylinder and '
    'formed a small, slow recirculation zone behind it. As the Reynolds number increased, the separated region '
    'grew into a wider, more chaotic turbulent wake with swirling vortices, and the streamlines bent farther '
    'around the cylinder.',
    'The separation point depends on whether the boundary layer is laminar or turbulent, which is set mainly by '
    'the Reynolds number, surface roughness, and freestream turbulence. A laminar boundary layer separates early, '
    'near 80°, which leaves a wide wake with low pressure behind the cylinder and a high drag coefficient. A '
    'turbulent boundary layer stays attached to about 140°, which narrows the wake, reduces pressure drag, and '
    'causes the sudden drop in drag coefficient known as the drag crisis.',
    'Periodic vortex shedding happens because the two shear layers that separate from the top and bottom of the '
    'cylinder are unstable. Each layer rolls up into a vortex, and as one vortex grows it pulls the opposite shear '
    'layer across the wake and cuts itself off. The vortices then form on alternating sides, creating the von '
    'Kármán vortex street. For a cylinder, shedding begins near Re = 90. Reference: Cengel and Cimbala, Fluid '
    'Mechanics: Fundamentals and Applications, Section 15-6.',
    'The Strouhal number, St = f·D/V, describes the vortex shedding frequency f. For a cylinder it stays near 0.2 '
    'over a wide range of Reynolds numbers. It is important because shedding creates oscillating forces, and if '
    'the shedding frequency matches a structure\'s natural frequency, resonance can cause large vibrations or '
    'failure. It is used in designing chimneys, bridges, power lines, heat exchanger tubes, offshore risers, and '
    'vortex flowmeters.',
]
S.space(10)
S.text('Q/A', bold=True, h=26)
for q in qa:
    S.text(q, w=740)

S.save(os.path.join(OUT, 'Lab_10_-_External_Flow_over_Cylinder.sm'), 'Grant Bellon', '8e4c1d27-6a93-4f50-b2e8-3d7a91c05f64')

np.set_printoptions(precision=4, suppress=True)
print('rho', E['ρ.water'], E['U.ρ_water'], 'mu', E['μ.water'])
print('V', E['V'], E['U.V']); print('Re', Re, U_Re); print('FD', E['F.D'], E['U.F_D'])
print('A', E['A'], E['U.A']); print('CD', CD, U_CD)
