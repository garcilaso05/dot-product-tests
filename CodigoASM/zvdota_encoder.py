#!/usr/bin/env python3
"""
zvdota_encoder.py - interactive generator of `.word 0x........` lines for Sargantana tests.

Tabs:
  * Zvdota               the 5 dot-product instructions (opcode 0x77)
  * vsetvli / vsetivli   every parameter selectable
  * vsetvl               vtype comes from a register (emits the `li` too)
  * Write vector regs    vmv.v.x / vmv.v.i / vmv.v.v / vmv.s.x / vid.v / vle*.v,
                         with decimal -> BF16 / FP32 / FP8 conversion built in
  * Number formats       decimal <-> BF16, FP32, FP8 E4M3, FP8 E5M2 (+ C array generator)

Run:   python3 zvdota_encoder.py          (GUI, needs tkinter: sudo apt install python3-tk)
Check: python3 zvdota_encoder.py --test   (self-test, no GUI)
"""
import math
import sys

# ============================================================================
# 1. INSTRUCTION ENCODING (no GUI). Every encoder returns a list of
#    (field_name, width_in_bits, value) from bit 31 down to bit 0.
# ============================================================================
OP_V, OP_LOAD_FP, OP_DOTP = 0b1010111, 0b0000111, 0b1110111          # major opcodes
F3_OPIVV, F3_OPFVV, F3_OPMVV, F3_OPIVI, F3_OPIVX, F3_OPMVX, F3_OPCFG = 0, 1, 2, 3, 4, 6, 7

# Zvdota: name -> (funct6, funct3, note)
ZVDOTA = {
    "vqwdotau":     (0b100110, F3_OPIVV, "Integer dot product, unsigned. Needs SEW=8 or 16 (any altfmt). vd is 4*SEW wide."),
    "vqwdotas":     (0b100111, F3_OPIVV, "Integer dot product, signed. Needs SEW=8 or 16 (any altfmt). vd is 4*SEW wide."),
    "vfwdota":      (0b100100, F3_OPFVV, "BF16 -> FP32. Needs SEW=16, altfmt=1 and mstatus.FS != 0. vd is 2*SEW wide."),
    "vfqwdota":     (0b100110, F3_OPFVV, "OFP8 -> FP32. Needs SEW=8 and mstatus.FS != 0 (altfmt selects the vs1 format). vd is 4*SEW wide."),
    "vfqwdota.alt": (0b100111, F3_OPFVV, "OFP8 (alt) -> FP32. Needs SEW=8 and mstatus.FS != 0. vd is 4*SEW wide."),
}

SEW = {"e8": 0b000, "e16": 0b001, "e32": 0b010, "e64": 0b011}
LMUL = {"m1": 0b000, "m2": 0b001, "m4": 0b010, "m8": 0b011,
        "mf8": 0b101, "mf4": 0b110, "mf2": 0b111}

# Scalar registers offered in the drop-downs (ABI name -> number).
# ra/sp/gp/tp/s0 are left out on purpose: GCC does not allow clobbering them.
SREGS = {"x0": 0, "t0": 5, "t1": 6, "t2": 7, "s1": 9,
         **{f"a{i}": 10 + i for i in range(8)},
         **{f"s{i}": 16 + i for i in range(2, 12)},
         "t3": 28, "t4": 29, "t5": 30, "t6": 31}


def pack(fields):
    """Concatenate the fields (MSB first) into a 32-bit word."""
    word, total = 0, 0
    for name, width, value in fields:
        if not 0 <= value < (1 << width):
            raise ValueError(f"{name}={value} does not fit in {width} bits")
        word = (word << width) | value
        total += width
    assert total == 32, f"fields add up to {total} bits"
    return word


def vtype_value(sew, lmul, ta, ma, altfmt):
    """vtype = altfmt[8] | vma[7] | vta[6] | vsew[5:3] | vlmul[2:0]"""
    return (altfmt << 8) | (ma << 7) | (ta << 6) | (SEW[sew] << 3) | LMUL[lmul]


def enc_dot(name, vd, vs2, vs1, masked):
    f6, f3, _ = ZVDOTA[name]
    return [("funct6", 6, f6), ("vm", 1, 0 if masked else 1), ("vs2", 5, vs2), ("vs1", 5, vs1),
            ("funct3", 3, f3), ("vd", 5, vd), ("opcode", 7, OP_DOTP)]


def enc_vsetvli(rd, rs1, zimm):      # bit 31 = 0, zimm = vtype (11 bits)
    return [("bit31", 1, 0), ("zimm[10:0]", 11, zimm), ("rs1", 5, rs1),
            ("funct3", 3, F3_OPCFG), ("rd", 5, rd), ("opcode", 7, OP_V)]


def enc_vsetivli(rd, uimm, zimm):    # bits 31:30 = 11, zimm = vtype (10 bits), AVL = uimm (5 bits)
    return [("bits31:30", 2, 0b11), ("zimm[9:0]", 10, zimm), ("uimm", 5, uimm),
            ("funct3", 3, F3_OPCFG), ("rd", 5, rd), ("opcode", 7, OP_V)]


def enc_vsetvl(rd, rs1, rs2):        # vtype comes from register rs2
    return [("funct7", 7, 0b1000000), ("rs2", 5, rs2), ("rs1", 5, rs1),
            ("funct3", 3, F3_OPCFG), ("rd", 5, rd), ("opcode", 7, OP_V)]


def _opv(funct6, vs2, rs1_field, funct3, vd):   # vm = 1 (unmasked) OP-V format
    return [("funct6", 6, funct6), ("vm", 1, 1), ("vs2", 5, vs2), ("rs1/vs1/imm", 5, rs1_field),
            ("funct3", 3, funct3), ("vd", 5, vd), ("opcode", 7, OP_V)]


