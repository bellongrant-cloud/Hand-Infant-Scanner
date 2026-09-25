import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from smgen import Sheet, UNITS

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
GPM = "'gal/'min"
S = Sheet()
N6 = ',6,1)'


def vec(vals, unit):
    return 'mat(' + ','.join(str(v) for v in vals) + N6 + (('*' + unit) if unit else '')


def vcall(fn):
    return 'mat(' + ','.join(f'{fn}({i})' for i in range(1, 7)) + N6


# ------------------------------------------------------------------ header
for t in ('Grant Bellon', 'Lab [4]', 'Flowrate Measurement'):
    S.text(t, bold=True, h=26, gap=12)
S.space(10)
S.text('Introduction', bold=True, h=26)
S.text('The objective of this experiment was to measure the volumetric flowrate of recirculating tap water '
       'using six independent techniques: a rotameter, a turbine flowmeter, a Venturi flowmeter, an orifice '
       'flowmeter, a Hall effect flowmeter, and a timed capture (weigh-tank) measurement. Readings were taken '
       'with the gate valve fully open and at approximately 80%, 70%, 60%, 50%, and 40% of the maximum '
       'flowrate. The Venturi and orifice flowrates were calculated from their measured pressure drops, and '
       'the Kline-McClintock method was used to propagate the measurement uncertainties.')
S.space(8)

# ------------------------------------------------------------------ given data
S.text('Given Data', bold=True, h=26)
S.text('Environmental conditions')
S.row([('def', "P.atm := 1004.8*'mbar", 140, 29), ('def', "U.P_atm := 0.1*'mbar", 140, 29),
       ('def', 'T.atm_degC := 24.4', 130, 29), ('def', 'U.T_atm_degC := 1', 130, 29)])
S.text('Geometry measurements')
S.row([('def', "D.V_upstream := 27.1*'mm", 170, 29), ('def', "U.D_V_upstream := 0.01*'mm", 190, 29)])
S.row([('def', "D.V_throat := 7.99*'mm", 170, 29), ('def', "U.D_V_throat := 0.01*'mm", 190, 29)])
S.row([('def', "D.o_upstream := 26.76*'mm", 170, 29), ('def', "U.D_o_upstream := 0.01*'mm", 190, 29)])
S.row([('def', "D.o_throat := 10.42*'mm", 170, 29), ('def', "U.D_o_throat := 0.01*'mm", 190, 29)])
S.text('Water density sample')
S.row([('def', "Vol.water := 36.5*'mL", 150, 29), ('def', "U.Vol_water := 0.5*'mL", 160, 29),
       ('def', "m.water := 36.09*'g", 140, 29), ('def', "U.m_water := 0.01*'g", 150, 29)])

S.text('Flowrate trials. Each vector lists the trials in order: 100% (fully open), 80%, 70%, 60%, 50%, and 40% '
       'of the maximum flowrate. The instrument uncertainties are the same for every trial.')
S.row([('def', "Q.max := 7.25*" + GPM, 160, 45)])
S.row([('defq', 'Q.target := Q.max*' + vec([1, 0.8, 0.7, 0.6, 0.5, 0.4], ''), 380, 140, GPM)])

