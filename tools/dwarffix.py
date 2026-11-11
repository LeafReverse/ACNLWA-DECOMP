#!/usr/bin/env python3
import struct
import subprocess
import sys
from pathlib import Path

DW_AT_LOCATION = 0x02
DW_AT_NAME = 0x03
DW_FORM_STRING = 0x08
DW_FORM_STRP = 0x0E
DW_AT_START_SCOPE = 0x2C
DW_AT_PADDING = 0x3FF0
DW_FORM_DATA4 = 0x06
DW_FORM_BLOCK1 = 0x0A
DW_FORM_IMPLICIT_CONST = 0x21
DW_OP_REG0 = 0x50
DW_OP_REG31 = 0x6F

def readUleb(data, offset):
    value = shift = 0
    while True:
        byte = data[offset]
        value |= (byte & 0x7F) << shift
        offset += 1
        shift += 7
        if not byte & 0x80: return value, offset

def uleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
            continue

        out.append(byte)
        return bytes(out)

def readAbbrevTable(data, offset):
    entries = {}
    while True:
        code, offset = readUleb(data, offset)
        if code == 0: return entries, offset

        tag, offset = readUleb(data, offset)
        children = data[offset]
        offset += 1
        specs = []
        while True:
            name, offset = readUleb(data, offset)
            form, offset = readUleb(data, offset)
            const = None
            if form == DW_FORM_IMPLICIT_CONST: const, offset = readUleb(data, offset)
            if name == 0 and form == 0: break

            specs.append((name, form, const))

        entries[code] = (tag, children, specs)


def encodeAbbrev(code, tag, children, specs):
    out = bytearray(uleb(code) + uleb(tag) + bytes([children]))
    for name, form, const in specs:
        out += uleb(name) + uleb(form)
        if form == DW_FORM_IMPLICIT_CONST: out += uleb(const)

    return bytes(out + b"\0\0")

def scopedResult(die):
    if die.tag != "DW_TAG_variable" or "DW_AT_start_scope" not in die.attributes: return None

    location = die.attributes.get("DW_AT_location")
    if not location or location.form not in ("DW_FORM_block", "DW_FORM_block1"): return None
    if len(location.value) != 1 or not DW_OP_REG0 <= location.value[0] <= DW_OP_REG31: return None

    parent = die.get_parent()
    if parent is None or "DW_AT_low_pc" not in parent.attributes or "DW_AT_high_pc" not in parent.attributes: return None

    low = parent.attributes["DW_AT_low_pc"].value
    high = parent.attributes["DW_AT_high_pc"].value
    if parent.attributes["DW_AT_high_pc"].form not in ("DW_FORM_addr",): high += low

    return low, high, die.attributes["DW_AT_start_scope"].value, location.value[0]


def locationList(base, low, high, scope, register):
    if low + scope >= high: return struct.pack("<II", 0, 0)

    expression = struct.pack("<H", 1) + bytes([register])
    return struct.pack("<II", low + scope - base, high - base) + expression + struct.pack("<II", 0, 0)


def respec(name, form, const, strp):
    if name == DW_AT_LOCATION: return name, DW_FORM_DATA4, None
    if strp and name == DW_AT_NAME and form == DW_FORM_STRING: return name, DW_FORM_STRP, None
    return name, form, const


def attributeBytes(info, die):
    attrs = list(die.attributes.values())
    ends = [a.offset for a in attrs[1:]] + [die.offset + die.size]
    return [(a, bytes(info[a.offset:end])) for a, end in zip(attrs, ends)]


