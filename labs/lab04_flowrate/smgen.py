"""Tiny SMath worksheet generator: infix -> SMath RPN XML, with a numeric
mirror evaluator so every result stored in the file is computed from the
same expression text that SMath will evaluate."""
import math, re, base64
from xml.sax.saxutils import escape
import numpy as np

UNITS = {
    'mbar': 100.0, 'mm': 1e-3, 'mL': 1e-6, 'g': 1e-3, 'kg': 1.0, 'm': 1.0,
    's': 1.0, 'min': 60.0, 'gal': 3.785411784e-3, 'L': 1e-3,
    'psi': 6894.757293168361, 'lb': 0.45359237, 'Pa': 1.0,
}

TOK = re.compile(r"\s*(?:(\d+\.\d+|\d+)|('[A-Za-z]+)|([A-Za-zΑ-Ωα-ωπΔ][\w.]*)|(:=|[-+*/^(),]))")


def tokenize(s):
    pos, out = 0, []
    s = s.strip()
    while pos < len(s):
        m = TOK.match(s, pos)
        if not m:
            raise SyntaxError(f"bad token at {s[pos:]!r}")
        pos = m.end()
        num, unit, ident, op = m.groups()
        if num: out.append(('num', num))
        elif unit: out.append(('unit', unit[1:]))
        elif ident: out.append(('id', ident))
        else: out.append(('op', op))
    return out


class P:
    """Recursive-descent parser producing AST tuples."""
    def __init__(self, s):
        self.t = tokenize(s); self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self, v=None):
        tok = self.t[self.i]
        if v is not None and tok[1] != v:
            raise SyntaxError(f"expected {v} got {tok}")
        self.i += 1; return tok

    def expr(self):
        n = self.term()
        while self.peek()[1] in ('+', '-'):
            op = self.eat()[1]; n = ('bin', op, n, self.term())
        return n

    def term(self):
        n = self.unary()
        while self.peek()[1] in ('*', '/'):
            op = self.eat()[1]; n = ('bin', op, n, self.unary())
        return n

    def unary(self):
        if self.peek()[1] == '-':
            self.eat(); return ('neg', self.unary())
        return self.power()

    def power(self):
        b = self.atom()
        if self.peek()[1] == '^':
            self.eat(); return ('bin', '^', b, self.unary())
        return b

    def atom(self):
        k, v = self.eat()
        if k == 'num': return ('num', v)
        if k == 'unit': return ('unit', v)
        if k == 'id':
            if self.peek()[1] == '(':
                self.eat('('); args = []
                if self.peek()[1] != ')':
                    args.append(self.expr())
                    while self.peek()[1] == ',':
                        self.eat(); args.append(self.expr())
                self.eat(')')
                return ('call', v, args)
            return ('id', v)
        if v == '(':
            e = self.expr(); self.eat(')'); return ('paren', e)
        raise SyntaxError(f"unexpected {v}")


def parse(s):
    p = P(s); e = p.expr()
    if p.i != len(p.t): raise SyntaxError(f"trailing tokens in {s}")
    return e


def rpn(n):
    k = n[0]
    if k == 'num': return [('operand', n[1], None)]
    if k == 'unit': return [('operand', n[1], 'unit')]
    if k == 'id': return [('operand', n[1], None)]
    if k == 'paren': return rpn(n[1]) + [('bracket', '(', None)]
    if k == 'neg': return rpn(n[1]) + [('operator', '-', 1)]
    if k == 'bin': return rpn(n[2]) + rpn(n[3]) + [('operator', n[1], 2)]
    if k == 'call':
        out = []
        for a in n[2]: out += rpn(a)
        return out + [('function', n[1], len(n[2]))]
    raise ValueError(n)