data = [
    ('Q.rotameter', [7.25, 5.81, 5.0, 4.3, 3.5, 2.8], GPM, 'U.Q_rotameter', '0.5*' + GPM),
    ('Q.turbine', [8.17, 6.66, 5.88, 5.13, 4.27, 3.47], GPM, 'U.Q_turbine', '0.01*' + GPM),
    ('P.V_upstream', [19.5, 12.35, 8, 6.5, 4, 1.66], "'psi", 'U.P_V_upstream', "0.25*'psi"),
    ('P.V_throat', [11, 6.8, 5.1, 3.4, 3.2, 1.2], "'psi", 'U.P_V_throat', "0.1*'psi"),
    ('P.o_upstream', [15, 8.5, 7, 5, 3, 1.5], "'psi", 'U.P_o_upstream', "0.25*'psi"),
    ('P.o_downstream', [9, 5.24, 4.4, 3.17, 2, 1.24], "'psi", 'U.P_o_downstream', "0.1*'psi"),
    ('Q.Hall', [38.1, 30.74, 26.64, 23.12, 18.66, 16.04], "'L/'min", 'U.Q_Hall', "0.1*'L/'min"),
    ('t.fill', [28.47, 31.60, 36.20, 41.87, 57.79, 52.57], "'s", 'U.t_fill', "0.01*'s"),
    ('m.captured', [28.5, 26, 26.79, 26.85, 26.55, 27.2], "'lb", 'U.m_captured', "0.1*'lb"),
]
for i in range(0, len(data), 3):
    S.row([('def', f'{n} := {vec(v, u)}', 250, 140) for n, v, u, _, _ in data[i:i + 3]], gap=10)
    S.row([('def', f'{un} := {uv}', 250, 42) for _, _, _, un, uv in data[i:i + 3]], gap=22)

S.text('Water viscosity from Table A-15 (Cengel, Cimbala, and Turner) at 20 °C and 25 °C, interpolated '
       'linearly to the room temperature T_atm.')
S.row([('def', "μ.20C := 1.002*10^(-3)*'kg/('m*'s)", 230, 45), ('def', "μ.25C := 0.891*10^(-3)*'kg/('m*'s)", 230, 45)])
S.row([('defq', 'μ.water := μ.20C+(T.atm_degC-20)/(25-20)*(μ.25C-μ.20C)', 560, 55, "'kg/('m*'s)")])
S.row([('def', 'F.1 := 0.433', 110, 29), ('def', 'F.2 := 0.47', 110, 29)])

# ------------------------------------------------------------------ density
S.space(10)
S.text('Water Density', bold=True, h=26)
S.row([('defq', 'ρ.water := m.water/Vol.water', 330, 55, "'kg/'m^3")])
S.text('Kline-McClintock uncertainty of the density')
S.row([('defq', 'U.ρ_water := sqrt((U.m_water/Vol.water)^2+(m.water*U.Vol_water/Vol.water^2)^2)', 560, 75, "'kg/'m^3")])

# ------------------------------------------------------------------ timed capture
S.space(10)
S.text('Timed Capture Analysis', bold=True, h=26)
S.text('Volumetric flowrate of the timed capture for trial k')
S.row([('fn', 'Q.cap_i(k) := el(m.captured,k)/(ρ.water*el(t.fill,k))', 330, 55)])
S.row([('defq', 'Q.captured := ' + vcall('Q.cap_i'), 470, 140, GPM)])
S.text('Kline-McClintock uncertainty, with ∂Q/∂m = 1/(ρ t), ∂Q/∂t = -m/(ρ t²), and ∂Q/∂ρ = -m/(ρ² t)')
S.row([('fn', 'U.Q_cap_i(k) := sqrt((U.m_captured/(ρ.water*el(t.fill,k)))^2+(el(m.captured,k)*U.t_fill/(ρ.water*el(t.fill,k)^2))^2+(el(m.captured,k)*U.ρ_water/(ρ.water^2*el(t.fill,k)))^2)', 900, 75)])
S.row([('defq', 'U.Q_captured := ' + vcall('U.Q_cap_i'), 520, 140, GPM)])

# ------------------------------------------------------------------ venturi
S.space(10)
S.text('Venturi Analysis', bold=True, h=26)
S.row([('defq', 'A.V_throat := π*D.V_throat^2/4', 300, 55, "'mm^2"),
       ('defq', 'β.V := D.V_throat/D.V_upstream', 260, 55)])
S.row([('defq', 'C.d_V := 0.9858-0.196*β.V^4.5', 330, 35)])
S.row([('fn', 'ΔP.V_i(k) := el(P.V_upstream,k)-el(P.V_throat,k)', 380, 35)])
S.row([('fn', 'Q.V_i(k) := C.d_V*A.V_throat*(2*ΔP.V_i(k)/(ρ.water*(1-β.V^4)))^(1/2)', 480, 75)])
S.row([('defq', 'Q.V := ' + vcall('Q.V_i'), 420, 140, GPM)])
S.text('Kline-McClintock uncertainty (U_Cd = U_β = 0), with ∂Q/∂D_throat = 2Q/D_throat, '
       '∂Q/∂P_upstream = Q/(2ΔP), ∂Q/∂P_throat = -Q/(2ΔP), and ∂Q/∂ρ = -Q/(2ρ)')