def enc_vmv_v_x(vd, rs1):  return _opv(0b010111, 0, rs1, F3_OPIVX, vd)
def enc_vmv_v_i(vd, imm):  return _opv(0b010111, 0, imm & 0x1F, F3_OPIVI, vd)
def enc_vmv_v_v(vd, vs1):  return _opv(0b010111, 0, vs1, F3_OPIVV, vd)
def enc_vmv_s_x(vd, rs1):  return _opv(0b010000, 0, rs1, F3_OPMVX, vd)
def enc_vid_v(vd):         return _opv(0b010100, 0, 0b10001, F3_OPMVV, vd)


LOAD_WIDTH = {"vle8.v": 0b000, "vle16.v": 0b101, "vle32.v": 0b110, "vle64.v": 0b111}
LOAD_BITS = {"vle8.v": 8, "vle16.v": 16, "vle32.v": 32, "vle64.v": 64}


def enc_vle(name, vd, rs1, masked):   # unit-stride load: nf=0, mew=0, mop=0, lumop=0
    return [("nf", 3, 0), ("mew", 1, 0), ("mop", 2, 0), ("vm", 1, 0 if masked else 1),
            ("lumop", 5, 0), ("rs1", 5, rs1), ("width", 3, LOAD_WIDTH[name]),
            ("vd", 5, vd), ("opcode", 7, OP_LOAD_FP)]


# ============================================================================
# 2. NUMBER FORMATS: decimal <-> BF16 / FP32 / FP8 E4M3 / FP8 E5M2
#    (round-to-nearest-even, subnormals supported)
# ============================================================================
# name: (exponent bits, mantissa bits, bias, has_infinity)
FORMATS = {
    "BF16":     (8, 7, 127, True),
    "FP32":     (8, 23, 127, True),
    "FP8 E4M3": (4, 3, 7, False),   # OCP OFP8: no infinities, NaN = S.1111.111, max finite 448
    "FP8 E5M2": (5, 2, 15, True),   # IEEE-like: inf and NaN exist, max finite 57344
}
FORMAT_BITS = {n: 1 + f[0] + f[1] for n, f in FORMATS.items()}          # 16, 32, 8, 8
C_TYPE = {16: "uint16_t", 32: "uint32_t", 8: "uint8_t", 64: "uint64_t"}
RAW = "Raw integer"
VALUE_FORMATS = [RAW] + list(FORMATS)


def _specials(fmt):
    eb, mb, _, has_inf = FORMATS[fmt]
    exp_all = ((1 << eb) - 1) << mb
    if has_inf:
        return eb + mb, exp_all | (1 << (mb - 1)), exp_all, (exp_all - (1 << mb)) | ((1 << mb) - 1)
    nan = exp_all | ((1 << mb) - 1)
    return eb + mb, nan, None, nan - 1            # (sign bit, NaN, Inf, max finite)


def encode_float(value, fmt, saturate=False):
    """Decimal -> bit pattern. Overflow gives Inf (NaN for E4M3) unless `saturate`."""
    eb, mb, bias, has_inf = FORMATS[fmt]
    sign_pos, nan, inf, maxf = _specials(fmt)
    s = (1 if math.copysign(1.0, value) < 0 else 0) << sign_pos
    if math.isnan(value):
        return nan | s
    a = abs(value)
    overflow = math.isinf(a)
    if not overflow:
        if a == 0:
            return s
        e = math.frexp(a)[1] - 1                          # a = 1.f * 2**e
        emin = 1 - bias
        if e < emin:                                      # subnormal range
            return s | round(math.ldexp(a, mb - emin))    # round() = half-to-even
        n = round(math.ldexp(a, mb - e))                  # significand in [2**mb, 2**(mb+1)]
        if n == 1 << (mb + 1):
            n, e = 1 << mb, e + 1
        pattern = ((e + bias) << mb) | (n - (1 << mb))
        overflow = pattern > maxf
        if not overflow:
            return s | pattern
    if saturate:
        return s | maxf
    return s | (inf if has_inf else nan)


def decode_float(pattern, fmt):
    """Bit pattern -> float."""
    eb, mb, bias, has_inf = FORMATS[fmt]
    sign_pos = eb + mb
    sign = -1.0 if (pattern >> sign_pos) & 1 else 1.0
    body = pattern & ((1 << sign_pos) - 1)
    ef, m = body >> mb, body & ((1 << mb) - 1)
    if ef == (1 << eb) - 1:
        if has_inf:
            return sign * math.inf if m == 0 else math.nan
        if m == (1 << mb) - 1:
            return math.nan
    if ef == 0:
        return sign * math.ldexp(m, 1 - bias - mb)
    return sign * math.ldexp((1 << mb) + m, ef - bias - mb)


def parse_decimal(text):
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"'{text}' is not a decimal number (examples: 1.5, -0.1, 1e-3, inf, nan)")


def split_values(text):
    return [t for t in text.replace(";", " ").replace(",", " ").split() if t]


def c_array(name, ctype, patterns, hex_digits, per_line=8):
    body = []
    for i in range(0, len(patterns), per_line):
        body.append(", ".join(f"0x{p:0{hex_digits}X}" for p in patterns[i:i + per_line]))
    return f"{ctype} {name}[] = {{" + (",\n    ".join(body)) + "};"


def breakdown(fields):
    return " | ".join(f"{n}={v:0{w}b}" for n, w, v in fields)