class Env:
    def __init__(self):
        self.vars, self.funcs = {}, {}

    def ev(self, n, loc=None):
        loc = loc or {}
        k = n[0]
        if k == 'num': return float(n[1])
        if k == 'unit': return UNITS[n[1]]
        if k == 'id':
            if n[1] in loc: return loc[n[1]]
            if n[1] == 'π': return math.pi
            return self.vars[n[1]]
        if k == 'paren': return self.ev(n[1], loc)
        if k == 'neg': return -self.ev(n[1], loc)
        if k == 'bin':
            a, b = self.ev(n[2], loc), self.ev(n[3], loc)
            return {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                    '/': lambda: a / b, '^': lambda: a ** b}[n[1]]()
        if k == 'call':
            name, args = n[1], [self.ev(a, loc) for a in n[2]]
            if name == 'sqrt': return np.sqrt(args[0])
            if name == 'el': return args[0][int(args[1]) - 1]
            if name == 'mat':
                r, c = int(args[-2]), int(args[-1])
                return np.array(args[:-2], dtype=float).reshape(r, c)[:, 0] if c == 1 else np.array(args[:-2]).reshape(r, c)
            params, body = self.funcs[name]
            return self.ev(body, dict(zip(params, args)))
        raise ValueError(n)


def e_xml(items, ind):
    out = []
    for typ, val, extra in items:
        if typ == 'operand':
            st = ' style="unit"' if extra == 'unit' else ''
            out.append(f'{ind}<e type="operand"{st}>{escape(val)}</e>')
        elif typ == 'bracket':
            out.append(f'{ind}<e type="bracket">(</e>')
        else:
            out.append(f'{ind}<e type="{typ}" args="{extra}">{escape(val)}</e>')
    return out


def fmt_num(v):
    """RPN items for a number, in SMath-like display (4 decimals, exp form)."""
    if v == 0: return [('operand', '0', None)]
    neg = v < 0; a = abs(v)
    if 1e-4 <= a < 1e5:
        s = f"{a:.4f}".rstrip('0').rstrip('.')
        if s in ('', '0'):
            s = f"{a:.6g}"
        items = [('operand', s, None)]
    else:
        ex = int(math.floor(math.log10(a))); mant = a / 10 ** ex
        s = f"{mant:.4f}".rstrip('0').rstrip('.')
        items = [('operand', s, None), ('operand', '10', None), ('operand', str(abs(ex)), None)]
        if ex < 0: items.append(('operator', '-', 1))
        items += [('operator', '^', 2), ('operator', '*', 2)]
    if neg: items.append(('operator', '-', 1))
    return items