class Rewriter:
    def __init__(self, info, abbrev, loc, strings):
        self.Info = bytearray(info)
        self.Abbrev = bytearray(abbrev)
        self.Loc = bytearray(loc)
        self.Str = bytearray(strings)
        self.Tables = {}
        self.Rewritten = 0

    def tableFor(self, cu):
        old = cu["debug_abbrev_offset"]
        if old in self.Tables: return self.Tables[old]

        entries, _ = readAbbrevTable(self.Abbrev, old)
        table = {"entries": entries, "added": {}, "next": max(entries) + 1 if entries else 1}
        self.Tables[old] = table

        return table

    def newCode(self, table, oldCode, strp, padding):
        key = (oldCode, strp, padding)
        if key in table["added"]: return table["added"][key]

        tag, children, specs = table["entries"][oldCode]
        specs = [respec(name, form, const, strp) for name, form, const in specs if name != DW_AT_START_SCOPE]
        if padding: specs.append((DW_AT_PADDING, DW_FORM_BLOCK1, None))

        code = table["next"]
        table["next"] += 1
        table["added"][key] = code
        table["entries"][code] = (tag, children, specs)

        return code

    def encode(self, table, die, body, strp):
        plain = uleb(self.newCode(table, die.abbrev_code, strp, False)) + body
        if len(plain) == die.size: return plain
        if len(plain) > die.size: return None

        head = uleb(self.newCode(table, die.abbrev_code, strp, True)) + body
        filler = die.size - len(head) - 1
        if filler < 0 or filler > 0xFF: return None

        return head + bytes([filler]) + bytes(filler)

    def body(self, die, locOffset, strp):
        body = bytearray()
        for attr, raw in attributeBytes(self.Info, die):
            if attr.name == "DW_AT_start_scope": continue
            if attr.name == "DW_AT_location": body += struct.pack("<I", locOffset)
            elif strp and attr.name == "DW_AT_name" and attr.form == "DW_FORM_string": body += struct.pack("<I", self.stringOffset(raw))
            else: body += raw

        return bytes(body)

    def stringOffset(self, raw):
        found = self.Str.find(raw)
        if found >= 0 and (found == 0 or self.Str[found - 1] == 0): return found

        self.Str += raw
        return len(self.Str) - len(raw)

    def rewrite(self, cu, die, scope):
        table = self.tableFor(cu)
        locOffset = len(self.Loc)
        encoded = None
        for strp in (False, True):
            encoded = self.encode(table, die, self.body(die, locOffset, strp), strp)
            if encoded: break

        if not encoded: return False

        top = cu.get_top_DIE().attributes.get("DW_AT_low_pc")
        self.Loc += locationList(top.value if top else 0, *scope)
        self.Info[die.offset:die.offset + die.size] = encoded
        self.Rewritten += 1
        return True

    def finishAbbrev(self, cuOffsets):
        for old, table in self.Tables.items():
            if not table["added"]: continue

            start = len(self.Abbrev)
            for code in sorted(table["entries"]): self.Abbrev += encodeAbbrev(code, *table["entries"][code])

            self.Abbrev += b"\0"
            for cuOffset, abbrevOffset in cuOffsets:
                if abbrevOffset == old: self.Info[cuOffset + 6:cuOffset + 10] = struct.pack("<I", start)


def ScopeResults(path, objcopy):
    from elftools.elf.elffile import ELFFile

    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        if not elf.has_dwarf_info(): return 0, 0

        info = elf.get_section_by_name(".debug_info").data()
        abbrev = elf.get_section_by_name(".debug_abbrev").data()
        locSection = elf.get_section_by_name(".debug_loc")
        strSection = elf.get_section_by_name(".debug_str")
        rewriter = Rewriter(info, abbrev, locSection.data() if locSection else b"", strSection.data() if strSection else b"")
        cuOffsets = []
        found = []

        for cu in elf.get_dwarf_info().iter_CUs():
            cuOffsets.append((cu.cu_offset, cu["debug_abbrev_offset"]))
            for die in cu.iter_DIEs():
                if die.is_null(): continue

                scope = scopedResult(die)
                if scope: found.append((cu, die, scope))

        for cu, die, scope in found: rewriter.rewrite(cu, die, scope)

    if not rewriter.Rewritten: return 0, len(found)

    rewriter.finishAbbrev(cuOffsets)
    work = Path(path).with_suffix(".dwarf")
    work.mkdir(exist_ok=True)
    sections = {".debug_info": (rewriter.Info, True), ".debug_abbrev": (rewriter.Abbrev, True), ".debug_loc": (rewriter.Loc, locSection), ".debug_str": (rewriter.Str, strSection)}
    args = [str(objcopy)]
    for name, (data, exists) in sections.items():
        if not data: continue

        file = work / name.lstrip(".")
        file.write_bytes(bytes(data))
        args += ["--update-section" if exists else "--add-section", "%s=%s" % (name, file)]

    result = subprocess.run(args + [str(path)], capture_output=True, text=True)
    if result.returncode: sys.exit("objcopy failed:\n" + result.stderr)

    return rewriter.Rewritten, len(found)