S.row([('fn', 'U.Q_V_i(k) := sqrt((2*Q.V_i(k)/D.V_throat*U.D_V_throat)^2+(Q.V_i(k)/(2*ΔP.V_i(k))*U.P_V_upstream)^2+(Q.V_i(k)/(2*ΔP.V_i(k))*U.P_V_throat)^2+(Q.V_i(k)/(2*ρ.water)*U.ρ_water)^2)', 1000, 75)])
S.row([('defq', 'U.Q_V := ' + vcall('U.Q_V_i'), 450, 140, GPM)])

# ------------------------------------------------------------------ orifice
S.space(10)
S.text('Orifice Analysis', bold=True, h=26)
S.row([('defq', 'A.o_upstream := π*D.o_upstream^2/4', 320, 55, "'mm^2"),
       ('defq', 'A.o_throat := π*D.o_throat^2/4', 300, 55, "'mm^2")])
S.row([('fn', 'V.o_i(k) := el(Q.captured,k)/A.o_upstream', 300, 55)])
S.row([('defq', 'V.o_upstream := ' + vcall('V.o_i'), 450, 140, "'m/'s")])
S.row([('fn', 'Re.D_o_i(k) := ρ.water*V.o_i(k)*D.o_upstream/μ.water', 380, 55)])
S.row([('defq', 'Re.D_o := ' + vcall('Re.D_o_i'), 480, 140)])
S.row([('defq', 'β.o := D.o_throat/D.o_upstream', 280, 55)])
S.row([('defq', 'f.β_o := 0.5959+0.0312*β.o^2.1-0.184*β.o^8', 400, 35)])
S.row([('fn', 'C.d_o_i(k) := f.β_o+91.71*β.o^2.5*Re.D_o_i(k)^(-0.75)+0.09*β.o^4/(1-β.o^4)*F.1-0.0337*β.o^3*F.2', 700, 60)])
S.row([('defq', 'C.d_o := ' + vcall('C.d_o_i'), 480, 140)])
S.row([('fn', 'ΔP.o_i(k) := el(P.o_upstream,k)-el(P.o_downstream,k)', 400, 35)])
S.row([('fn', 'Q.o_i(k) := C.d_o_i(k)*A.o_throat*(2*ΔP.o_i(k)/(ρ.water*(1-β.o^4)))^(1/2)', 500, 75)])
S.row([('defq', 'Q.o := ' + vcall('Q.o_i'), 420, 140, GPM)])
S.text('Kline-McClintock uncertainty (U_Cd = U_β = 0), with ∂Q/∂D_throat = 2Q/D_throat, '
       '∂Q/∂P_upstream = Q/(2ΔP), ∂Q/∂P_downstream = -Q/(2ΔP), and ∂Q/∂ρ = -Q/(2ρ)')
S.row([('fn', 'U.Q_o_i(k) := sqrt((2*Q.o_i(k)/D.o_throat*U.D_o_throat)^2+(Q.o_i(k)/(2*ΔP.o_i(k))*U.P_o_upstream)^2+(Q.o_i(k)/(2*ΔP.o_i(k))*U.P_o_downstream)^2+(Q.o_i(k)/(2*ρ.water)*U.ρ_water)^2)', 1000, 75)])
S.row([('defq', 'U.Q_o := ' + vcall('U.Q_o_i'), 450, 140, GPM)])

# ------------------------------------------------------------------ summary (all in GPM)
S.space(10)
S.text('Summary of Flowrates (GPM)', bold=True, h=26)
S.text('Directly read instruments converted to GPM, alongside the calculated flowrates (trial order 100%, 80%, 70%, 60%, 50%, 40%).')
S.row([('eval', 'Q.target', 190, 140, GPM), ('eval', 'Q.rotameter', 210, 140, GPM),
       ('eval', 'Q.turbine', 200, 140, GPM), ('eval', 'Q.Hall', 190, 140, GPM)])