class Sheet:
    def __init__(self):
        self.env = Env(); self.regions = []; self.y = 0

    # ---- region builders -------------------------------------------------
    def _math(self, left, top, w, h, inp_items, contract=None, result=None):
        ind = '          '
        x = [f'    <region left="{left}" top="{top}" width="{w}" height="{h}" color="#000000" fontSize="10">',
             '      <math>', '        <input>'] + e_xml(inp_items, ind) + ['        </input>']
        if contract:
            x += ['        <contract>'] + e_xml(rpn(parse(contract)), ind) + ['        </contract>']
        if result is not None:
            x += ['        <result action="numeric">'] + e_xml(result, ind) + ['        </result>']
        x += ['      </math>', '    </region>']
        self.regions.append('\n'.join(x))

    def _result_items(self, val, contract):
        f = self.env.ev(parse(contract)) if contract else 1.0
        cu = rpn(parse(contract)) if contract else []
        v = np.asarray(val, dtype=float) / f
        if v.ndim == 0:
            items = fmt_num(float(v))
        else:
            items = []
            for x in v: items += fmt_num(float(x))
            items += [('operand', str(len(v)), None), ('operand', '1', None), ('function', 'mat', len(v) + 2)]
        if cu:
            items += cu + [('operator', '*', 2)]
        return items

    def text(self, s, bold=False, w=760, h=None, left=18, gap=8):
        if h is None:
            lines = max(1, math.ceil(len(s) / (w / 6.6)))
            h = 10 + 17 * lines
        style = ' style="font-size: 12px; font-weight: bold;"' if bold else ''
        fs = 12 if bold else 10
        self.regions.append('\n'.join([
            f'    <region left="{left}" top="{self.y}" width="{w}" height="{h}" color="#000000" fontSize="{fs}">',
            '      <text lang="eng" fontFamily="Arial" fontSize="10">', '        <content>',
            f'          <p{style}>{escape(s)}</p>', '        </content>', '      </text>', '    </region>']))
        self.y += h + gap

    def row(self, items, gap=14):
        """items: list of (kind, src, width, height[, contract]) laid out left->right.
        kind 'def' : 'name := expr' (shows result if show, contract optional)
        kind 'defq': definition, show result
        kind 'fn'  : 'f(a,b) := body'
        kind 'eval': 'name' with result"""
        left = 18; hmax = 0
        for it in items:
            kind, src, w, h = it[:4]; contract = it[4] if len(it) > 4 else None
            if kind in ('def', 'defq'):
                name, rhs = [s.strip() for s in src.split(':=', 1)]
                node = parse(rhs)
                val = self.env.ev(node); self.env.vars[name] = val
                items_ = [('operand', name, None)] + rpn(node) + [('operator', ':', 2)]
                res = self._result_items(val, contract) if kind == 'defq' else None
                self._math(left, self.y, w, h, items_, contract if kind == 'defq' else None, res)
            elif kind == 'fn':
                lhs, rhs = [s.strip() for s in src.split(':=', 1)]
                fname, params = re.match(r"([^\(]+)\((.*)\)", lhs).groups()
                params = [p.strip() for p in params.split(',')]
                node = parse(rhs); self.env.funcs[fname] = (params, node)
                items_ = [('operand', p, None) for p in params] + [('function', fname, len(params))] + rpn(node) + [('operator', ':', 2)]
                self._math(left, self.y, w, h, items_)
            elif kind == 'eval':
                node = parse(src); val = self.env.ev(node)
                self._math(left, self.y, w, h, rpn(node), contract, self._result_items(val, contract))
            left += w + 20; hmax = max(hmax, h)
        self.y += hmax + gap

    def picture(self, png_path, w, h, left=18, gap=16):
        b64 = base64.b64encode(open(png_path, 'rb').read()).decode()
        self.regions.append('\n'.join([
            f'    <region left="{left}" top="{self.y}" width="{w}" height="{h}" color="#000000">',
            '      <picture>', f'        <raw format="png" encoding="base64">{b64}</raw>',
            '      </picture>', '    </region>']))
        self.y += h + gap

    def space(self, h): self.y += h

    def save(self, path, author, docid):
        head = f'''﻿<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<?application progid="SMath Solver" version="1.5.0.9678"?>
<worksheet xmlns="http://smath.info/schemas/worksheet/1.0">
  <settings ppi="96">
    <identity>
      <id>{docid}</id>
      <revision>1</revision>
    </identity>
    <metadata lang="eng">
      <author>{escape(author)}</author>
    </metadata>
    <calculation>
      <precision>4</precision>
      <exponentialThreshold>5</exponentialThreshold>
      <trailingZeros>false</trailingZeros>
      <significantDigitsMode>false</significantDigitsMode>
      <mixedNumbers>false</mixedNumbers>
      <roundingMode>0</roundingMode>
      <approximateEqualAccuracy>3</approximateEqualAccuracy>
      <fractions>decimal</fractions>
    </calculation>
    <pageModel active="false" viewMode="2" printGrid="false" printAreas="true" simpleEqualsOnly="false" printBackgroundImages="true" hideElementsHighlightings="false">
      <paper id="1" orientation="Portrait" width="850" height="1100" />
      <margins left="39" right="39" top="49" bottom="49" />
      <header alignment="Center" color="#a9a9a9">&amp;[DATE] &amp;[TIME] - &amp;[FILENAME]</header>
      <footer alignment="Center" color="#a9a9a9">&amp;[PAGENUM] / &amp;[COUNT]</footer>
      <backgrounds />
    </pageModel>
    <dependencies>
      <assembly name="SMath Core" version="1.75.9678.0" guid="a37cba83-b69c-4c71-9992-55ff666763bd" />
      <assembly name="MathRegion" version="1.75.9678.0" guid="02f1ab51-215b-466e-a74d-5d8b1cf85e8d" />
      <assembly name="PictureRegion" version="1.75.9678.0" guid="06b5df04-393e-4be7-9107-305196fcb861" />
      <assembly name="TextRegion" version="1.75.9678.0" guid="485d28c5-349a-48b6-93be-12a35a1c1e39" />
    </dependencies>
  </settings>
  <regions type="content">
'''
        with open(path, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(head + '\n'.join(self.regions) + '\n  </regions>\n</worksheet>\n')