# ============================================================================
# 3. SELF TEST  (instruction words: llvm-mc -mattr=+v; Zvdota: equivalent .insn;
#                number formats: ml_dtypes / struct)
# ============================================================================
def self_test():
    t0, t1, t2, a1, a2, a3 = 5, 6, 7, 11, 12, 13
    checks = [
        (enc_vsetvli(t0, 0, vtype_value("e8", "m1", 0, 0, 0)),        0x000072D7),
        (enc_vsetvli(t0, 0, vtype_value("e16", "mf2", 1, 1, 0)),      0x0CF072D7),
        (enc_vsetvli(t0, 0, 0x100),                                    0x100072D7),
        (enc_vsetvli(t0, 0, 0x200),                                    0x200072D7),
        (enc_vsetivli(t0, 5, vtype_value("e32", "m2", 0, 0, 0)),      0xC112F2D7),
        (enc_vsetvl(t0, 0, t2),                                        0x807072D7),
        (enc_vsetvl(a1, a2, a3),                                       0x80D675D7),
        (enc_vmv_v_x(1, t1),                                           0x5E0340D7),
        (enc_vmv_v_i(1, 5),                                            0x5E02B0D7),
        (enc_vmv_v_i(2, -16),                                          0x5E083157),
        (enc_vmv_v_v(1, 3),                                            0x5E0180D7),
        (enc_vmv_s_x(1, t1),                                           0x420360D7),
        (enc_vid_v(1),                                                 0x5208A0D7),
        (enc_vle("vle8.v", 1, t1, False),                              0x02030087),
        (enc_vle("vle16.v", 1, t1, False),                             0x02035087),
        (enc_vle("vle32.v", 1, t1, False),                             0x02036087),
        (enc_vle("vle64.v", 1, t1, False),                             0x02037087),
        (enc_vle("vle8.v", 1, t1, True),                               0x00030087),
        (enc_dot("vqwdotau", 1, 2, 3, False),                          0x9A2180F7),
        (enc_dot("vqwdotau", 1, 2, 3, True),                           0x982180F7),
        (enc_dot("vqwdotas", 1, 2, 3, False),                          0x9E2180F7),
        (enc_dot("vfwdota", 1, 2, 3, False),                           0x922190F7),
        (enc_dot("vfqwdota", 1, 2, 3, False),                          0x9A2190F7),
        (enc_dot("vfqwdota.alt", 1, 2, 3, False),                      0x9E2190F7),
    ]
    bad = 0
    for fields, expected in checks:
        got = pack(fields)
        if got != expected:
            bad += 1
            print(f"FAIL: got 0x{got:08X}, expected 0x{expected:08X}  ({breakdown(fields)})")
    n_instr = len(checks)

    numbers = [   # value, BF16, FP32, E4M3, E5M2
        (1.0,     0x3F80, 0x3F800000, 0x38, 0x3C),
        (1.5,     0x3FC0, 0x3FC00000, 0x3C, 0x3E),
        (-2.0,    0xC000, 0xC0000000, 0xC0, 0xC0),
        (0.1,     0x3DCD, 0x3DCCCCCD, 0x1D, 0x2E),
        (448.0,   0x43E0, 0x43E00000, 0x7E, 0x5F),
        (57344.0, 0x4760, 0x47600000, 0x7F, 0x7B),   # E4M3 overflows to NaN (0x7F)
    ]
    n_num = 0
    for v, *exp in numbers:
        for fmt, e in zip(FORMATS, exp):
            n_num += 1
            got = encode_float(v, fmt)
            if got != e:
                bad += 1
                print(f"FAIL: {v} as {fmt}: got 0x{got:X}, expected 0x{e:X}")
    for fmt, p, v in (("BF16", 0x3FC0, 1.5), ("FP32", 0x3FC00000, 1.5), ("FP8 E4M3", 0x3C, 1.5), ("FP8 E5M2", 0x3E, 1.5)):
        n_num += 1
        if decode_float(p, fmt) != v:
            bad += 1
            print(f"FAIL: decode 0x{p:X} as {fmt}")
    print(f"{n_instr}/{n_instr} instruction encodings and {n_num} number conversions checked: "
          + ("ALL OK" if bad == 0 else f"{bad} FAILED"))
    return bad == 0


# ============================================================================
# 4. OUTPUT FORMATTING.  item = (kind, text, comment, clobbers)
#    kind: 'word' (.word), 'asm' (any asm line, e.g. li/la), 'raw' (C code, printed as is)
# ============================================================================
STYLES = ['C: __asm__ volatile ("...");',
          'C: line inside a multi-line asm block  "...\\n"',
          'Plain assembly']


def render(item, style):
    kind, text, comment, clobbers = item
    if kind == "raw":
        return f"{text}   // {comment}" if comment else text
    body = f".word {text}" if kind == "word" else text
    if style == STYLES[0]:
        cl = (" : : : " + ", ".join(f'"{c}"' for c in clobbers)) if clobbers else ""
        line, mark = f'__asm__ volatile ("{body}"{cl});', "//"
    elif style == STYLES[1]:
        line, mark = f'"{body}\\n"', "//"
    else:
        line, mark = body, "#"
    return f"{line}   {mark} {comment}" if comment else line


def word_item(fields, comment, clobbers=()):
    return ("word", f"0x{pack(fields):08X}", comment, list(clobbers))


# ============================================================================
# 5. GUI
# ============================================================================
PAL = dict(bg="#eef1f6", card="#ffffff", ink="#1f2933", muted="#6b7785", border="#d5dbe6",
           accent="#3b6ef5", accent_dark="#2c56c9", header="#1f2a44",
           code_bg="#16192a", code_fg="#e6e9f5", warn_bg="#fdecea", warn_fg="#b3261e",
           tip_bg="#eaf1ff", tip_fg="#27458f", tab="#dfe4ee")