S.row([('eval', 'Q.captured', 210, 140, GPM), ('eval', 'Q.V', 180, 140, GPM), ('eval', 'Q.o', 180, 140, GPM)])
S.row([('eval', 'U.Q_rotameter', 230, 42, GPM), ('eval', 'U.Q_turbine', 220, 42, GPM), ('eval', 'U.Q_Hall', 220, 42, GPM)])

# ------------------------------------------------------------------ plot
g = UNITS['gal'] / 60
E = S.env.vars
series = [
    ('Rotameter', E['Q.rotameter'], np.full(6, E['U.Q_rotameter']), 'o'),
    ('Turbine Flowmeter', E['Q.turbine'], np.full(6, E['U.Q_turbine']), 's'),
    ('Venturi Flowmeter', E['Q.V'], E['U.Q_V'], '^'),
    ('Orifice Flowmeter', E['Q.o'], E['U.Q_o'], 'v'),
    ('Hall Effect Flowmeter', E['Q.Hall'], np.full(6, E['U.Q_Hall']), 'D'),
    ('Timed Capture', E['Q.captured'], E['U.Q_captured'], 'P'),
]
x = E['Q.target'] / g
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(7.2, 5.0), dpi=100)
for name, y, u, mk in series:
    ax.errorbar(x, y / g, yerr=u / g, marker=mk, ms=5, capsize=3, lw=1, label=name)
ax.plot([2, 8], [2, 8], 'k--', lw=0.8, label='Q = Q_target')
ax.set_xlabel('Target Flowrate, Q_target (GPM)')
ax.set_ylabel('Measured Flowrate, Q (GPM)')
ax.set_title('Measured Flowrate vs. Target Flowrate')
ax.grid(alpha=0.3)
ax.legend(fontsize=8, loc='upper left')
fig.tight_layout()
png = os.path.join(OUT, 'Lab_04_-_Flowrate_Plot.png')
fig.savefig(png)

S.space(10)
S.text('Plots', bold=True, h=26)
S.text('All six flowrate measurements vs. the target flowrate, with error bars showing ± uncertainty '
       '(the same chart is built in the accompanying Excel workbook).')
S.picture(png, 720, 500)

# ------------------------------------------------------------------ excel workbook with native chart
from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.chart.error_bar import ErrorBars
from openpyxl.chart.data_source import NumDataSource, NumRef
wb = Workbook(); ws = wb.active; ws.title = 'Flowrates (GPM)'
hdr = ['Setting', 'Q_target']
for name, *_ in series:
    hdr += [name, 'U ' + name]
ws.append(hdr)
for k, pct in enumerate([100, 80, 70, 60, 50, 40]):
    r = [f'{pct}%', round(float(x[k]), 4)]
    for _, y, u, _ in series:
        r += [round(float(y[k] / g), 4), round(float(u[k] / g), 4)]
    ws.append(r)
ch = ScatterChart(); ch.title = 'Measured Flowrate vs. Target Flowrate'; ch.style = 13
ch.x_axis.title = 'Target Flowrate, Q_target (GPM)'; ch.y_axis.title = 'Measured Flowrate (GPM)'
ch.height, ch.width = 11, 18
xr = Reference(ws, min_col=2, min_row=2, max_row=7)
for j, (name, *_rest) in enumerate(series):
    col = 3 + 2 * j
    s = Series(Reference(ws, min_col=col, min_row=2, max_row=7), xr, title=name)
    s.marker.symbol = 'circle'; s.graphicalProperties.line.noFill = True
    ref = NumRef(f=f"'Flowrates (GPM)'!${chr(64 + col + 1)}$2:${chr(64 + col + 1)}$7")
    s.errBars = ErrorBars(errDir='y', errBarType='both', errValType='cust', noEndCap=False,
                          plus=NumDataSource(numRef=ref), minus=NumDataSource(numRef=ref))
    ch.series.append(s)
