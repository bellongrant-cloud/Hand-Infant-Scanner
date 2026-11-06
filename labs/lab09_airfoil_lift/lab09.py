"""Build the Lab 09 (Anemometry and Airfoil Lift) SMath worksheet and its Excel plot workbook.

Usage: python3 lab09.py OUTPUT_DIR
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import subprocess, tempfile, shutil
import numpy as np
from smgen import Sheet

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
S = Sheet()
MS = "'m/'s"


def vec(vals, unit):
    return f"mat({','.join(str(v) for v in vals)},{len(vals)},1)" + (('*' + unit) if unit else '')


def vcall(fn, n):
    return f"mat({','.join(f'{fn}({i})' for i in range(1, n + 1))},{n},1)"


def vh(n):
    return 20 * n + 20


# ------------------------------------------------------------------ data from the data sheets
beta = [1.0, 0.9, 0.8, 0.7, 0.6]
NA = len(beta)
h_man = [0.25, 0.225, 0.18, 0.11, 0.085]          # in H2O
U_h_man = [0.025, 0.025, 0.025, 0.005, 0.005]     # in H2O (0.6 blank: same as 0.7)
V_hot = [11.51, 11.67, 8.48, 8.35, 7.74]          # m/s
V_turb = [11.00, 9.979, 8.459, 7.099, 6.455]      # m/s
U_V_turb = [0.01, 0.01, 0.01, 0.001, 0.001]       # m/s (0.6 blank: same as 0.7)
alpha = [0.75, 2.02, 4.01, 6.26, 7.89, 10.09, 12.15]   # deg
m_scale = [-123.50, -154.32, -216.34, -228.37, -282.53, -343.99, -325.31]  # g
NB = len(alpha)
# NACA 4412 section lift coefficient read from the NASA plot (Supplemental Data - 26),
# smooth-airfoil curves at Re = 3 to 9 x 10^6, no flap.
alpha_ref = [-4, -2, 0, 2, 4, 6, 8, 10, 12, 14, 16]
CL_ref = [0.0, 0.19, 0.40, 0.61, 0.82, 1.02, 1.20, 1.35, 1.48, 1.58, 1.63]

# ------------------------------------------------------------------ header
for t in ('Grant Bellon', 'Lab [9]', 'Anemometry and Airfoil Lift'):
    S.text(t, bold=True, h=26, gap=12)
S.space(10)
S.text('Introduction', bold=True, h=26)
S.text('The objective of this experiment was to measure air velocity in an open-circuit wind tunnel with three '
       'instruments (a hot wire anemometer, a turbine (vane) anemometer, and a Pitot-static probe with an '
       'inclined manometer) at fan settings from 100% down to 60% of the maximum speed, and then to measure '
       'the lift on a 3D-printed NACA 4412 airfoil at angles of attack from 0 to 12 degrees. The lift was read '
       'as a negative mass on a digital scale, converted to a lift coefficient, and compared with NASA '
       'reference data. Uncertainties were propagated with the Kline-McClintock method.')
S.space(8)

# ------------------------------------------------------------------ given data
S.text('Given Data', bold=True, h=26)
S.text('Environmental conditions and constants')
S.row([('def', "P.atm := 1003.8*'mbar", 140, 29), ('def', "U.P_atm := 0.1*'mbar", 140, 29),
       ('def', "T.atm := (21.9+273.15)*'K", 200, 29), ('def', "U.T_atm := 1*'K", 120, 29)])
S.row([('def', "g := 9.81*'m/'s^2", 120, 50), ('def', "ρ.water := 1000*'kg/'m^3", 170, 50),
       ('def', "R.air := 0.287*1000*'J/('kg*'K)", 220, 50)])

S.text('Part A: wind velocity. Each vector lists β = 1.0, 0.9, 0.8, 0.7, and 0.6. The uncertainties at β = 0.6 '
       'were left blank on the data sheet, so the β = 0.7 values are used.')
S.row([('def', "in.H2O := 0.0254*'m", 160, 29)])
S.row([('def', f"β := {vec(beta, '')}", 150, vh(NA)),
       ('def', f"h.manometer := {vec(h_man, 'in.H2O')}", 260, vh(NA)),
       ('def', f"U.h_manometer := {vec(U_h_man, 'in.H2O')}", 280, vh(NA))], gap=10)
S.row([('def', f"V.hotwire := {vec(V_hot, MS)}", 230, vh(NA)),
       ('def', f"V.turbine := {vec(V_turb, MS)}", 240, vh(NA)),
       ('def', f"U.V_turbine := {vec(U_V_turb, MS)}", 250, vh(NA))], gap=10)
S.row([('def', "U.V_hotwire := 0.01*" + MS, 200, 42)], gap=22)

S.text('Part B: airfoil geometry and lift at maximum velocity. The h_max box on the data sheet holds a lift '
       'reading in grams instead of a manometer height, so the β = 1.0 manometer reading is used (Part B was '
       'run at the same maximum fan setting).')
S.row([('def', "L.chord := (5+7/8)*'in", 170, 40), ('def', "U.L_chord := 1/64*'in", 150, 40),
       ('def', "w := 12*'in", 110, 40), ('def', "U.w := 1/8*'in", 130, 40)])
S.row([('def', 'h.max := el(h.manometer,1)', 230, 29), ('def', 'U.h_max := el(U.h_manometer,1)', 250, 29)])
S.text('Angle of attack (degrees) and scale reading for each lift run (nominally 0, 2, 4, 6, 8, 10, and 12 degrees)')
S.row([('def', f"α := {vec(alpha, '')}", 160, vh(NB)), ('def', 'U.α := 0.01', 110, 29),
       ('def', f"m.scale := {vec(m_scale, chr(39) + 'g')}", 250, vh(NB)), ('def', "U.m_scale := 1*'g", 140, 29)])
S.text('NASA reference lift coefficient for the NACA 4412, transcribed from the section lift coefficient plot '
       '(Supplemental Data - 26, Re = 3 to 9 × 10^6, no flap)')
S.row([('def', f"α.ref := {vec(alpha_ref, '')}", 160, vh(len(alpha_ref))),
       ('def', f"C.L_ref := {vec(CL_ref, '')}", 200, vh(len(alpha_ref)))])
S.text('Air viscosity from Table A-22 (Cengel, Cimbala, and Turner) at 20 °C and 25 °C, interpolated linearly to T_atm')
S.row([('def', "μ.20C := 1.825*10^(-5)*'kg/('m*'s)", 240, 45), ('def', "μ.25C := 1.849*10^(-5)*'kg/('m*'s)", 240, 45)])
S.row([('defq', "μ.air := μ.20C+(T.atm-293.15*'K)/(5*'K)*(μ.25C-μ.20C)", 560, 55, "'kg/('m*'s)")])

# ------------------------------------------------------------------ air density
S.space(10)
S.text('Air Density', bold=True, h=26)
S.row([('defq', 'ρ.air := P.atm/(R.air*T.atm)', 320, 55, "'kg/'m^3")])
S.text('Kline-McClintock uncertainty: ∂ρ/∂P = 1/(RT), ∂ρ/∂T = -P/(RT²)')
S.row([('defq', 'U.ρ_air := sqrt((U.P_atm/(R.air*T.atm))^2+(P.atm*U.T_atm/(R.air*T.atm^2))^2)', 600, 60, "'kg/'m^3")])

# ------------------------------------------------------------------ part A
S.space(10)
S.text('External Velocity Measurements (Part A)', bold=True, h=26)
S.text('Pitot-static pressure difference and velocity for setting k')
S.row([('fn', 'ΔP.k(k) := ρ.water*g*el(h.manometer,k)', 330, 35),
       ('fn', 'V.Pitot_k(k) := sqrt(2*ΔP.k(k)/ρ.air)', 300, 60)])
S.row([('defq', 'ΔP := ' + vcall('ΔP.k', NA), 380, vh(NA), "'Pa"),
       ('defq', 'V.Pitot := ' + vcall('V.Pitot_k', NA), 380, vh(NA), MS)])
S.text('Kline-McClintock uncertainty: U_ΔP = ρ_water·g·U_h, and with V = √(2ΔP/ρ), ∂V/∂ΔP = V/(2ΔP) and ∂V/∂ρ = -V/(2ρ)')
S.row([('fn', 'U.V_Pitot_k(k) := sqrt((V.Pitot_k(k)/(2*ΔP.k(k))*ρ.water*g*el(U.h_manometer,k))^2+(V.Pitot_k(k)/(2*ρ.air)*U.ρ_air)^2)', 900, 60)])
S.row([('defq', 'U.V_Pitot := ' + vcall('U.V_Pitot_k', NA), 420, vh(NA), MS)])

# ------------------------------------------------------------------ part B
S.space(10)
S.text('Airfoil Lift Measurements (Part B)', bold=True, h=26)
S.text('Maximum wind tunnel velocity from the Pitot-static probe')
S.row([('defq', 'ΔP.max := ρ.water*g*h.max', 300, 35, "'Pa"),
       ('defq', 'V.Pitot_max := sqrt(2*ΔP.max/ρ.air)', 340, 60, MS)])
S.row([('defq', 'U.V_Pitot_max := el(U.V_Pitot,1)', 300, 35, MS)])
S.text('Planform area and lift force (the scale reads a negative mass, so F_L = -m_scale·g)')
S.row([('defq', 'A.planform := L.chord*w', 260, 35, "'m^2"),
       ('fn', 'F.L_k(k) := -el(m.scale,k)*g', 240, 35)])
S.row([('defq', 'F.L := ' + vcall('F.L_k', NB), 380, vh(NB), "'N")])
S.text('Lift coefficient at each angle of attack')
S.row([('fn', 'C.L_k(k) := F.L_k(k)/(1/2*ρ.air*V.Pitot_max^2*A.planform)', 460, 60)])
S.row([('defq', 'C.L := ' + vcall('C.L_k', NB), 380, vh(NB))])
S.text('Kline-McClintock uncertainty. Since ½ρV² = ΔP_max, the air density cancels and C_L = F_L/(ΔP_max·L·w): '
       'each input contributes its relative uncertainty.')
S.row([('defq', "U.F_L := U.m_scale*g", 220, 29, "'N")])
S.row([('fn', 'U.C_L_k(k) := C.L_k(k)*sqrt((U.F_L/F.L_k(k))^2+(ρ.water*g*U.h_max/ΔP.max)^2+(U.L_chord/L.chord)^2+(U.w/w)^2)', 860, 60)])
S.row([('defq', 'U.C_L := ' + vcall('U.C_L_k', NB), 400, vh(NB))])

# ------------------------------------------------------------------ Reynolds number
S.space(10)
S.text('Reynolds Number', bold=True, h=26)
S.text('Reynolds number at the trailing edge of the airfoil (x = L_chord)')
S.row([('defq', 'Re.L := ρ.air*V.Pitot_max*L.chord/μ.air', 440, 55)])
S.text('Transition on a flat plate occurs near Re_x ≈ 5 × 10^5, so the flow at the trailing edge is laminar.')

# ------------------------------------------------------------------ Cessna question
S.space(10)
S.text('Lift on a Full-Scale NACA 4412 Wing', bold=True, h=26)
S.text('Measured lift coefficient at 6°, interpolated between the 4.01° and 6.26° runs')
S.row([('defq', 'C.L_6deg := el(C.L,3)+(6-el(α,3))/(el(α,4)-el(α,3))*(el(C.L,4)-el(C.L,3))', 640, 55)])
S.text('Cessna 172 wing: chord 4.83 ft, wingspan 36 ft; takeoff at 55 knots (1 knot = 0.514444 m/s), '
       'using the lab air density')
S.row([('defq', "A.wing := 4.83*'ft*36*'ft", 260, 35, "'m^2"),
       ('defq', 'V.takeoff := 55*0.514444*' + MS, 300, 45, MS)])
S.row([('defq', 'F.L_wing := C.L_6deg*1/2*ρ.air*V.takeoff^2*A.wing', 460, 55, "'N")])
S.row([('eval', 'F.L_wing', 220, 29, "'lbf")])

# ------------------------------------------------------------------ numbers for plots and Q&A
E = S.env.vars
V_pitot, U_V_pitot = E['V.Pitot'], E['U.V_Pitot']
CL, U_CL = E['C.L'], E['U.C_L']
ref_at = np.interp(alpha, alpha_ref, CL_ref)
pct_diff = (CL - ref_at) / ref_at * 100

# ------------------------------------------------------------------ excel workbook (source of the plots)
from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.chart.error_bar import ErrorBars
from openpyxl.chart.data_source import NumDataSource, NumRef
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties

DATA = 'Data'
COLORS = ['1F77B4', 'FF7F0E', '2CA02C']
SYMBOLS = ['circle', 'square', 'triangle']
PA = (3, 2 + NA)
PB = (PA[1] + 4, PA[1] + 3 + NB)
RF = (PB[1] + 4, PB[1] + 3 + len(alpha_ref))


def fill_data(ws):
    def table(title, row0, hdr, rows):
        ws.cell(row0 - 2, 1, title)
        for j, h in enumerate(hdr):
            ws.cell(row0 - 1, j + 1, h)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                ws.cell(row0 + i, j + 1, v if isinstance(v, str) else round(float(v), 5))
    table('Part A: Wind Velocity', PA[0],
          ['β', 'V_hotwire (m/s)', 'U V_hotwire (m/s)', 'V_turbine (m/s)', 'U V_turbine (m/s)',
           'V_Pitot (m/s)', 'U V_Pitot (m/s)'],
          [[beta[k], V_hot[k], 0.01, V_turb[k], U_V_turb[k], V_pitot[k], U_V_pitot[k]] for k in range(NA)])
    table('Part B: Measured Lift Coefficient', PB[0],
          ['α (deg)', 'C_L measured', 'U C_L'],
          [[alpha[k], CL[k], U_CL[k]] for k in range(NB)])
    table('NACA 4412 Reference (NASA)', RF[0], ['α (deg)', 'C_L reference'],
          [[alpha_ref[k], CL_ref[k]] for k in range(len(alpha_ref))])


def chart(ws, title, xt, yt, xr, yr, series):
    """series: list of (name, rows, xcol, ycol, ucol or None). Markers joined by lines."""
    ch = ScatterChart(); ch.title = title; ch.style = 2; ch.scatterStyle = 'lineMarker'
    ch.x_axis.title, ch.y_axis.title = xt, yt
    ch.x_axis.scaling.min, ch.x_axis.scaling.max, ch.x_axis.majorUnit = xr
    ch.y_axis.scaling.min, ch.y_axis.scaling.max, ch.y_axis.majorUnit = yr
    ch.x_axis.delete = False; ch.y_axis.delete = False
    ch.legend.position = 'b'
    ch.height, ch.width = 11, 18
    for j, (name, (r0, r1), xc, yc, uc) in enumerate(series):
        s = Series(Reference(ws, min_col=yc, min_row=r0, max_row=r1),
                   Reference(ws, min_col=xc, min_row=r0, max_row=r1), title=name)
        s.marker.symbol = SYMBOLS[j]; s.marker.size = 7
        s.marker.graphicalProperties = GraphicalProperties(solidFill=COLORS[j])
        s.marker.graphicalProperties.line.solidFill = COLORS[j]
        s.graphicalProperties.line.solidFill = COLORS[j]
        s.graphicalProperties.line.width = 19050
        s.smooth = False
        if uc:
            L = chr(64 + uc)
            ref = NumRef(f=f"'{DATA}'!${L}${r0}:${L}${r1}")
            s.errBars = ErrorBars(errDir='y', errBarType='both', errValType='cust', noEndCap=False,
                                  plus=NumDataSource(numRef=ref), minus=NumDataSource(numRef=ref),
                                  spPr=GraphicalProperties(ln=LineProperties(solidFill=COLORS[j], w=12700)))
        ch.series.append(s)
    return ch


def charts(ws):
    return [
        ('velocity', chart(ws, 'Wind Tunnel Velocity vs. Fan Setting', 'Fraction of Maximum Velocity, β',
                           'Air Velocity, V (m/s)', (0.5, 1.05, 0.1), (0, 14, 2), [
            ('Hot Wire Anemometer', PA, 1, 2, 3), ('Turbine Anemometer', PA, 1, 4, 5),
            ('Pitot Static Probe', PA, 1, 6, 7)])),
        ('lift_coefficient', chart(ws, 'NACA 4412 Lift Coefficient vs. Angle of Attack', 'Angle of Attack, α (deg)',
                                   'Lift Coefficient, C_L', (-4, 16, 2), (0, 1.8, 0.2), [
            ('Measured', PB, 1, 2, 3), ('Reference', RF, 1, 2, None)])),
    ]


xlsx = os.path.join(OUT, 'Lab_09_-_Airfoil_Lift_Plots.xlsx')
wb = Workbook(); ws = wb.active; ws.title = DATA; fill_data(ws)
cs = wb.create_sheet('Charts')
for i, (_, ch) in enumerate(charts(ws)):
    cs.add_chart(ch, f'A{1 + 24 * i}')
wb.save(xlsx)

# Render each chart to PNG with LibreOffice: one chart per landscape sheet -> PDF page -> PNG.
import pymupdf
from PIL import Image, ImageChops
tmp = tempfile.mkdtemp()
wb = Workbook(); ws = wb.active; ws.title = DATA; fill_data(ws)
names = []
for i, (name, ch) in enumerate(charts(ws)):
    sh = wb.create_sheet(name, i); sh.add_chart(ch, 'A1'); names.append(name)
    sh.page_setup.orientation = 'landscape'
    sh.page_margins.left = sh.page_margins.right = sh.page_margins.top = sh.page_margins.bottom = 0.3
wb.active = 0
wb.save(os.path.join(tmp, 'charts.xlsx'))
subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', tmp,
                os.path.join(tmp, 'charts.xlsx')], check=True, capture_output=True)
doc = pymupdf.open(os.path.join(tmp, 'charts.pdf'))
pngs = []
for i, name in enumerate(names):
    path = os.path.join(OUT, f'Lab_09_-_{name}.png')
    doc[i].get_pixmap(dpi=110).save(path)
    im = Image.open(path).convert('RGB')
    bbox = ImageChops.difference(im, Image.new('RGB', im.size, 'white')).getbbox()
    im = im.crop((max(bbox[0] - 12, 0), max(bbox[1] - 12, 0), bbox[2] + 12, bbox[3] + 12))
    im.thumbnail((720, 720)); im.save(path)
    pngs.append((path, im.size))
shutil.rmtree(tmp)

S.space(10)
S.text('Plots', bold=True, h=26)
S.text('Charts generated in MS Excel (Lab_09_-_Airfoil_Lift_Plots.xlsx) and pasted here. Error bars show ± uncertainty.')
for (path, (w_, h_)), cap in zip(pngs, ['Part A: measured wind tunnel velocity vs. β',
                                       'Part B: measured and NASA reference lift coefficient vs. angle of attack']):
    S.text(cap)
    S.picture(path, w_, h_)

# ------------------------------------------------------------------ Q&A
Re = float(E['Re.L'])
F_wing = float(E['F.L_wing'])
lo, hi = pct_diff.min(), pct_diff.max()
qa = [
    'Advantages and disadvantages of each technique: The hot wire anemometer is small, responds quickly, and '
    'reads velocity directly with fine resolution, but the wire is fragile, it must be calibrated, and it is '
    'sensitive to air temperature and to probe orientation; in our data it read higher than the other two '
    'instruments and even gave a higher reading at β = 0.9 than at β = 1.0. The turbine (vane) anemometer is '
    'inexpensive, rugged, and easy to read, but its relatively large vane averages the flow over its area, '
    'disturbs the flow, and has friction that makes it under-read at low speeds. The Pitot-static probe has '
    'no moving parts, needs no calibration, and is the standard reference for airspeed (it is used on '
    'aircraft), but it must be aligned with the flow, it requires a manometer and a density calculation, and '
    'the small manometer heights at low speeds are hard to read precisely, which gives it the largest '
    'uncertainty of the three.',
    f'Comparison with NASA: our measured lift coefficients were {-hi:.0f}% to {-lo:.0f}% lower than the NASA '
    'reference values at the same angles of attack. The general trend matched (the lift coefficient rose '
    'roughly linearly with angle of attack), but our values were lower and the airfoil stalled earlier, '
    'near 10°, instead of about 14° to 16°. The main reasons are: (1) Reynolds number - our test ran at about '
    f'Re = {Re:,.0f}, while the NASA data were taken at 3 to 9 million, and lift falls and stall occurs earlier '
    'at low Reynolds numbers; (2) the NASA data are for a two-dimensional section (infinite span), while our '
    'airfoil has a finite span with tip vortices and wall gaps that reduce lift; (3) the rough surface and '
    'layer lines of the 3D-printed airfoil; (4) blockage and non-uniform flow in the small wind tunnel; and '
    '(5) friction or contact on the scale and rods, plus angle and manometer reading errors.',
    f'Reynolds number at the trailing edge: Re_L ≈ {Re:,.0f}. This is below the flat-plate transition '
    'Reynolds number of about 5 × 10^5, so the boundary layer at the trailing edge is laminar.',
    f'Lift on a full-scale wing: using our measured lift coefficient at 6° (C_L ≈ {float(E["C.L_6deg"]):.3f}), a '
    'Cessna 172-sized wing (4.83 ft chord × 36 ft span = 173.9 ft²) at a takeoff speed of 55 knots '
    f'(28.3 m/s) and the lab air density would produce a lift force of about {F_wing:,.0f} N, or about '
    f'{F_wing / 4.4482216:,.0f} lbf. This is less than a Cessna 172\'s maximum takeoff weight of about '
    '2,450 lbf, because our measured lift coefficient is lower than the NASA value (which would give about '
    f'{np.interp(6, alpha_ref, CL_ref) / float(E["C.L_6deg"]) * F_wing / 4.4482216:,.0f} lbf); a real '
    'Cessna also uses flaps and a higher angle of attack at rotation.',
]
S.space(10)
S.text('Q/A', bold=True, h=26)
for q in qa:
    S.text(q, w=760)

S.save(os.path.join(OUT, 'Lab_09_-_Airfoil_Lift.sm'), 'Grant Bellon', '6a2e8f14-9b37-4c05-b1d8-2f7e4c90a613')

np.set_printoptions(precision=4, suppress=True)
print('rho_air', E['ρ.air'], '+-', E['U.ρ_air'], 'mu', E['μ.air'])
print('V_pitot', V_pitot, U_V_pitot)
print('V_max', E['V.Pitot_max'], 'A', E['A.planform'])
print('CL', CL, U_CL); print('ref', ref_at); print('pct', pct_diff)
print('Re', Re, 'CL6', E['C.L_6deg'], 'F_wing N', F_wing, 'lbf', F_wing / 4.4482216)
