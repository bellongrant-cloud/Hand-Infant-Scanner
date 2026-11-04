"""Build the drive-wheel torque calculation SMath worksheet.

Usage: python3 torque.py OUTPUT_DIR
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smgen import Sheet

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
S = Sheet()

S.text('Grant Bellon', bold=True, h=26, gap=12)
S.text('Drive Wheel Torque Calculation', bold=True, h=26, gap=12)
S.space(10)
S.text('The torque the drive motor must supply at the wheel is the wheel radius times the total force needed '
       'to overcome rolling resistance, climb the incline, and accelerate the load. A safety factor is then '
       'applied to get the design torque.')
S.space(8)

S.text('Given Data', bold=True, h=26)
S.row([('def', "R := 48*'mm", 120, 29)])
S.text('Wheel radius')
S.row([('def', 'C.f := 0.02', 110, 29)])
S.text('Rolling resistance coefficient (rubber on concrete)')
S.row([('def', "W := 1470*'N", 120, 29), ('def', "m := 150*'kg", 120, 29)])
S.text('Total weight and mass of the loaded vehicle')
S.row([('def', "a := 0.447*'m/'s^2", 140, 50)])
S.text('Acceleration')
S.row([('def', 'θ.ramp := 4.76*π/180', 180, 45), ('def', 'θ := 5*π/180', 150, 45)])
S.text('Incline angle: 4.76° (a 1:12 ramp) rounded up to 5° for the design calculation (angles in radians)')
S.row([('def', 'SF := 1.5', 100, 29)])
S.text('Safety factor')
S.space(10)

S.text('Forces at the Wheel', bold=True, h=26)
S.text('Rolling resistance')
S.row([('defq', 'F.R := W*C.f*cos(θ)', 300, 35, "'N")])
S.text('Grade (incline) force')
S.row([('defq', 'F.B := W*sin(θ)', 260, 35, "'N")])
S.text('Acceleration force')
S.row([('defq', 'F.A := m*a', 220, 35, "'N")])
S.text('Total force')
S.row([('defq', 'F.total := F.R+F.B+F.A', 320, 35, "'N")])
S.space(10)

S.text('Torque', bold=True, h=26)
S.text('Required wheel torque')
S.row([('defq', 'T := R*F.total', 240, 35, "'N*'m")])
S.text('Design torque with the safety factor applied')
S.row([('defq', 'T.design := SF*T', 260, 35, "'N*'m")])

S.save(os.path.join(OUT, 'Torque_Calculation.sm'), 'Grant Bellon', '3c71e9a4-2b58-4d0f-8e16-5a9b7d24c3e8')
E = S.env.vars
for k in ('F.R', 'F.B', 'F.A', 'F.total', 'T', 'T.design'):
    print(k, round(float(E[k]), 3))