ch.x_axis.delete = False; ch.y_axis.delete = False
ws.add_chart(ch, 'B10')
wb.save(os.path.join(OUT, 'Lab_04_-_Flowrate_Plot.xlsx'))

# ------------------------------------------------------------------ Q&A
S.text('Q/A', bold=True, h=26)
qa = [
    'Advantages and disadvantages of each technique: The rotameter is inexpensive, needs no power, and gives '
    'an instant visual reading, but it must be mounted vertically, is read by eye (large uncertainty, ±0.5 GPM '
    'here), and is calibrated for one fluid density. The turbine flowmeter is accurate and has a digital output '
    'with fine resolution, but it has moving parts that wear, needs clean fluid, and adds a pressure loss. The '
    'Venturi meter has no moving parts, a low permanent pressure loss, and is reliable, but it is long, expensive '
    'to machine, and needs two pressure readings plus a calculation. The orifice plate is the cheapest and '
    'simplest differential-pressure meter and is easy to install or replace, but it causes a large permanent '
    'pressure loss and its discharge coefficient depends on the Reynolds number. The Hall effect flowmeter is '
    'very inexpensive and gives an electronic signal, but it is a low-cost paddle-wheel device whose calibration '
    'drifted noticeably from the other meters (it read about 4.5 L/min per GPM of turbine flow instead of 3.785). '
    'Timed capture is a direct, primary measurement that needs no calibration, but it is slow, cannot be done '
    'continuously, and requires the flow to be diverted into a tank.',
    'For high-pressure or high-temperature piping I would use a differential-pressure meter such as a Venturi or '
    'orifice plate, because they have no moving parts, can be made from high-strength alloys, and the pressure '
    'transmitters can be located away from the hot pipe. The orifice plate is the most common choice for steam '
    'and high-pressure lines because it is inexpensive and easy to replace.',
    'Yes. Timed capture (the "bucket and stopwatch" or weigh-tank method) is used in industry to calibrate or '
    'verify other flowmeters, and for low-flow batching, pump tests, and field checks, but it is not practical '
    'for continuous monitoring of large or closed, pressurized systems.',
    'The timed capture method is considered the most accurate because it measures mass and time directly with '
    'precise instruments (±0.1 lb and ±0.01 s) and does not depend on a calibration curve or empirical discharge '
    'coefficient. Its uncertainty was the smallest of the calculated flowrates. Among the inline meters, the '
    'turbine flowmeter had the finest resolution.',
    'Gas flowrate measurement is important for natural gas pipelines and custody transfer (billing), compressed '
    'air systems in manufacturing, steam distribution in power plants and process industries, HVAC ventilation '
    'and air handling, combustion air/fuel control in boilers and engines, medical gases, and semiconductor '
    'process gases.',
    'Gas volumetric flowrate is normally reported in standard cubic feet per minute (SCFM), or in normal cubic '
    'meters per hour (Nm³/h) in SI. Because a gas is compressible, the flow is corrected to a stated standard '
    'temperature and pressure (e.g. 60 °F or 70 °F and 14.7 psia) so that SCFM represents a fixed amount of gas. '
    'Reference: "Standard cubic feet per minute," Wikipedia, https://en.wikipedia.org/wiki/Standard_cubic_feet_per_minute.',
]
for q in qa:
    S.text(q, w=760)

S.save(os.path.join(OUT, 'Lab_04_-_Flowrate.sm'), 'Grant Bellon', '4b8e2d61-7a3c-4f19-9c5e-2a6d0f84b173')

# summary for chat
for name, y, u, _ in series:
    print(f'{name:22s}', ' '.join(f'{a:6.3f}±{b:5.3f}' for a, b in zip(y / g, u / g)))
print('target', x)
print('rho', E['ρ.water'], 'U', E['U.ρ_water'], 'mu', E['μ.water'])
print('ReD', E['Re.D_o']); print('Cdo', E['C.d_o']); print('CdV', E['C.d_V'], 'bV', E['β.V'], 'bo', E['β.o'])