def field_color(name):
    """(background, foreground) of a bit field in the coloured strip."""
    if name == "opcode":                                   return "#2d3a5c", "#ffffff"
    if name.startswith("funct") or name == "width":        return "#7a4fc4", "#ffffff"
    if name in ("vd", "rd"):                               return "#2e9d6b", "#ffffff"
    if name in ("vs1", "rs1", "uimm", "rs1/vs1/imm"):      return "#3b6ef5", "#ffffff"
    if name in ("vs2", "rs2"):                             return "#e9893a", "#ffffff"
    if name.startswith("zimm"):                            return "#2aa3b5", "#ffffff"
    if name == "vm":                                       return "#8892a3", "#ffffff"
    return "#c9d0dc", "#1f2933"


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter import font as tkfont
    except ImportError:
        sys.exit("tkinter is not installed. On Ubuntu/Debian: sudo apt install python3-tk")

    VREGS = [f"v{i}" for i in range(32)]
    SREG_NAMES = list(SREGS)
    vnum = lambda s: int(s[1:])

    def parse_int(text, what):
        try:
            return int(text.strip(), 0)
        except ValueError:
            raise ValueError(f"{what}: '{text}' is not a number (use 123 or 0x7B)")

    # ------------------------------------------------------------------ tabs
    class Tab(ttk.Frame):
        """Base class. Subclasses implement generate() -> (items, fields_or_None, messages)."""
        def __init__(self, app, nb, title):
            super().__init__(nb, padding=(18, 12), style="Card.TFrame")
            nb.add(self, text=f"  {title}  ")
            self.app, self.row, self.rows = app, 0, {}
            self.columnconfigure(1, weight=1)

        def _changed(self, *_):
            self.app.refresh()

        def row_of(self, label, parts, key=None):
            """One form row: a label on the left and one or more widgets on the right.
            parts: ("combo", values, default, width) | ("check", text, default)
                   | ("entry", default, width) | ("text", string)
            Returns the tk variables of the parts (None for "text")."""
            lbl = ttk.Label(self, text=label, style="Card.TLabel")
            lbl.grid(row=self.row, column=0, sticky="w", pady=4, padx=(0, 14))
            frame = ttk.Frame(self, style="Card.TFrame")
            frame.grid(row=self.row, column=1, sticky="w")
            out = []
            for p in parts:
                if p[0] == "combo":
                    var = tk.StringVar(value=p[2])
                    w = ttk.Combobox(frame, textvariable=var, values=list(p[1]), state="readonly", width=p[3])
                    w.bind("<<ComboboxSelected>>", self._changed)
                elif p[0] == "check":
                    var = tk.BooleanVar(value=p[2])
                    w = ttk.Checkbutton(frame, text=p[1], variable=var, command=self._changed, style="Card.TCheckbutton")
                elif p[0] == "entry":
                    var = tk.StringVar(value=p[1])
                    var.trace_add("write", self._changed)
                    w = ttk.Entry(frame, textvariable=var, width=p[2])
                else:
                    var, w = None, ttk.Label(frame, text=p[1], style="Card.TLabel")
                w.pack(side="left", padx=(0, 12))
                out.append(var)
            self.rows[key or f"row{self.row}"] = (lbl, frame)
            self.row += 1
            return out

        def combo(self, label, values, default, width=40, key=None):
            return self.row_of(label, [("combo", values, default, width)], key)[0]

        def entry(self, label, default="", width=42, key=None):
            return self.row_of(label, [("entry", default, width)], key)[0]

        def check(self, text, default=False, key=None):
            return self.row_of("", [("check", text, default)], key)[0]

        def show(self, key, visible):
            for w in self.rows[key]:
                w.grid() if visible else w.grid_remove()

        def note(self, text=""):
            lbl = ttk.Label(self, text=text, style="Muted.TLabel", wraplength=740, justify="left")
            lbl.grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(10, 0))
            self.row += 1
            return lbl

    class DotTab(Tab):
        def __init__(self, app, nb):
            super().__init__(app, nb, "Zvdota")
            self.name = self.combo("Instruction", ZVDOTA, "vqwdotau", width=20)
            self.vd, self.vs2, self.vs1 = [v for v in self.row_of("Registers", [
                ("text", "vd"), ("combo", VREGS, "v1", 5), ("text", "vs2"), ("combo", VREGS, "v2", 5),
                ("text", "vs1"), ("combo", VREGS, "v3", 5)]) if v is not None]
            self.masked = self.check("Masked (vm=0, uses v0 as mask)")
            self.info = self.note()

        def generate(self):
            name = self.name.get()
            vd, vs2, vs1 = vnum(self.vd.get()), vnum(self.vs2.get()), vnum(self.vs1.get())
            masked = self.masked.get()
            self.info.config(text=ZVDOTA[name][2] + "  (rules of the proposed Part B decode)")
            fields = enc_dot(name, vd, vs2, vs1, masked)
            msgs = ["vd overlaps vs1/vs2: the decoder will mark this ILLEGAL."] if vd in (vs1, vs2) else []
            txt = f"{name}.vv v{vd}, v{vs2}, v{vs1}" + (", v0.t" if masked else "")
            return [word_item(fields, txt)], fields, msgs

    def vtype_rows(tab, default_alt):
        """SEW/LMUL row + policy row shared by the vset tabs."""
        sew, lmul = [v for v in tab.row_of("SEW / LMUL", [("text", "SEW"), ("combo", SEW, "e8", 6),
                                                          ("text", "LMUL"), ("combo", LMUL, "m1", 6)]) if v is not None]
        ta, ma, alt = tab.row_of("Policies", [("check", "ta (off = tu)", False), ("check", "ma (off = mu)", False),
                                              ("check", "altfmt (vtype bit 8)", default_alt)])
        return sew, lmul, ta, ma, alt

    class VsetliTab(Tab):
        def __init__(self, app, nb):
            super().__init__(app, nb, "vsetvli / vsetivli")
            self.kind = self.combo("Variant", ["vsetvli  (AVL in register rs1)",
                                               "vsetivli (AVL = immediate 0..31)"], "vsetvli  (AVL in register rs1)")
            self.rd = self.combo("rd (receives the new vl)", SREG_NAMES, "t0", width=10)
            self.rs1 = self.combo("rs1 (AVL)", SREG_NAMES, "x0", width=10, key="rs1")
            self.uimm = self.entry("AVL immediate", "4", width=10, key="uimm")
            self.sew, self.lmul, self.ta, self.ma, self.alt = vtype_rows(self, False)
            self.custom = self.entry("Custom vtype (optional)", "", width=14)
            self.info = self.note()

        def generate(self):
            immediate = self.kind.get().startswith("vsetivli")
            self.show("rs1", not immediate)
            self.show("uimm", immediate)
            rd, rs1 = SREGS[self.rd.get()], SREGS[self.rs1.get()]
            vt = vtype_value(self.sew.get(), self.lmul.get(), int(self.ta.get()),
                             int(self.ma.get()), int(self.alt.get()))
            if self.custom.get().strip():
                vt = parse_int(self.custom.get(), "Custom vtype")
            if immediate:
                uimm = parse_int(self.uimm.get(), "AVL immediate")
                fields = enc_vsetivli(rd, uimm, vt)
            else:
                fields = enc_vsetvli(rd, rs1, vt)
            msgs = []
            if vt >> 9:
                msgs.append("vtype has reserved bits (>= bit 9) set: the hardware should set vill.")
            self.info.config(text=f"vtype = 0x{vt:03X}.  rd gets the new vl. With rs1=x0 and rd!=x0: vl = VLMAX. "
                                  "With rs1=x0 and rd=x0: vl is kept, only vtype changes.")
            mnem = "vsetivli" if immediate else "vsetvli"
            if self.custom.get().strip():
                cfg = f"vtype=0x{vt:X} (custom)"
            else:
                cfg = (f"{self.sew.get()}, {self.lmul.get()}, {'ta' if self.ta.get() else 'tu'}, "
                       f"{'ma' if self.ma.get() else 'mu'}" + (", altfmt=1" if self.alt.get() else ""))
            txt = f"{mnem} {self.rd.get()}, {uimm if immediate else self.rs1.get()}, {cfg}"
            return [word_item(fields, txt, [self.rd.get()] if rd else [])], fields, msgs

    class VsetvlTab(Tab):
        def __init__(self, app, nb):
            super().__init__(app, nb, "vsetvl")
            self.rd, self.rs1, self.rs2 = [v for v in self.row_of("Registers", [
                ("text", "rd"), ("combo", SREG_NAMES, "t0", 6), ("text", "rs1 (AVL)"), ("combo", SREG_NAMES, "x0", 6),
                ("text", "rs2 (vtype)"), ("combo", SREG_NAMES, "t2", 6)]) if v is not None]
            self.sew, self.lmul, self.ta, self.ma, self.alt = vtype_rows(self, True)
            self.custom = self.entry("Custom vtype (optional)", "", width=14)
            self.addli = self.check("Also emit `li rs2, vtype` before it", True)
            self.note("vsetvl takes the vtype from a REGISTER (rs2) at run time, so rs2 must be loaded first. "
                      "vsetvli takes it from a constant inside the instruction.")

        def generate(self):
            rd, rs1, rs2 = SREGS[self.rd.get()], SREGS[self.rs1.get()], SREGS[self.rs2.get()]
            vt = vtype_value(self.sew.get(), self.lmul.get(), int(self.ta.get()),
                             int(self.ma.get()), int(self.alt.get()))
            if self.custom.get().strip():
                vt = parse_int(self.custom.get(), "Custom vtype")
            items, msgs = [], []
            if self.addli.get():
                if rs2 == 0:
                    msgs.append("rs2 is x0 (always 0): no `li` emitted, vtype will be 0.")
                else:
                    items.append(("asm", f"li {self.rs2.get()}, 0x{vt:X}", "load the vtype", [self.rs2.get()]))
            if vt >> 9:
                msgs.append("vtype has reserved bits (>= bit 9) set: the hardware should set vill.")
            fields = enc_vsetvl(rd, rs1, rs2)
            items.append(word_item(fields, f"vsetvl {self.rd.get()}, {self.rs1.get()}, {self.rs2.get()}",
                                   [self.rd.get()] if rd else []))
            return items, fields, msgs

    OPS = ["vmv.v.x  vd, rs1      (scalar register -> ALL elements)",
           "vmv.v.i  vd, imm      (immediate -16..15 -> ALL elements)",
           "vmv.v.v  vd, vs1      (copy a vector register)",
           "vmv.s.x  vd, rs1      (scalar register -> element 0 only)",
           "vid.v    vd           (elements = 0, 1, 2, 3 ...)",
           "vle8.v   vd, (rs1)    (load from memory)",
           "vle16.v  vd, (rs1)    (load from memory)",
           "vle32.v  vd, (rs1)    (load from memory)",
           "vle64.v  vd, (rs1)    (load from memory)"]
    FMT_SEW = {"BF16": 16, "FP32": 32, "FP8 E4M3": 8, "FP8 E5M2": 8}

    def to_pattern(text, fmt, bits, saturate=False):
        """One user value -> integer pattern of `bits` bits (decimal if fmt is a float format)."""
        if fmt == RAW:
            return parse_int(text, "value") & ((1 << bits) - 1)
        return encode_float(parse_decimal(text), fmt, saturate)

    class WriteTab(Tab):
        def __init__(self, app, nb):
            super().__init__(app, nb, "Write vector registers")
            self.op = self.combo("Operation", OPS, OPS[0], width=52)
            self.vd = self.combo("vd", VREGS, "v2", width=8)
            self.vs1 = self.combo("vs1", VREGS, "v3", width=8, key="vs1")
            self.rs1 = self.combo("rs1 (scalar / pointer)", SREG_NAMES, "t1", width=8, key="rs1")
            self.imm = self.entry("imm (-16..15)", "5", width=10, key="imm")
            self.fmt = self.combo("Value format", VALUE_FORMATS, "BF16", width=14, key="fmt")
            self.val = self.entry("Value (decimal → `li`)", "1.5", width=24, key="val")
            self.arr = self.entry("Array values (comma separated)", "1, 2.5, -3, 0.1, 100, 7, 8, 9", width=52, key="arr")
            self.sym = self.entry("C array name (→ `la`)", "data", width=16, key="sym")
            self.masked = self.check("Masked (vm=0)", key="masked")
            self.note("Element width and count come from the last vset*: run a vsetvli first, with the SEW that "
                      "matches the format (BF16 = e16, FP32 = e32, FP8 = e8). For DIFFERENT values per element "
                      "use vle with an array (declare it OUTSIDE main), or vid.v (0, 1, 2...).")

        def generate(self):
            op = self.op.get().split()[0]
            vx, vle = op in ("vmv.v.x", "vmv.s.x"), op.startswith("vle")
            self.show("vs1", op == "vmv.v.v")
            self.show("rs1", vx or vle)
            self.show("imm", op == "vmv.v.i")
            for k in ("fmt",):
                self.show(k, vx or vle)
            self.show("val", vx)
            for k in ("arr", "sym", "masked"):
                self.show(k, vle)
            vd, vs1, rs1 = vnum(self.vd.get()), vnum(self.vs1.get()), SREGS[self.rs1.get()]
            rs1n, fmt = self.rs1.get(), self.fmt.get()
            items, msgs = [], []
            if vx and self.val.get().strip():
                bits = FMT_SEW.get(fmt, 64)
                p = to_pattern(self.val.get(), fmt, bits)
                hexd = max(2, bits // 4) if fmt != RAW else 1
                comment = f"{self.val.get().strip()} as {fmt}" if fmt != RAW else "scalar value"
                items.append(("asm", f"li {rs1n}, 0x{p:0{hexd}X}", comment, [rs1n]))
                if fmt != RAW:
                    msgs.append(f"Tip: {fmt} is {bits} bits, so run vsetvli with e{bits} before this.")
            if op == "vmv.v.i":
                imm = parse_int(self.imm.get(), "imm")
                if not -16 <= imm <= 15:
                    raise ValueError("imm must be between -16 and 15")
            if vle:
                width = LOAD_BITS[op]
                sym = self.sym.get().strip()
                vals = split_values(self.arr.get())
                if vals:
                    if not sym:
                        raise ValueError("Give a C array name to emit the array")
                    if fmt != RAW and FMT_SEW[fmt] != width:
                        msgs.append(f"{fmt} elements are {FMT_SEW[fmt]} bits: use vle{FMT_SEW[fmt]}.v, not {op}.")
                    bits = FMT_SEW.get(fmt, width)
                    pats = [to_pattern(v, fmt, bits) for v in vals]
                    items.append(("raw", c_array(sym, C_TYPE[bits], pats, bits // 4),
                                  f"{fmt}: {', '.join(vals)}", []))
                    need = 128 // width
                    if len(vals) < need:
                        msgs.append(f"Tip: vle reads vl elements (VLEN/SEW = {need} with the default VLEN=128). "
                                    f"You gave {len(vals)}: add more or lower vl.")
                if sym:
                    items.append(("asm", f"la {rs1n}, {sym}", "pointer to the array", [rs1n]))
            if op == "vmv.v.x":
                fields, txt = enc_vmv_v_x(vd, rs1), f"vmv.v.x v{vd}, {rs1n}"
            elif op == "vmv.v.i":
                fields, txt = enc_vmv_v_i(vd, imm), f"vmv.v.i v{vd}, {imm}"
            elif op == "vmv.v.v":
                fields, txt = enc_vmv_v_v(vd, vs1), f"vmv.v.v v{vd}, v{vs1}"
            elif op == "vmv.s.x":
                fields, txt = enc_vmv_s_x(vd, rs1), f"vmv.s.x v{vd}, {rs1n}"
            elif op == "vid.v":
                fields, txt = enc_vid_v(vd), f"vid.v v{vd}"
            else:
                fields = enc_vle(op, vd, rs1, self.masked.get())
                txt = f"{op} v{vd}, ({rs1n})" + (", v0.t" if self.masked.get() else "")
            items.append(word_item(fields, txt))
            return items, fields, msgs

    class NumberTab(Tab):
        def __init__(self, app, nb):
            super().__init__(app, nb, "Number formats")
            self.value, self.sat = self.row_of("Decimal value", [
                ("entry", "1.5", 18), ("check", "Saturate on overflow (default: Inf, NaN for E4M3)", False)])
            table = ttk.Frame(self, style="Card.TFrame")
            table.grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(8, 4))
            self.row += 1
            for c, h in enumerate(("Format", "Hex", "sign · exponent · mantissa", "Value stored", "Error")):
                ttk.Label(table, text=h, style="Head.TLabel").grid(row=0, column=c, sticky="w", padx=(0, 14), pady=(0, 4))
            self.cells = {}
            for r, f in enumerate(FORMATS, start=1):
                ttk.Label(table, text=f, style="Card.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=3)
                cells = []
                for c, style in enumerate(("Mono.TLabel", "Mono2.TLabel", "Card.TLabel", "Card.TLabel"), start=1):
                    lbl = ttk.Label(table, text="", style=style)
                    lbl.grid(row=r, column=c, sticky="w", padx=(0, 14), pady=3)
                    cells.append(lbl)
                ttk.Button(table, text="Copy", style="Small.TButton",
                           command=lambda f=f: self.app.to_clipboard(self.cells[f][0].cget("text"))
                           ).grid(row=r, column=5, pady=2)
                self.cells[f] = cells
            ttk.Separator(self).grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=8)
            self.row += 1
            self.rev_hex, _, self.rev_fmt, _ = self.row_of("Hex → decimal", [
                ("entry", "0x3FC0", 12), ("text", "as"), ("combo", list(FORMATS), "BF16", 11), ("text", "")], key="rev")
            self.rev_out = ttk.Label(self.rows["rev"][1], text="", style="Mono.TLabel")
            self.rev_out.pack(side="left")
            ttk.Separator(self).grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=8)
            self.row += 1
            self.list, self.list_fmt, _, self.list_name = self.row_of("Values → C array", [
                ("entry", "", 34), ("combo", list(FORMATS), "BF16", 11), ("text", "name"), ("entry", "data", 9)])
            self.note("Fill the list (comma separated decimals) to get a C array with the bit patterns, "
                      "ready to load with vle.  Put it OUTSIDE main().")

        @staticmethod
        def _error_text(v, stored):
            if math.isnan(v):
                return "NaN"
            if math.isnan(stored):
                return "overflow → NaN"
            if math.isinf(stored) and not math.isinf(v):
                return "overflow → Inf"
            if stored == v:
                return "exact"
            d = stored - v
            return f"{d:+.3g}" + (f" ({d / v * 100:+.2f} %)" if v else "")

        def generate(self):
            v = parse_decimal(self.value.get())
            for f, (hex_l, bin_l, val_l, err_l) in self.cells.items():
                eb, mb, _, _ = FORMATS[f]
                p = encode_float(v, f, self.sat.get())
                stored = decode_float(p, f)
                hex_l.config(text=f"0x{p:0{FORMAT_BITS[f] // 4}X}")
                bin_l.config(text=f"{p >> (eb + mb):b} · {(p >> mb) & ((1 << eb) - 1):0{eb}b} · {p & ((1 << mb) - 1):0{mb}b}")
                val_l.config(text=f"{stored:.9g}")
                err_l.config(text=self._error_text(v, stored))
            try:
                f = self.rev_fmt.get()
                raw = int(self.rev_hex.get().strip(), 0)
                if raw >> FORMAT_BITS[f]:
                    self.rev_out.config(text=f"does not fit in {FORMAT_BITS[f]} bits")
                else:
                    self.rev_out.config(text=f"= {decode_float(raw, f):.9g}")
            except ValueError:
                self.rev_out.config(text="type a hex pattern, e.g. 0x3FC0")
            items = []
            vals = split_values(self.list.get())
            if vals:
                f, name = self.list_fmt.get(), self.list_name.get().strip() or "data"
                pats = [encode_float(parse_decimal(t), f, self.sat.get()) for t in vals]
                bits = FORMAT_BITS[f]
                items.append(("raw", c_array(name, C_TYPE[bits], pats, bits // 4),
                              f"{f}: {', '.join(vals)}", []))
            return items, None, []

    # -------------------------------------------------------------- main app
    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Zvdota / RVV instruction encoder")
            self.geometry("940x1010")
            self.minsize(900, 780)
            self.configure(bg=PAL["bg"])
            fams = set(tkfont.families())
            pick = lambda *c: next((f for f in c if f in fams), c[-1])
            self.ui = pick("Inter", "Segoe UI", "SF Pro Text", "Noto Sans", "DejaVu Sans", "Helvetica")
            self.mono = pick("JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier")
            self._style()

            head = tk.Frame(self, bg=PAL["header"])
            head.pack(fill="x")
            tk.Label(head, text="Zvdota / RVV encoder", bg=PAL["header"], fg="white",
                     font=(self.ui, 16, "bold")).pack(side="left", padx=20, pady=(12, 12))
            tk.Label(head, text="generate .word lines for Sargantana tests", bg=PAL["header"],
                     fg="#aab4cf", font=(self.ui, 10)).pack(side="left", pady=(16, 8))

            bar = tk.Frame(self, bg=PAL["bg"])
            bar.pack(fill="x", padx=20, pady=(12, 6))
            ttk.Label(bar, text="Output format", style="Bg.TLabel").pack(side="left")
            self.style_var = tk.StringVar(value=STYLES[0])
            cb = ttk.Combobox(bar, textvariable=self.style_var, values=STYLES, state="readonly", width=46)
            cb.pack(side="left", padx=10)
            cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="x", padx=20)
            self.tabs = [DotTab(self, self.nb), VsetliTab(self, self.nb), VsetvlTab(self, self.nb),
                         WriteTab(self, self.nb), NumberTab(self, self.nb)]
            self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh())

            self.items = []
            self._result_card()
            self._program_card()
            self.refresh()

        # ---- styling
        def _style(self):
            st = ttk.Style(self)
            st.theme_use("clam")
            ui, mono, P = self.ui, self.mono, PAL
            self.option_add("*TCombobox*Listbox.font", (ui, 10))
            st.configure(".", background=P["bg"], foreground=P["ink"], font=(ui, 10))
            st.configure("Bg.TLabel", background=P["bg"], foreground=P["ink"])
            st.configure("Card.TFrame", background=P["card"])
            st.configure("Card.TLabel", background=P["card"], foreground=P["ink"])
            st.configure("Head.TLabel", background=P["card"], foreground=P["muted"], font=(ui, 9, "bold"))
            st.configure("Muted.TLabel", background=P["card"], foreground=P["muted"], font=(ui, 9))
            st.configure("Mono.TLabel", background=P["card"], foreground=P["ink"], font=(mono, 10, "bold"))
            st.configure("Mono2.TLabel", background=P["card"], foreground=P["ink"], font=(mono, 9))
            st.configure("Small.TButton", background="#e3e8f2", foreground=P["ink"], padding=(8, 2), borderwidth=0)
            st.map("Small.TButton", background=[("active", "#d3dae9")])
            st.configure("Card.TCheckbutton", background=P["card"], foreground=P["ink"])
            st.map("Card.TCheckbutton", background=[("active", P["card"])])
            st.configure("TSeparator", background=P["border"])
            st.configure("TCombobox", padding=4, arrowcolor=P["muted"], bordercolor=P["border"])
            st.map("TCombobox", fieldbackground=[("readonly", "white")], background=[("readonly", "white")],
                   selectbackground=[("readonly", "white")], selectforeground=[("readonly", P["ink"])])
            st.configure("TEntry", padding=5, bordercolor=P["border"])
            st.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
            st.configure("TNotebook.Tab", padding=(10, 8), font=(ui, 10, "bold"), background=P["tab"],
                         foreground=P["muted"], borderwidth=0)
            st.map("TNotebook.Tab", background=[("selected", P["card"])], foreground=[("selected", P["accent"])])
            st.configure("Accent.TButton", background=P["accent"], foreground="white", padding=(16, 8),
                         font=(ui, 10, "bold"), borderwidth=0)
            st.map("Accent.TButton", background=[("active", P["accent_dark"]), ("pressed", P["accent_dark"])])
            st.configure("Ghost.TButton", background="#e3e8f2", foreground=P["ink"], padding=(12, 6), borderwidth=0)
            st.map("Ghost.TButton", background=[("active", "#d3dae9")])

        def _card(self, parent, **pack):
            f = tk.Frame(parent, bg=PAL["card"], highlightbackground=PAL["border"], highlightthickness=1)
            f.pack(**pack)
            return f

        def _code_box(self, parent, height):
            t = tk.Text(parent, height=height, font=(self.mono, 11), bg=PAL["code_bg"], fg=PAL["code_fg"],
                        insertbackground="white", relief="flat", padx=12, pady=10, wrap="none",
                        selectbackground="#3a4570")
            return t

        def _result_card(self):
            card = self._card(self, fill="x", padx=20, pady=(12, 6))
            top = tk.Frame(card, bg=PAL["card"])
            top.pack(fill="x", padx=14, pady=(10, 2))
            tk.Label(top, text="RESULT", bg=PAL["card"], fg=PAL["muted"], font=(self.ui, 9, "bold")).pack(side="left")
            self.hex_lbl = tk.Label(top, text="", bg=PAL["card"], fg=PAL["accent"], font=(self.mono, 18, "bold"))
            self.hex_lbl.pack(side="right")
            self.strip = tk.Canvas(card, width=876, height=56, bg=PAL["card"], highlightthickness=0)
            self.out = self._code_box(card, 4)
            self.out.pack(fill="x", padx=14, pady=(8, 0))
            self.warn = tk.Label(card, text="", bg=PAL["warn_bg"], fg=PAL["warn_fg"], font=(self.ui, 9),
                                 anchor="w", justify="left", wraplength=860, padx=10, pady=6)
            self.tip = tk.Label(card, text="", bg=PAL["tip_bg"], fg=PAL["tip_fg"], font=(self.ui, 9),
                                anchor="w", justify="left", wraplength=860, padx=10, pady=6)
            self.btns = tk.Frame(card, bg=PAL["card"])
            self.btns.pack(fill="x", padx=14, pady=10)
            ttk.Button(self.btns, text="Add to program  ↓", style="Accent.TButton", command=self.add).pack(side="right")
            ttk.Button(self.btns, text="Copy result", style="Ghost.TButton",
                       command=lambda: self.to_clipboard(self.out.get("1.0", "end").rstrip("\n"))).pack(side="right", padx=8)

        def _program_card(self):
            card = self._card(self, fill="both", expand=True, padx=20, pady=(6, 16))
            top = tk.Frame(card, bg=PAL["card"])
            top.pack(fill="x", padx=14, pady=(10, 6))
            tk.Label(top, text="PROGRAM", bg=PAL["card"], fg=PAL["muted"], font=(self.ui, 9, "bold")).pack(side="left")
            ttk.Button(top, text="Clear", style="Ghost.TButton",
                       command=lambda: self.prog.delete("1.0", "end")).pack(side="right")
            ttk.Button(top, text="Copy all", style="Ghost.TButton",
                       command=lambda: self.to_clipboard(self.prog.get("1.0", "end").rstrip("\n"))).pack(side="right", padx=8)
            self.prog = self._code_box(card, 6)
            self.prog.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # ---- behaviour
        def to_clipboard(self, text):
            self.clipboard_clear()
            self.clipboard_append(text)

        def current(self):
            return self.tabs[self.nb.index(self.nb.select())]

        def draw_strip(self, fields):
            c = self.strip
            c.delete("all")
            if not fields:
                c.pack_forget()
                return
            c.pack(padx=14, pady=(2, 0), before=self.out)
            W, minw = int(c["width"]), 26
            k = (W - len(fields) * minw) / 32.0
            x = 0.0
            for name, width, value in fields:
                w = minw + width * k
                bg, fg = field_color(name)
                c.create_rectangle(x + 1, 4, x + w - 1, 52, fill=bg, outline=bg)
                c.create_text(x + w / 2, 17, text=name, fill=fg, font=(self.ui, 8, "bold"))
                c.create_text(x + w / 2, 37, text=f"{value:0{width}b}", fill=fg, font=(self.mono, 10))
                x += w

        def show_messages(self, msgs):
            warns = [m for m in msgs if not m.startswith("Tip:")]
            tips = [m[4:].strip() for m in msgs if m.startswith("Tip:")]
            for lbl, lines in ((self.warn, warns), (self.tip, tips)):
                if lines:
                    lbl.config(text="\n".join(lines))
                    lbl.pack(fill="x", padx=14, pady=(8, 0), before=self.btns)
                else:
                    lbl.config(text="")
                    lbl.pack_forget()

        def refresh(self):
            try:
                items, fields, msgs = self.current().generate()
                self.items = items
                text = "\n".join(render(i, self.style_var.get()) for i in items)
                self.hex_lbl.config(text=f"0x{pack(fields):08X}" if fields else "")
                self.draw_strip(fields)
                self.show_messages(msgs)
            except (ValueError, KeyError) as e:
                self.items, text = [], ""
                self.hex_lbl.config(text="")
                self.draw_strip(None)
                self.show_messages([str(e)])
            self.out.config(state="normal")
            self.out.delete("1.0", "end")
            self.out.insert("1.0", text)
            self.out.config(state="disabled")

        def add(self):
            for i in self.items:
                self.prog.insert("end", render(i, self.style_var.get()) + "\n")

    App().mainloop()


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    run_gui()
